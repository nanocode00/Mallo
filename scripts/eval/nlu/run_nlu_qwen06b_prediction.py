"""Run validation-only predictions for the pinned Qwen3-0.6B NLU experiment.

This wrapper reuses the frozen 1.7B prediction engine while overriding its model identity in-process.
It deliberately does not expose the test split or final-test flags.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import adapters.nlu.qwen_prediction_runner as runner
from adapters.nlu.qwen06b_config import MODEL_ID, MODEL_REVISION, reject_test_path
from adapters.nlu.qwen_training_data import DEFAULT_PROCESSED_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_PROCESSED_DIR / "validation.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-format", choices=("peft", "merged"), required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--merged-model", type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--warmup-count", type=int, default=5)
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument("--cache-implementation", choices=("dynamic", "static"), default="dynamic")
    parser.add_argument("--compile-mode", choices=("none", "reduce-overhead"), default="none")
    parser.add_argument("--attention-backend", choices=("auto", "sdpa"), default="auto")
    parser.add_argument("--prompt-lookup-num-tokens", type=int)
    parser.add_argument("--max-matching-ngram-size", type=int)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()

    reject_test_path(args.input, label="input")
    reject_test_path(args.output, label="output")
    if args.adapter:
        reject_test_path(args.adapter, label="adapter")
    if args.merged_model:
        reject_test_path(args.merged_model, label="merged-model")
    if args.model_format == "peft" and args.adapter is None:
        parser.error("PEFT 평가에는 --adapter가 필요합니다")
    if args.model_format == "merged" and args.merged_model is None:
        parser.error("merged 평가에는 --merged-model이 필요합니다")
    if args.prompt_lookup_num_tokens is not None and args.prompt_lookup_num_tokens < 1:
        parser.error("prompt lookup token 수는 1 이상이어야 합니다")
    if args.compile_mode != "none" and args.cache_implementation != "static":
        parser.error("compile은 static cache에서만 허용합니다")

    runner.MODEL_ID = MODEL_ID
    runner.MODEL_REVISION = MODEL_REVISION
    config = runner.PredictionConfig(
        split="validation",
        variant="fine-tuned",
        input_path=args.input,
        output_path=args.output,
        adapter_path=args.adapter,
        experiment_id=args.experiment_id,
        final_test=False,
        allow_download=args.allow_download,
        max_new_tokens=args.max_new_tokens,
        warmup_count=args.warmup_count,
        prompt_profile="v1",
        generation_profile="clean-greedy",
        batch_size=1,
        limit=args.limit,
        precision="bf16",
        model_format=args.model_format,
        merged_model_path=args.merged_model,
        cache_implementation=args.cache_implementation,
        compile_mode=args.compile_mode,
        attention_backend=args.attention_backend,
        output_profile="canonical",
        sdpa_kernel_backend="auto",
        prefix_cache=False,
        prompt_lookup_num_tokens=args.prompt_lookup_num_tokens,
        max_matching_ngram_size=args.max_matching_ngram_size,
    )
    manifest = runner.run_predictions(config, runner.detect_hardware())
    manifest["experiment_model"] = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "test_split_opened": False,
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
