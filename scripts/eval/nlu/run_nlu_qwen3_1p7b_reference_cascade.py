"""Qwen3-1.7B merged BF16 + resident NF4 validation-only reference cascade benchmark.

REFERENCE ONLY: this script does not validate the Qwen3-0.6B service path integrated by PR #209.
Use qwen06b_nlu.py / HTTP NLU sidecar for the current 0.6B service candidate.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from scripts.eval.nlu.model_evaluator import NLUEvaluator, summarize

from adapters.nlu.qwen_prediction_runner import generation_options, inference_messages
from adapters.nlu.qwen_training_data import build_system_prompt, canonical_json


REFERENCE_SCOPE = "reference_only_not_qwen3_0p6b_service_validation"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, __import__("math").ceil(fraction * len(ordered)) - 1)]


def gpu_used_mib() -> int | None:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            text=True,
        )
        own_pid = str(__import__("os").getpid())
        return sum(int(line.split(",")[1].strip()) for line in output.splitlines() if line.split(",")[0].strip() == own_pid)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--merged-model", type=Path, required=True)
    parser.add_argument("--nf4-adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument("--prompt-lookup-num-tokens", type=int, default=8)
    args = parser.parse_args()
    if "test" in str(args.validation).lower() or "test" in str(args.output).lower():
        raise ValueError("test split/artifact 접근 금지")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    records = [json.loads(line) for line in args.validation.read_text(encoding="utf-8").splitlines()][: args.limit]
    tokenizer = AutoTokenizer.from_pretrained(args.merged_model, local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    system_prompt = build_system_prompt()
    load_started = time.perf_counter()
    merged = AutoModelForCausalLM.from_pretrained(
        args.merged_model, torch_dtype=torch.bfloat16, device_map={"": 0}, local_files_only=True,
        attn_implementation="sdpa",
    ).eval()
    merged_load_ms = (time.perf_counter() - load_started) * 1000
    merged_vram = gpu_used_mib()
    base_id = json.loads((args.nf4_adapter / "adapter_config.json").read_text(encoding="utf-8"))["base_model_name_or_path"]
    load_started = time.perf_counter()
    nf4_base = AutoModelForCausalLM.from_pretrained(
        base_id, local_files_only=True, device_map={"": 0},
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True),
        attn_implementation="sdpa",
    )
    nf4 = PeftModel.from_pretrained(nf4_base, args.nf4_adapter, local_files_only=True).eval()
    nf4_load_ms = (time.perf_counter() - load_started) * 1000
    total_vram = gpu_used_mib()
    evaluator = NLUEvaluator()
    results: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    merged_latencies: list[float] = []
    fallback_latencies: list[float] = []
    overall_latencies: list[float] = []

    def generate(model: Any, record: dict[str, Any], *, lookup: bool) -> tuple[str, list[int], float]:
        messages = inference_messages(record, system_prompt)
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = tokenizer(text, return_tensors="pt").to("cuda")
        options = generation_options(max_new_tokens=args.max_new_tokens, eos_token_id=tokenizer.eos_token_id, pad_token_id=tokenizer.pad_token_id)
        if lookup:
            options["prompt_lookup_num_tokens"] = args.prompt_lookup_num_tokens
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(**inputs, **options)
        torch.cuda.synchronize()
        latency = (time.perf_counter() - started) * 1000
        ids = generated[0, inputs["input_ids"].shape[1] :].tolist()
        return tokenizer.decode(ids, skip_special_tokens=True).strip(), ids, latency

    for model, lookup in ((merged, True), (nf4, False)):
        generate(model, records[0], lookup=lookup)
    torch.cuda.reset_peak_memory_stats()
    wall_started = time.perf_counter()
    for record in records:
        merged_text, merged_ids, merged_ms = generate(merged, record, lookup=True)
        merged_score = evaluator.score(record, merged_text)
        fallback_used = not merged_score["schema_valid"]
        final_text, final_ids, fallback_ms = merged_text, merged_ids, None
        if fallback_used:
            final_text, final_ids, fallback_ms = generate(nf4, record, lookup=False)
            fallback_latencies.append(fallback_ms)
        total_ms = merged_ms + (fallback_ms or 0.0)
        merged_latencies.append(merged_ms)
        overall_latencies.append(total_ms)
        results.append(evaluator.score(record, final_text))
        outputs.append({"sample_id": record["sample_id"], "prediction": final_text, "generated_token_ids": final_ids, "merged_latency_ms": merged_ms, "fallback_used": fallback_used, "fallback_latency_ms": fallback_ms, "latency_ms": total_ms})
    wall_seconds = time.perf_counter() - wall_started
    metrics = summarize(results, overall_latencies)
    normal_latencies = [x for x, o in zip(merged_latencies, outputs) if not o["fallback_used"]]
    fallback_request_latencies = [o["latency_ms"] for o in outputs if o["fallback_used"]]
    report = {
        "benchmark_scope": REFERENCE_SCOPE,
        "sample_count": len(records), "fallback_count": len(fallback_latencies),
        "fallback_rate": len(fallback_latencies) / len(records), "metrics": metrics,
        "overall_latency_ms": {"median": statistics.median(overall_latencies), "p95": percentile(overall_latencies, 0.95)},
        "normal_merged_only_latency_ms": ({"median": statistics.median(normal_latencies), "p95": percentile(normal_latencies, 0.95)} if normal_latencies else None),
        "fallback_request_latency_ms": ({"median": statistics.median(fallback_request_latencies), "p95": percentile(fallback_request_latencies, 0.95)} if fallback_request_latencies else None),
        "wall_time_seconds": wall_seconds, "cold_load_ms": {"merged": merged_load_ms, "nf4": nf4_load_ms},
        "nvidia_smi_process_mib": {"merged_only": merged_vram, "both_resident": total_vram, "nf4_increment": (total_vram - merged_vram if total_vram is not None and merged_vram is not None else None)},
        "pytorch_peak_bytes": {"allocated": torch.cuda.max_memory_allocated(), "reserved": torch.cuda.max_memory_reserved()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(canonical_json(row) + "\n" for row in outputs), encoding="utf-8")
    args.output.with_suffix(".summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
