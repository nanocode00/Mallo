"""Evaluate the production Qwen3-0.6B NLU path on the real-use challenge.

This intentionally does not load the 1.7B reference model. Every case goes
through Qwen06BNLU.parse, including normalization and deterministic repair.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.eval.nlu.challenge_evaluator import summarize
from adapters.nlu.qwen06b_nlu import DEFAULT_SERVICE_MERGED_MODEL, Qwen06BNLU
from adapters.nlu.qwen_training_data import canonical_json
from domain.models import BeverageOptions, Cart, CartItem, Temperature
from domain.order_command_error import OrderCommandError

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CHALLENGE = ROOT / "data/nlu/challenges/mallo-real-v1.jsonl"


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def cart_from_payload(rows: list[dict[str, Any]]) -> Cart:
    return Cart(items=[CartItem(
        menu_id=row["menu_id"], quantity=row["quantity"], unit_price=0,
        temperature=Temperature(row["temperature"]) if row["temperature"] is not None else None,
        options=BeverageOptions.from_mapping(row["options"]),
    ) for row in rows])


def semantic_payload(result: Any) -> list[dict[str, Any]] | dict[str, Any]:
    if isinstance(result, OrderCommandError):
        return result.to_dict()
    return [{key: value for key, value in command.to_dict().items() if key != "request_id"} for command in result]


def run_production_nlu(nlu: Qwen06BNLU, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    for row in rows:
        result = nlu.parse(row["input"]["utterance"], cart_from_payload(row["input"]["cart_before"]))
        final = semantic_payload(result)
        predictions.append({
            "sample_id": row["sample_id"],
            "original_utterance": nlu.last_original_text,
            "normalized_utterance": nlu.last_normalized_text,
            "normalization_replacements": [list(item) for item in nlu.last_normalization_replacements],
            "raw_prediction": nlu.last_raw_prediction,
            "repaired_payload": nlu.last_repaired_payload,
            "final_semantic_result": final,
            "prediction": canonical_json(final),
            "latency_ms": nlu.last_latency_ms,
        })
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--challenge", type=Path, default=DEFAULT_CHALLENGE)
    parser.add_argument("--merged-06", type=Path, default=DEFAULT_SERVICE_MERGED_MODEL)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--prompt-lookup-num-tokens", type=int, default=8)
    args = parser.parse_args()
    rows = load_rows(args.challenge)
    root = args.output_root or ROOT / "artifacts/nlu-challenge" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.challenge, root / "challenge-set.snapshot.jsonl")
    nlu = Qwen06BNLU(merged_model_path=args.merged_06, prompt_lookup_num_tokens=args.prompt_lookup_num_tokens)
    predictions = run_production_nlu(nlu, rows)
    prediction_path = root / "qwen3-0.6b-production-predictions.jsonl"
    prediction_path.write_text("".join(canonical_json(row) + "\n" for row in predictions), encoding="utf-8")
    results, report = summarize(rows, {row["sample_id"]: row for row in predictions})
    report.update({
        "model": "qwen3-0.6b",
        "evaluation_layer": "production_nlu_semantic",
        "inference_path": "normalize -> Qwen06BNLU.generate -> repair -> OrderCommand parse",
        "load_latency_ms": nlu.load_latency_ms,
    })
    (root / "qwen3-0.6b-production-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = [
        {"case": case, "prediction": prediction, "failure_reason": score["failure_reason"]}
        for case, prediction, score in zip(rows, predictions, results)
        if score["scored"] and not score["semantic_pass"]
    ]
    failure_dir = root / "failures"
    failure_dir.mkdir()
    (failure_dir / "qwen3-0.6b-production.jsonl").write_text("".join(canonical_json(row) + "\n" for row in failures), encoding="utf-8")
    print(root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
