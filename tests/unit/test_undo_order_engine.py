from __future__ import annotations

import pytest

from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import Cart, CartItem, ErrorCode, OrderCommand, Temperature


def add_americano(agent: ConversationAgent) -> Cart:
    result = agent.execute(
        [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="americano",
                quantity=1,
                temperature=Temperature.ICED,
            )
        ],
        Cart(),
    )
    assert result.success is True
    return result.cart


def test_undo_add_item_restores_empty_cart() -> None:
    agent = ConversationAgent(load_menu())
    added = add_americano(agent)

    result = agent.execute([OrderCommand.create(Intent.UNDO)], added)

    assert result.success is True
    assert result.cart.items == []
    assert result.response_text == (
        "방금 변경을 취소했습니다. 장바구니가 비어 있습니다."
    )


@pytest.mark.parametrize(
    "command",
    [
        OrderCommand.create(
            Intent.UPDATE_QUANTITY,
            target_item_id="americano",
            quantity=3,
            temperature=Temperature.ICED,
        ),
        OrderCommand.create(
            Intent.UPDATE_OPTION,
            target_item_id="americano",
            temperature=Temperature.HOT,
        ),
        OrderCommand.create(
            Intent.REMOVE_ITEM,
            target_item_id="americano",
            temperature=Temperature.ICED,
        ),
    ],
)
def test_undo_restores_update_and_remove(command: OrderCommand) -> None:
    agent = ConversationAgent(load_menu())
    original = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])
    changed = agent.execute([command], original)
    assert changed.success is True

    undone = agent.execute([OrderCommand.create(Intent.UNDO)], changed.cart)

    assert undone.success is True
    assert undone.cart == original


def test_undo_cancel_restores_entire_cart() -> None:
    agent = ConversationAgent(load_menu())
    original = Cart(
        [
            CartItem("americano", 2, Temperature.ICED, 4700),
            CartItem("basque_cheesecake", 1, None, 6500),
        ]
    )
    cancelled = agent.execute([OrderCommand.create(Intent.CANCEL)], original)

    undone = agent.execute([OrderCommand.create(Intent.UNDO)], cancelled.cart)

    assert undone.success is True
    assert undone.cart == original
    assert "15,900원" in undone.response_text


def test_query_and_failed_mutation_do_not_overwrite_history() -> None:
    agent = ConversationAgent(load_menu())
    added = add_americano(agent)
    queried = agent.execute([OrderCommand.create(Intent.QUERY_CART)], added)
    assert queried.success is True
    failed = agent.execute(
        [
            OrderCommand.create(
                Intent.UPDATE_QUANTITY,
                target_item_id="unknown",
                quantity=2,
            )
        ],
        queried.cart,
    )
    assert failed.success is False

    undone = agent.execute([OrderCommand.create(Intent.UNDO)], failed.cart)

    assert undone.success is True
    assert undone.cart.items == []


def test_only_latest_mutation_can_be_undone_once() -> None:
    agent = ConversationAgent(load_menu())
    first = add_americano(agent)
    second = agent.execute(
        [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="cafe_latte",
                quantity=1,
                temperature=Temperature.HOT,
            )
        ],
        first,
    )

    undone = agent.execute([OrderCommand.create(Intent.UNDO)], second.cart)
    repeated = agent.execute([OrderCommand.create(Intent.UNDO)], undone.cart)

    assert undone.success is True
    assert undone.cart == first
    assert repeated.error_code is ErrorCode.INVALID_COMMAND
    assert repeated.cart == first


def test_undo_rejects_mismatched_current_cart_and_discards_history() -> None:
    agent = ConversationAgent(load_menu())
    added = add_americano(agent)
    unrelated = Cart([CartItem("cafe_latte", 1, Temperature.HOT, 5200)])

    mismatch = agent.execute([OrderCommand.create(Intent.UNDO)], unrelated)
    retry = agent.execute([OrderCommand.create(Intent.UNDO)], added)

    assert mismatch.error_code is ErrorCode.INVALID_COMMAND
    assert mismatch.cart == unrelated
    assert retry.error_code is ErrorCode.INVALID_COMMAND
    assert retry.cart == added


def test_reset_session_clears_undo_history() -> None:
    agent = ConversationAgent(load_menu())
    added = add_americano(agent)
    agent.reset_session()

    result = agent.execute([OrderCommand.create(Intent.UNDO)], added)

    assert result.error_code is ErrorCode.INVALID_COMMAND


def test_successful_noop_does_not_create_undo_history() -> None:
    agent = ConversationAgent(load_menu())
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])
    unchanged = agent.execute(
        [
            OrderCommand.create(
                Intent.UPDATE_QUANTITY,
                target_item_id="americano",
                quantity=1,
                temperature=Temperature.ICED,
            )
        ],
        cart,
    )
    assert unchanged.success is True

    result = agent.execute([OrderCommand.create(Intent.UNDO)], unchanged.cart)

    assert result.error_code is ErrorCode.INVALID_COMMAND
