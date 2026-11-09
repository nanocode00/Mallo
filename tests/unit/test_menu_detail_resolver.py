from adapters.nlu.menu_detail_resolver import resolve_menu_detail_query
from config.settings import load_menu
from domain.models import MenuDetailField


def test_resolves_official_menu_and_description() -> None:
    result = resolve_menu_detail_query("아메리카노는 어떤 음료야?", load_menu())

    assert result == ("americano", (MenuDetailField.DESCRIPTION,))


def test_resolves_multiple_fields_in_utterance_order() -> None:
    result = resolve_menu_detail_query(
        "카페라떼에 우유하고 카페인이 있어?",
        load_menu(),
    )

    assert result == (
        "cafe_latte",
        (MenuDetailField.MILK, MenuDetailField.CAFFEINE),
    )


def test_returns_none_without_exactly_one_menu_or_detail_field() -> None:
    assert resolve_menu_detail_query("카페인 있어?", load_menu()) is None
    assert resolve_menu_detail_query("아메리카노 알려줘", []) is None
