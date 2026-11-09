from adapters.nlu.menu_tag_resolver import resolve_menu_query_tags
from config.settings import load_menu_tag_definitions


def test_low_sweetness_aliases_resolve_to_same_tag() -> None:
    definitions = load_menu_tag_definitions()

    assert resolve_menu_query_tags("안 단 거 있어요?", definitions) == (
        "sweetness_low",
    )
    assert resolve_menu_query_tags("당도가 낮은 거 있어요?", definitions) == (
        "sweetness_low",
    )
    assert resolve_menu_query_tags("달지 않은 음료 알려줘", definitions) == (
        "sweetness_low",
    )


def test_multiple_conditions_preserve_definition_order() -> None:
    tags = resolve_menu_query_tags(
        "카페인 없고 우유 안 들어간 차가운 거 보여줘",
        load_menu_tag_definitions(),
    )

    assert tags == ("caffeine_free", "milk_free", "iced")


def test_unknown_expression_returns_empty_tuple() -> None:
    assert resolve_menu_query_tags("아무 조건이나", load_menu_tag_definitions()) == ()
