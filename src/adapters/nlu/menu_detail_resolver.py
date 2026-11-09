from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from domain.models import MenuDetailField, MenuItem


_FIELD_KEYWORDS = {
    MenuDetailField.DESCRIPTION: (
        "어떤 음료",
        "어떤 메뉴",
        "무슨 음료",
        "뭐야",
        "설명",
        "알려",
    ),
    MenuDetailField.PRICE: ("가격", "얼마"),
    MenuDetailField.SWEETNESS: ("단맛", "당도", "달아", "달아요", "달지"),
    MenuDetailField.CAFFEINE: ("카페인",),
    MenuDetailField.MILK: ("우유",),
    MenuDetailField.TEMPERATURE: ("온도", "따뜻", "뜨겁", "차갑", "아이스", "핫"),
}


def _search_key(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return "".join(character for character in normalized if character.isalnum())


def resolve_menu_detail_query(
    text: str,
    menu_items: Iterable[MenuItem],
) -> tuple[str, tuple[MenuDetailField, ...]] | None:
    """공식 메뉴명과 질문 항목이 있는 상세 조회를 정규화한다."""
    utterance_key = _search_key(text)
    targets = [item for item in menu_items if _search_key(item.name) in utterance_key]
    if len(targets) != 1:
        return None

    matches: list[tuple[int, MenuDetailField]] = []
    for field, keywords in _FIELD_KEYWORDS.items():
        positions = [
            utterance_key.find(_search_key(keyword))
            for keyword in keywords
            if _search_key(keyword) in utterance_key
        ]
        if positions:
            matches.append((min(positions), field))
    if not matches:
        return None
    fields = tuple(field for _, field in sorted(matches, key=lambda match: match[0]))
    return targets[0].id, fields
