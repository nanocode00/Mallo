"""Resume the Qwen3-0.6B overnight sweep from durable per-stage artifacts.

This wrapper imports the max overnight sweep, then replaces the per-variant training pipeline
with a resumable implementation. Completed training, merge, and validation artifacts are reused
only after their contracts are checked. The frozen test split is never exposed.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import run_nlu_qwen06b_overnight_max as max_runner


sweep = max_runner.sweep
ORIGINAL_TRAIN_MERGE_VALIDATE = sweep.train_merge_validate


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON object가 필요합니다: {path}")
    return payload


def _same_number(actual: Any, expected: float | int) -> bool:
    try:
        return abs(float(actual) - float(expected)) < 1e-12
    except (TypeError, ValueError):
        return False


def _validate_training_manifest(path: Path, variant: Any) -> dict[str, Any]:
    manifest = _read_json(path)
    config = manifest.get("config")
    if not isinstance(config, dict):
        raise RuntimeError("training-manifest.config가 없습니다")
    expected = {
        "epochs": variant.epochs,
        "learning_rate": variant.learning_rate,
        "micro_batch_size": variant.micro_batch_size,
        "gradient_accumulation_steps": variant.gradient_accumulation_steps,
        "lora_r": variant.lora_r,
        "lora_alpha": variant.lora_alpha,
        "lora_dropout": variant.lora_dropout,
        "seed": variant.seed,
    }
    mismatches = {
        key: {"actual": config.get(key), "expected": value}
        for key, value in expected.items()
        if not _same_number(config.get(key), value)
    }
    if config.get("training_precision") != "bf16":
        mismatches["training_precision"] = {
            "actual": config.get("training_precision"),
            "expected": "bf16",
        }
    if config.get("model_id") != sweep.MODEL_ID:
        mismatches["model_id"] = {
            "actual": config.get("model_id"),
            "expected": sweep.MODEL_ID,
        }
    if config.get("revision") != sweep.MODEL_REVISION:
        mismatches["revision"] = {
            "actual": config.get("revision"),
            "expected": sweep.MODEL_REVISION,
        }
    if mismatches:
        raise RuntimeError(f"partial training config mismatch: {mismatches}")
    return manifest


def _prediction_complete(prediction: Path) -> bool:
    manifest = prediction.with_suffix(".manifest.json")
    if not prediction.is_file() or not manifest.is_file():
        return False
    rows = prediction.read_text(encoding="utf-8").splitlines()
    if len(rows) != 300:
        return False
    payload = _read_json(manifest)
    return (
        payload.get("sample_count") == 300
        and payload.get("split") == "validation"
        and payload.get("model_id") == sweep.MODEL_ID
        and payload.get("model_format") == "merged"
    )


def _archive(path: Path, *, reason: str) -> Path:
    target = path.with_name(f"{path.name}.interrupted-{int(time.time())}")
    print(f"[RESUME] archive {path} -> {target} ({reason})", flush=True)
    path.rename(target)
    return target


def _build_result(
    variant: Any,
    *,
    run_dir: Path,
    training_manifest: dict[str, Any],
    prediction: Path,
    eval_summary: Path,
    resumed_stages: list[str],
) -> dict[str, Any]:
    merged_summary = _read_json(eval_summary)
    pred_manifest = _read_json(prediction.with_suffix(".manifest.json"))
    adapter = run_dir / "final-adapter"
    merged = run_dir / "merged-bf16"
    payload = {
        "state": "PASS",
        "variant": {
            "name": variant.name,
            "epochs": variant.epochs,
            "learning_rate": variant.learning_rate,
            "micro_batch_size": variant.micro_batch_size,
            "gradient_accumulation_steps": variant.gradient_accumulation_steps,
            "lora_r": variant.lora_r,
            "lora_alpha": variant.lora_alpha,
            "lora_dropout": variant.lora_dropout,
            "seed": variant.seed,
        },
        "elapsed_seconds": None,
        "best_checkpoint": training_manifest.get("best_model_checkpoint"),
        "best_metric": training_manifest.get("best_metric"),
        "merged_summary": merged_summary,
        "quality_gate": sweep.quality_gate(merged_summary),
        "prediction_sha256": sweep.prediction_sha(prediction),
        "peak_vram_allocated": pred_manifest.get("peak_vram_allocated"),
        "peak_vram_reserved": pred_manifest.get("peak_vram_reserved"),
        "model_id": sweep.MODEL_ID,
        "revision": sweep.MODEL_REVISION,
        "test_split_opened": False,
        "resumed_from_partial": True,
        "resumed_stages": resumed_stages,
        "paths": {
            "run_dir": str(run_dir),
            "adapter": str(adapter),
            "merged": str(merged),
        },
    }
    sweep.write_json(run_dir / "variant-summary.json", payload)
    return payload


def resumable_train_merge_validate(
    variant: Any,
    *,
    sweep_root: Path,
    sweep_id: str,
) -> dict[str, Any]:
    run_dir = sweep_root / variant.name
    result_path = run_dir / "variant-summary.json"
    if result_path.is_file():
        existing = _read_json(result_path)
        if existing.get("state") == "PASS":
            print(f"[RESUME] {variant.name}: completed summary exists", flush=True)
            return existing

    if not run_dir.exists() or not any(run_dir.iterdir()):
        return ORIGINAL_TRAIN_MERGE_VALIDATE(
            variant,
            sweep_root=sweep_root,
            sweep_id=sweep_id,
        )

    adapter = run_dir / "final-adapter"
    training_manifest_path = run_dir / "training-manifest.json"
    if not adapter.is_dir() or not training_manifest_path.is_file():
        _archive(run_dir, reason="training stage incomplete")
        return ORIGINAL_TRAIN_MERGE_VALIDATE(
            variant,
            sweep_root=sweep_root,
            sweep_id=sweep_id,
        )

    training_manifest = _validate_training_manifest(training_manifest_path, variant)
    resumed_stages = ["training"]
    print(f"[RESUME] {variant.name}: reuse completed training", flush=True)

    merged = run_dir / "merged-bf16"
    merge_manifest = merged / "merge-manifest.json"
    if not merged.is_dir() or not merge_manifest.is_file():
        if merged.exists():
            if merged.is_dir():
                shutil.rmtree(merged)
            else:
                merged.unlink()
        sweep.run(
            [
                str(sweep.PYTHON),
                "scripts/merge_nlu_qwen06b_adapter.py",
                "--adapter",
                str(adapter),
                "--output",
                str(merged),
            ],
            stage="MERGE",
            sweep_id=sweep_id,
            variant=variant.name,
        )
    else:
        resumed_stages.append("merge")
        print(f"[RESUME] {variant.name}: reuse completed merge", flush=True)

    eval_dir = run_dir / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)
    prediction = eval_dir / "validation-merged-dynamic.jsonl"
    eval_summary = eval_dir / "validation-merged-dynamic-summary.json"

    if not _prediction_complete(prediction):
        for path in (prediction, prediction.with_suffix(".manifest.json")):
            if path.exists():
                path.unlink()
        sweep.run(
            [
                str(sweep.PYTHON),
                "scripts/run_nlu_qwen06b_prediction.py",
                "--model-format",
                "merged",
                "--merged-model",
                str(merged),
                "--experiment-id",
                f"{sweep_id}-{variant.name}-merged-dynamic",
                "--output",
                str(prediction),
            ],
            stage="VALIDATION",
            sweep_id=sweep_id,
            variant=variant.name,
        )
        if not _prediction_complete(prediction):
            raise RuntimeError(f"validation prediction completion contract 실패: {prediction}")
    else:
        resumed_stages.append("validation")
        print(f"[RESUME] {variant.name}: reuse completed validation 300/300", flush=True)

    if not eval_summary.is_file():
        sweep.run(
            [
                str(sweep.PYTHON),
                "-m",
                "scripts.eval.nlu.model_evaluator",
                "--gold",
                str(sweep.GOLD),
                "--predictions",
                str(prediction),
                "--summary",
                str(eval_summary),
            ],
            stage="EVALUATE",
            sweep_id=sweep_id,
            variant=variant.name,
        )
    else:
        resumed_stages.append("evaluation")
        print(f"[RESUME] {variant.name}: reuse completed evaluation", flush=True)

    return _build_result(
        variant,
        run_dir=run_dir,
        training_manifest=training_manifest,
        prediction=prediction,
        eval_summary=eval_summary,
        resumed_stages=resumed_stages,
    )


sweep.train_merge_validate = resumable_train_merge_validate


if __name__ == "__main__":
    raise SystemExit(sweep.main())
