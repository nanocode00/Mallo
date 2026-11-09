"""Score the contract-focused real-use NLU challenge without changing runtime behavior."""

from __future__ import annotations

import copy
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from adapters.nlu.qwen_training_data import (
    DEFAULT_COMMAND_SCHEMA_PATH,
    DEFAULT_ERROR_SCHEMA_PATH,
    canonical_json,
)
from config.settings import load_menu


COMMAND_FIELDS = (
    "intent", "target_item_id", "category_id", "quantity", "temperature",
    "query_tags", "detail_fields", "options",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _command_validator() -> Draft202012Validator:
    schema = copy.deepcopy(_load_json(DEFAULT_COMMAND_SCHEMA_PATH))
    command = schema["$defs"]["orderCommand"]
    # NLU output intentionally has no runtime request_id. fulfillment_type is an
    # additive runtime field absent from the frozen model labels.
    for field in ("request_id", "fulfillment_type"):
        command["required"].remove(field)
        command["properties"].pop(field)
    return Draft202012Validator(schema)


def _percent(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _p95(values: list[float]) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)] if values else None


class ChallengeEvaluator:
    def __init__(self) -> None:
        self.command_validator = _command_validator()
        self.error_validator = Draft202012Validator(_load_json(DEFAULT_ERROR_SCHEMA_PATH))
        self._single_temperature = {
            item.id: item.temperature_options[0].value
            for item in load_menu()
            if len(item.temperature_options) == 1
        }

    def _canonical_payload(self, payload: Any) -> Any:
        """Canonicalize command envelopes and production-only defaults for comparison."""
        if isinstance(payload, dict) and payload.get("type") == "commands":
            payload = payload.get("value")
        if not isinstance(payload, list):
            return payload  # Errors remain distinct from command arrays.
        canonical: list[dict[str, Any]] = []
        for command in payload:
            if not isinstance(command, dict):
                return payload
            row = {field: command.get(field) for field in COMMAND_FIELDS}
            singleton = self._single_temperature.get(row["target_item_id"])
            if row["intent"] == "ADD_ITEM" and singleton is not None and row["temperature"] is None:
                row["temperature"] = singleton
            canonical.append(row)
        return canonical

    def score(self, case: dict[str, Any], prediction_text: str) -> dict[str, Any]:
        metadata = case["metadata"]
        result: dict[str, Any] = {
            "sample_id": case["sample_id"], "category": metadata["category"],
            "scored": metadata["scored"], "behavioral": metadata.get("behavioral"),
            "json_valid": False, "schema_valid": False, "exact_match": False,
            "semantic_pass": False, "quantity_pass": None, "failure_reason": None,
            "evaluation_layer": "production_nlu_semantic",
        }
        try:
            prediction = json.loads(prediction_text)
        except (TypeError, json.JSONDecodeError):
            result["failure_reason"] = "invalid_json"
            return result
        result["json_valid"] = True
        canonical_prediction = self._canonical_payload(prediction)
        validator = self.command_validator if isinstance(canonical_prediction, list) else self.error_validator
        result["schema_valid"] = not list(validator.iter_errors(canonical_prediction))
        if not metadata["scored"]:
            result["semantic_pass"] = None
            return result
        if not result["schema_valid"]:
            result["failure_reason"] = "schema_invalid"
            return result
        if metadata.get("behavioral") == "temperature_no_question":
            asked_temperature = isinstance(prediction, dict) and prediction.get("code") == "MISSING_FIELD" and prediction.get("field") == "temperature"
            result["semantic_pass"] = not asked_temperature
            result["exact_match"] = None
            result["failure_reason"] = "asked_missing_temperature" if asked_temperature else None
            return result
        expected = self._canonical_payload(case["output"])
        result["exact_match"] = canonical_json(canonical_prediction) == canonical_json(expected)
        result["semantic_pass"] = result["exact_match"]
        if isinstance(expected, list):
            result["quantity_pass"] = (
                isinstance(canonical_prediction, list) and len(canonical_prediction) == len(expected)
                and all(actual.get("quantity") == wanted.get("quantity") for actual, wanted in zip(canonical_prediction, expected))
            )
        if not result["semantic_pass"]:
            result["failure_reason"] = "semantic_mismatch"
        return result


def summarize(cases: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evaluator = ChallengeEvaluator()
    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case in cases:
        row = predictions[case["sample_id"]]
        score = evaluator.score(case, row.get("prediction", ""))
        if isinstance(row.get("latency_ms"), (int, float)):
            latencies.append(float(row["latency_ms"]))
        results.append(score)
    scored = [row for row in results if row["scored"]]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        by_category[row["category"]].append(row)
    metric = lambda key: _percent([bool(row[key]) for row in scored if row[key] is not None])
    multi = by_category.get("multi_item", [])
    return results, {
        "scored_case_count": len(scored), "exact_match": metric("exact_match"),
        "semantic_pass_rate": metric("semantic_pass"),
        "json_schema_valid_rate": _percent([row["schema_valid"] for row in results]),
        "quantity_pass_rate": metric("quantity_pass"),
        "multi_item_exact_pass_rate": _percent([bool(row["exact_match"]) for row in multi]),
        "multi_item_semantic_pass_rate": _percent([bool(row["semantic_pass"]) for row in multi]),
        "alias_stt_confusion_pass_rate": _percent([bool(row["semantic_pass"]) for row in by_category.get("alias_stt_confusion", [])]),
        "existing_cart_add_pass_rate": _percent([bool(row["semantic_pass"]) for row in by_category.get("existing_cart_add", [])]),
        "confirm_order_pass_rate": _percent([bool(row["semantic_pass"]) for row in by_category.get("confirm_order", [])]),
        "temperature_no_question_behavioral_pass_rate": _percent([bool(row["semantic_pass"]) for row in by_category.get("temperature_no_question", [])]),
        "category_pass_rates": {key: _percent([bool(row["semantic_pass"]) for row in value]) for key, value in sorted(by_category.items())},
        "latency_ms": {"median": statistics.median(latencies) if latencies else None, "p95": _p95(latencies)},
    }
