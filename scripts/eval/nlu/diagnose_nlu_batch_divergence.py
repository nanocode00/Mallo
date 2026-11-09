"""Qwen NLU batch=1/8 첫 생성 분기의 입력과 logits를 진단한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from adapters.nlu.qwen_prediction_runner import generation_options, inference_messages
from scripts.train.nlu.qwen_qlora_train import MODEL_ID, MODEL_REVISION, detect_hardware

from adapters.nlu.qwen_training_data import build_system_prompt


def read_records(path: Path, limit: int) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[:limit]]


def top_logits(logits: Any, tokenizer: Any, count: int = 5) -> dict[str, Any]:
    values, ids = logits.float().topk(count)
    rows = [
        {
            "token_id": int(token_id),
            "token": tokenizer.decode([int(token_id)]),
            "logit": float(value),
        }
        for value, token_id in zip(values, ids, strict=True)
    ]
    return {"top5": rows, "top1_top2_margin": rows[0]["logit"] - rows[1]["logit"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=64)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    hardware = detect_hardware()
    dtype = torch.bfloat16 if hardware.bf16_supported else torch.float16
    load_options = {"revision": MODEL_REVISION, "local_files_only": True}
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **load_options)
    initial_padding_side = tokenizer.padding_side
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        ),
        device_map={"": 0},
        dtype=dtype,
        **load_options,
    )
    model = PeftModel.from_pretrained(model, str(args.adapter), is_trainable=False)
    model.eval()
    model.generation_config.do_sample = False
    model.generation_config.temperature = None
    model.generation_config.top_p = None
    model.generation_config.top_k = None

    records = read_records(args.input, args.limit)
    target_index = next(i for i, row in enumerate(records) if row["sample_id"] == args.sample_id)
    offset = target_index // args.batch_size * args.batch_size
    batch_records = records[offset : offset + args.batch_size]
    batch_target_index = target_index - offset
    target_record = records[target_index]
    system_prompt = build_system_prompt()

    def prepare(selected: list[dict[str, Any]]) -> Any:
        texts = [
            tokenizer.apply_chat_template(
                inference_messages(record, system_prompt),
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            for record in selected
        ]
        return tokenizer(texts, return_tensors="pt", padding=True).to(model.device)

    single_inputs = prepare([target_record])
    batch_inputs = prepare(batch_records)
    single_unpadded = single_inputs["input_ids"][0][single_inputs["attention_mask"][0].bool()]
    batch_unpadded = batch_inputs["input_ids"][batch_target_index][
        batch_inputs["attention_mask"][batch_target_index].bool()
    ]
    inputs_equal = torch.equal(single_unpadded.cpu(), batch_unpadded.cpu())

    options = generation_options(
        max_new_tokens=96,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    )

    def generate(inputs: Any) -> Any:
        with torch.inference_mode():
            return model.generate(
                **inputs,
                **options,
                return_dict_in_generate=True,
                output_logits=True,
            )

    single_output = generate(single_inputs)
    batch_output = generate(batch_inputs)
    single_generated = single_output.sequences[0, single_inputs["input_ids"].shape[1] :]
    batch_generated = batch_output.sequences[
        batch_target_index, batch_inputs["input_ids"].shape[1] :
    ]

    def trim_at_eos(ids: Any) -> Any:
        positions = (ids == tokenizer.eos_token_id).nonzero(as_tuple=False)
        return ids[: int(positions[0].item()) + 1] if positions.numel() else ids

    single_generated = trim_at_eos(single_generated)
    batch_generated = trim_at_eos(batch_generated)
    common = min(len(single_generated), len(batch_generated))
    divergence = next(
        (i for i in range(common) if single_generated[i] != batch_generated[i]),
        common if len(single_generated) != len(batch_generated) else None,
    )
    report: dict[str, Any] = {
        "sample_id": args.sample_id,
        "batch_ids": [row["sample_id"] for row in batch_records],
        "tokenizer": {
            "initial_padding_side": initial_padding_side,
            "effective_padding_side": tokenizer.padding_side,
            "pad_token_id": tokenizer.pad_token_id,
            "pad_token": tokenizer.pad_token,
            "eos_token_id": tokenizer.eos_token_id,
            "eos_token": tokenizer.eos_token,
            "pad_equals_eos": tokenizer.pad_token_id == tokenizer.eos_token_id,
        },
        "attention_mask": {
            "single_present": "attention_mask" in single_inputs,
            "batch_present": "attention_mask" in batch_inputs,
            "single_nonpad_tokens": int(single_inputs["attention_mask"][0].sum()),
            "batch_target_nonpad_tokens": int(
                batch_inputs["attention_mask"][batch_target_index].sum()
            ),
            "batch_target_left_padding": int(
                (batch_inputs["attention_mask"][batch_target_index] == 0).sum()
            ),
        },
        "prompt_tokens": {
            "unpadded_equal": inputs_equal,
            "single_count": len(single_unpadded),
            "batch_target_count": len(batch_unpadded),
        },
        "generation": {
            "single_text": tokenizer.decode(single_generated, skip_special_tokens=True).strip(),
            "batch_text": tokenizer.decode(batch_generated, skip_special_tokens=True).strip(),
            "single_token_ids": single_generated.tolist(),
            "batch_token_ids": batch_generated.tolist(),
            "first_divergence_index": divergence,
        },
    }
    if divergence is not None and divergence < len(single_output.logits):
        report["generation"]["divergence_logits"] = {
            "single": top_logits(single_output.logits[divergence][0], tokenizer),
            "batch": top_logits(
                batch_output.logits[divergence][batch_target_index], tokenizer
            ),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
