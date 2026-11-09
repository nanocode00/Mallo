from __future__ import annotations

import pytest

from adapters.nlu.mock_nlu import MockNLU
from domain.intents import Intent
from domain.models import Cart, OrderCommandError, OrderCommandErrorCode, Temperature


@pytest.mark.parametrize(
    ("text", "menu_id", "quantity", "temperature"),
    [
        ("아메리카노 한 잔 주세요", "americano", 1, None),
        ("아메리카노 하나 주세요", "americano", 1, None),
        ("아메리카노 하나 줘", "americano", 1, None),
        ("아메리카노 두 잔 주세요", "americano", 2, None),
        ("아이스 아메리카노 하나 줘", "americano", 1, Temperature.ICED),
        ("아이스 아메리카노 두 잔 주세요", "americano", 2, Temperature.ICED),
        ("캐모마일티 한 잔 주세요", "chamomile_tea", 1, None),
        ("말차라떼 두 잔 주세요", "matcha_latte", 2, None),
    ],
)
def test_general_order_phrases_are_add_item(
    text: str,
    menu_id: str,
    quantity: int,
    temperature: Temperature | None,
) -> None:
    result = MockNLU().parse(text, Cart())

    assert not isinstance(result, OrderCommandError)
    assert len(result) == 1
    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].target_item_id == menu_id
    assert result[0].quantity == quantity
    assert result[0].temperature is temperature


@pytest.mark.parametrize(
    ("text", "detail_field"),
    [
        ("말차라떼가 뭐야?", "description"),
        ("아메리카노 설명해줘", "description"),
        ("아메리카노는 아이스도 돼?", "temperature"),
        ("아메리카노 따뜻하게도 돼?", "temperature"),
    ],
)
def test_menu_questions_remain_query_menu(text: str, detail_field: str) -> None:
    result = MockNLU().parse(text, Cart())

    assert not isinstance(result, OrderCommandError)
    assert len(result) == 1
    assert result[0].intent is Intent.QUERY_MENU
    assert [field.value for field in result[0].detail_fields or ()] == [detail_field]


@pytest.mark.parametrize("text", ["차는 뭐가 있어?", "차 종류는 뭐 있어?"])
def test_tea_category_questions_use_category_id_before_tag_search(text: str) -> None:
    result = MockNLU().parse(text, Cart())

    assert not isinstance(result, OrderCommandError)
    assert result[0].intent is Intent.QUERY_MENU
    assert result[0].category_id == "tea"
    assert result[0].query_tags is None


def test_unrelated_sentence_is_unsupported() -> None:
    result = MockNLU().parse("오늘 날씨가 참 좋네요", Cart())

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE
