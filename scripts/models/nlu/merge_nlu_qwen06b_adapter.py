"""Merge the pinned Qwen3-0.6B BF16 LoRA adapter into a standalone BF16 model."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from adapters.nlu.qwen06b_config import MODEL_ID, MODEL_REVISION, reject_test_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    for label, path in (("adapter", args.adapter), ("output", args.output)):
        reject_test_path(path, label=label)
    if not args.adapter.is_dir():
        parser.error(f"adapter 디렉터리가 없습니다: {args.adapter}")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error(f"비어 있지 않은 output 디렉터리는 덮어쓰지 않습니다: {args.output}")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    load_options = {
        "revision": MODEL_REVISION,
        "local_files_only": not args.allow_download,
    }
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **load_options)
    base = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.bfloat16,
        device_map={"": "cpu"},
        **load_options,
    )
    peft_model = PeftModel.from_pretrained(base, str(args.adapter), is_trainable=False)
    merged = peft_model.merge_and_unload(safe_merge=True)
    merged.to(dtype=torch.bfloat16)
    args.output.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(args.output, safe_serialization=True, max_shard_size="2GB")
    tokenizer.save_pretrained(args.output)
    manifest = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "adapter": str(args.adapter),
        "output": str(args.output),
        "merge_compute_dtype": "bfloat16",
        "output_dtype": "bfloat16",
        "safe_merge": True,
        "elapsed_seconds": time.perf_counter() - started,
        "test_split_opened": False,
    }
    (args.output / "merge-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
