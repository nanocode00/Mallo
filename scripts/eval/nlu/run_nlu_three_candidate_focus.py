"""Run the focused challenge against the three current Mallo NLU candidates.

Candidates:
1) Qwen3-1.7B merged BF16 -> strict schema fallback -> resident NF4 PEFT
2) Qwen3-0.6B epochs4_seed7 merged BF16 + prompt lookup 5
3) Qwen3-0.6B epochs4_seed7 merged BF16 + prompt lookup 8

The frozen test split is never read. The focused challenge is a synthetic contract
stress suite and must not be reported as a pristine generalization estimate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.eval.nlu.model_evaluator import evaluate_files, summarize
from adapters.nlu.qwen_training_data import canonical_json

ROOT = Path(__file__).resolve().parents[3]
PYTHON = ROOT / ".venvs/dev/bin/python"
DEFAULT_CHALLENGE = ROOT / "data/nlu/challenges/focused-v1.jsonl"
DEFAULT_17_MERGED = ROOT / "models/nlu/qwen3-1.7b-lora/honorbear-20260824-qwen3-1p7b-bf16-native-lora-v1/merged-bf16"
DEFAULT_17_NF4 = ROOT / "models/nlu/qwen3-1.7b-qlora/honorbear-20260824-qwen3-1p7b-qlora-v1/final-adapter"
DEFAULT_06_MERGED = ROOT / "models/nlu/final-qwen06b-merged-bf16"
STATUS = ROOT / "logs/nlu-three-candidate-focus.status"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def set_status(stage: str, state: str, *, run_id: str, detail: str = "") -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(
        f"stage={stage}\nstate={state}\nrun_id={run_id}\ndetail={detail}\nupdated_at={datetime.now().astimezone().isoformat()}\n",
        encoding="utf-8",
    )


def ensure_no_test_path(*paths: Path) -> None:
    for path in paths:
        if "test" in str(path).lower():
            raise ValueError(f"frozen test path/artifact 접근 금지: {path}")


def run(command: list[str], *, stage: str, run_id: str) -> None:
    set_status(stage, "RUNNING", run_id=run_id, detail=" ".join(command))
    print(f"\n[{stage}] {' '.join(command)}", flush=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(ROOT / "scripts"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def ensure_challenge(challenge: Path, *, run_id: str) -> dict[str, Any]:
    manifest_path = challenge.with_suffix(".manifest.json")
    if not challenge.exists():
        run(
            [str(PYTHON), "scripts/build_nlu_focused_challenge_v1.py", "--output", str(challenge)],
            stage="BUILD_CHALLENGE",
            run_id=run_id,
        )
    if not manifest_path.exists():
        raise FileNotFoundError(f"challenge manifest missing: {manifest_path}")
    manifest = read_json(manifest_path)
    actual = sha256_file(challenge)
    if actual != manifest.get("sha256"):
        raise RuntimeError(f"challenge SHA256 mismatch: {actual} != {manifest.get('sha256')}")
    if manifest.get("test_split_opened") is not False:
        raise RuntimeError("challenge manifest test guard is not safe")
    return manifest


def semantic(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def candidate_report(gold: Path, prediction: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    scored, total = evaluate_files(gold, prediction)
    gold_rows = {row["sample_id"]: row for row in read_jsonl(gold)}
    pred_rows = {row["sample_id"]: row for row in read_jsonl(prediction)}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_latencies: dict[str, list[float]] = defaultdict(list)
    for score in scored:
        sid = score["sample_id"]
        scenario = gold_rows[sid]["metadata"]["scenario"]
        grouped[scenario].append(score)
        latency = pred_rows[sid].get("latency_ms")
        if isinstance(latency, (int, float)):
            group_latencies[scenario].append(float(latency))
    per_scenario = {
        name: summarize(rows, group_latencies.get(name, []))
        for name, rows in sorted(grouped.items())
    }
    compact = {
        "sample_count": total["sample_count"],
        "exact_match": total["exact_match"],
        "intent_accuracy": total["intent_accuracy"],
        "slot_accuracy": total["slot_accuracy"],
        "json_schema_valid_rate": total["json_schema_valid_rate"],
        "invalid_menu_output_rate": total["invalid_menu_output_rate"],
        "error_code_accuracy": total["error_code_accuracy"],
        "multi_command_order_accuracy": total["multi_command_order_accuracy"],
        "warm_latency_ms": total["warm_latency_ms"],
        "failure_counts": total["failure_counts"],
    }
    return scored, compact, per_scenario


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"focus3-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--challenge", type=Path, default=DEFAULT_CHALLENGE)
    parser.add_argument("--qwen17-merged", type=Path, default=DEFAULT_17_MERGED)
    parser.add_argument("--qwen17-nf4-adapter", type=Path, default=DEFAULT_17_NF4)
    parser.add_argument("--qwen06-merged", type=Path, default=DEFAULT_06_MERGED)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rerun", action="store_true", help="rerun candidate predictions even if complete artifacts already exist")
    args = parser.parse_args()

    out_dir = ROOT / "models/nlu/focused-benchmarks" / args.run_id
    final_path = out_dir / "final-summary.json"
    ensure_no_test_path(args.challenge, args.qwen17_merged, args.qwen17_nf4_adapter, args.qwen06_merged, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not PYTHON.exists():
        raise FileNotFoundError(PYTHON)
    for path in (args.qwen17_merged, args.qwen17_nf4_adapter, args.qwen06_merged):
        if not path.exists():
            raise FileNotFoundError(path)

    challenge_manifest = ensure_challenge(args.challenge, run_id=args.run_id)
    sample_count = int(challenge_manifest["sample_count"])
    print("[CHALLENGE]", json.dumps(challenge_manifest, ensure_ascii=False), flush=True)

    candidate_paths = {
        "qwen17b_resident_cascade": out_dir / "qwen17b-resident-cascade.jsonl",
        "qwen06b_promptlookup5": out_dir / "qwen06b-promptlookup5.jsonl",
        "qwen06b_promptlookup8": out_dir / "qwen06b-promptlookup8.jsonl",
    }

    commands = {
        "qwen17b_resident_cascade": [
            str(PYTHON), "scripts/run_nlu_qwen3_1p7b_reference_cascade.py",
            "--validation", str(args.challenge),
            "--merged-model", str(args.qwen17_merged),
            "--nf4-adapter", str(args.qwen17_nf4_adapter),
            "--output", str(candidate_paths["qwen17b_resident_cascade"]),
            "--limit", str(sample_count),
            "--max-new-tokens", "96",
            "--prompt-lookup-num-tokens", "8",
        ],
        "qwen06b_promptlookup5": [
            str(PYTHON), "scripts/run_nlu_qwen06b_prediction.py",
            "--input", str(args.challenge),
            "--output", str(candidate_paths["qwen06b_promptlookup5"]),
            "--model-format", "merged",
            "--merged-model", str(args.qwen06_merged),
            "--experiment-id", f"{args.run_id}-qwen06b-promptlookup5",
            "--warmup-count", "5",
            "--max-new-tokens", "96",
            "--cache-implementation", "dynamic",
            "--prompt-lookup-num-tokens", "5",
        ],
        "qwen06b_promptlookup8": [
            str(PYTHON), "scripts/run_nlu_qwen06b_prediction.py",
            "--input", str(args.challenge),
            "--output", str(candidate_paths["qwen06b_promptlookup8"]),
            "--model-format", "merged",
            "--merged-model", str(args.qwen06_merged),
            "--experiment-id", f"{args.run_id}-qwen06b-promptlookup8",
            "--warmup-count", "5",
            "--max-new-tokens", "96",
            "--cache-implementation", "dynamic",
            "--prompt-lookup-num-tokens", "8",
        ],
    }

    if args.dry_run:
        print(json.dumps({"run_id": args.run_id, "challenge": challenge_manifest, "commands": commands}, ensure_ascii=False, indent=2))
        set_status("DRY_RUN", "PASS", run_id=args.run_id, detail=str(out_dir))
        return 0

    for label in ("qwen17b_resident_cascade", "qwen06b_promptlookup5", "qwen06b_promptlookup8"):
        output = candidate_paths[label]
        rows_ok = False
        if output.exists() and not args.rerun:
            try:
                rows_ok = len(read_jsonl(output)) == sample_count
            except Exception:
                rows_ok = False
        if rows_ok:
            print(f"[RESUME] {label}: reuse complete {sample_count}-row prediction", flush=True)
        else:
            run(commands[label], stage=f"RUN_{label.upper()}", run_id=args.run_id)

    gold_rows = {row["sample_id"]: row for row in read_jsonl(args.challenge)}
    all_scores: dict[str, dict[str, dict[str, Any]]] = {}
    reports: dict[str, Any] = {}
    predictions: dict[str, dict[str, dict[str, Any]]] = {}

    for label, path in candidate_paths.items():
        scores, summary, per_scenario = candidate_report(args.challenge, path)
        all_scores[label] = {row["sample_id"]: row for row in scores}
        predictions[label] = {row["sample_id"]: row for row in read_jsonl(path)}
        runtime: dict[str, Any] = {}
        if label == "qwen17b_resident_cascade":
            summary_path = path.with_suffix(".summary.json")
            if summary_path.exists():
                runtime = read_json(summary_path)
        else:
            manifest_path = path.with_suffix(".manifest.json")
            if manifest_path.exists():
                runtime = read_json(manifest_path)
        reports[label] = {
            "summary": summary,
            "per_scenario": per_scenario,
            "runtime": runtime,
        }

    labels = list(candidate_paths)
    pairwise: dict[str, Any] = {}
    for i, left in enumerate(labels):
        for right in labels[i + 1 :]:
            semantic_equal = 0
            left_exact_right_wrong = 0
            right_exact_left_wrong = 0
            for sid in gold_rows:
                if semantic(predictions[left][sid].get("prediction")) == semantic(predictions[right][sid].get("prediction")):
                    semantic_equal += 1
                le = bool(all_scores[left][sid]["exact_match"])
                re = bool(all_scores[right][sid]["exact_match"])
                left_exact_right_wrong += int(le and not re)
                right_exact_left_wrong += int(re and not le)
            pairwise[f"{left}__vs__{right}"] = {
                "semantic_equal": semantic_equal,
                "semantic_changed": sample_count - semantic_equal,
                "left_exact_right_wrong": left_exact_right_wrong,
                "right_exact_left_wrong": right_exact_left_wrong,
            }

    disagreements = []
    all_correct = 0
    all_wrong = 0
    unique_wins = {label: 0 for label in labels}
    for sid, gold in gold_rows.items():
        correct = {label: bool(all_scores[label][sid]["exact_match"]) for label in labels}
        count = sum(correct.values())
        all_correct += int(count == len(labels))
        all_wrong += int(count == 0)
        if count == 1:
            unique_wins[next(label for label, ok in correct.items() if ok)] += 1
        semantic_values = [canonical_json(semantic(predictions[label][sid].get("prediction"))) for label in labels]
        if len(set(semantic_values)) > 1 or count not in (0, len(labels)):
            disagreements.append(
                {
                    "sample_id": sid,
                    "scenario": gold["metadata"]["scenario"],
                    "utterance": gold["input"]["utterance"],
                    "gold": gold["output"]["value"],
                    "correct": correct,
                    "predictions": {label: semantic(predictions[label][sid].get("prediction")) for label in labels},
                }
            )

    ranking = sorted(
        labels,
        key=lambda label: (
            reports[label]["summary"]["exact_match"] or 0,
            reports[label]["summary"]["json_schema_valid_rate"] or 0,
            reports[label]["summary"]["error_code_accuracy"] or 0,
            -((reports[label]["summary"]["warm_latency_ms"] or {}).get("p95") or 10**9),
        ),
        reverse=True,
    )

    final = {
        "state": "PASS",
        "run_id": args.run_id,
        "challenge": challenge_manifest,
        "warning": "focused-v1 is a synthetic contract stress suite, not a pristine final generalization holdout.",
        "test_split_opened": False,
        "candidates": reports,
        "objective_ranking": ranking,
        "pairwise": pairwise,
        "all_correct_count": all_correct,
        "all_wrong_count": all_wrong,
        "unique_exact_wins": unique_wins,
        "disagreement_count": len(disagreements),
        "disagreements_path": str(out_dir / "disagreements.json"),
    }
    write_json(out_dir / "disagreements.json", disagreements)
    write_json(final_path, final)
    set_status("FINAL", "PASS", run_id=args.run_id, detail=str(final_path))
    print("\n[FINAL] PASS", flush=True)
    print(f"summary={final_path}", flush=True)
    print(json.dumps({"ranking": ranking, "unique_exact_wins": unique_wins, "all_correct": all_correct, "all_wrong": all_wrong, "disagreements": len(disagreements)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        run_id = "unknown"
        try:
            run_id = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--run-id=")), "unknown")
        except Exception:
            pass
        set_status("FAILED", "FAILED", run_id=run_id, detail=f"{type(exc).__name__}: {exc}")
        raise
