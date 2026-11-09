"""Qwen NLU PEFT adapter를 BF16 base model에 merge해 로컬 artifact로 저장한다."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from adapters.nlu.qwen_qlora_train import MODEL_ID, MODEL_REVISION


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-model", type=Path)
    parser.add_argument(
        "--merge-compute-dtype",
        choices=("bf16", "float32"),
        default="bf16",
        help="LoRA merge 연산 dtype. 저장 artifact는 항상 BF16이다.",
    )
    args = parser.parse_args()
    if not args.adapter.is_dir():
        parser.error(f"adapter 디렉터리가 없습니다: {args.adapter}")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error(f"비어 있지 않은 output 디렉터리는 덮어쓰지 않습니다: {args.output}")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    started = time.perf_counter()
    model_source = str(args.base_model) if args.base_model else MODEL_ID
    load_options = (
        {"local_files_only": True}
        if args.base_model
        else {"revision": MODEL_REVISION, "local_files_only": True}
    )
    tokenizer = AutoTokenizer.from_pretrained(model_source, **load_options)
    merge_dtype = torch.bfloat16 if args.merge_compute_dtype == "bf16" else torch.float32
    base = AutoModelForCausalLM.from_pretrained(
        model_source,
        dtype=merge_dtype,
        device_map={"": "cpu"},
        **load_options,
    )
    peft_model = PeftModel.from_pretrained(base, str(args.adapter), is_trainable=False)
    merged = peft_model.merge_and_unload(safe_merge=True)
    if merge_dtype != torch.bfloat16:
        merged.to(dtype=torch.bfloat16)
    args.output.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(args.output, safe_serialization=True, max_shard_size="2GB")
    tokenizer.save_pretrained(args.output)
    manifest = {
        "model_id": MODEL_ID,
        "base_model_source": model_source,
        "revision": MODEL_REVISION,
        "adapter": str(args.adapter),
        "merge_compute_dtype": args.merge_compute_dtype,
        "output_dtype": "bfloat16",
        "safe_merge": True,
        "elapsed_seconds": time.perf_counter() - started,
    }
    (args.output / "merge-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
