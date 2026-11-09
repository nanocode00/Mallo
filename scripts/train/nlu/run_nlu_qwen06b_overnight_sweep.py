"""Run an overnight validation-only Qwen3-0.6B BF16 LoRA sweep for Mallo NLU.

The frozen test split is never exposed. The sweep intentionally uses validation for
hyperparameter comparison; any final production claim still requires a fresh unseen holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from adapters.nlu.qwen06b_config import MODEL_ID, MODEL_REVISION, reject_test_path


ROOT = Path(__file__).resolve().parents[3]
PYTHON = Path(sys.executable)
GOLD = ROOT / "data/nlu/processed/validation.jsonl"
PREFLIGHT = ROOT / "scratch/nlu-qwen06b/preflight/preflight.ok.json"
STATUS = ROOT / "logs/nlu-qwen06b.status"


@dataclass(frozen=True)
class Variant:
    name: str
    epochs: float = 3.0
    learning_rate: float = 2e-4
    micro_batch_size: int = 2
    gradient_accumulation_steps: int = 8
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    seed: int = 42


INITIAL_VARIANTS = (
    Variant("baseline_e3_lr2e4_r16"),
    Variant("lr1e4", learning_rate=1e-4),
    Variant("lr1p5e4", learning_rate=1.5e-4),
    Variant("lr2p5e4", learning_rate=2.5e-4),
    Variant("lr3e4", learning_rate=3e-4),
    Variant("epochs2", epochs=2.0),
    Variant("epochs4", epochs=4.0),
    Variant("lora_r8", lora_r=8, lora_alpha=16),
    Variant("lora_r32", lora_r=32, lora_alpha=64),
    Variant("dropout0", lora_dropout=0.0),
    Variant("mb4_ga4", micro_batch_size=4, gradient_accumulation_steps=4),
    Variant("mb8_ga2", micro_batch_size=8, gradient_accumulation_steps=2),
)


class StageFailure(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def status(stage: str, state: str, *, sweep_id: str, detail: str = "", variant: str = "") -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(
        "\n".join(
            [
                f"stage={stage}",
                f"state={state}",
                f"sweep_id={sweep_id}",
                f"variant={variant}",
                f"detail={detail}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def check_preflight(sweep_id: str) -> None:
    status("PRECHECK", "RUNNING", sweep_id=sweep_id)
    if not PREFLIGHT.is_file():
        raise StageFailure("preflight marker가 없습니다")
    marker = read_json(PREFLIGHT)
    if marker.get("status") != "PASS":
        raise StageFailure("preflight marker가 PASS가 아닙니다")
    current = git_sha()
    if marker.get("git_sha") != current:
        raise StageFailure(f"preflight 이후 Git SHA 변경: {marker.get('git_sha')} -> {current}")
    if marker.get("model_id") != MODEL_ID or marker.get("model_revision") != MODEL_REVISION:
        raise StageFailure("preflight model identity가 현재 sweep과 다릅니다")
    if marker.get("test_split_opened") is not False:
        raise StageFailure("preflight test guard 상태가 안전하지 않습니다")


def run(command: list[str], *, stage: str, sweep_id: str, variant: str = "") -> None:
    status(stage, "RUNNING", sweep_id=sweep_id, variant=variant, detail=" ".join(command))
    print(f"[{stage}] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def prediction_sha(path: Path) -> str:
    digest = hashlib.sha256()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        digest.update(
            canonical_json({"sample_id": row["sample_id"], "prediction": row.get("prediction")}).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def quality_gate(summary: dict[str, Any]) -> dict[str, bool]:
    latency = summary.get("warm_latency_ms", {})
    median = latency.get("median")
    return {
        "exact_gte_0_90": (summary.get("exact_match") or 0) >= 0.90,
        "schema_gte_0_98": (summary.get("json_schema_valid_rate") or 0) >= 0.98,
        "invalid_menu_eq_0": summary.get("invalid_menu_output_rate") == 0,
        "median_lt_1s": median is not None and median < 1000,
    }


def rank_key(result: dict[str, Any]) -> tuple[Any, ...]:
    summary = result.get("merged_summary") or {}
    gate = quality_gate(summary) if summary else {}
    quality_pass = all(gate.get(key, False) for key in ("exact_gte_0_90", "schema_gte_0_98", "invalid_menu_eq_0"))
    median = (summary.get("warm_latency_ms") or {}).get("median")
    return (
        int(result.get("state") == "PASS"),
        int(quality_pass),
        summary.get("exact_match") or 0,
        summary.get("json_schema_valid_rate") or 0,
        summary.get("error_code_accuracy") or 0,
        -(median if isinstance(median, (int, float)) else 10**9),
    )


def train_merge_validate(variant: Variant, *, sweep_root: Path, sweep_id: str) -> dict[str, Any]:
    run_dir = sweep_root / variant.name
    result_path = run_dir / "variant-summary.json"
    if result_path.is_file():
        existing = read_json(result_path)
        if existing.get("state") == "PASS":
            print(f"[SKIP] {variant.name}: completed summary exists", flush=True)
            return existing
    if run_dir.exists() and any(run_dir.iterdir()):
        raise StageFailure(f"partial/non-empty variant directory는 자동 덮어쓰기하지 않습니다: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    eval_dir = run_dir / "evaluations"
    adapter = run_dir / "final-adapter"
    merged = run_dir / "merged-bf16"
    prediction = eval_dir / "validation-merged-dynamic.jsonl"
    eval_summary = eval_dir / "validation-merged-dynamic-summary.json"
    started = time.perf_counter()

    train_cmd = [
        str(PYTHON), "scripts/run_nlu_qwen06b_training.py",
        "--output-dir", str(run_dir),
        "--epochs", str(variant.epochs),
        "--learning-rate", str(variant.learning_rate),
        "--micro-batch-size", str(variant.micro_batch_size),
        "--gradient-accumulation-steps", str(variant.gradient_accumulation_steps),
        "--lora-r", str(variant.lora_r),
        "--lora-alpha", str(variant.lora_alpha),
        "--lora-dropout", str(variant.lora_dropout),
        "--seed", str(variant.seed),
    ]
    run(train_cmd, stage="TRAINING", sweep_id=sweep_id, variant=variant.name)
    run(
        [str(PYTHON), "scripts/merge_nlu_qwen06b_adapter.py", "--adapter", str(adapter), "--output", str(merged)],
        stage="MERGE", sweep_id=sweep_id, variant=variant.name,
    )
    run(
        [
            str(PYTHON), "scripts/run_nlu_qwen06b_prediction.py",
            "--model-format", "merged",
            "--merged-model", str(merged),
            "--experiment-id", f"{sweep_id}-{variant.name}-merged-dynamic",
            "--output", str(prediction),
        ],
        stage="VALIDATION", sweep_id=sweep_id, variant=variant.name,
    )
    run(
        [
            str(PYTHON), "-m", "scripts.eval.nlu.model_evaluator",
            "--gold", str(GOLD), "--predictions", str(prediction), "--summary", str(eval_summary),
        ],
        stage="EVALUATE", sweep_id=sweep_id, variant=variant.name,
    )
    merged_summary = read_json(eval_summary)
    pred_manifest = read_json(prediction.with_suffix(".manifest.json"))
    train_manifest = read_json(run_dir / "training-manifest.json")
    payload = {
        "state": "PASS",
        "variant": asdict(variant),
        "elapsed_seconds": time.perf_counter() - started,
        "best_checkpoint": train_manifest.get("best_model_checkpoint"),
        "best_metric": train_manifest.get("best_metric"),
        "merged_summary": merged_summary,
        "quality_gate": quality_gate(merged_summary),
        "prediction_sha256": prediction_sha(prediction),
        "peak_vram_allocated": pred_manifest.get("peak_vram_allocated"),
        "peak_vram_reserved": pred_manifest.get("peak_vram_reserved"),
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "test_split_opened": False,
        "paths": {"run_dir": str(run_dir), "adapter": str(adapter), "merged": str(merged)},
    }
    write_json(result_path, payload)
    return payload


def safe_train_variant(variant: Variant, *, sweep_root: Path, sweep_id: str) -> dict[str, Any]:
    try:
        return train_merge_validate(variant, sweep_root=sweep_root, sweep_id=sweep_id)
    except Exception as exc:  # keep the overnight sweep progressing across experimental failures
        payload = {
            "state": "FAILED",
            "variant": asdict(variant),
            "error": f"{type(exc).__name__}: {exc}",
            "test_split_opened": False,
        }
        write_json(sweep_root / variant.name / "variant-summary.json", payload)
        print(f"[VARIANT FAILED] {variant.name}: {payload['error']}", flush=True)
        return payload


def prediction_rows(path: Path) -> dict[str, dict[str, Any]]:
    return {row["sample_id"]: row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def semantic_prediction(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return object()


def inference_benchmark(
    *,
    label: str,
    merged: Path,
    baseline_prediction: Path,
    output_dir: Path,
    sweep_id: str,
    extra_args: list[str],
) -> dict[str, Any]:
    output = output_dir / f"validation-{label}.jsonl"
    summary_path = output_dir / f"validation-{label}-summary.json"
    try:
        run(
            [
                str(PYTHON), "scripts/run_nlu_qwen06b_prediction.py",
                "--model-format", "merged",
                "--merged-model", str(merged),
                "--experiment-id", f"{sweep_id}-{label}",
                "--output", str(output),
                *extra_args,
            ],
            stage="INFERENCE_BENCH", sweep_id=sweep_id, variant=label,
        )
        run(
            [
                str(PYTHON), "-m", "scripts.eval.nlu.model_evaluator",
                "--gold", str(GOLD), "--predictions", str(output), "--summary", str(summary_path),
            ],
            stage="INFERENCE_EVAL", sweep_id=sweep_id, variant=label,
        )
        baseline = prediction_rows(baseline_prediction)
        candidate = prediction_rows(output)
        byte_equal = 0
        semantic_equal = 0
        changed = []
        for sample_id, base in baseline.items():
            cand = candidate[sample_id]
            if base.get("prediction") == cand.get("prediction"):
                byte_equal += 1
            if semantic_prediction(base.get("prediction")) == semantic_prediction(cand.get("prediction")):
                semantic_equal += 1
            else:
                changed.append(sample_id)
        manifest = read_json(output.with_suffix(".manifest.json"))
        return {
            "state": "PASS",
            "label": label,
            "summary": read_json(summary_path),
            "prediction_sha256": prediction_sha(output),
            "byte_equal": byte_equal,
            "semantic_equal": semantic_equal,
            "semantic_changed_sample_ids": changed,
            "peak_vram_allocated": manifest.get("peak_vram_allocated"),
            "peak_vram_reserved": manifest.get("peak_vram_reserved"),
            "target_forward_steps": manifest.get("target_forward_steps"),
            "test_split_opened": False,
        }
    except Exception as exc:
        print(f"[INFERENCE FAILED] {label}: {exc}", flush=True)
        return {"state": "FAILED", "label": label, "error": f"{type(exc).__name__}: {exc}"}


def peft_merge_parity(result: dict[str, Any], *, sweep_root: Path, sweep_id: str) -> dict[str, Any]:
    variant_name = result["variant"]["name"]
    run_dir = Path(result["paths"]["run_dir"])
    adapter = Path(result["paths"]["adapter"])
    merged_prediction = run_dir / "evaluations/validation-merged-dynamic.jsonl"
    output = run_dir / "evaluations/validation-peft.jsonl"
    summary_path = run_dir / "evaluations/validation-peft-summary.json"
    try:
        run(
            [
                str(PYTHON), "scripts/eval/nlu/run_nlu_qwen06b_prediction.py",
                "--model-format", "peft", "--adapter", str(adapter),
                "--experiment-id", f"{sweep_id}-{variant_name}-peft",
                "--output", str(output),
            ],
            stage="PEFT_PARITY", sweep_id=sweep_id, variant=variant_name,
        )
        run(
            [str(PYTHON), "-m", "scripts.eval.nlu.model_evaluator", "--gold", str(GOLD), "--predictions", str(output), "--summary", str(summary_path)],
            stage="PEFT_EVAL", sweep_id=sweep_id, variant=variant_name,
        )
        base = prediction_rows(merged_prediction)
        peft = prediction_rows(output)
        changed = [sample_id for sample_id in base if base[sample_id].get("prediction") != peft[sample_id].get("prediction")]
        semantic_changed = [
            sample_id for sample_id in base
            if semantic_prediction(base[sample_id].get("prediction")) != semantic_prediction(peft[sample_id].get("prediction"))
        ]
        return {
            "state": "PASS",
            "variant": variant_name,
            "summary": read_json(summary_path),
            "byte_changed_count": len(changed),
            "byte_changed_sample_ids": changed,
            "semantic_changed_count": len(semantic_changed),
            "semantic_changed_sample_ids": semantic_changed,
        }
    except Exception as exc:
        return {"state": "FAILED", "variant": variant_name, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-id", default=f"honorbear-{datetime.now().strftime('%Y%m%d-%H%M%S')}-qwen3-0p6b-overnight")
    parser.add_argument("--skip-seed-repeats", action="store_true")
    args = parser.parse_args()
    reject_test_path(Path(args.sweep_id), label="sweep-id")
    sweep_id = args.sweep_id
    sweep_root = ROOT / "models/nlu/qwen3-0.6b-sweeps" / sweep_id
    final_summary_path = sweep_root / "final-summary.json"
    sweep_root.mkdir(parents=True, exist_ok=True)

    try:
        check_preflight(sweep_id)
    except Exception as exc:
        status("PRECHECK", "FAILED", sweep_id=sweep_id, detail=str(exc))
        raise

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for index, variant in enumerate(INITIAL_VARIANTS, start=1):
        print(f"\n===== TRAIN VARIANT {index}/{len(INITIAL_VARIANTS)}: {variant.name} =====", flush=True)
        results.append(safe_train_variant(variant, sweep_root=sweep_root, sweep_id=sweep_id))
        write_json(sweep_root / "progress-summary.json", {"completed": index, "results": results})

    successful = sorted((row for row in results if row.get("state") == "PASS"), key=rank_key, reverse=True)
    seed_repeats: list[dict[str, Any]] = []
    if successful and not args.skip_seed_repeats:
        top_cfg = Variant(**successful[0]["variant"])
        for seed in (7, 123):
            repeated = replace(top_cfg, name=f"{top_cfg.name}_seed{seed}", seed=seed)
            print(f"\n===== SEED REPEAT: {repeated.name} =====", flush=True)
            result = safe_train_variant(repeated, sweep_root=sweep_root, sweep_id=sweep_id)
            results.append(result)
            seed_repeats.append(result)

    successful = sorted((row for row in results if row.get("state") == "PASS"), key=rank_key, reverse=True)
    parity: list[dict[str, Any]] = []
    for candidate in successful[:2]:
        parity.append(peft_merge_parity(candidate, sweep_root=sweep_root, sweep_id=sweep_id))

    inference_results: list[dict[str, Any]] = []
    if successful:
        top = successful[0]
        run_dir = Path(top["paths"]["run_dir"])
        merged = Path(top["paths"]["merged"])
        baseline_prediction = run_dir / "evaluations/validation-merged-dynamic.jsonl"
        bench_dir = run_dir / "inference-benchmarks"
        configs = [
            ("promptlookup3", ["--prompt-lookup-num-tokens", "3"]),
            ("promptlookup5", ["--prompt-lookup-num-tokens", "5"]),
            ("promptlookup8", ["--prompt-lookup-num-tokens", "8"]),
            ("static", ["--cache-implementation", "static"]),
            ("static_compile", ["--cache-implementation", "static", "--compile-mode", "reduce-overhead"]),
        ]
        for label, extra in configs:
            inference_results.append(
                inference_benchmark(
                    label=label,
                    merged=merged,
                    baseline_prediction=baseline_prediction,
                    output_dir=bench_dir,
                    sweep_id=sweep_id,
                    extra_args=extra,
                )
            )
        if len(successful) > 1:
            second = successful[1]
            second_run = Path(second["paths"]["run_dir"])
            inference_results.append(
                inference_benchmark(
                    label=f"second-{second['variant']['name']}-promptlookup8",
                    merged=Path(second["paths"]["merged"]),
                    baseline_prediction=second_run / "evaluations/validation-merged-dynamic.jsonl",
                    output_dir=second_run / "inference-benchmarks",
                    sweep_id=sweep_id,
                    extra_args=["--prompt-lookup-num-tokens", "8"],
                )
            )

    final = {
        "state": "PASS" if successful else "FAILED",
        "sweep_id": sweep_id,
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "git_sha": git_sha(),
        "elapsed_seconds": time.perf_counter() - started,
        "test_split_opened": False,
        "validation_tuning_warning": "Multiple variants were selected using validation. Do not treat validation ranking as a pristine final generalization estimate; use a fresh unseen holdout for a final v2 claim.",
        "reference_1p7b_resident_cascade": {
            "exact_match": 0.9667,
            "schema_valid": 0.9967,
            "invalid_menu": 0.0,
            "median_latency_ms": 1086,
            "p95_latency_ms": 1818,
            "fallback_rate": 0.0233,
        },
        "variant_count_requested": len(INITIAL_VARIANTS) + (0 if args.skip_seed_repeats or not successful else 2),
        "variant_results": results,
        "ranking": [
            {
                "rank": index,
                "name": row["variant"]["name"],
                "config": row["variant"],
                "summary": row["merged_summary"],
                "quality_gate": row["quality_gate"],
                "prediction_sha256": row["prediction_sha256"],
            }
            for index, row in enumerate(successful, start=1)
        ],
        "seed_repeats": seed_repeats,
        "top2_peft_vs_merged": parity,
        "top_inference_benchmarks": inference_results,
        "recommended_candidate": successful[0] if successful else None,
    }
    write_json(final_summary_path, final)
    state = final["state"]
    status("FINAL", state, sweep_id=sweep_id, detail=str(final_summary_path))
    print(f"\n[FINAL] {state}", flush=True)
    print(f"summary={final_summary_path}", flush=True)
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
