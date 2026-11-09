"""Re-score an existing Qwen3-0.6B prediction after deterministic runtime guards.

No model is loaded and the frozen test split is rejected. This is intended to
measure the effect of the runtime guard against focused-v1 without another GPU run.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.eval.nlu.model_evaluator import evaluate_files, summarize
from adapters.nlu.qwen06b_guard import repair_qwen06b_payload
from adapters.nlu.qwen_training_data import canonical_json


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def reject_test(*paths: Path) -> None:
    for path in paths:
        if "test" in str(path).lower():
            raise ValueError(f"test split/artifact 접근 금지: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reject_test(args.gold, args.predictions, args.output)

    gold_rows = read_jsonl(args.gold)
    pred_rows = read_jsonl(args.predictions)
    gold_by_id = {row["sample_id"]: row for row in gold_rows}
    if set(gold_by_id) != {row.get("sample_id") for row in pred_rows}:
        raise ValueError("gold/prediction sample_id가 일치하지 않습니다")

    repaired_rows: list[dict[str, Any]] = []
    changed_ids: list[str] = []
    for row in pred_rows:
        sid = row["sample_id"]
        gold = gold_by_id[sid]
        try:
            raw_payload = json.loads(row["prediction"])
        except (json.JSONDecodeError, TypeError):
            repaired_rows.append(row)
            continue
        repaired = repair_qwen06b_payload(
            gold["input"]["utterance"],
            gold["input"]["cart_before"],
            raw_payload,
        )
        repaired_text = canonical_json(repaired)
        if canonical_json(raw_payload) != repaired_text:
            changed_ids.append(sid)
        repaired_row = dict(row)
        repaired_row["prediction"] = repaired_text
        repaired_rows.append(repaired_row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(canonical_json(row) + "\n" for row in repaired_rows),
        encoding="utf-8",
    )

    scored, total = evaluate_files(args.gold, args.output)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    latencies: dict[str, list[float]] = defaultdict(list)
    repaired_by_id = {row["sample_id"]: row for row in repaired_rows}
    for score in scored:
        sid = score["sample_id"]
        scenario = gold_by_id[sid]["metadata"].get("scenario", "unknown")
        grouped[scenario].append(score)
        latency = repaired_by_id[sid].get("latency_ms")
        if isinstance(latency, (int, float)):
            latencies[scenario].append(float(latency))

    report = {
        "changed_count": len(changed_ids),
        "changed_sample_ids": changed_ids,
        "summary": total,
        "per_scenario": {
            scenario: summarize(rows, latencies.get(scenario, []))
            for scenario, rows in sorted(grouped.items())
        },
        "test_split_opened": False,
    }
    report_path = args.output.with_suffix(".summary.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
