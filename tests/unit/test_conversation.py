from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import (
    BeverageOptions,
    Cart,
    CartItem,
    ErrorCode,
    FulfillmentType,
    MenuItem,
    OrderCommand,
    Temperature,
)


def americano() -> MenuItem:
    return MenuItem(
        id="americano",
        category_id="coffee",
        name="아메리카노",
        description="에스프레소에 물을 더한 커피",
        base_price=4700,
        unit="잔",
        temperature_options=(Temperature.HOT, Temperature.ICED),
        price_source_brand="스타벅스",
        price_source_menu_name="카페 아메리카노 Tall",
        price_source_url="https://example.com/americano",
        price_checked_at="2026-08-14",
    )


def cheesecake() -> MenuItem:
    return MenuItem(
        id="basque_cheesecake",
        category_id="dessert",
        name="바스크 치즈 케이크",
        description="진한 치즈 풍미의 촉촉한 케이크",
        base_price=6500,
        unit="개",
        temperature_options=(),
        price_source_brand="어쏠트먼트",
        price_source_menu_name="바스크 치즈 케이크",
        price_source_url="https://example.com/basque-cheesecake",
        price_checked_at="2026-08-14",
    )


def grapefruit_ade() -> MenuItem:
    return MenuItem(
        id="grapefruit_ade",
        category_id="non_coffee",
        name="자몽에이드",
        description="자몽의 상큼함을 담은 음료",
        base_price=3500,
        unit="잔",
        temperature_options=(Temperature.ICED,),
        price_source_brand="메가MGC커피",
        price_source_menu_name="자몽에이드",
        price_source_url="https://example.com/grapefruit-ade",
        price_checked_at="2026-08-14",
    )


def build_agent() -> ConversationAgent:
    return ConversationAgent([americano(), grapefruit_ade(), cheesecake()])


def add_command(
    target_item_id: str,
    quantity: int | None,
    temperature: Temperature | None,
) -> OrderCommand:
    return OrderCommand.create(
        Intent.ADD_ITEM,
        target_item_id=target_item_id,
        quantity=quantity,
        temperature=temperature,
    )


def test_add_iced_americano_and_calculate_price() -> None:
    result = build_agent().execute(
        [add_command("americano", 2, Temperature.ICED)],
        Cart(),
    )

    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700)
    ]
    assert result.cart.total_price == 9400
    assert result.response_text == "아이스 아메리카노 두 잔을 담았습니다."


def test_readding_same_menu_increments_cart_quantity() -> None:
    cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)])

    result = build_agent().execute(
        [add_command("americano", 3, Temperature.ICED)],
        cart,
    )

    assert result.cart.items == [
        CartItem("americano", 5, Temperature.ICED, 4700)
    ]
    assert result.cart.total_price == 23500


def test_dual_temperature_add_is_rejected_until_clarified() -> None:
    result = build_agent().execute(
        [add_command("americano", 1, None)],
        Cart(),
    )

    assert result.success is False
    assert result.error_code == ErrorCode.MISSING_FIELD
    assert result.response_text == "따뜻하게 드릴까요, 아이스로 드릴까요?"
    assert result.cart.items == []


def test_same_menu_with_different_temperature_is_separate() -> None:
    result = build_agent().execute(
        [
            add_command("americano", 1, Temperature.ICED),
            add_command("americano", 1, Temperature.HOT),
        ],
        Cart(),
    )

    assert result.cart.items == [
        CartItem("americano", 1, Temperature.ICED, 4700),
        CartItem("americano", 1, Temperature.HOT, 4700),
    ]


def test_duplicate_menu_and_temperature_are_merged_in_first_seen_order() -> None:
    result = build_agent().execute(
        [
            add_command("americano", 1, Temperature.ICED),
            add_command("basque_cheesecake", 1, None),
            add_command("americano", 2, Temperature.ICED),
        ],
        Cart(),
    )

    assert result.cart.items == [
        CartItem("americano", 3, Temperature.ICED, 4700),
        CartItem(
            "basque_cheesecake",
            1,
            None,
            6500,
            BeverageOptions(size=None),
        ),
    ]


def test_missing_temperature_requires_a_follow_up_question() -> None:
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])

    result = build_agent().execute(
        [add_command("americano", 1, None)],
        cart,
    )

    assert result.success is False
    assert result.error_code is ErrorCode.MISSING_FIELD
    assert result.cart.items == [CartItem("americano", 1, Temperature.ICED, 4700)]


def test_iced_only_menu_gets_its_catalog_temperature_when_unspecified() -> None:
    result = build_agent().execute(
        [add_command("grapefruit_ade", 1, None)],
        Cart(),
    )

    assert result.success is True
    assert result.cart.items[0].temperature is Temperature.ICED


def test_dessert_rejects_temperature() -> None:
    result = build_agent().execute(
        [add_command("basque_cheesecake", 1, Temperature.ICED)],
        Cart(),
    )

    assert result.error_code is ErrorCode.INVALID_OPTION
    assert result.cart.items == []


def test_dessert_without_temperature_is_added() -> None:
    result = build_agent().execute(
        [add_command("basque_cheesecake", 1, None)],
        Cart(),
    )

    assert result.success is True
    assert result.cart.items == [
        CartItem(
            "basque_cheesecake",
            1,
            None,
            6500,
            BeverageOptions(size=None),
        )
    ]


def test_iced_only_drink_is_added_with_iced_temperature() -> None:
    result = build_agent().execute(
        [add_command("grapefruit_ade", 1, Temperature.ICED)],
        Cart(),
    )

    assert result.success is True
    assert result.cart.items == [
        CartItem("grapefruit_ade", 1, Temperature.ICED, 3500)
    ]
    assert result.response_text == "자몽에이드 한 잔을 담았습니다."


def test_iced_only_drink_rejects_hot_temperature() -> None:
    result = build_agent().execute(
        [add_command("grapefruit_ade", 1, Temperature.HOT)],
        Cart(),
    )

    assert result.error_code is ErrorCode.INVALID_OPTION


def test_unknown_menu_does_not_mutate_cart() -> None:
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])

    result = build_agent().execute(
        [add_command("unknown_menu", 1, Temperature.HOT)],
        cart,
    )

    assert result.error_code is ErrorCode.MENU_NOT_FOUND
    assert result.cart == cart


def test_invalid_quantity_does_not_mutate_cart() -> None:
    result = build_agent().execute(
        [add_command("americano", 0, Temperature.ICED)],
        Cart(),
    )

    assert result.error_code is ErrorCode.INVALID_QUANTITY


def test_category_id_is_null_for_add_item() -> None:
    command = OrderCommand.create(
        Intent.ADD_ITEM,
        target_item_id="americano",
        category_id="coffee",
        quantity=1,
        temperature=Temperature.ICED,
    )

    result = build_agent().execute([command], Cart())

    assert result.error_code is ErrorCode.INVALID_COMMAND


def test_multiple_commands_are_applied_as_one_batch() -> None:
    result = build_agent().execute(
        [
            add_command("americano", 2, Temperature.ICED),
            add_command("basque_cheesecake", 1, None),
        ],
        Cart(),
    )

    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700),
        CartItem(
            "basque_cheesecake",
            1,
            None,
            6500,
            BeverageOptions(size=None),
        ),
    ]
    assert result.cart.total_price == 15900


def test_invalid_second_command_cancels_entire_batch() -> None:
    cart = Cart([CartItem("americano", 1, Temperature.HOT, 4700)])

    result = build_agent().execute(
        [
            add_command("americano", 2, Temperature.ICED),
            add_command("unknown_menu", 1, None),
        ],
        cart,
    )

    assert result.error_code is ErrorCode.MENU_NOT_FOUND
    assert result.cart == cart


def test_unsupported_mixed_intents_are_not_executed() -> None:
    result = build_agent().execute(
        [
            add_command("americano", 1, Temperature.ICED),
            OrderCommand.create(Intent.CONFIRM_ORDER),
        ],
        Cart(),
    )

    assert result.error_code is ErrorCode.MIXED_INTENT
    assert result.response_text == (
        "사용자의 주문을 이해하지 못했습니다. "
        "한 번에 하나씩 주문해 주시면 감사하겠습니다."
    )
    assert result.cart.items == []


def test_empty_cart_one_shot_order_batch_confirms_atomically() -> None:
    result = build_agent().execute(
        [
            OrderCommand.create(Intent.SET_FULFILLMENT, fulfillment_type=FulfillmentType.TAKEOUT),
            add_command("americano", 1, Temperature.ICED),
            OrderCommand.create(Intent.CONFIRM_ORDER),
        ],
        Cart(),
    )

    assert result.success is True
    assert result.cart.fulfillment_type is FulfillmentType.TAKEOUT
    assert result.cart.items == [CartItem("americano", 1, Temperature.ICED, 4700)]
    assert result.cart.confirmed is True


def test_unsupported_intent_execution_fails() -> None:
    result = build_agent().execute(
        [OrderCommand.create(Intent.REQUEST_REPEAT)],
        Cart(),
    )

    assert result.error_code is ErrorCode.UNSUPPORTED_UTTERANCE



def test_empty_batch_is_invalid_command() -> None:
    result = build_agent().execute([], Cart())

    assert result.error_code is ErrorCode.INVALID_COMMAND
