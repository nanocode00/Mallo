from __future__ import annotations

import pytest

from app.main import select_fulfillment
from app.service import build_mock_service
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import (
    Cart,
    CartItem,
    FulfillmentType,
    OrderCommand,
    Temperature,
)
from domain.session_state import SessionState


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        (FulfillmentType.DINE_IN, FulfillmentType.DINE_IN),
        ("dine_in", FulfillmentType.DINE_IN),
        ("takeout", FulfillmentType.TAKEOUT),
    ],
)
def test_start_order_creates_selected_empty_cart(
    choice: FulfillmentType | str,
    expected: FulfillmentType,
) -> None:
    cart = build_mock_service().start_order(choice)

    assert cart.items == []
    assert cart.fulfillment_type is expected


def test_start_order_rejects_unknown_choice() -> None:
    with pytest.raises(ValueError, match="dine_in 또는 takeout"):
        build_mock_service().start_order("delivery")


def test_app_retries_until_valid_fulfillment_choice(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answers = iter(["잘 모르겠어요", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    selected = select_fulfillment()

    assert selected is FulfillmentType.TAKEOUT
    assert "선택해 주세요" in capsys.readouterr().out


def test_cart_copy_and_session_serialization_preserve_fulfillment() -> None:
    cart = Cart(fulfillment_type=FulfillmentType.DINE_IN)

    copied = cart.copy()
    serialized = SessionState(cart=cart).to_dict()

    assert copied is not cart
    assert copied.fulfillment_type is FulfillmentType.DINE_IN
    assert serialized["cart"]["fulfillment_type"] == "dine_in"


def test_query_and_confirm_announce_takeout() -> None:
    agent = ConversationAgent(load_menu())
    cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.TAKEOUT,
    )

    queried = agent.execute([OrderCommand.create(Intent.QUERY_CART)], cart)
    confirmed = agent.execute([OrderCommand.create(Intent.CONFIRM_ORDER)], cart)

    assert queried.cart.fulfillment_type is FulfillmentType.TAKEOUT
    assert "포장 주문" in queried.response_text
    assert confirmed.cart.fulfillment_type is FulfillmentType.TAKEOUT
    assert "포장 주문입니다" in confirmed.response_text


def test_cancel_resets_items_and_fulfillment() -> None:
    agent = ConversationAgent(load_menu())
    cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.DINE_IN,
    )

    result = agent.execute([OrderCommand.create(Intent.CANCEL)], cart)

    assert result.success is True
    assert result.cart.items == []
    assert result.cart.fulfillment_type is None
