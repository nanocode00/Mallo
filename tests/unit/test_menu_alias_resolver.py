import pytest

from adapters.nlu.menu_alias_resolver import (
    AmbiguousMenuAliasError,
    resolve_menu_aliases,
)
from config.settings import load_menu_alias_definitions
from domain.models import MenuAliasDefinition, Temperature


@pytest.mark.parametrize(
    ("alias", "target_item_id", "temperature"),
    [
        ("아아", "americano", Temperature.ICED),
        ("뜨아", "americano", Temperature.HOT),
        ("아라", "cafe_latte", Temperature.ICED),
        ("뜨라", "cafe_latte", Temperature.HOT),
        ("아바라", "vanilla_latte", Temperature.ICED),
        ("뜨바라", "vanilla_latte", Temperature.HOT),
    ],
)
def test_resolves_approved_aliases(alias, target_item_id, temperature) -> None:
    matches = resolve_menu_aliases(f"{alias} 두 잔 주세요", load_menu_alias_definitions())

    assert len(matches) == 1
    assert matches[0].target_item_id == target_item_id
    assert matches[0].temperature is temperature


@pytest.mark.parametrize("alias", ["아초", "아돌라"])
def test_ignores_aliases_for_menus_not_in_catalog(alias: str) -> None:
    assert resolve_menu_aliases(alias, load_menu_alias_definitions()) == ()


def test_ambiguous_alias_returns_unique_candidates() -> None:
    definitions = (
        MenuAliasDefinition("라떼", "cafe_latte", Temperature.ICED),
        MenuAliasDefinition("라떼", "vanilla_latte", Temperature.ICED),
        MenuAliasDefinition("라떼", "cafe_latte", Temperature.ICED),
    )

    with pytest.raises(AmbiguousMenuAliasError) as error:
        resolve_menu_aliases("라떼 주세요", definitions)

    assert error.value.candidates == ("cafe_latte", "vanilla_latte")


def test_preserves_alias_utterance_order() -> None:
    matches = resolve_menu_aliases(
        "뜨라 한 잔하고 아아 두 잔",
        load_menu_alias_definitions(),
    )

    assert [match.alias for match in matches] == ["뜨라", "아아"]


def test_does_not_match_alias_inside_unrelated_word() -> None:
    assert resolve_menu_aliases(
        "이제 메뉴를 알아라",
        load_menu_alias_definitions(),
    ) == ()
