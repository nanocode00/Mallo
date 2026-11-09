"""Run a tiny BF16 LoRA training smoke test for Qwen3-0.6B without touching test data."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from adapters.nlu.qwen06b_config import (
    DEFAULT_SCRATCH_DIR,
    MODEL_ID,
    MODEL_REVISION,
    reject_test_path,
)
from scripts.train.nlu.qwen_qlora_train import TrainingConfig, detect_hardware, run_training

from adapters.nlu.qwen_training_data import DEFAULT_OUTPUT_DIR


def copy_prefix(source: Path, target: Path, count: int) -> None:
    reject_test_path(source, label="source")
    rows = source.read_text(encoding="utf-8").splitlines()
    if len(rows) < count:
        raise RuntimeError(f"smoke subset 부족: {source} has {len(rows)} rows")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(rows[:count]) + "\n", encoding="utf-8")


def adapter_nonzero_stats(adapter_dir: Path) -> dict[str, int]:
    from safetensors.torch import load_file

    tensor_path = adapter_dir / "adapter_model.safetensors"
    if not tensor_path.is_file():
        raise RuntimeError(f"adapter safetensors가 없습니다: {tensor_path}")
    tensors = load_file(str(tensor_path), device="cpu")
    lora_tensors = {name: tensor for name, tensor in tensors.items() if "lora_" in name}
    if not lora_tensors:
        raise RuntimeError("LoRA tensor가 저장되지 않았습니다")
    nonzero_tensors = sum(int(tensor.count_nonzero().item()) > 0 for tensor in lora_tensors.values())
    nonzero_values = sum(int(tensor.count_nonzero().item()) for tensor in lora_tensors.values())
    if nonzero_tensors == 0 or nonzero_values == 0:
        raise RuntimeError("학습 후 LoRA tensor가 모두 0입니다")
    return {
        "lora_tensor_count": len(lora_tensors),
        "nonzero_lora_tensors": nonzero_tensors,
        "nonzero_lora_values": nonzero_values,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=DEFAULT_OUTPUT_DIR / "train.jsonl")
    parser.add_argument("--validation", type=Path, default=DEFAULT_OUTPUT_DIR / "validation.jsonl")
    parser.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH_DIR / "smoke")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    for label, path in (("train", args.train), ("validation", args.validation), ("scratch", args.scratch)):
        reject_test_path(path, label=label)
    if args.report:
        reject_test_path(args.report, label="report")

    import torch

    if args.scratch.exists():
        shutil.rmtree(args.scratch)
    subset_dir = args.scratch / "data"
    train_subset = subset_dir / "train.jsonl"
    validation_subset = subset_dir / "validation.jsonl"
    copy_prefix(args.train, train_subset, 8)
    copy_prefix(args.validation, validation_subset, 4)

    output_dir = args.scratch / "experiment"
    config = TrainingConfig(
        train_path=train_subset,
        validation_path=validation_subset,
        output_dir=output_dir,
        model_id=MODEL_ID,
        revision=MODEL_REVISION,
        epochs=1.0,
        learning_rate=2e-4,
        micro_batch_size=2,
        gradient_accumulation_steps=1,
        lora_r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        seed=42,
        training_precision="bf16",
        allow_download=args.allow_download,
    )
    hardware = detect_hardware()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    adapter_dir = run_training(config, hardware)
    elapsed = time.perf_counter() - started
    peak_allocated = torch.cuda.max_memory_allocated()
    peak_reserved = torch.cuda.max_memory_reserved()
    manifest_path = output_dir / "training-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("smoke training manifest가 생성되지 않았습니다")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    train_loss = manifest.get("train_metrics", {}).get("train_loss")
    if not isinstance(train_loss, (int, float)) or train_loss != train_loss:
        raise RuntimeError(f"finite train loss를 확인할 수 없습니다: {train_loss}")
    tensor_stats = adapter_nonzero_stats(adapter_dir)

    report = {
        "status": "PASS",
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "train_rows": 8,
        "validation_rows": 4,
        "training_precision": "bf16",
        "micro_batch_size": 2,
        "gradient_accumulation_steps": 1,
        "train_loss": train_loss,
        "elapsed_seconds": elapsed,
        "peak_allocated_bytes": peak_allocated,
        "peak_reserved_bytes": peak_reserved,
        "adapter_dir": str(adapter_dir),
        **tensor_stats,
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
