"""Run the maximum Qwen3-0.6B overnight sweep and reuse a completed baseline when safe.

The first sweep variant is identical to the standalone BF16 baseline. If that baseline has
already completed, this wrapper validates its frozen configuration and artifacts, then imports
it into the sweep instead of training it again. Any mismatch falls back to normal retraining.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import run_nlu_qwen06b_overnight_sweep as sweep


sweep.INITIAL_VARIANTS = sweep.INITIAL_VARIANTS + (
    sweep.Variant("mb16_ga1", micro_batch_size=16, gradient_accumulation_steps=1),
)

BASELINE_VARIANT_NAME = "baseline_e3_lr2e4_r16"
DEFAULT_BASELINE_DIR = (
    sweep.ROOT
    / "models/nlu/qwen3-0.6b-lora/honorbear-20260825-qwen3-0p6b-bf16-lora-v1"
)
ORIGINAL_SAFE_TRAIN_VARIANT = sweep.safe_train_variant


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


def _require_baseline_contract(source: Path, variant: sweep.Variant) -> dict[str, Any]:
    final_summary_path = source / "final-summary.json"
    training_manifest_path = source / "training-manifest.json"
    adapter = source / "final-adapter"
    merged = source / "merged-bf16"
    prediction = source / "evaluations/validation-bf16-merged.jsonl"
    prediction_manifest = prediction.with_suffix(".manifest.json")

    required = (
        final_summary_path,
        training_manifest_path,
        adapter,
        merged,
        prediction,
        prediction_manifest,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"baseline artifact 누락: {missing}")

    final = _read_json(final_summary_path)
    manifest = _read_json(training_manifest_path)
    if final.get("status") != "PASS":
        raise RuntimeError("standalone baseline final-summary가 PASS가 아닙니다")
    if final.get("model_id") != sweep.MODEL_ID or final.get("revision") != sweep.MODEL_REVISION:
        raise RuntimeError("standalone baseline model identity가 sweep과 다릅니다")
    if final.get("test_split_opened") is not False:
        raise RuntimeError("standalone baseline test guard 상태가 안전하지 않습니다")

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
        mismatches["model_id"] = {"actual": config.get("model_id"), "expected": sweep.MODEL_ID}
    if config.get("revision") != sweep.MODEL_REVISION:
        mismatches["revision"] = {
            "actual": config.get("revision"),
            "expected": sweep.MODEL_REVISION,
        }
    if mismatches:
        raise RuntimeError(f"standalone baseline config mismatch: {mismatches}")

    merged_block = final.get("merged")
    if not isinstance(merged_block, dict) or not isinstance(merged_block.get("summary"), dict):
        raise RuntimeError("standalone baseline merged summary가 없습니다")
    return {
        "final": final,
        "manifest": manifest,
        "adapter": adapter,
        "merged": merged,
        "prediction": prediction,
        "prediction_manifest": prediction_manifest,
        "final_summary_path": final_summary_path,
    }


def _link(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.resolve() != source.resolve():
            raise RuntimeError(f"import target이 이미 다른 artifact를 가리킵니다: {target}")
        return
    target.symlink_to(source.resolve(), target_is_directory=source.is_dir())


def _import_completed_baseline(
    variant: sweep.Variant,
    *,
    sweep_root: Path,
    sweep_id: str,
) -> dict[str, Any] | None:
    source = Path(
        os.environ.get("NLU_QWEN06B_BASELINE_DIR", str(DEFAULT_BASELINE_DIR))
    ).expanduser()
    try:
        verified = _require_baseline_contract(source, variant)
        imported_dir = sweep_root / variant.name
        result_path = imported_dir / "variant-summary.json"
        if result_path.is_file():
            existing = _read_json(result_path)
            if existing.get("state") == "PASS":
                print(f"[BASELINE REUSE] existing imported result: {result_path}", flush=True)
                return existing
            raise RuntimeError(f"기존 imported baseline summary가 PASS가 아닙니다: {result_path}")

        adapter_link = imported_dir / "final-adapter"
        merged_link = imported_dir / "merged-bf16"
        prediction_link = imported_dir / "evaluations/validation-merged-dynamic.jsonl"
        prediction_manifest_link = prediction_link.with_suffix(".manifest.json")
        _link(verified["adapter"], adapter_link)
        _link(verified["merged"], merged_link)
        _link(verified["prediction"], prediction_link)
        _link(verified["prediction_manifest"], prediction_manifest_link)

        final = verified["final"]
        merged_block = final["merged"]
        merged_summary = merged_block["summary"]
        training = final.get("training") if isinstance(final.get("training"), dict) else {}
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
            "elapsed_seconds": training.get("elapsed_seconds"),
            "best_checkpoint": training.get("best_model_checkpoint"),
            "best_metric": training.get("best_metric"),
            "merged_summary": merged_summary,
            "quality_gate": sweep.quality_gate(merged_summary),
            "prediction_sha256": merged_block.get("prediction_sha256"),
            "peak_vram_allocated": merged_block.get("peak_vram_allocated"),
            "peak_vram_reserved": merged_block.get("peak_vram_reserved"),
            "model_id": sweep.MODEL_ID,
            "revision": sweep.MODEL_REVISION,
            "test_split_opened": False,
            "imported_baseline": True,
            "import_source": str(source),
            "import_source_summary": str(verified["final_summary_path"]),
            "paths": {
                "run_dir": str(imported_dir),
                "adapter": str(adapter_link),
                "merged": str(merged_link),
            },
        }
        sweep.write_json(result_path, payload)
        print(
            f"[BASELINE REUSE] imported completed standalone baseline -> {result_path}",
            flush=True,
        )
        return payload
    except Exception as exc:
        print(
            f"[BASELINE REUSE] unavailable/unsafe ({type(exc).__name__}: {exc}); retraining baseline",
            flush=True,
        )
        return None


def safe_train_variant_with_baseline_reuse(
    variant: sweep.Variant,
    *,
    sweep_root: Path,
    sweep_id: str,
) -> dict[str, Any]:
    if variant.name == BASELINE_VARIANT_NAME:
        imported = _import_completed_baseline(
            variant,
            sweep_root=sweep_root,
            sweep_id=sweep_id,
        )
        if imported is not None:
            return imported
    return ORIGINAL_SAFE_TRAIN_VARIANT(
        variant,
        sweep_root=sweep_root,
        sweep_id=sweep_id,
    )


sweep.safe_train_variant = safe_train_variant_with_baseline_reuse


if __name__ == "__main__":
    raise SystemExit(sweep.main())
