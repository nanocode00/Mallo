from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from adapters.nlu.http_nlu import HTTPClientNLU
from domain.models import (
    BeverageOptions,
    Cart,
    CartItem,
    FulfillmentType,
    Temperature,
)
from domain.order_command_error import OrderCommandError, OrderCommandErrorCode
from interfaces.nlu import NLUFailure


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_http_nlu_round_trips_cart_and_command(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "ok": True,
                "commands": [
                    {
                        "intent": "ADD_ITEM",
                        "target_item_id": "americano",
                        "category_id": None,
                        "quantity": 1,
                        "temperature": "iced",
                        "query_tags": None,
                        "detail_fields": None,
                        "options": {
                            "size": None,
                            "extra_shots": None,
                            "caffeine": None,
                            "syrup_pumps": None,
                            "ice_amount": None,
                        },
                    }
                ],
                "error": None,
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    cart = Cart(
        items=[
            CartItem(
                menu_id="cafe_latte",
                quantity=2,
                temperature=Temperature.ICED,
                unit_price=4500,
                options=BeverageOptions(),
            )
        ],
        fulfillment_type=FulfillmentType.TAKEOUT,
    )

    result = HTTPClientNLU(timeout=7).parse("아메리카노 하나 추가", cart)

    assert result[0].intent.value == "ADD_ITEM"
    assert result[0].target_item_id == "americano"
    assert captured["timeout"] == 7
    assert captured["body"]["cart"]["fulfillment_type"] == "takeout"
    assert captured["body"]["cart"]["items"][0]["menu_id"] == "cafe_latte"
    assert "unit_price" not in captured["body"]["cart"]["items"][0]


def test_http_nlu_returns_semantic_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeResponse(
            {
                "ok": True,
                "commands": None,
                "error": {
                    "code": "AMBIGUOUS_TARGET",
                    "message": "대상을 다시 말씀해 주세요.",
                    "retryable": True,
                    "command_index": None,
                    "field": "target_item_id",
                    "candidates": ["americano", "cafe_latte"],
                },
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = HTTPClientNLU().parse("그거 빼줘", Cart())

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.AMBIGUOUS_TARGET
    assert result.candidates == ("americano", "cafe_latte")


def test_http_nlu_transport_failure_hides_internal_exception(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("offline: connection refused on 127.0.0.1:8002")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(NLUFailure) as exc_info:
        HTTPClientNLU().parse("아메리카노 하나", Cart())

    assert exc_info.value.error.code is OrderCommandErrorCode.SCHEMA_ERROR
    assert exc_info.value.error.message == (
        "음성 주문 서비스를 잠시 사용할 수 없습니다. 다시 시도해 주세요."
    )
    assert "offline" not in exc_info.value.error.message
    assert "127.0.0.1" not in exc_info.value.error.message


def test_http_nlu_non_ok_response_hides_sidecar_detail(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return _FakeResponse(
            {
                "ok": False,
                "error": "CUDA out of memory at /home/user/models/private-adapter",
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(NLUFailure) as exc_info:
        HTTPClientNLU().parse("아메리카노 하나", Cart())

    assert exc_info.value.error.message == (
        "음성 주문 서비스를 잠시 사용할 수 없습니다. 다시 시도해 주세요."
    )
    assert "CUDA" not in exc_info.value.error.message
    assert "/home/" not in exc_info.value.error.message
