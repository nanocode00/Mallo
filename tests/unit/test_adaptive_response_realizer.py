from __future__ import annotations

import pytest

from config.settings import load_menu
from domain.adaptive_response_realizer import AdaptiveResponseRealizer
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.korean_normalizer import normalize_korean_text_for_tts
from domain.models import Cart, FulfillmentType, OrderCommand, Temperature
from domain.text_transformer import AdaptiveTextTransformer


def _realize(commands: list[OrderCommand], cart: Cart, level: int):
    agent = ConversationAgent(load_menu())
    result = agent.execute(commands, cart)
    return AdaptiveResponseRealizer({item.id: item for item in load_menu()}).realize(
        result, commands, level=level,
    )


def _assert_contract(realized, level: int) -> None:
    display = " ".join(realized.display_segments or (realized.text,))
    chunks = AdaptiveTextTransformer.transform_to_chunks(realized.text, level=level)
    assert normalize_korean_text_for_tts(display) == normalize_korean_text_for_tts(realized.text)
    assert " ".join(chunks) == normalize_korean_text_for_tts(realized.text)


@pytest.mark.parametrize("level", [0, 1, 2])
def test_multi_add_is_semantic_source_for_each_level(level: int) -> None:
    commands = [
        OrderCommand.create(Intent.ADD_ITEM, "americano", quantity=2, temperature=Temperature.ICED),
        OrderCommand.create(Intent.ADD_ITEM, "cafe_latte", quantity=1, temperature=Temperature.HOT),
    ]
    realized = _realize(commands, Cart(), level)
    _assert_contract(realized, level)
    if level in (0, 1):
        assert realized.text == (
            "아이스 아메리카노 두 잔과 따뜻한 카페라떼 한 잔을 장바구니에 담았습니다."
        )
    if level == 2:
        assert realized.text == (
            "아이스 아메리카노 두 잔입니다. 따뜻한 카페라떼 한 잔입니다. 장바구니에 담았습니다."
        )
        assert realized.display_segments == (
            "아이스 아메리카노 두 잔입니다.",
            "따뜻한 카페라떼 한 잔입니다.",
            "장바구니에 담았습니다.",
        )


@pytest.mark.parametrize("category", [None, "coffee", "non_coffee", "tea", "dessert"])
@pytest.mark.parametrize("level", [0, 1, 2])
def test_menu_realization_preserves_every_menu_fact(category: str | None, level: int) -> None:
    command = OrderCommand.create(Intent.QUERY_MENU, category_id=category)
    realized = _realize([command], Cart(), level)
    _assert_contract(realized, level)
    if level == 2:
        expected_header = "커피 메뉴입니다." if category is None else {
            "coffee": "커피 메뉴입니다.",
            "non_coffee": "논커피 메뉴입니다.",
            "tea": "티 메뉴입니다.",
            "dessert": "디저트 메뉴입니다.",
        }[category]
        assert realized.display_segments[0] == expected_header
        assert all("메뉴는" not in segment or segment.endswith("메뉴입니다.") for segment in realized.display_segments)


@pytest.mark.parametrize("level", [0, 1, 2])
def test_order_summary_replay_shape_is_semantic_at_level_two(level: int) -> None:
    cart = Cart(
        fulfillment_type=FulfillmentType.TAKEOUT,
        items=[],
    )
    add = [OrderCommand.create(Intent.ADD_ITEM, "americano", quantity=2, temperature=Temperature.ICED)]
    cart = ConversationAgent(load_menu()).execute(add, cart).cart
    realized = _realize([OrderCommand.create(Intent.QUERY_CART)], cart, level)
    _assert_contract(realized, level)
    if level == 2:
        assert realized.display_segments == (
            "포장 주문입니다.",
            "아이스 아메리카노 두 잔입니다.",
            "총 결제 금액은 9,400원입니다.",
        )
