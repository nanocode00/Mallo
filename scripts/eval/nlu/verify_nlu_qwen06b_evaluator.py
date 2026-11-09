"""Verify that the frozen validation evaluator still reproduces the known 1.7B reference metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.eval.nlu.model_evaluator import evaluate_files

from adapters.nlu.qwen06b_config import reject_test_path
from adapters.nlu.qwen_training_data import DEFAULT_PROCESSED_DIR, REPOSITORY_ROOT


DEFAULT_REFERENCE = (
    REPOSITORY_ROOT
    / "models/nlu/qwen3-1.7b-qlora/honorbear-20260824-qwen3-1p7b-qlora-v1/evaluations/validation-max96.jsonl"
)
EXPECTED = {
    "sample_count": 300,
    "intent_accuracy": 0.965385,
    "slot_accuracy": 0.960989,
    "exact_match": 0.916667,
    "json_schema_valid_rate": 0.983333,
    "invalid_menu_output_rate": 0.0,
    "error_code_accuracy": 0.775,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_PROCESSED_DIR / "validation.jsonl")
    parser.add_argument("--predictions", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    for label, path in (("gold", args.gold), ("predictions", args.predictions)):
        reject_test_path(path, label=label)
        if not path.is_file():
            raise RuntimeError(f"{label} 파일이 없습니다: {path}")
    if args.report:
        reject_test_path(args.report, label="report")

    _, summary = evaluate_files(args.gold, args.predictions)
    mismatches: dict[str, dict[str, object]] = {}
    for key, expected in EXPECTED.items():
        actual = summary.get(key)
        if isinstance(expected, float):
            matches = isinstance(actual, (int, float)) and abs(float(actual) - expected) <= 1e-6
        else:
            matches = actual == expected
        if not matches:
            mismatches[key] = {"expected": expected, "actual": actual}
    if mismatches:
        raise RuntimeError(f"evaluator reference metric drift: {json.dumps(mismatches, ensure_ascii=False)}")

    report = {
        "status": "PASS",
        "gold": str(args.gold),
        "predictions": str(args.predictions),
        "expected": EXPECTED,
        "actual": {key: summary.get(key) for key in EXPECTED},
        "test_split_opened": False,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
