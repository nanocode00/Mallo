from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from domain.models import MenuTagDefinition


def _search_key(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return "".join(character for character in normalized if character.isalnum())


def resolve_menu_query_tags(
    text: str,
    definitions: Iterable[MenuTagDefinition],
) -> tuple[str, ...]:
    """자연어 메뉴 조건을 Menu DB의 표준 태그 순서로 정규화한다."""
    utterance_key = _search_key(text)
    if not utterance_key:
        return ()

    resolved: list[str] = []
    for definition in definitions:
        if any(_search_key(alias) in utterance_key for alias in definition.aliases):
            resolved.append(definition.id)
    return tuple(resolved)
