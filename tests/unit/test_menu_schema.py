import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[2]
MENU_PATH = ROOT / "src" / "config" / "menu.json"
SCHEMA_PATH = ROOT / "schemas" / "menu.schema.json"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_menu_catalog_matches_json_schema() -> None:
    Draft202012Validator(load_json(SCHEMA_PATH)).validate(load_json(MENU_PATH))


def test_menu_catalog_has_four_categories_and_ten_items() -> None:
    catalog = load_json(MENU_PATH)

    assert len(catalog["categories"]) == 4
    assert len(catalog["items"]) == 10
    assert len({item["id"] for item in catalog["items"]}) == 10


def test_category_references_are_valid() -> None:
    catalog = load_json(MENU_PATH)
    category_ids = {category["id"] for category in catalog["categories"]}

    assert all(item["category_id"] in category_ids for item in catalog["items"])


def test_menu_tags_reference_definitions_and_aliases_are_unique() -> None:
    catalog = load_json(MENU_PATH)
    definitions = catalog["tag_definitions"]
    tag_ids = {definition["id"] for definition in definitions}
    aliases = [alias for definition in definitions for alias in definition["aliases"]]

    assert len(tag_ids) == len(definitions)
    assert len(aliases) == len(set(aliases))
    assert all(set(item["tags"]).issubset(tag_ids) for item in catalog["items"])


def test_menu_name_aliases_reference_existing_menu_and_temperature() -> None:
    catalog = load_json(MENU_PATH)
    menu_items = {item["id"]: item for item in catalog["items"]}
    expected = {
        "아아": ("americano", "iced"),
        "뜨아": ("americano", "hot"),
        "아라": ("cafe_latte", "iced"),
        "뜨라": ("cafe_latte", "hot"),
        "아바라": ("vanilla_latte", "iced"),
        "뜨바라": ("vanilla_latte", "hot"),
    }
    actual = {
        definition["alias"]: (
            definition["target_item_id"],
            definition["temperature"],
        )
        for definition in catalog["menu_aliases"]
    }

    assert actual == expected
    assert all(target in menu_items for target, _ in actual.values())
    assert all(
        temperature in menu_items[target]["temperature_options"]
        for target, temperature in actual.values()
    )


def test_temperature_tags_match_temperature_options() -> None:
    for item in load_json(MENU_PATH)["items"]:
        temperature_tags = set(item["tags"]) & {"hot", "iced"}
        assert temperature_tags == set(item["temperature_options"])


def test_beverage_option_policies_match_supported_menu_scope() -> None:
    items = {item["id"]: item for item in load_json(MENU_PATH)["items"]}

    assert {
        menu_id
        for menu_id, item in items.items()
        if item["option_policy"]["shot_supported"]
    } == {"americano", "cafe_latte", "vanilla_latte", "iced_tea"}
    assert {
        menu_id
        for menu_id, item in items.items()
        if item["option_policy"]["decaf_available"]
    } == {"americano", "cafe_latte", "vanilla_latte"}
    assert all(
        item["option_policy"]["size_supported"] == (item["unit"] == "잔")
        for item in items.values()
    )
    assert all(
        item["option_policy"]["syrup_supported"] == (item["unit"] == "잔")
        for item in items.values()
    )
    assert all(
        item["option_policy"]["ice_amount_available"] == (item["unit"] == "잔")
        for item in items.values()
    )


def test_alias_availability_and_size_fields_do_not_exist() -> None:
    for item in load_json(MENU_PATH)["items"]:
        assert "aliases" not in item
        assert "available" not in item
        assert "size" not in item
        assert "sizes" not in item


def test_drinks_and_desserts_have_expected_temperature_policy() -> None:
    iced_only_ids = {"grapefruit_ade", "iced_tea"}

    for item in load_json(MENU_PATH)["items"]:
        if item["id"] in iced_only_ids:
            assert item["temperature_options"] == ["iced"]
        elif item["unit"] == "잔":
            assert item["temperature_options"] == ["hot", "iced"]
        else:
            assert item["temperature_options"] == []


def test_all_prices_are_positive_integers() -> None:
    for item in load_json(MENU_PATH)["items"]:
        assert isinstance(item["base_price"], int)
        assert item["base_price"] > 0


def test_prices_match_verified_same_name_sources() -> None:
    expected = {
        "americano": (4700, "스타벅스", "카페 아메리카노 Tall"),
        "cafe_latte": (5200, "스타벅스", "카페 라떼 Tall"),
        "vanilla_latte": (3400, "메가MGC커피", "바닐라라떼"),
        "grapefruit_ade": (3500, "메가MGC커피", "자몽에이드"),
        "matcha_latte": (3500, "더벤티", "말차라떼"),
        "milk_tea": (3500, "빽다방", "밀크티"),
        "chamomile_tea": (3700, "매머드커피", "캐모마일티"),
        "iced_tea": (4700, "할리스", "아이스티"),
        "croffle_icecream": (5500, "에브리커피", "크로플 아이스크림"),
        "basque_cheesecake": (6500, "어쏠트먼트", "바스크 치즈 케이크"),
    }

    actual = {
        item["id"]: (
            item["base_price"],
            item["price_source_brand"],
            item["price_source_menu_name"],
        )
        for item in load_json(MENU_PATH)["items"]
    }

    assert actual == expected


def test_price_sources_include_url_and_checked_date() -> None:
    for item in load_json(MENU_PATH)["items"]:
        assert item["price_source_url"].startswith("https://")
        assert item["price_checked_at"] == "2026-08-14"
