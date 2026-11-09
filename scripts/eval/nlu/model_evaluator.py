"""Baseline과 Fine-tuned NLU prediction JSONL의 계약 지표를 계산한다."""

from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from adapters.nlu.qwen_training_data import (
    DEFAULT_COMMAND_SCHEMA_PATH,
    DEFAULT_ERROR_SCHEMA_PATH,
    DEFAULT_MENU_PATH,
    canonical_json,
)


SEMANTIC_SLOTS = (
    "target_item_id",
    "category_id",
    "quantity",
    "temperature",
    "query_tags",
    "detail_fields",
    "options",
)


class EvaluationError(ValueError):
    """평가 입력 또는 sample_id 계약 오류."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationError(f"JSON 파일을 읽을 수 없습니다: {path}") from error


def _semantic_command_validator(path: Path) -> Draft202012Validator:
    schema = copy.deepcopy(_load_json(path))
    command = schema["$defs"]["orderCommand"]
    command["required"].remove("request_id")
    del command["properties"]["request_id"]
    return Draft202012Validator(schema)


class NLUEvaluator:
    def __init__(
        self,
        *,
        menu_path: Path = DEFAULT_MENU_PATH,
        command_schema_path: Path = DEFAULT_COMMAND_SCHEMA_PATH,
        error_schema_path: Path = DEFAULT_ERROR_SCHEMA_PATH,
    ) -> None:
        menu = _load_json(menu_path)
        self.menu_ids = {row["id"] for row in menu["items"]}
        self.category_ids = {row["id"] for row in menu["categories"]}
        self.tag_ids = {row["id"] for row in menu["tag_definitions"]}
        self.command_validator = _semantic_command_validator(command_schema_path)
        self.error_validator = Draft202012Validator(_load_json(error_schema_path))

    def _schema_valid(self, prediction: Any) -> bool:
        validator = self.command_validator if isinstance(prediction, list) else self.error_validator
        return not list(validator.iter_errors(prediction))

    def _invalid_menu(self, prediction: Any) -> bool:
        if not isinstance(prediction, list):
            return False
        for command in prediction:
            if not isinstance(command, dict):
                continue
            if command.get("target_item_id") not in self.menu_ids | {None}:
                return True
            if command.get("category_id") not in self.category_ids | {None}:
                return True
            tags = command.get("query_tags")
            if isinstance(tags, list) and any(tag not in self.tag_ids for tag in tags):
                return True
        return False

    def score(self, gold: dict[str, Any], prediction_text: str) -> dict[str, Any]:
        expected = gold["output"]["value"]
        expected_type = gold["output"]["type"]
        result: dict[str, Any] = {
            "sample_id": gold["sample_id"],
            "label_group": gold["metadata"]["label_group"],
            "json_valid": False,
            "schema_valid": False,
            "invalid_menu": False,
            "exact_match": False,
            "intent_correct": None,
            "slot_correct": 0,
            "slot_total": 0,
            "error_code_correct": None,
            "command_order_correct": None,
            "predicted_label": "INVALID_JSON",
        }
        try:
            prediction = json.loads(prediction_text)
        except (json.JSONDecodeError, TypeError):
            return result
        result["json_valid"] = True
        result["schema_valid"] = self._schema_valid(prediction)
        result["invalid_menu"] = self._invalid_menu(prediction)
        result["exact_match"] = canonical_json(prediction) == canonical_json(expected)

        if expected_type == "error":
            predicted_code = prediction.get("code") if isinstance(prediction, dict) else None
            result["error_code_correct"] = predicted_code == expected["code"]
            result["predicted_label"] = predicted_code or "SCHEMA_ERROR"
            return result

        expected_commands = expected
        predicted_commands = prediction if isinstance(prediction, list) else []
        predicted_intents = [row.get("intent") for row in predicted_commands if isinstance(row, dict)]
        expected_intents = [row["intent"] for row in expected_commands]
        result["intent_correct"] = predicted_intents == expected_intents
        result["predicted_label"] = (
            "+".join(str(intent) for intent in predicted_intents) if predicted_intents else "SCHEMA_ERROR"
        )
        result["slot_total"] = len(expected_commands) * len(SEMANTIC_SLOTS)
        for index, expected_command in enumerate(expected_commands):
            predicted_command = predicted_commands[index] if index < len(predicted_commands) else {}
            if not isinstance(predicted_command, dict):
                predicted_command = {}
            result["slot_correct"] += sum(
                predicted_command.get(field, object()) == expected_command[field]
                for field in SEMANTIC_SLOTS
            )
        if len(expected_commands) > 1:
            expected_order = [(row["intent"], row.get("target_item_id")) for row in expected_commands]
            predicted_order = [
                (row.get("intent"), row.get("target_item_id"))
                for row in predicted_commands
                if isinstance(row, dict)
            ]
            result["command_order_correct"] = predicted_order == expected_order
        return result


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def summarize(results: list[dict[str, Any]], latencies_ms: list[float]) -> dict[str, Any]:
    if not results:
        raise EvaluationError("평가 결과가 비어 있습니다")
    intent_rows = [row for row in results if row["intent_correct"] is not None]
    error_rows = [row for row in results if row["error_code_correct"] is not None]
    order_rows = [row for row in results if row["command_order_correct"] is not None]
    slot_total = sum(row["slot_total"] for row in results)
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for row in results:
        confusion[row["label_group"]][row["predicted_label"]] += 1
    return {
        "sample_count": len(results),
        "intent_accuracy": _percentage(sum(row["intent_correct"] for row in intent_rows), len(intent_rows)),
        "slot_accuracy": _percentage(sum(row["slot_correct"] for row in results), slot_total),
        "exact_match": _percentage(sum(row["exact_match"] for row in results), len(results)),
        "json_schema_valid_rate": _percentage(sum(row["schema_valid"] for row in results), len(results)),
        "invalid_menu_output_rate": _percentage(sum(row["invalid_menu"] for row in results), len(results)),
        "error_code_accuracy": _percentage(
            sum(row["error_code_correct"] for row in error_rows), len(error_rows)
        ),
        "multi_command_order_accuracy": _percentage(
            sum(row["command_order_correct"] for row in order_rows), len(order_rows)
        ),
        "failure_counts": {
            "invalid_json": sum(not row["json_valid"] for row in results),
            "schema_error": sum(row["json_valid"] and not row["schema_valid"] for row in results),
            "invalid_menu": sum(row["invalid_menu"] for row in results),
            "command_order": sum(row["command_order_correct"] is False for row in results),
        },
        "warm_latency_ms": {
            "median": statistics.median(latencies_ms) if latencies_ms else None,
            "p95": _percentile(latencies_ms, 0.95),
        },
        "confusion_matrix": {label: dict(counts) for label, counts in sorted(confusion.items())},
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationError(f"JSONL 파싱 오류: {path}:{line_number}") from error
        if not isinstance(row, dict):
            raise EvaluationError(f"JSONL 행은 객체여야 합니다: {path}:{line_number}")
        rows.append(row)
    return rows


def evaluate_files(gold_path: Path, prediction_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gold_rows = _read_jsonl(gold_path)
    predictions = _read_jsonl(prediction_path)
    prediction_by_id = {row.get("sample_id"): row for row in predictions}
    if len(prediction_by_id) != len(predictions) or set(prediction_by_id) != {
        row["sample_id"] for row in gold_rows
    }:
        raise EvaluationError("prediction sample_id가 중복·누락됐거나 정답과 다릅니다")
    evaluator = NLUEvaluator()
    results = []
    latencies = []
    for gold in gold_rows:
        prediction = prediction_by_id[gold["sample_id"]]
        results.append(evaluator.score(gold, prediction.get("prediction")))
        if isinstance(prediction.get("latency_ms"), (int, float)):
            latencies.append(float(prediction["latency_ms"]))
    return results, summarize(results, latencies)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args(argv)
    _, summary = evaluate_files(args.gold, args.predictions)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
