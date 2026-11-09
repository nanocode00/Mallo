"""Production-oriented Qwen3-0.6B merged-BF16 NLU adapter.

Selected runtime profile:
- Qwen3-0.6B epochs4_seed7 merged BF16
- dynamic KV cache
- prompt lookup = 8
- deterministic conservative output guard
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from adapters.nlu.qwen06b_config import MODEL_ID, MODEL_REVISION
from adapters.nlu.qwen06b_guard import repair_qwen06b_payload
from adapters.nlu.input_normalizer import normalize_nlu_input
from adapters.nlu.qwen_prediction_runner import generation_options, inference_messages
from adapters.nlu.qwen_training_data import REPOSITORY_ROOT, build_system_prompt
from domain.models import Cart, OrderCommand, OrderCommandError, OrderCommandErrorCode


DEFAULT_SERVICE_MERGED_MODEL = (
    REPOSITORY_ROOT
    / "models"
    / "nlu"
    / "final-qwen06b-merged-bf16"
)



class Qwen06BNLU:
    """Resident merged-BF16 Qwen3-0.6B adapter implementing ``NLU.parse``."""

    def __init__(
        self,
        merged_model_path: Path | str = DEFAULT_SERVICE_MERGED_MODEL,
        *,
        max_new_tokens: int = 96,
        prompt_lookup_num_tokens: int = 8,
        allow_download: bool = False,
    ) -> None:
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        if prompt_lookup_num_tokens < 1:
            raise ValueError("prompt_lookup_num_tokens must be positive")

        merged_model = Path(merged_model_path)
        if not merged_model.is_dir():
            raise ValueError(f"merged model 디렉터리가 없습니다: {merged_model}")

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise RuntimeError(f"Qwen 0.6B NLU runtime 의존성이 없습니다: {error.name}") from error

        self._torch = torch
        started = time.perf_counter()
        local_files_only = not allow_download

        self._tokenizer = AutoTokenizer.from_pretrained(
            merged_model,
            local_files_only=local_files_only,
        )
        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        self._model = AutoModelForCausalLM.from_pretrained(
            merged_model,
            dtype=dtype,
            device_map={"": 0},
            local_files_only=local_files_only,
            attn_implementation="sdpa",
        ).eval()
        self._model.generation_config.do_sample = False
        self._model.generation_config.temperature = None
        self._model.generation_config.top_p = None
        self._model.generation_config.top_k = None

        self._system_prompt = build_system_prompt()
        self._options = generation_options(
            max_new_tokens=max_new_tokens,
            eos_token_id=self._tokenizer.eos_token_id,
            pad_token_id=self._tokenizer.pad_token_id,
        )
        self._options["prompt_lookup_num_tokens"] = prompt_lookup_num_tokens

        self._lock = threading.Lock()
        self.merged_model_path = merged_model
        self.model_id = MODEL_ID
        self.model_revision = MODEL_REVISION
        self.prompt_lookup_num_tokens = prompt_lookup_num_tokens
        self.load_latency_ms = (time.perf_counter() - started) * 1000
        self.last_input_tokens = 0
        self.last_output_tokens = 0
        self.last_latency_ms = 0.0
        self.last_raw_prediction = ""
        self.last_repaired_payload: Any = None
        self.last_original_text = ""
        self.last_normalized_text = ""
        self.last_normalization_replacements: tuple[tuple[str, str], ...] = ()

    @staticmethod
    def cart_payload(cart: Cart) -> list[dict[str, Any]]:
        return [
            {
                "menu_id": item.menu_id,
                "quantity": item.quantity,
                "temperature": item.temperature.value if item.temperature is not None else None,
                "options": item.options.to_dict(),
            }
            for item in cart.items
        ]

    @staticmethod
    def payload_to_result(payload: Any) -> list[OrderCommand] | OrderCommandError:
        try:
            if isinstance(payload, list) and payload:
                return [OrderCommand.from_nlu_payload(row) for row in payload]
            if isinstance(payload, dict):
                candidates = payload.get("candidates")
                return OrderCommandError(
                    code=OrderCommandErrorCode(payload["code"]),
                    message=payload["message"],
                    retryable=payload.get("retryable", True),
                    command_index=payload.get("command_index"),
                    field=payload.get("field"),
                    candidates=tuple(candidates) if candidates is not None else None,
                )
        except (KeyError, TypeError, ValueError):
            pass
        return OrderCommandError(
            code=OrderCommandErrorCode.SCHEMA_ERROR,
            message="주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요.",
        )

    @classmethod
    def parse_prediction(
        cls,
        prediction: str,
        *,
        text: str,
        cart_before: list[dict[str, Any]],
    ) -> tuple[list[OrderCommand] | OrderCommandError, Any]:
        try:
            payload = json.loads(prediction)
        except json.JSONDecodeError:
            repaired = repair_qwen06b_payload(
                text,
                cart_before,
                {"code": "INVALID_JSON"},
            )
            if isinstance(repaired, list):
                return cls.payload_to_result(repaired), repaired
            error = OrderCommandError(
                code=OrderCommandErrorCode.INVALID_JSON,
                message="주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요.",
            )
            return error, None

        repaired = repair_qwen06b_payload(text, cart_before, payload)
        return cls.payload_to_result(repaired), repaired

    def parse(self, text: str, current_order_state: Cart) -> list[OrderCommand] | OrderCommandError:
        normalized_input = normalize_nlu_input(text)
        self.last_original_text = normalized_input.original_text
        self.last_normalized_text = normalized_input.normalized_text
        self.last_normalization_replacements = normalized_input.replacements
        cart_before = self.cart_payload(current_order_state)
        record = {
            "input": {
                "utterance": normalized_input.normalized_text,
                "cart_before": cart_before,
            }
        }
        rendered = self._tokenizer.apply_chat_template(
            inference_messages(record, self._system_prompt),
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self._tokenizer(rendered, return_tensors="pt").to(self._model.device)

        with self._lock:
            self._torch.cuda.synchronize()
            started = time.perf_counter()
            with self._torch.inference_mode():
                output = self._model.generate(**inputs, **self._options)
            self._torch.cuda.synchronize()

        self.last_latency_ms = (time.perf_counter() - started) * 1000
        prediction_ids = output[0, inputs["input_ids"].shape[1] :]
        self.last_input_tokens = int(inputs["input_ids"].shape[1])
        self.last_output_tokens = int(prediction_ids.shape[0])
        self.last_raw_prediction = self._tokenizer.decode(
            prediction_ids,
            skip_special_tokens=True,
        ).strip()

        result, repaired = self.parse_prediction(
            self.last_raw_prediction,
            text=normalized_input.normalized_text,
            cart_before=cart_before,
        )
        self.last_repaired_payload = repaired
        return result
