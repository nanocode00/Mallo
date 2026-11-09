from __future__ import annotations

import hashlib
import json

import pytest

from adapters.nlu.qwen_runtime import (
    QwenNLU,
    QwenRuntimeError,
    build_system_prompt,
    decode_nlu_output,
)
from adapters.tts.mock_tts import MockTTS
from app.service import MalloService, build_service
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import (
    BeverageOptions,
    Cart,
    CartItem,
    ErrorCode,
    OrderCommand,
    Temperature,
)
from domain.order_command_error import OrderCommandError, OrderCommandErrorCode


def command_json(**updates) -> str:
    command = {
        "intent": "ADD_ITEM",
        "target_item_id": "americano",
        "category_id": None,
        "quantity": 2,
        "temperature": "iced",
        "query_tags": None,
        "detail_fields": None,
        "options": None,
    }
    command.update(updates)
    return json.dumps([command], ensure_ascii=False)


class StubBackend:
    def __init__(self, output: str) -> None:
        self.output = output
        self.messages: list[dict[str, str]] | None = None

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return self.output


def test_system_prompt_matches_trained_adapter_contract() -> None:
    digest = hashlib.sha256(build_system_prompt().encode("utf-8")).hexdigest()

    assert digest == (
        "770903d61725207eea516c6bbb6997ddff184581cbc741f574626c3b332ff7ee"
    )


def test_decode_valid_command_injects_runtime_request_id() -> None:
    result = decode_nlu_output(command_json())

    assert isinstance(result, list)
    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].target_item_id == "americano"
    assert result[0].request_id


def test_decode_valid_error_preserves_recovery_fields() -> None:
    raw = json.dumps(
        {
            "code": "AMBIGUOUS_TARGET",
            "message": "어떤 아메리카노인지 말씀해 주세요.",
            "retryable": True,
            "command_index": 0,
            "field": "target_item_id",
            "candidates": ["americano"],
        },
        ensure_ascii=False,
    )

    result = decode_nlu_output(raw)

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.AMBIGUOUS_TARGET
    assert result.candidates == ("americano",)
    assert result.message == "어떤 메뉴를 변경할지 명확하지 않습니다."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("설명입니다", OrderCommandErrorCode.INVALID_JSON),
        (command_json(extra_field="bad"), OrderCommandErrorCode.SCHEMA_ERROR),
        ("[]", OrderCommandErrorCode.SCHEMA_ERROR),
    ],
)
def test_decode_invalid_output_fails_closed(raw: str, expected: OrderCommandErrorCode) -> None:
    result = decode_nlu_output(raw)

    assert isinstance(result, OrderCommandError)
    assert result.code is expected


def test_parse_sends_training_contract_with_current_cart() -> None:
    backend = StubBackend(
        command_json(
            intent="QUERY_CART",
            target_item_id=None,
            quantity=None,
            temperature=None,
        )
    )
    nlu = QwenNLU(backend=backend)
    cart = Cart(
        [
            CartItem(
                "americano",
                1,
                Temperature.ICED,
                4700,
                BeverageOptions(),
            )
        ]
    )

    result = nlu.parse("현재 주문 알려 주세요", cart)

    assert isinstance(result, list)
    assert backend.messages is not None
    assert backend.messages[0]["role"] == "system"
    user = json.loads(backend.messages[1]["content"])
    assert user["utterance"] == "현재 주문 알려 주세요"
    assert user["cart_before"][0]["menu_id"] == "americano"
    assert user["cart_before"][0]["options"]["size"] is None


def test_invalid_model_output_keeps_cart_unchanged() -> None:
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])
    service = MalloService(
        nlu=QwenNLU(backend=StubBackend("not-json")),
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
    )

    result = service.handle_text("이 요청을 실행해", cart)

    assert not result.success
    assert result.error_code is ErrorCode.INVALID_JSON
    assert result.cart == cart


def test_qwen_requires_adapter_without_injected_backend() -> None:
    with pytest.raises(QwenRuntimeError, match="adapter 경로"):
        QwenNLU()


def test_build_service_rejects_unknown_nlu_backend() -> None:
    with pytest.raises(ValueError, match="nlu_backend은"):
        build_service(nlu_backend="unknown")


def test_build_service_selects_qwen_backend(monkeypatch, tmp_path) -> None:
    captured = {}

    class FakeQwenNLU:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def parse(self, text: str, current_order_state: Cart):
            return [OrderCommand.create(Intent.QUERY_CART)]

    monkeypatch.setattr("adapters.nlu.qwen06b_nlu.Qwen06BNLU", FakeQwenNLU)
    service = build_service(
        nlu_backend="qwen06b",
        nlu_model_path=tmp_path,
    )

    result = service.handle_text("현재 주문 알려 주세요", Cart())

    assert result.success
    assert captured == {
        "merged_model_path": tmp_path,
        "prompt_lookup_num_tokens": 8,
    }
