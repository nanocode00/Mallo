"""Verify that Qwen3-0.6B and the frozen Qwen3-1.7B tokenize validation identically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adapters.nlu.qwen06b_config import MODEL_ID as MODEL06_ID
from adapters.nlu.qwen06b_config import MODEL_REVISION as MODEL06_REVISION
from adapters.nlu.qwen06b_config import reject_test_path
from adapters.nlu.qwen_qlora_train import MODEL_ID as MODEL17_ID
from adapters.nlu.qwen_qlora_train import MODEL_REVISION as MODEL17_REVISION
from adapters.nlu.qwen_training_data import DEFAULT_OUTPUT_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, default=DEFAULT_OUTPUT_DIR / "validation.jsonl")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reject_test_path(args.validation, label="validation")
    if args.report:
        reject_test_path(args.report, label="report")

    from transformers import AutoTokenizer

    options06 = {"revision": MODEL06_REVISION, "local_files_only": not args.allow_download}
    options17 = {"revision": MODEL17_REVISION, "local_files_only": not args.allow_download}
    tokenizer06 = AutoTokenizer.from_pretrained(MODEL06_ID, **options06)
    tokenizer17 = AutoTokenizer.from_pretrained(MODEL17_ID, **options17)
    for tokenizer in (tokenizer06, tokenizer17):
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "right"

    special = {
        "eos_token_id": (tokenizer17.eos_token_id, tokenizer06.eos_token_id),
        "pad_token_id": (tokenizer17.pad_token_id, tokenizer06.pad_token_id),
        "bos_token_id": (tokenizer17.bos_token_id, tokenizer06.bos_token_id),
        "vocab_size": (len(tokenizer17), len(tokenizer06)),
    }
    mismatched_special = {key: value for key, value in special.items() if value[0] != value[1]}
    if mismatched_special:
        raise RuntimeError(f"1.7B/0.6B tokenizer special-token mismatch: {mismatched_special}")

    rows = [json.loads(line) for line in args.validation.read_text(encoding="utf-8").splitlines()]
    mismatches: list[dict[str, object]] = []
    max_tokens = 0
    for row in rows:
        messages = row["messages"]
        ids17 = tokenizer17.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
            enable_thinking=False,
        )
        ids06 = tokenizer06.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
            enable_thinking=False,
        )
        max_tokens = max(max_tokens, len(ids06))
        if ids17 != ids06:
            first_diff = next(
                (index for index, pair in enumerate(zip(ids17, ids06)) if pair[0] != pair[1]),
                min(len(ids17), len(ids06)),
            )
            mismatches.append(
                {
                    "sample_id": row.get("sample_id"),
                    "len_1p7b": len(ids17),
                    "len_0p6b": len(ids06),
                    "first_diff_index": first_diff,
                }
            )
            if len(mismatches) >= 10:
                break
    if mismatches:
        raise RuntimeError(
            "1.7B/0.6B validation tokenization이 동일하지 않습니다: "
            + json.dumps(mismatches, ensure_ascii=False)
        )

    vocab_equal = tokenizer17.get_vocab() == tokenizer06.get_vocab()
    report = {
        "status": "PASS",
        "model_1p7b": {"id": MODEL17_ID, "revision": MODEL17_REVISION},
        "model_0p6b": {"id": MODEL06_ID, "revision": MODEL06_REVISION},
        "validation_rows": len(rows),
        "validation_token_sequences_equal": True,
        "special_token_contract": special,
        "vocab_mapping_equal": vocab_equal,
        "chat_template_text_equal": tokenizer17.chat_template == tokenizer06.chat_template,
        "max_rendered_tokens": max_tokens,
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
