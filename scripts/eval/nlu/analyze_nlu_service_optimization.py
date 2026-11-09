"""Validation-only NLU optimization artifacts를 비교하고 요약한다."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.eval.nlu.model_evaluator import NLUEvaluator, summarize

from adapters.nlu.qwen_training_data import canonical_json


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if "test" in path.name.lower():
        raise ValueError(f"test artifact 접근 금지: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_schema_error(evaluator: NLUEvaluator, prediction_text: str) -> list[str]:
    try:
        value = json.loads(prediction_text)
    except json.JSONDecodeError:
        return ["JSON syntax"]
    validator = evaluator.command_validator if isinstance(value, list) else evaluator.error_validator
    categories: list[str] = []
    for error in validator.iter_errors(value):
        message = error.message
        if error.validator == "required":
            kind = "required field 누락"
        elif error.validator == "type":
            kind = "field type"
        elif error.validator in {"enum", "const"}:
            kind = "enum/domain"
        elif "is not valid under any of the given schemas" in message:
            kind = "intent/field combination"
        else:
            kind = "기타"
        if "ice_amount" in "/".join(map(str, error.absolute_path)) and "iced" in message:
            kind = "cross-field 오류"
        categories.append(kind)
    return sorted(set(categories)) or ["기타"]


def semantic(text: str) -> str | None:
    try:
        return canonical_json(json.loads(text))
    except (json.JSONDecodeError, TypeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--fallback", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.gold, args.baseline, args.candidate, args.fallback):
        if "test" in str(path).lower():
            raise ValueError(f"test 경로 접근 금지: {path}")

    gold_rows = read_jsonl(args.gold)
    gold = {row["sample_id"]: row for row in gold_rows}
    baseline = {row["sample_id"]: row for row in read_jsonl(args.baseline)}
    candidate = {row["sample_id"]: row for row in read_jsonl(args.candidate)}
    fallback = {row["sample_id"]: row for row in read_jsonl(args.fallback)}
    selected = set(candidate)
    if selected != {row["sample_id"] for row in gold_rows[: len(candidate)]}:
        raise ValueError("candidate가 고정 validation prefix와 일치하지 않습니다")

    evaluator = NLUEvaluator()
    invalid: list[dict[str, Any]] = []
    for sample_id in selected:
        merged_score = evaluator.score(gold[sample_id], baseline[sample_id]["prediction"])
        if merged_score["schema_valid"]:
            continue
        nf4_score = evaluator.score(gold[sample_id], fallback[sample_id]["prediction"])
        invalid.append(
            {
                "sample_id": sample_id,
                "gold": gold[sample_id]["output"]["value"],
                "merged_raw_output": baseline[sample_id].get("raw_prediction"),
                "merged_semantic_prediction": semantic(baseline[sample_id]["prediction"]),
                "schema_violation_types": classify_schema_error(
                    evaluator, baseline[sample_id]["prediction"]
                ),
                "nf4_raw_output": fallback[sample_id].get("raw_prediction"),
                "nf4_schema_valid": nf4_score["schema_valid"],
                "nf4_semantic_prediction": semantic(fallback[sample_id]["prediction"]),
                "nf4_gold_recovered": nf4_score["exact_match"],
            }
        )

    candidate_scores = [
        evaluator.score(gold[row["sample_id"]], row["prediction"])
        for row in read_jsonl(args.candidate)
    ]
    candidate_latencies = [
        float(row["latency_ms"])
        for row in read_jsonl(args.candidate)
        if isinstance(row.get("latency_ms"), (int, float))
    ]
    metrics = summarize(candidate_scores, candidate_latencies)
    baseline_selected_bytes = "".join(
        canonical_json(baseline[row["sample_id"]]) + "\n" for row in read_jsonl(args.candidate)
    ).encode("utf-8")
    byte_equal = baseline_selected_bytes == args.candidate.read_bytes()
    semantic_equal = all(
        semantic(candidate[sid]["prediction"]) == semantic(baseline[sid]["prediction"])
        for sid in selected
    )
    token_equal = all(
        candidate[sid].get("generated_token_ids") == baseline[sid].get("generated_token_ids")
        for sid in selected
    )
    report = {
        "candidate_metrics": metrics,
        "prediction_sha256": sha256(args.candidate),
        "baseline_sha256": sha256(args.baseline),
        "byte_exact_equal": byte_equal,
        "semantic_normalized_equal": semantic_equal,
        "generated_token_sequence_equal": token_equal,
        "semantic_divergence_count": sum(
            semantic(candidate[sid]["prediction"]) != semantic(baseline[sid]["prediction"])
            for sid in selected
        ),
        "merged_invalid_cases": invalid,
        "nf4_schema_recovered_count": sum(row["nf4_schema_valid"] for row in invalid),
        "nf4_gold_recovered_count": sum(row["nf4_gold_recovered"] for row in invalid),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
