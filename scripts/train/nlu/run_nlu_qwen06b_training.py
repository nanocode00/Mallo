"""Train the pinned Qwen3-0.6B Mallo NLU baseline with BF16-native LoRA.

Only train/validation inputs are accepted. Test paths are rejected.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adapters.nlu.qwen06b_config import (
    DEFAULT_RUN_DIR,
    MODEL_ID,
    MODEL_PARAMETER_COUNT,
    MODEL_REVISION,
    MODEL_WEIGHT_BYTES,
    reject_test_path,
)
from scripts.train.nlu.qwen_qlora_train import TrainingConfig, detect_hardware, run_training

from adapters.nlu.qwen_training_data import DEFAULT_OUTPUT_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=DEFAULT_OUTPUT_DIR / "train.jsonl")
    parser.add_argument("--validation", type=Path, default=DEFAULT_OUTPUT_DIR / "validation.jsonl")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--micro-batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for label, path in (
        ("train", args.train),
        ("validation", args.validation),
        ("output", args.output_dir),
    ):
        reject_test_path(path, label=label)
    if args.lora_r < 1 or args.lora_alpha < 1:
        parser.error("LoRA r/alpha는 1 이상이어야 합니다")
    if not 0 <= args.lora_dropout < 1:
        parser.error("LoRA dropout은 [0, 1) 범위여야 합니다")

    config = TrainingConfig(
        train_path=args.train,
        validation_path=args.validation,
        output_dir=args.output_dir,
        model_id=MODEL_ID,
        revision=MODEL_REVISION,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        micro_batch_size=args.micro_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        seed=args.seed,
        training_precision="bf16",
        allow_download=args.allow_download,
    )
    hardware = detect_hardware()
    if args.dry_run:
        report = {
            "status": "DRY_RUN",
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "parameter_count": MODEL_PARAMETER_COUNT,
            "model_weight_bytes": MODEL_WEIGHT_BYTES,
            "train": str(config.train_path),
            "validation": str(config.validation_path),
            "output_dir": str(config.output_dir),
            "epochs": config.epochs,
            "learning_rate": config.learning_rate,
            "micro_batch_size": config.micro_batch_size,
            "gradient_accumulation_steps": config.gradient_accumulation_steps,
            "lora_r": config.lora_r,
            "lora_alpha": config.lora_alpha,
            "lora_dropout": config.lora_dropout,
            "seed": config.seed,
            "training_precision": config.training_precision,
            "cuda_available": hardware.cuda_available,
            "bf16_supported": hardware.bf16_supported,
            "total_vram_bytes": hardware.total_vram_bytes,
            "test_split_opened": False,
        }
        config.validate()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    adapter_dir = run_training(config, hardware)
    manifest_path = args.output_dir / "training-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experiment_model"] = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "parameter_count": MODEL_PARAMETER_COUNT,
        "model_weight_bytes": MODEL_WEIGHT_BYTES,
        "training_precision": "bf16",
        "epochs": config.epochs,
        "learning_rate": config.learning_rate,
        "micro_batch_size": config.micro_batch_size,
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "lora_r": config.lora_r,
        "lora_alpha": config.lora_alpha,
        "lora_dropout": config.lora_dropout,
        "seed": config.seed,
        "test_split_opened": False,
    }
    if isinstance(manifest.get("model_download"), dict):
        manifest["model_download"]["required_bytes"] = MODEL_WEIGHT_BYTES
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"Qwen3-0.6B BF16 LoRA 학습 완료: {adapter_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
