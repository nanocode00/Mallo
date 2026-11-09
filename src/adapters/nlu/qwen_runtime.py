"""Qwen3-1.7B QLoRA adapter를 실시간 NLU 인터페이스에 연결한다."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, ValidationError

from domain.errors import ErrorCode, get_default_error_response
from domain.models import Cart, OrderCommand
from domain.order_command_error import OrderCommandError, OrderCommandErrorCode
from interfaces.nlu import NLUResult
from utils.schema_validation import validate_order_commands


MODEL_ID = "Qwen/Qwen3-1.7B"
MODEL_REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MENU_PATH = REPOSITORY_ROOT / "src/config/menu.json"
COMMAND_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/order-command.schema.json"
ERROR_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/order-command-error.schema.json"


class QwenRuntimeError(RuntimeError):
    """모델·adapter 로딩 또는 런타임 설정 오류."""


class GenerationBackend(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> str: ...


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QwenRuntimeError(f"NLU 계약 파일을 읽을 수 없습니다: {path}") from error
    if not isinstance(value, dict):
        raise QwenRuntimeError(f"NLU 계약 JSON 객체가 필요합니다: {path}")
    return value


def build_system_prompt() -> str:
    """학습 때 사용한 Menu DB·Schema 기반 system prompt를 그대로 생성한다."""
    menu = _load_object(MENU_PATH)
    command_schema = _load_object(COMMAND_SCHEMA_PATH)
    error_schema = _load_object(ERROR_SCHEMA_PATH)
    try:
        properties = command_schema["$defs"]["orderCommand"]["properties"]
        catalog = {
            "menu_version": menu["version"],
            "categories": {row["id"]: row["name"] for row in menu["categories"]},
            "menus": {
                row["id"]: {
                    "name": row["name"],
                    "category": row["category_id"],
                    "temperatures": row["temperature_options"],
                }
                for row in menu["items"]
            },
            "tags": {row["id"]: row["name"] for row in menu["tag_definitions"]},
        }
        intents = properties["intent"]["enum"]
        error_codes = error_schema["properties"]["code"]["enum"]
    except (KeyError, TypeError) as error:
        raise QwenRuntimeError("Menu DB 또는 NLU Schema 구조가 올바르지 않습니다") from error

    semantic_fields = [key for key in properties if key != "request_id"]
    rules = [
        "당신은 말로 카페 키오스크의 한국어 NLU다. /no_think",
        "입력의 utterance와 cart_before만 해석하고 설명이나 Markdown 없이 JSON 하나만 출력한다.",
        "정상은 발화 순서의 OrderCommand 배열, 오류는 OrderCommandError 객체다.",
        f"Command 필드={_canonical_json(semantic_fields)}; 사용하지 않는 필드는 null이며 request_id는 출력 금지다.",
        f"Intent={_canonical_json(intents)}; 오류 code={_canonical_json(error_codes)}.",
        "메뉴·카테고리·태그는 아래 공식 ID만 사용한다. 가격과 총액은 만들지 않는다.",
        "같은 메뉴·온도·옵션은 수량을 합치고, 수량 변경은 변경 후 최종 수량을 출력한다.",
        "수정·삭제 대상은 cart_before에 있어야 하며 여러 후보를 특정할 수 없으면 AMBIGUOUS_TARGET이다.",
        "온도 선택이 필요한 추가 요청에 온도가 없으면 MISSING_FIELD다.",
        "지원되지 않는 혼합 요청은 MIXED_INTENT, 단일 요청은 UNSUPPORTED_UTTERANCE다.",
        f"공식 카탈로그={_canonical_json(catalog)}",
    ]
    return "\n".join(rules)


def cart_payload(cart: Cart) -> list[dict[str, Any]]:
    return [
        {
            "menu_id": item.menu_id,
            "quantity": item.quantity,
            "temperature": item.temperature.value if item.temperature else None,
            "options": item.options.to_dict(),
        }
        for item in cart.items
    ]


def _runtime_error(code: OrderCommandErrorCode, message: str) -> OrderCommandError:
    return OrderCommandError(code=code, message=message, retryable=True)


def decode_nlu_output(raw: str) -> NLUResult:
    """모델 문자열을 검증된 도메인 NLUResult로 fail-closed 변환한다."""
    try:
        payload = json.loads(raw.strip())
    except (AttributeError, json.JSONDecodeError):
        return _runtime_error(
            OrderCommandErrorCode.INVALID_JSON,
            "주문 형식을 해석하지 못했습니다. 다시 말씀해 주세요.",
        )

    try:
        if isinstance(payload, list):
            commands = [OrderCommand.from_nlu_payload(row) for row in payload]
            validate_order_commands(commands)
            return commands
        if isinstance(payload, dict):
            Draft202012Validator(_load_object(ERROR_SCHEMA_PATH)).validate(payload)
            code = OrderCommandErrorCode(payload["code"])
            return OrderCommandError(
                code=code,
                message=get_default_error_response(ErrorCode(code.value)).user_message,
                retryable=payload["retryable"],
                command_index=payload.get("command_index"),
                field=payload.get("field"),
                candidates=(
                    tuple(payload["candidates"])
                    if payload.get("candidates") is not None
                    else None
                ),
            )
    except (KeyError, TypeError, ValueError, ValidationError):
        # 모델 출력 내용은 로그/응답에 노출하지 않는다.
        pass
    return _runtime_error(
        OrderCommandErrorCode.SCHEMA_ERROR,
        "주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요.",
    )


class TransformersQwenBackend:
    """Transformers+PEFT 추론 backend. 모델은 생성 시 한 번만 로딩한다."""

    def __init__(
        self,
        adapter_path: Path | str,
        *,
        device: str = "auto",
        local_files_only: bool = False,
        max_new_tokens: int = 768,
    ) -> None:
        adapter = Path(adapter_path).expanduser().resolve()
        if not (adapter / "adapter_config.json").is_file() or not any(
            adapter.glob("adapter_model.*")
        ):
            raise QwenRuntimeError(f"유효한 Qwen NLU adapter가 아닙니다: {adapter}")
        if max_new_tokens < 1:
            raise QwenRuntimeError("max_new_tokens는 1 이상이어야 합니다")
        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError as error:
            raise QwenRuntimeError(f"Qwen NLU 의존성이 없습니다: {error.name}") from error

        selected = (
            "cuda:0" if torch.cuda.is_available() else "cpu"
        ) if device == "auto" else device
        if selected.startswith("cuda") and not torch.cuda.is_available():
            raise QwenRuntimeError("CUDA NLU를 요청했지만 사용할 수 있는 GPU가 없습니다")
        load_options = {
            "revision": MODEL_REVISION,
            "local_files_only": local_files_only,
        }
        self._tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **load_options)
        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        if selected.startswith("cuda"):
            index = int(selected.partition(":")[2] or "0")
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID,
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=dtype,
                ),
                device_map={"": index},
                dtype=dtype,
                **load_options,
            )
        elif selected == "cpu":
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID,
                device_map={"": "cpu"},
                dtype=torch.float32,
                **load_options,
            )
        else:
            raise QwenRuntimeError("NLU device는 auto, cpu 또는 cuda[:N]이어야 합니다")

        self._torch = torch
        self._model = PeftModel.from_pretrained(model, str(adapter), is_trainable=False)
        self._model.eval()
        self._max_new_tokens = max_new_tokens
        self._lock = threading.Lock()

    def generate(self, messages: list[dict[str, str]]) -> str:
        prompt = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        options = {
            "do_sample": False,
            "max_new_tokens": self._max_new_tokens,
            "eos_token_id": self._tokenizer.eos_token_id,
            "pad_token_id": self._tokenizer.pad_token_id,
        }
        with self._lock, self._torch.inference_mode():
            output = self._model.generate(**inputs, **options)
        prediction = output[0, inputs["input_ids"].shape[1] :]
        return self._tokenizer.decode(prediction, skip_special_tokens=True).strip()


class QwenNLU:
    """기존 NLU Protocol을 구현하는 Qwen3 adapter."""

    def __init__(
        self,
        adapter_path: Path | str | None = None,
        *,
        device: str = "auto",
        local_files_only: bool = False,
        backend: GenerationBackend | None = None,
    ) -> None:
        if backend is None:
            if adapter_path is None:
                raise QwenRuntimeError("Qwen NLU adapter 경로가 필요합니다")
            backend = TransformersQwenBackend(
                adapter_path, device=device, local_files_only=local_files_only
            )
        self._backend = backend
        self._system_prompt = build_system_prompt()

    def parse(self, text: str, current_order_state: Cart) -> NLUResult:
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": _canonical_json(
                    {"utterance": text, "cart_before": cart_payload(current_order_state)}
                ),
            },
        ]
        return decode_nlu_output(self._backend.generate(messages))
