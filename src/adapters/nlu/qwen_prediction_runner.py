"""Qwen3 Baseline/Fine-tuned NLU prediction JSONL 생성 CLI."""

from __future__ import annotations

import argparse
import copy
from contextlib import nullcontext
import json
import math
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.train.nlu.qwen_qlora_train import (
        DEFAULT_RUN_DIR,
        MODEL_ID,
        MODEL_REVISION,
        HardwareReport,
        TrainingEnvironmentError,
        detect_hardware,
        require_training_hardware,
    )
except ImportError:
    from adapters.nlu.qwen_runtime import MODEL_ID, MODEL_REVISION

from adapters.nlu.qwen_training_data import (
    DEFAULT_PROCESSED_DIR,
    build_compact_system_prompt,
    build_compact_output_system_prompt,
    build_system_prompt,
    canonical_json,
)


DEFAULT_EVALUATION_DIR = DEFAULT_RUN_DIR / "evaluations"
DEFAULT_TEST_LEDGER = DEFAULT_EVALUATION_DIR / "test-runs.json"


class PredictionError(RuntimeError):
    """추론 입력, 실행 모드 또는 Test 단회 계약 위반."""


@dataclass(frozen=True)
class PredictionConfig:
    split: str
    variant: str
    input_path: Path
    output_path: Path
    adapter_path: Path | None = None
    experiment_id: str | None = None
    final_test: bool = False
    allow_download: bool = False
    max_new_tokens: int = 768
    warmup_count: int = 5
    prompt_profile: str = "v1"
    generation_profile: str = "current"
    batch_size: int = 1
    limit: int | None = None
    precision: str = "4bit"
    model_format: str = "peft"
    merged_model_path: Path | None = None
    cache_implementation: str = "dynamic"
    compile_mode: str = "none"
    attention_backend: str = "auto"
    output_profile: str = "canonical"
    sdpa_kernel_backend: str = "auto"
    prefix_cache: bool = False
    prefix_cache_gate_size: int = 0
    prompt_lookup_num_tokens: int | None = None
    max_matching_ngram_size: int | None = None
    ledger_path: Path = DEFAULT_TEST_LEDGER

    def validate(self) -> None:
        if self.split not in {"validation", "test"}:
            raise PredictionError("prediction은 validation 또는 test Split만 허용합니다")
        if self.variant not in {"baseline", "fine-tuned"}:
            raise PredictionError("variant는 baseline 또는 fine-tuned여야 합니다")
        if not self.input_path.is_file():
            raise PredictionError(f"평가 입력 파일이 없습니다: {self.input_path}")
        if self.variant == "fine-tuned" and self.model_format == "peft" and (
            self.adapter_path is None or not self.adapter_path.is_dir()
        ):
            raise PredictionError("Fine-tuned 평가에는 adapter 디렉터리가 필요합니다")
        if self.model_format not in {"peft", "merged"}:
            raise PredictionError("model format은 peft 또는 merged여야 합니다")
        if self.model_format == "merged" and (
            self.merged_model_path is None or not self.merged_model_path.is_dir()
        ):
            raise PredictionError("merged 평가에는 merged model 디렉터리가 필요합니다")
        if self.model_format == "merged" and self.precision != "bf16":
            raise PredictionError("merged model은 bf16 precision으로 평가해야 합니다")
        if self.cache_implementation not in {"dynamic", "static"}:
            raise PredictionError("cache implementation은 dynamic 또는 static이어야 합니다")
        if self.compile_mode not in {"none", "reduce-overhead"}:
            raise PredictionError("compile mode는 none 또는 reduce-overhead여야 합니다")
        if self.compile_mode != "none" and self.cache_implementation != "static":
            raise PredictionError("generation compile은 static cache에서만 허용합니다")
        if self.attention_backend not in {"auto", "sdpa", "flash_attention_2"}:
            raise PredictionError("attention backend가 올바르지 않습니다")
        if self.output_profile not in {"canonical", "compact"}:
            raise PredictionError("output profile은 canonical 또는 compact여야 합니다")
        if self.sdpa_kernel_backend not in {"auto", "flash-only"}:
            raise PredictionError("SDPA kernel backend는 auto 또는 flash-only여야 합니다")
        if self.sdpa_kernel_backend == "flash-only" and self.attention_backend not in {
            "auto",
            "sdpa",
        }:
            raise PredictionError("flash-only SDPA kernel은 sdpa attention에서만 허용합니다")
        if self.prefix_cache and (
            self.batch_size != 1
            or self.cache_implementation != "dynamic"
            or self.compile_mode != "none"
        ):
            raise PredictionError("prefix cache는 batch=1 Dynamic cache 비-compile 경로만 허용합니다")
        if self.prefix_cache_gate_size < 0:
            raise PredictionError("prefix cache gate size는 0 이상이어야 합니다")
        if self.prefix_cache_gate_size and not self.prefix_cache:
            raise PredictionError("prefix cache gate는 --prefix-cache와 함께 사용해야 합니다")
        if self.prefix_cache_gate_size == 1:
            raise PredictionError("A-B-A 검증을 위해 prefix cache gate size는 2 이상이어야 합니다")
        if self.prompt_lookup_num_tokens is not None and (
            self.prompt_lookup_num_tokens < 1 or self.batch_size != 1 or self.prefix_cache
        ):
            raise PredictionError("prompt lookup은 양수 token, batch=1, 비-prefix-cache 경로만 허용합니다")
        if self.max_matching_ngram_size is not None and (
            self.max_matching_ngram_size < 1 or self.prompt_lookup_num_tokens is None
        ):
            raise PredictionError("max matching ngram은 prompt lookup과 함께 양수로 지정해야 합니다")
        if self.split == "test" and (not self.final_test or not self.experiment_id):
            raise PredictionError("Test는 --final-test와 experiment ID가 모두 필요합니다")
        if self.max_new_tokens < 1 or self.warmup_count < 0:
            raise PredictionError("생성 길이는 양수, warmup은 0 이상이어야 합니다")
        if self.prompt_profile not in {"v1", "compact"}:
            raise PredictionError("prompt profile은 v1 또는 compact여야 합니다")
        if self.generation_profile not in {"current", "clean-greedy"}:
            raise PredictionError("generation profile은 current 또는 clean-greedy여야 합니다")
        if self.batch_size < 1 or (self.limit is not None and self.limit < 1):
            raise PredictionError("batch size와 limit은 양수여야 합니다")
        if self.precision not in {"4bit", "bf16"}:
            raise PredictionError("precision은 4bit 또는 bf16이어야 합니다")


def inference_messages(record: dict[str, Any], system_prompt: str) -> list[dict[str, str]]:
    try:
        utterance = record["input"]["utterance"]
        cart_before = record["input"]["cart_before"]
    except (KeyError, TypeError) as error:
        raise PredictionError("processed 평가 행의 input 필드가 누락됐습니다") from error
    if not isinstance(utterance, str) or not isinstance(cart_before, list):
        raise PredictionError("utterance는 문자열, cart_before는 배열이어야 합니다")
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": canonical_json({"utterance": utterance, "cart_before": cart_before}),
        },
    ]


def generation_options(*, max_new_tokens: int, eos_token_id: int, pad_token_id: int) -> dict[str, Any]:
    return {
        "do_sample": False,
        "max_new_tokens": max_new_tokens,
        "eos_token_id": eos_token_id,
        "pad_token_id": pad_token_id,
    }


def _metric_summary(values: list[float | int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "median": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)],
        "max": ordered[-1],
    }


def longest_common_token_prefix(token_sequences: list[list[int]]) -> list[int]:
    """최종 tokenizer token ID 배열들의 최대 공통 prefix를 반환한다."""

    if not token_sequences:
        raise PredictionError("공통 prefix를 계산할 token sequence가 없습니다")
    shortest = min(len(sequence) for sequence in token_sequences)
    prefix_length = 0
    for index in range(shortest):
        token_id = token_sequences[0][index]
        if any(sequence[index] != token_id for sequence in token_sequences[1:]):
            break
        prefix_length += 1
    if prefix_length == 0:
        raise PredictionError("validation prompt에 공통 token prefix가 없습니다")
    return token_sequences[0][:prefix_length]


def _prompt_component_tokens(tokenizer: Any, system_prompt: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    lines = system_prompt.splitlines()
    schema_lines = [
        line for line in lines if line.startswith(("Command 필드=", "Intent=", "필드=", "I="))
    ]
    menu_lines = [
        line for line in lines if line.startswith(("공식 카탈로그=", "ID(c=category"))
    ]
    instruction_lines = [line for line in lines if line not in schema_lines + menu_lines]

    def token_count(text: str) -> int:
        return len(tokenizer(text, add_special_tokens=False)["input_ids"])

    utterance_tokens = []
    cart_tokens = []
    user_payload_tokens = []
    for record in records:
        utterance = record["input"]["utterance"]
        cart_before = record["input"]["cart_before"]
        utterance_tokens.append(token_count(utterance))
        cart_tokens.append(token_count(canonical_json(cart_before)))
        user_payload_tokens.append(
            token_count(canonical_json({"utterance": utterance, "cart_before": cart_before}))
        )
    return {
        "system_prompt": token_count(system_prompt),
        "system_instructions": token_count("\n".join(instruction_lines)),
        "schema_contract": token_count("\n".join(schema_lines)),
        "menu_catalog": token_count("\n".join(menu_lines)),
        "utterance": _metric_summary(utterance_tokens),
        "cart_context": _metric_summary(cart_tokens),
        "user_payload": _metric_summary(user_payload_tokens),
    }


def _ledger_key(config: PredictionConfig) -> str:
    return f"{config.experiment_id}:{config.variant}"


def assert_test_run_available(config: PredictionConfig) -> None:
    config.validate()
    if config.split != "test" or not config.ledger_path.exists():
        return
    try:
        ledger = json.loads(config.ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PredictionError("Test 실행 ledger JSON이 손상됐습니다") from error
    if _ledger_key(config) in ledger.get("completed", {}):
        raise PredictionError("같은 실험·variant의 Test prediction은 이미 완료됐습니다")


def mark_test_run_complete(config: PredictionConfig, *, sample_count: int) -> None:
    if config.split != "test":
        return
    ledger = {"completed": {}}
    if config.ledger_path.exists():
        ledger = json.loads(config.ledger_path.read_text(encoding="utf-8"))
    ledger.setdefault("completed", {})[_ledger_key(config)] = {
        "sample_count": sample_count,
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "output": str(config.output_path),
    }
    config.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    config.ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _read_records(path: Path) -> list[dict[str, Any]]:
    records = []
    seen = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            record = json.loads(line)
            sample_id = record["sample_id"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise PredictionError(f"평가 JSONL 오류: {path}:{line_number}") from error
        if sample_id in seen:
            raise PredictionError(f"sample_id 중복: {sample_id}")
        seen.add(sample_id)
        records.append(record)
    if not records:
        raise PredictionError("평가 입력이 비어 있습니다")
    return records


COMMAND_FIELDS = (
    "intent",
    "target_item_id",
    "category_id",
    "quantity",
    "temperature",
    "query_tags",
    "detail_fields",
    "options",
)
OPTION_FIELDS = ("size", "extra_shots", "caffeine", "syrup_pumps", "ice_amount")
ERROR_FIELDS = ("code", "message", "command_index", "field", "candidates", "retryable")


def restore_compact_prediction(prediction: str) -> str:
    """생략된 nullable 의미 필드를 evaluator의 canonical 계약으로 복원한다."""

    try:
        payload = json.loads(prediction)
    except json.JSONDecodeError:
        return prediction
    if isinstance(payload, list):
        restored = []
        for row in payload:
            if not isinstance(row, dict):
                return prediction
            command = {field: row.get(field) for field in COMMAND_FIELDS}
            if isinstance(command["options"], dict):
                command["options"] = {
                    field: command["options"].get(field) for field in OPTION_FIELDS
                }
            restored.append(command)
        payload = restored
    elif isinstance(payload, dict):
        payload = {
            "code": payload.get("code"),
            "message": payload.get("message"),
            "command_index": payload.get("command_index"),
            "field": payload.get("field"),
            "candidates": payload.get("candidates"),
            "retryable": payload.get("retryable", True),
        }
    return canonical_json(payload)


class GPUUtilizationSampler:
    """nvidia-smi를 짧게 polling해 평가 구간 GPU utilization을 기록한다."""

    def __init__(self, interval_seconds: float = 0.25) -> None:
        self.interval_seconds = interval_seconds
        self.values: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        while not self._stop.is_set():
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                self.values.append(int(result.stdout.strip().splitlines()[0]))
            except (OSError, ValueError, subprocess.SubprocessError, IndexError):
                pass
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def summary(self) -> dict[str, float | int | None]:
        return {
            "sample_count": len(self.values),
            "mean_percent": statistics.mean(self.values) if self.values else None,
            "max_percent": max(self.values) if self.values else None,
        }


def run_predictions(config: PredictionConfig, hardware: HardwareReport) -> dict[str, Any]:
    config.validate()
    assert_test_run_available(config)
    try:
        require_training_hardware(hardware)
    except TrainingEnvironmentError as error:
        raise PredictionError(str(error)) from error
    try:
        import torch
        from torch.nn.attention import SDPBackend, sdpa_kernel
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            CompileConfig,
            DynamicCache,
        )
    except ImportError as error:
        raise PredictionError(f"NLU 추론 의존성이 없습니다: {error.name}") from error

    dtype = torch.bfloat16 if hardware.bf16_supported else torch.float16
    load_options: dict[str, Any] = {
        "revision": MODEL_REVISION,
        "local_files_only": not config.allow_download,
    }
    load_started = time.perf_counter()
    model_source = MODEL_ID if config.model_format == "peft" else str(config.merged_model_path)
    source_options = load_options if config.model_format == "peft" else {"local_files_only": True}
    # merged 비교에서도 PEFT 기준과 동일한 pinned tokenizer를 사용한다. 로컬 artifact
    # 경로로 tokenizer를 열면 Transformers의 regex 자동 판정 경로가 달라질 수 있다.
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **load_options)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    if config.batch_size > 1:
        tokenizer.padding_side = "left"
    model_options: dict[str, Any] = {
        "device_map": {"": 0},
        "dtype": dtype,
        **source_options,
    }
    if config.precision == "4bit":
        model_options["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        )
    if config.attention_backend != "auto":
        model_options["attn_implementation"] = config.attention_backend
    model = AutoModelForCausalLM.from_pretrained(model_source, **model_options)
    if config.variant == "fine-tuned" and config.model_format == "peft":
        try:
            from peft import PeftModel
        except ImportError as error:
            raise PredictionError(
                f"NLU PEFT 추론 의존성이 없습니다: {error.name}"
            ) from error
        model = PeftModel.from_pretrained(
            model,
            str(config.adapter_path),
            is_trainable=False,
        )
    model.eval()
    if config.generation_profile == "clean-greedy":
        model.generation_config.do_sample = False
        model.generation_config.temperature = None
        model.generation_config.top_p = None
        model.generation_config.top_k = None
    model_load_ms = (time.perf_counter() - load_started) * 1000
    all_records = _read_records(config.input_path)
    records = all_records[: config.limit] if config.limit is not None else all_records
    if config.output_profile == "compact":
        system_prompt = build_compact_output_system_prompt()
    elif config.prompt_profile == "v1":
        system_prompt = build_system_prompt()
    else:
        system_prompt = build_compact_system_prompt()
    prompt_components = _prompt_component_tokens(tokenizer, system_prompt, records)
    prompt_texts = [
        tokenizer.apply_chat_template(
            inference_messages(record, system_prompt),
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        for record in all_records
    ]
    prompt_token_ids = [tokenizer(text)["input_ids"] for text in prompt_texts]
    common_prefix_ids = longest_common_token_prefix(prompt_token_ids)
    prefix_token_count = len(common_prefix_ids)
    suffix_token_counts = [len(ids) - prefix_token_count for ids in prompt_token_ids]
    if any(ids[:prefix_token_count] != common_prefix_ids for ids in prompt_token_ids):
        raise PredictionError("validation prompt의 token ID 공통 prefix 검증에 실패했습니다")

    prefix_decoded = tokenizer.decode(common_prefix_ids, skip_special_tokens=False)
    # 최대 공통 prefix는 완전한 system role과 user role delimiter, 그리고 canonical
    # payload의 고정 key 일부까지만 포함해야 한다. 첫 request-dependent cart 값/utterance는
    # 모든 행의 token ID가 갈라지는 suffix에 남긴다.
    safe_role_boundary = '<|im_end|>\n<|im_start|>user\n{"cart_before'
    role_boundary_safe = prefix_decoded.endswith(safe_role_boundary)
    if not role_boundary_safe:
        raise PredictionError("공통 prefix가 안전한 user payload 경계에서 끝나지 않습니다")

    prefix_cache_template = None
    prefix_cache_create_ms = None
    if config.prefix_cache:
        prefix_input_ids = torch.tensor(
            [common_prefix_ids], dtype=torch.long, device=model.device
        )
        prefix_attention_mask = torch.ones_like(prefix_input_ids)
        prefix_cache_position = torch.arange(
            prefix_token_count, dtype=torch.long, device=model.device
        )
        torch.cuda.synchronize()
        prefix_started = time.perf_counter()
        with torch.inference_mode():
            prefix_output = model(
                input_ids=prefix_input_ids,
                attention_mask=prefix_attention_mask,
                past_key_values=DynamicCache(),
                cache_position=prefix_cache_position,
                use_cache=True,
            )
        torch.cuda.synchronize()
        prefix_cache_create_ms = (time.perf_counter() - prefix_started) * 1000
        prefix_cache_template = prefix_output.past_key_values
        if prefix_cache_template.get_seq_length() != prefix_token_count:
            raise PredictionError("prefill cache 길이가 공통 prefix token 수와 다릅니다")
    options = generation_options(
        max_new_tokens=config.max_new_tokens,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    )
    options["cache_implementation"] = config.cache_implementation
    if config.prompt_lookup_num_tokens is not None:
        options["prompt_lookup_num_tokens"] = config.prompt_lookup_num_tokens
    if config.max_matching_ngram_size is not None:
        options["max_matching_ngram_size"] = config.max_matching_ngram_size
    if config.compile_mode == "reduce-overhead":
        options["compile_config"] = CompileConfig(mode="reduce-overhead")

    def dynamo_counters() -> dict[str, dict[str, int]]:
        if config.compile_mode == "none":
            return {}
        return {
            group: {key: int(value) for key, value in values.items()}
            for group, values in torch._dynamo.utils.counters.items()
            if values
        }

    def format_result(
        *, prediction_ids: Any, latency_ms: float, tokenization_ms: float,
        input_tokens: int, cache_copy_ms: float = 0.0,
        request_prefill_ms: float = 0.0, decode_ms: float = 0.0,
        target_forward_steps: int | None = None,
    ) -> dict[str, Any]:
        eos_positions = (prediction_ids == tokenizer.eos_token_id).nonzero(as_tuple=False)
        eos_reached = bool(eos_positions.numel())
        if eos_reached:
            prediction_ids = prediction_ids[: int(eos_positions[0].item()) + 1]
        output_tokens = int(prediction_ids.shape[0])
        raw_prediction = tokenizer.decode(prediction_ids, skip_special_tokens=True).strip()
        prediction = (
            restore_compact_prediction(raw_prediction)
            if config.output_profile == "compact"
            else raw_prediction
        )
        return {
            "prediction": prediction,
            "raw_prediction": raw_prediction,
            "generated_token_ids": prediction_ids.tolist(),
            "latency_ms": latency_ms,
            "batch_latency_ms": latency_ms,
            "sample_processing_ms": latency_ms + tokenization_ms,
            "tokenization_ms": tokenization_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "eos_reached": eos_reached,
            "max_new_tokens_reached": output_tokens >= config.max_new_tokens and not eos_reached,
            "cache_copy_ms": cache_copy_ms,
            "request_prefill_ms": request_prefill_ms,
            "decode_ms": decode_ms,
            "target_forward_steps": target_forward_steps,
        }

    def generate_full(record: dict[str, Any]) -> dict[str, Any]:
        tokenization_started = time.perf_counter()
        text = tokenizer.apply_chat_template(
            inference_messages(record, system_prompt), tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        )
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        tokenization_ms = (time.perf_counter() - tokenization_started) * 1000
        torch.cuda.synchronize()
        started = time.perf_counter()
        target_forward_steps = 0
        hook_model = model.get_base_model() if hasattr(model, "get_base_model") else model

        def count_target_forward(_module: Any, _args: Any) -> None:
            nonlocal target_forward_steps
            target_forward_steps += 1

        forward_handle = hook_model.register_forward_pre_hook(count_target_forward)
        with torch.inference_mode():
            try:
                kernel_context = (
                    sdpa_kernel(SDPBackend.FLASH_ATTENTION)
                    if config.sdpa_kernel_backend == "flash-only"
                    else nullcontext()
                )
                with kernel_context:
                    output = model.generate(**inputs, **options)
            finally:
                forward_handle.remove()
        torch.cuda.synchronize()
        latency_ms = (time.perf_counter() - started) * 1000
        generated = output[:, inputs["input_ids"].shape[1] :]
        return format_result(
            prediction_ids=generated[0], latency_ms=latency_ms,
            tokenization_ms=tokenization_ms,
            input_tokens=int(inputs["attention_mask"][0].sum().item()),
            target_forward_steps=target_forward_steps,
        )

    def generate_full_batch(batch_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(batch_records) == 1:
            return [generate_full(batch_records[0])]
        tokenization_started = time.perf_counter()
        texts = [
            tokenizer.apply_chat_template(
                inference_messages(record, system_prompt), tokenize=False,
                add_generation_prompt=True, enable_thinking=False,
            )
            for record in batch_records
        ]
        inputs = tokenizer(texts, return_tensors="pt", padding=True).to(model.device)
        tokenization_ms = (time.perf_counter() - tokenization_started) * 1000
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            kernel_context = (
                sdpa_kernel(SDPBackend.FLASH_ATTENTION)
                if config.sdpa_kernel_backend == "flash-only"
                else nullcontext()
            )
            with kernel_context:
                output = model.generate(**inputs, **options)
        torch.cuda.synchronize()
        latency_ms = (time.perf_counter() - started) * 1000
        generated = output[:, inputs["input_ids"].shape[1]:]
        return [
            format_result(
                prediction_ids=prediction_ids,
                latency_ms=latency_ms,
                tokenization_ms=tokenization_ms / len(batch_records),
                input_tokens=int(inputs["attention_mask"][index].sum().item()),
            )
            for index, prediction_ids in enumerate(generated)
        ]

    def generate_prefix_cached(record: dict[str, Any]) -> dict[str, Any]:
        if prefix_cache_template is None:
            raise PredictionError("prefix cache template이 준비되지 않았습니다")
        tokenization_started = time.perf_counter()
        text = tokenizer.apply_chat_template(
            inference_messages(record, system_prompt), tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        )
        full_ids = tokenizer(text, return_tensors="pt")["input_ids"].to(model.device)
        if full_ids[0, :prefix_token_count].tolist() != common_prefix_ids:
            raise PredictionError("요청 prompt가 검증된 공통 prefix와 다릅니다")
        suffix_ids = full_ids[:, prefix_token_count:]
        tokenization_ms = (time.perf_counter() - tokenization_started) * 1000

        torch.cuda.synchronize()
        request_started = time.perf_counter()
        copy_started = time.perf_counter()
        request_cache = copy.deepcopy(prefix_cache_template)
        torch.cuda.synchronize()
        cache_copy_ms = (time.perf_counter() - copy_started) * 1000
        if request_cache.get_seq_length() != prefix_token_count:
            raise PredictionError("복사된 prefix cache 길이가 변경됐습니다")

        full_attention_mask = torch.ones(
            (1, full_ids.shape[1]), dtype=torch.long, device=model.device
        )
        suffix_cache_position = torch.arange(
            prefix_token_count, full_ids.shape[1], dtype=torch.long, device=model.device
        )
        prefill_events: list[Any] = []

        def prefill_start_hook(_module: Any, _args: Any) -> None:
            if not prefill_events:
                event = torch.cuda.Event(enable_timing=True)
                event.record()
                prefill_events.append(event)

        def prefill_end_hook(_module: Any, _args: Any, _output: Any) -> None:
            if len(prefill_events) == 1:
                event = torch.cuda.Event(enable_timing=True)
                event.record()
                prefill_events.append(event)

        hook_model = model.get_base_model() if hasattr(model, "get_base_model") else model
        pre_handle = hook_model.register_forward_pre_hook(prefill_start_hook)
        post_handle = hook_model.register_forward_hook(prefill_end_hook)
        try:
            with torch.inference_mode():
                prefix_generation_options = {
                    key: value for key, value in options.items()
                    if key != "cache_implementation"
                }
                output = model.generate(
                    input_ids=suffix_ids,
                    attention_mask=full_attention_mask,
                    past_key_values=request_cache,
                    cache_position=suffix_cache_position,
                    **prefix_generation_options,
                )
        finally:
            pre_handle.remove()
            post_handle.remove()
        torch.cuda.synchronize()
        if len(prefill_events) != 2:
            raise PredictionError("generate 첫 suffix prefill 계측에 실패했습니다")
        request_prefill_ms = prefill_events[0].elapsed_time(prefill_events[1])
        latency_ms = (time.perf_counter() - request_started) * 1000
        decode_ms = max(0.0, latency_ms - cache_copy_ms - request_prefill_ms)
        prediction_ids = output[0, suffix_ids.shape[1]:]
        return format_result(
            prediction_ids=prediction_ids, latency_ms=latency_ms,
            tokenization_ms=tokenization_ms, input_tokens=int(full_ids.shape[1]),
            cache_copy_ms=cache_copy_ms, request_prefill_ms=request_prefill_ms,
            decode_ms=decode_ms,
        )

    generate_one = generate_prefix_cached if config.prefix_cache else generate_full

    gate = None
    if config.prefix_cache_gate_size:
        gate_records = records[: min(config.prefix_cache_gate_size, len(records))]
        full_gate = [generate_full(record) for record in gate_records]
        cached_gate = [generate_prefix_cached(record) for record in gate_records]
        reverse_gate = {
            record["sample_id"]: generate_prefix_cached(record)
            for record in reversed(gate_records)
        }
        a_record = gate_records[0]
        a_first = generate_prefix_cached(a_record)
        _ = generate_prefix_cached(gate_records[1])
        a_second = generate_prefix_cached(a_record)
        fields = ("prediction", "generated_token_ids", "eos_reached")
        mismatches = [
            record["sample_id"] for record, full, cached in zip(
                gate_records, full_gate, cached_gate, strict=True
            ) if any(full[field] != cached[field] for field in fields)
        ]
        reverse_mismatches = [
            record["sample_id"] for record, cached in zip(
                gate_records, cached_gate, strict=True
            ) if any(cached[field] != reverse_gate[record["sample_id"]][field] for field in fields)
        ]
        aba_match = all(a_first[field] == a_second[field] for field in fields)
        gate = {
            "sample_count": len(gate_records),
            "full_vs_cached_mismatches": mismatches,
            "reverse_order_mismatches": reverse_mismatches,
            "a_b_a_sample_id": a_record["sample_id"],
            "a_b_a_match": aba_match,
            "passed": not mismatches and not reverse_mismatches and aba_match,
        }
        if not gate["passed"]:
            raise PredictionError(f"prefix cache correctness gate 실패: {gate}")

    cold_first_generation_ms = None
    for index in range(config.warmup_count):
        warmup = generate_one(records[index % len(records)])
        if index == 0:
            cold_first_generation_ms = warmup["latency_ms"]
    counters_after_warmup = dynamo_counters()
    torch.cuda.reset_peak_memory_stats()
    sampler = GPUUtilizationSampler()
    sampler.start()
    evaluation_started = time.perf_counter()
    predictions = []
    batch_latencies = []
    if config.prefix_cache:
        for record in records:
            result = generate_prefix_cached(record)
            batch_latencies.append(result["batch_latency_ms"])
            predictions.append({"sample_id": record["sample_id"], **result})
    else:
        for offset in range(0, len(records), config.batch_size):
            batch_records = records[offset:offset + config.batch_size]
            batch_results = generate_full_batch(batch_records)
            batch_latencies.append(batch_results[0]["batch_latency_ms"])
            predictions.extend(
                {"sample_id": record["sample_id"], **result}
                for record, result in zip(batch_records, batch_results, strict=True)
            )
    evaluation_wall_seconds = time.perf_counter() - evaluation_started
    sampler.stop()
    counters_after_evaluation = dynamo_counters()
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_path.write_text(
        "".join(canonical_json(row) + "\n" for row in predictions), encoding="utf-8"
    )
    manifest = {
        "sample_count": len(predictions),
        "variant": config.variant,
        "split": config.split,
        "model_id": MODEL_ID,
        "model_source": model_source,
        "revision": MODEL_REVISION,
        "max_new_tokens": config.max_new_tokens,
        "warmup_count": config.warmup_count,
        "prompt_profile": config.prompt_profile,
        "generation_profile": config.generation_profile,
        "batch_size": config.batch_size,
        "precision": config.precision,
        "model_format": config.model_format,
        "cache_implementation": config.cache_implementation,
        "compile_mode": config.compile_mode,
        "attention_backend_requested": config.attention_backend,
        "attention_backend_effective": model.config._attn_implementation,
        "sdpa_kernel_backend": config.sdpa_kernel_backend,
        "prefix_cache": config.prefix_cache,
        "prefix_cache_gate": gate,
        "prompt_lookup_num_tokens": config.prompt_lookup_num_tokens,
        "max_matching_ngram_size": config.max_matching_ngram_size,
        "output_profile": config.output_profile,
        "dynamo_counters_after_warmup": counters_after_warmup,
        "dynamo_counters_after_evaluation": counters_after_evaluation,
        "unique_input_lengths": len({row["input_tokens"] for row in predictions}),
        "evaluation_wall_seconds": evaluation_wall_seconds,
        "samples_per_second": len(predictions) / evaluation_wall_seconds,
        "batch_latency_ms": _metric_summary(batch_latencies),
        "sample_processing_ms": _metric_summary(
            [row["sample_processing_ms"] for row in predictions]
        ),
        "gpu_utilization": sampler.summary(),
        "model_load_ms": model_load_ms,
        "cold_first_generation_ms": cold_first_generation_ms,
        "input_tokens": _metric_summary([row["input_tokens"] for row in predictions]),
        "output_tokens": _metric_summary([row["output_tokens"] for row in predictions]),
        "tokenization_ms": _metric_summary([row["tokenization_ms"] for row in predictions]),
        "generation_latency_ms": _metric_summary([row["latency_ms"] for row in predictions]),
        "eos_reached_rate": sum(row["eos_reached"] for row in predictions) / len(predictions),
        "max_new_tokens_reached_count": sum(
            row["max_new_tokens_reached"] for row in predictions
        ),
        "prompt_component_tokens": prompt_components,
        "prefix_analysis": {
            "all_token_id_prefix_equal": True,
            "prefix_token_count": prefix_token_count,
            "input_tokens": _metric_summary([len(ids) for ids in prompt_token_ids]),
            "suffix_tokens": _metric_summary(suffix_token_counts),
            "request_value_in_prefix": False,
            "role_boundary_safe": role_boundary_safe,
            "prefix_decoded": prefix_decoded,
        },
        "prefix_cache_create_ms": prefix_cache_create_ms,
        "cache_copy_ms": _metric_summary([row["cache_copy_ms"] for row in predictions]),
        "request_prefill_ms": _metric_summary([row["request_prefill_ms"] for row in predictions]),
        "decode_ms": _metric_summary([row["decode_ms"] for row in predictions]),
        "target_forward_steps": _metric_summary(
            [row["target_forward_steps"] for row in predictions if row["target_forward_steps"] is not None]
        ),
        "peak_vram_allocated": torch.cuda.max_memory_allocated(),
        "peak_vram_reserved": torch.cuda.max_memory_reserved(),
    }
    config.output_path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    mark_test_run_complete(config, sample_count=len(predictions))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", required=True, choices=("validation", "test"))
    parser.add_argument("--variant", required=True, choices=("baseline", "fine-tuned"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--final-test", action="store_true")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--max-new-tokens", type=int, default=768)
    parser.add_argument("--warmup-count", type=int, default=5)
    parser.add_argument("--prompt-profile", choices=("v1", "compact"), default="v1")
    parser.add_argument(
        "--generation-profile", choices=("current", "clean-greedy"), default="current"
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--precision", choices=("4bit", "bf16"), default="4bit")
    parser.add_argument("--model-format", choices=("peft", "merged"), default="peft")
    parser.add_argument("--merged-model", type=Path)
    parser.add_argument("--cache-implementation", choices=("dynamic", "static"), default="dynamic")
    parser.add_argument("--compile-mode", choices=("none", "reduce-overhead"), default="none")
    parser.add_argument(
        "--attention-backend",
        choices=("auto", "sdpa", "flash_attention_2"),
        default="auto",
    )
    parser.add_argument("--output-profile", choices=("canonical", "compact"), default="canonical")
    parser.add_argument("--sdpa-kernel-backend", choices=("auto", "flash-only"), default="auto")
    parser.add_argument("--prefix-cache", action="store_true")
    parser.add_argument("--prefix-cache-gate-size", type=int, default=0)
    parser.add_argument("--prompt-lookup-num-tokens", type=int)
    parser.add_argument("--max-matching-ngram-size", type=int)
    args = parser.parse_args(argv)
    output = args.output or DEFAULT_EVALUATION_DIR / f"{args.split}-{args.variant}.jsonl"
    config = PredictionConfig(
        split=args.split,
        variant=args.variant,
        input_path=args.input or DEFAULT_PROCESSED_DIR / f"{args.split}.jsonl",
        output_path=output,
        adapter_path=args.adapter,
        experiment_id=args.experiment_id,
        final_test=args.final_test,
        allow_download=args.allow_download,
        max_new_tokens=args.max_new_tokens,
        warmup_count=args.warmup_count,
        prompt_profile=args.prompt_profile,
        generation_profile=args.generation_profile,
        batch_size=args.batch_size,
        limit=args.limit,
        precision=args.precision,
        model_format=args.model_format,
        merged_model_path=args.merged_model,
        cache_implementation=args.cache_implementation,
        compile_mode=args.compile_mode,
        attention_backend=args.attention_backend,
        output_profile=args.output_profile,
        sdpa_kernel_backend=args.sdpa_kernel_backend,
        prefix_cache=args.prefix_cache,
        prefix_cache_gate_size=args.prefix_cache_gate_size,
        prompt_lookup_num_tokens=args.prompt_lookup_num_tokens,
        max_matching_ngram_size=args.max_matching_ngram_size,
    )
    manifest = run_predictions(config, detect_hardware())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
