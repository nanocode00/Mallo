"""Verify Qwen3-0.6B model/tokenizer/BF16/LoRA compatibility for Mallo NLU."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adapters.nlu.qwen06b_config import (
    MODEL_ID,
    MODEL_PARAMETER_COUNT,
    MODEL_REVISION,
    reject_test_path,
)
from adapters.nlu.qwen_training_data import DEFAULT_OUTPUT_DIR, build_system_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, default=DEFAULT_OUTPUT_DIR / "validation.jsonl")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reject_test_path(args.validation, label="validation")
    if args.report:
        reject_test_path(args.report, label="report")

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU가 없습니다")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("GPU가 BF16을 지원하지 않습니다")

    load_options = {
        "revision": MODEL_REVISION,
        "local_files_only": not args.allow_download,
    }
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **load_options)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    rows = args.validation.read_text(encoding="utf-8").splitlines()
    if not rows:
        raise RuntimeError("validation이 비어 있습니다")
    first = json.loads(rows[0])
    messages = first.get("messages")
    if not isinstance(messages, list) or len(messages) != 3:
        raise RuntimeError("validation conversation 계약이 아닙니다")
    expected_system = build_system_prompt()
    if messages[0].get("content") != expected_system:
        raise RuntimeError("validation system prompt가 canonical prompt와 다릅니다")

    rendered = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    token_ids = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    if not rendered or not token_ids:
        raise RuntimeError("Qwen chat template 렌더링 실패")
    if len(token_ids) > 2048:
        raise RuntimeError(f"첫 validation sample이 max_length 2048을 초과합니다: {len(token_ids)}")

    torch.cuda.reset_peak_memory_stats()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.bfloat16,
        device_map={"": 0},
        attn_implementation="sdpa",
        **load_options,
    )
    actual_parameters = sum(parameter.numel() for parameter in model.parameters())
    if actual_parameters != MODEL_PARAMETER_COUNT:
        raise RuntimeError(
            f"parameter count 불일치: {actual_parameters} != {MODEL_PARAMETER_COUNT}"
        )
    architecture = type(model).__name__
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    peft_model = get_peft_model(
        model,
        LoraConfig(
            task_type="CAUSAL_LM",
            target_modules="all-linear",
            r=16,
            lora_alpha=32,
            lora_dropout=0.05,
            bias="none",
        ),
    )
    trainable = sum(p.numel() for p in peft_model.parameters() if p.requires_grad)
    if trainable <= 0:
        raise RuntimeError("all-linear LoRA trainable parameter가 0입니다")

    report = {
        "status": "PASS",
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "architecture": architecture,
        "parameter_count": actual_parameters,
        "bf16_supported": True,
        "attention_backend": getattr(peft_model.config, "_attn_implementation", None),
        "tokenizer": {
            "vocab_size": len(tokenizer),
            "eos_token": tokenizer.eos_token,
            "eos_token_id": tokenizer.eos_token_id,
            "pad_token": tokenizer.pad_token,
            "pad_token_id": tokenizer.pad_token_id,
            "padding_side": tokenizer.padding_side,
            "chat_template_present": bool(tokenizer.chat_template),
            "first_validation_tokens": len(token_ids),
            "non_thinking_template": "<think>" in rendered or "/no_think" in expected_system,
        },
        "lora": {
            "target_modules": "all-linear",
            "r": 16,
            "alpha": 32,
            "dropout": 0.05,
            "trainable_parameters": trainable,
        },
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "test_split_opened": False,
    }
    rendered_report = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
