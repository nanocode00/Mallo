import pytest

from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import (
    BeverageOptions,
    CaffeineOption,
    Cart,
    CartItem,
    ErrorCode,
    OrderCommand,
    Temperature,
)


FAILURE_MESSAGE = (
    "사용자의 주문을 이해하지 못했습니다. 다시 말씀해 주시거나 "
    "한 번에 하나씩 주문해 주시면 감사하겠습니다."
)


def command(
    intent: Intent,
    menu_id: str | None = None,
    *,
    quantity: int | None = None,
    temperature: Temperature | None = None,
) -> OrderCommand:
    return OrderCommand.create(
        intent,
        target_item_id=menu_id,
        quantity=quantity,
        temperature=temperature,
    )


def initial_cart() -> Cart:
    return Cart(
        [
            CartItem("cafe_latte", 1, Temperature.ICED, 5200),
            CartItem("milk_tea", 1, Temperature.HOT, 3500),
        ]
    )


def test_remove_then_add_runs_in_order_and_undoes_as_one_batch() -> None:
    agent = ConversationAgent(load_menu())
    original = initial_cart()
    result = agent.execute(
        [
            command(Intent.REMOVE_ITEM, "cafe_latte", temperature=Temperature.ICED),
            command(
                Intent.ADD_ITEM,
                "americano",
                quantity=1,
                temperature=Temperature.ICED,
            ),
        ],
        original,
    )

    assert [item.menu_id for item in result.cart.items] == ["milk_tea", "americano"]
    assert result.response_text.index("삭제했습니다") < result.response_text.index("담았습니다")
    assert agent.execute([command(Intent.UNDO)], result.cart).cart == original


def test_two_mutations_may_end_with_query_cart() -> None:
    result = ConversationAgent(load_menu()).execute(
        [
            command(
                Intent.UPDATE_QUANTITY,
                "milk_tea",
                quantity=2,
                temperature=Temperature.HOT,
            ),
            command(
                Intent.ADD_ITEM,
                "americano",
                quantity=1,
                temperature=Temperature.ICED,
            ),
            command(Intent.QUERY_CART),
        ],
        initial_cart(),
    )

    assert result.success is True
    assert result.cart.items[1].quantity == 2
    assert result.response_text.index("변경했습니다") < result.response_text.index("담았습니다")
    assert result.response_text.index("담았습니다") < result.response_text.index("현재")


def test_option_change_may_run_before_another_cart_change() -> None:
    result = ConversationAgent(load_menu()).execute(
        [
            OrderCommand.create(
                Intent.UPDATE_OPTION,
                target_item_id="cafe_latte",
                options=BeverageOptions(caffeine=CaffeineOption.DECAF),
            ),
            command(Intent.REMOVE_ITEM, "milk_tea", temperature=Temperature.HOT),
        ],
        initial_cart(),
    )

    assert result.success is True
    assert result.cart.items[0].options.caffeine is CaffeineOption.DECAF
    assert len(result.cart.items) == 1


@pytest.mark.parametrize(
    "commands",
    [
        [
            command(Intent.QUERY_CART),
            command(Intent.ADD_ITEM, "americano", quantity=1, temperature=Temperature.ICED),
        ],
        [
            command(Intent.REMOVE_ITEM, "cafe_latte", temperature=Temperature.ICED),
            command(Intent.UPDATE_QUANTITY, "milk_tea", quantity=2, temperature=Temperature.HOT),
            command(Intent.ADD_ITEM, "americano", quantity=1, temperature=Temperature.ICED),
        ],
    ],
)
def test_unsafe_sequence_is_rejected(commands: list[OrderCommand]) -> None:
    original = initial_cart()
    result = ConversationAgent(load_menu()).execute(commands, original)

    assert result.error_code is ErrorCode.MIXED_INTENT
    assert result.cart == original


def test_later_failure_rolls_back_entire_batch() -> None:
    original = initial_cart()
    result = ConversationAgent(load_menu()).execute(
        [
            command(Intent.REMOVE_ITEM, "cafe_latte", temperature=Temperature.ICED),
            command(Intent.ADD_ITEM, "unknown_menu", quantity=1, temperature=Temperature.ICED),
        ],
        original,
    )

    assert result.response_text == FAILURE_MESSAGE
    assert result.cart == original


def test_change_target_must_exist_in_initial_cart() -> None:
    original = initial_cart()
    result = ConversationAgent(load_menu()).execute(
        [
            command(Intent.ADD_ITEM, "americano", quantity=1, temperature=Temperature.ICED),
            command(Intent.UPDATE_QUANTITY, "americano", quantity=2, temperature=Temperature.ICED),
        ],
        original,
    )

    assert result.response_text == FAILURE_MESSAGE
    assert result.cart == original


def test_ambiguous_target_rolls_back_entire_batch() -> None:
    original = Cart(
        [
            CartItem("americano", 1, Temperature.HOT, 4700),
            CartItem("americano", 1, Temperature.ICED, 4700),
        ]
    )
    result = ConversationAgent(load_menu()).execute(
        [
            command(Intent.REMOVE_ITEM, "americano"),
            command(Intent.ADD_ITEM, "cafe_latte", quantity=1, temperature=Temperature.ICED),
        ],
        original,
    )

    assert result.error_code is ErrorCode.AMBIGUOUS_TARGET
    assert result.response_text == FAILURE_MESSAGE
    assert result.cart == original
