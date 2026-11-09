from __future__ import annotations

import pytest

from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import Cart, CartItem, ErrorCode, FulfillmentType, OrderCommand, Temperature


@pytest.fixture
def agent() -> ConversationAgent:
    return ConversationAgent(load_menu())


def test_remove_item_success(agent: ConversationAgent) -> None:
    """REMOVE_ITEM 실행 시 장바구니에서 해당 메뉴가 삭제되어야 한다 (AC-01)."""
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=2,
                temperature=Temperature.ICED,
                unit_price=4700,
            )
        ],
    )
    cmd = OrderCommand.create(
        intent=Intent.REMOVE_ITEM,
        target_item_id="americano",
        temperature=Temperature.ICED,
    )

    result = agent.execute([cmd], cart)
    assert result.success is True
    assert len(result.cart.items) == 0
    assert "아이스 아메리카노를 장바구니에서 삭제했습니다." in result.response_text


def test_remove_item_not_in_cart(agent: ConversationAgent) -> None:
    """장바구니에 없는 메뉴 삭제 시 MENU_NOT_FOUND 에러를 반환해야 한다 (EC-01)."""
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=2,
                temperature=Temperature.ICED,
                unit_price=4700,
            )
        ],
        fulfillment_type=FulfillmentType.TAKEOUT,
    )
    cmd = OrderCommand.create(
        intent=Intent.REMOVE_ITEM,
        target_item_id="caffe_latte",
        temperature=Temperature.HOT,
    )

    result = agent.execute([cmd], cart)
    assert result.success is False
    assert result.error_code == ErrorCode.MENU_NOT_FOUND
    assert len(result.cart.items) == 1  # Cart 보존


def test_remove_same_menu_with_both_temperatures_requires_temperature(agent: ConversationAgent) -> None:
    cart = Cart([
        CartItem("cafe_latte", 1, Temperature.HOT, 5200),
        CartItem("cafe_latte", 1, Temperature.ICED, 5200),
    ])

    result = agent.execute([
        OrderCommand.create(Intent.REMOVE_ITEM, target_item_id="cafe_latte")
    ], cart)

    assert result.success is False
    assert result.error_code is ErrorCode.AMBIGUOUS_TARGET
    assert result.cart == cart


def test_remove_same_menu_with_explicit_temperature_removes_only_that_line(agent: ConversationAgent) -> None:
    cart = Cart([
        CartItem("cafe_latte", 1, Temperature.HOT, 5200),
        CartItem("cafe_latte", 1, Temperature.ICED, 5200),
    ])

    result = agent.execute([
        OrderCommand.create(Intent.REMOVE_ITEM, target_item_id="cafe_latte", temperature=Temperature.ICED)
    ], cart)

    assert result.success is True
    assert result.cart.items == [CartItem("cafe_latte", 1, Temperature.HOT, 5200)]


def test_update_quantity_success(agent: ConversationAgent) -> None:
    """UPDATE_QUANTITY 실행 시 해당 메뉴의 수량이 갱신되어야 한다 (AC-02)."""
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=1,
                temperature=Temperature.ICED,
                unit_price=4700,
            )
        ]
    )
    cmd = OrderCommand.create(
        intent=Intent.UPDATE_QUANTITY,
        target_item_id="americano",
        quantity=3,
        temperature=Temperature.ICED,
    )

    result = agent.execute([cmd], cart)
    assert result.success is True
    assert result.cart.items[0].quantity == 3
    assert result.cart.total_price == 14100
    assert "3잔으로 변경했습니다." in result.response_text


def test_update_quantity_invalid(agent: ConversationAgent) -> None:
    """수량이 0 이하인 UPDATE_QUANTITY는 INVALID_QUANTITY 에러를 반환해야 한다 (EC-02)."""
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=1,
                temperature=Temperature.ICED,
                unit_price=4700,
            )
        ]
    )
    cmd = OrderCommand.create(
        intent=Intent.UPDATE_QUANTITY,
        target_item_id="americano",
        quantity=0,
    )

    result = agent.execute([cmd], cart)
    assert result.success is False
    assert result.error_code == ErrorCode.INVALID_QUANTITY


def test_update_option_success(agent: ConversationAgent) -> None:
    """UPDATE_OPTION 실행 시 메뉴의 온도 옵션이 변경되어야 한다 (AC-03)."""
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=1,
                temperature=Temperature.ICED,
                unit_price=4700,
            )
        ]
    )
    cmd = OrderCommand.create(
        intent=Intent.UPDATE_OPTION,
        target_item_id="americano",
        temperature=Temperature.HOT,
    )

    result = agent.execute([cmd], cart)
    assert result.success is True
    assert result.cart.items[0].temperature == Temperature.HOT
    assert "따뜻한 음료로 변경했습니다." in result.response_text


def test_update_option_invalid_for_menu(agent: ConversationAgent) -> None:
    """ICE 전용 메뉴에 HOT 온도로 옵션 변경 요청 시 INVALID_OPTION 에러를 반환해야 한다 (EC-03)."""
    cart = Cart(
        items=[
            CartItem(
                menu_id="grapefruit_ade",
                quantity=1,
                temperature=Temperature.ICED,
                unit_price=5800,
            )
        ]
    )
    cmd = OrderCommand.create(
        intent=Intent.UPDATE_OPTION,
        target_item_id="grapefruit_ade",
        temperature=Temperature.HOT,
    )

    result = agent.execute([cmd], cart)
    assert result.success is False
    assert result.error_code == ErrorCode.INVALID_OPTION
    assert len(result.cart.items) == 1
    assert result.cart.items[0].temperature == Temperature.ICED


def test_query_cart_empty_and_filled(agent: ConversationAgent) -> None:
    """QUERY_CART 실행 시 장바구니 내용과 총액이 안내되어야 한다 (AC-04, EC-05)."""
    cmd = OrderCommand.create(intent=Intent.QUERY_CART)

    # 빈 장바구니
    empty_result = agent.execute([cmd], Cart())
    assert empty_result.success is True
    assert "장바구니가 비어 있습니다." in empty_result.response_text

    # 담긴 장바구니
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=2,
                temperature=Temperature.ICED,
                unit_price=4700,
            )
        ]
    )
    filled_result = agent.execute([cmd], cart)
    assert filled_result.success is True
    assert "9,400원" in filled_result.response_text


def test_query_menu_by_category_keeps_cart(agent: ConversationAgent) -> None:
    cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)]
    )
    command = OrderCommand.create(Intent.QUERY_MENU, category_id="coffee")

    result = agent.execute([command], cart)

    assert result.success is True
    assert result.cart == cart
    assert result.cart is not cart
    assert result.response_text == (
        "커피 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, "
        "바닐라라떼 3,400원입니다."
    )


def test_query_single_menu_includes_price_and_temperature(
    agent: ConversationAgent,
) -> None:
    command = OrderCommand.create(Intent.QUERY_MENU, target_item_id="americano")

    result = agent.execute([command], Cart())

    assert result.success is True
    assert result.response_text == (
        "아메리카노는 4,700원입니다. 따뜻하게 또는 아이스로 주문할 수 있습니다."
    )


def test_query_all_menu_preserves_catalog_order(agent: ConversationAgent) -> None:
    result = agent.execute(
        [OrderCommand.create(Intent.QUERY_MENU)],
        Cart(),
    )

    assert result.success is True
    assert result.response_text.startswith(
        "커피 메뉴는 아메리카노 4,700원, 카페라떼 5,200원"
    )
    assert "전체 메뉴는" not in result.response_text
    assert result.response_text.endswith("바스크 치즈 케이크 6,500원입니다.")


def test_query_menu_by_single_tag_keeps_cart(agent: ConversationAgent) -> None:
    cart = Cart(items=[CartItem("americano", 1, Temperature.ICED, 4700)])
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        query_tags=("sweetness_low",),
    )

    result = agent.execute([command], cart)

    assert result.success is True
    assert result.cart == cart
    assert result.cart is not cart
    assert result.response_text == (
        "조건에 맞는 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, "
        "캐모마일티 3,700원입니다."
    )


def test_query_menu_combines_category_and_tags_with_and(agent: ConversationAgent) -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        category_id="tea",
        query_tags=("caffeine_free", "milk_free", "iced"),
    )

    result = agent.execute([command], Cart())

    assert result.success is True
    assert result.response_text == (
        "조건에 맞는 티 메뉴는 캐모마일티 3,700원입니다."
    )


def test_query_menu_rejects_unknown_or_unmatched_tags(agent: ConversationAgent) -> None:
    unknown = agent.execute(
        [OrderCommand.create(Intent.QUERY_MENU, query_tags=("unknown_tag",))],
        Cart(),
    )
    unmatched = agent.execute(
        [
            OrderCommand.create(
                Intent.QUERY_MENU,
                query_tags=("caffeine_free", "caffeine_present"),
            )
        ],
        Cart(),
    )

    assert unknown.error_code is ErrorCode.INVALID_OPTION
    assert unmatched.error_code is ErrorCode.MENU_NOT_FOUND


def test_query_menu_rejects_target_with_tags(agent: ConversationAgent) -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        target_item_id="americano",
        query_tags=("sweetness_low",),
    )

    result = agent.execute([command], Cart())

    assert result.error_code is ErrorCode.INVALID_COMMAND


@pytest.mark.parametrize(
    ("detail_field", "expected"),
    [
        ("description", "아메리카노는 에스프레소에 물을 더한 커피입니다."),
        ("price", "아메리카노 가격은 4,700원입니다."),
        ("sweetness", "아메리카노는 당도가 낮은 편입니다."),
        ("caffeine", "아메리카노에는 카페인이 있습니다."),
        ("milk", "아메리카노에는 우유가 들어가지 않습니다."),
        ("temperature", "아메리카노는 따뜻하게 또는 아이스로 주문할 수 있습니다."),
    ],
)
def test_query_single_menu_detail_field(
    agent: ConversationAgent,
    detail_field: str,
    expected: str,
) -> None:
    cart = Cart(items=[CartItem("americano", 1, Temperature.ICED, 4700)])
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        target_item_id="americano",
        detail_fields=(detail_field,),
    )

    result = agent.execute([command], cart)

    assert result.success is True
    assert result.response_text == expected
    assert result.cart == cart
    assert result.cart is not cart


def test_query_menu_multiple_details_preserve_requested_order(
    agent: ConversationAgent,
) -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        target_item_id="cafe_latte",
        detail_fields=("milk", "caffeine"),
    )

    result = agent.execute([command], Cart())

    assert result.success is True
    assert result.response_text == (
        "카페라떼에는 우유가 들어갑니다. 카페라떼에는 카페인이 있습니다."
    )


def test_query_menu_detail_requires_target(agent: ConversationAgent) -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        detail_fields=("price",),
    )

    result = agent.execute([command], Cart())

    assert result.error_code is ErrorCode.INVALID_COMMAND


@pytest.mark.parametrize(
    "command",
    [
        OrderCommand.create(Intent.QUERY_MENU, category_id="unknown"),
        OrderCommand.create(Intent.QUERY_MENU, target_item_id="unknown"),
    ],
)
def test_query_unknown_menu_scope_fails_without_cart_change(
    agent: ConversationAgent,
    command: OrderCommand,
) -> None:
    cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)]
    )

    result = agent.execute([command], cart)

    assert result.error_code is ErrorCode.MENU_NOT_FOUND
    assert result.cart == cart


def test_query_menu_rejects_target_and_category_together(
    agent: ConversationAgent,
) -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        target_item_id="americano",
        category_id="coffee",
    )

    result = agent.execute([command], Cart())

    assert result.error_code is ErrorCode.INVALID_COMMAND


def test_confirm_order_empty_and_filled(agent: ConversationAgent) -> None:
    """CONFIRM_ORDER 실행 시 빈 장바구니는 거부하고 담긴 경우 결제 안내를 해야 한다 (EC-04)."""
    cmd = OrderCommand.create(intent=Intent.CONFIRM_ORDER)

    # 빈 장바구니 거부
    empty_result = agent.execute([cmd], Cart())
    assert empty_result.success is False
    assert empty_result.error_code == ErrorCode.INVALID_COMMAND

    # 담긴 장바구니 성공
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=1,
                temperature=Temperature.ICED,
                unit_price=4700,
            )
        ],
        fulfillment_type=FulfillmentType.TAKEOUT,
    )
    filled_result = agent.execute([cmd], cart)
    assert filled_result.success is True
    assert "총 결제 금액은 4,700원입니다." in filled_result.response_text


def test_select_payment_method_requires_confirmed_cart(agent: ConversationAgent) -> None:
    cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.TAKEOUT,
    )
    command = OrderCommand.create(Intent.SELECT_PAYMENT_METHOD, target_item_id="card")

    blocked = agent.execute([command], cart)
    assert blocked.success is False
    assert blocked.error_code is ErrorCode.INVALID_COMMAND

    cart.confirmed = True
    selected = agent.execute([command], cart)
    assert selected.success is True
    assert selected.cart.confirmed is True
    assert "카드 결제를 선택했습니다." in selected.response_text


def test_cancel_all_clears_cart(agent: ConversationAgent) -> None:
    """CANCEL 실행 시 장바구니가 완전히 비워져야 한다 (AC-05)."""
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=2,
                temperature=Temperature.ICED,
                unit_price=4700,
            )
        ]
    )
    cmd = OrderCommand.create(intent=Intent.CANCEL)

    result = agent.execute([cmd], cart)
    assert result.success is True
    assert len(result.cart.items) == 0
    assert "주문이 모두 취소되었습니다." in result.response_text


def test_mixed_intents_in_batch_rejected(agent: ConversationAgent) -> None:
    """허용 목록 밖의 혼합 Intent는 거부되어야 한다."""
    cart = Cart()
    cmds = [
        OrderCommand.create(
            intent=Intent.ADD_ITEM,
            target_item_id="americano",
            quantity=1,
            temperature=Temperature.ICED,
        ),
        OrderCommand.create(intent=Intent.CANCEL),
    ]

    result = agent.execute(cmds, cart)
    assert result.success is False
    assert result.error_code == ErrorCode.MIXED_INTENT
    assert result.response_text == (
        "사용자의 주문을 이해하지 못했습니다. "
        "한 번에 하나씩 주문해 주시면 감사하겠습니다."
    )


def test_reset_order_clears_cart_fulfillment_confirmation_and_undo(agent: ConversationAgent) -> None:
    cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.TAKEOUT,
        confirmed=True,
    )

    reset = agent.execute([OrderCommand.create(Intent.RESET_ORDER)], cart)
    undo = agent.execute([OrderCommand.create(Intent.UNDO)], reset.cart)

    assert reset.success is True
    assert reset.cart == Cart()
    assert "처음부터 다시 시작" in reset.response_text
    assert undo.success is False


def test_update_option_full_line_merges_with_existing_target_temperature(agent: ConversationAgent) -> None:
    cart = Cart(items=[
        CartItem("cafe_latte", 1, Temperature.ICED, 5200),
        CartItem("cafe_latte", 1, Temperature.HOT, 5200),
    ])

    result = agent.execute([OrderCommand.create(
        Intent.UPDATE_OPTION,
        target_item_id="cafe_latte",
        quantity=1,
        temperature=Temperature.HOT,
    )], cart)

    assert result.success is True
    assert [(item.temperature, item.quantity) for item in result.cart.items] == [
        (Temperature.HOT, 2),
    ]
    assert result.cart.total_price == 10400


def test_update_quantity_above_five_preserves_server_cart(agent: ConversationAgent) -> None:
    cart = Cart(items=[CartItem("cafe_latte", 5, Temperature.ICED, 5200)])

    result = agent.execute([OrderCommand.create(
        Intent.UPDATE_QUANTITY,
        target_item_id="cafe_latte",
        quantity=6,
        temperature=Temperature.ICED,
    )], cart)

    assert result.success is False
    assert result.error_code == ErrorCode.INVALID_QUANTITY
    assert result.cart.items[0].quantity == 5
