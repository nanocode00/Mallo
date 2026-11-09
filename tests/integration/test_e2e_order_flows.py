from __future__ import annotations

from app.service import build_mock_service
from domain.models import Cart, CartItem, FulfillmentType, Temperature


def test_add_then_query_cart_flow() -> None:
    service = build_mock_service()

    added = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    assert added.success
    assert added.cart.items == [CartItem("americano", 2, Temperature.ICED, 4700)]

    queried = service.handle_text("현재 주문 알려 주세요", added.cart)
    assert queried.success
    assert "아이스 아메리카노" in queried.response_text
    assert queried.cart == added.cart


def test_remove_item_flow() -> None:
    service = build_mock_service()
    cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)])

    result = service.handle_text("아이스 아메리카노 삭제해 주세요", cart)

    assert result.success
    assert result.cart.items == []


def test_update_quantity_flow() -> None:
    service = build_mock_service()
    cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)])

    result = service.handle_text("아이스 아메리카노 세 잔으로 바꿔 주세요", cart)

    assert result.success
    assert result.cart.items == [CartItem("americano", 3, Temperature.ICED, 4700)]


def test_update_option_flow() -> None:
    service = build_mock_service()
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])

    result = service.handle_text("아메리카노를 따뜻하게 바꿔 주세요", cart)

    assert result.success
    assert result.cart.items == [CartItem("americano", 1, Temperature.HOT, 4700)]


def test_confirm_and_cancel_flow() -> None:
    service = build_mock_service()
    cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)], fulfillment_type=FulfillmentType.DINE_IN)

    confirmed = service.handle_text("주문 확정할게요", cart)
    assert confirmed.success
    assert "9,400" in confirmed.response_text

    cancelled = service.handle_text("전체 주문 취소해 주세요", confirmed.cart)
    assert cancelled.success
    assert cancelled.cart.items == []


def test_undo_restores_previous_cart() -> None:
    service = build_mock_service()
    added = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())

    undone = service.handle_text("방금 거 취소해 주세요", added.cart)

    assert undone.success
    assert undone.cart.items == []


def test_tts_control_intents_change_level_then_reset() -> None:
    service = build_mock_service()
    ordered = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())

    slower = service.handle_text("천천히 말해 주세요", ordered.cart)
    assert slower.success
    assert service.tts_level == 1

    default = service.handle_text("기본 속도로 말해 주세요", ordered.cart)
    assert default.success
    assert service.tts_level == 0


def test_full_happy_path_sequence() -> None:
    service = build_mock_service()
    steps = [
        "아이스 아메리카노 두 잔 주세요",
        "따뜻한 카페라떼 한 잔 주세요",
        "아이스 아메리카노 세 잔으로 바꿔 주세요",
        "현재 주문 알려 주세요",
        "주문 확정할게요",
    ]
    cart = Cart(fulfillment_type=FulfillmentType.DINE_IN)
    last = None
    for text in steps:
        last = service.handle_text(text, cart)
        cart = last.cart
        assert last.success, f"failed at: {text}"
    # 아이스 아메리카노 3잔(14,100) + 따뜻한 카페라떼 1잔(5,200) = 19,300
    assert cart.total_price == 19300
    assert last is not None and "19,300" in last.response_text
