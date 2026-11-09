"""상주 Qwen3-1.7B QLoRA NLU runtime adapter."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from adapters.nlu.qwen_prediction_runner import generation_options, inference_messages
from adapters.nlu.qwen_runtime import MODEL_ID, MODEL_REVISION

from adapters.nlu.qwen_training_data import build_system_prompt
from domain.models import Cart, OrderCommand, OrderCommandError, OrderCommandErrorCode


class QwenNLU:
    """모델과 tokenizer를 한 번 로드해 batch=1 요청에서 재사용한다."""

    def __init__(
        self,
        adapter_path: Path | str,
        *,
        max_new_tokens: int = 96,
        allow_download: bool = False,
    ) -> None:
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        adapter = Path(adapter_path)
        if not adapter.is_dir():
            raise ValueError(f"adapter 디렉터리가 없습니다: {adapter}")
        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError as error:
            raise RuntimeError(f"Qwen NLU runtime 의존성이 없습니다: {error.name}") from error

        started = time.perf_counter()
        load_options = {
            "revision": MODEL_REVISION,
            "local_files_only": not allow_download,
        }
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **load_options)
        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        base = AutoModelForCausalLM.from_pretrained(
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
        self._model = PeftModel.from_pretrained(base, str(adapter), is_trainable=False)
        self._model.eval()
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
        self._lock = threading.Lock()
        self.load_latency_ms = (time.perf_counter() - started) * 1000
        self.last_input_tokens = 0
        self.last_output_tokens = 0
        self.last_latency_ms = 0.0

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
    def parse_prediction(prediction: str) -> list[OrderCommand] | OrderCommandError:
        try:
            payload = json.loads(prediction)
        except json.JSONDecodeError:
            return OrderCommandError(
                code=OrderCommandErrorCode.INVALID_JSON,
                message="주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요.",
            )
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

    def parse(self, text: str, current_order_state: Cart) -> list[OrderCommand] | OrderCommandError:
        record = {
            "input": {
                "utterance": text,
                "cart_before": self.cart_payload(current_order_state),
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
        prediction = self._tokenizer.decode(prediction_ids, skip_special_tokens=True).strip()
        return self.parse_prediction(prediction)
