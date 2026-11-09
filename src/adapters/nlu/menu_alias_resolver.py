from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from domain.models import MenuAliasDefinition


class AmbiguousMenuAliasError(ValueError):
    def __init__(self, alias: str, candidates: Iterable[str]) -> None:
        self.alias = alias
        self.candidates = tuple(dict.fromkeys(candidates))
        super().__init__(f"모호한 메뉴 별칭입니다: {alias}")


def _search_key(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _alias_position(text: str, alias: str) -> int | None:
    normalized = unicodedata.normalize("NFC", text).casefold()
    alias_key = _search_key(alias)
    particles = "은|는|이|가|을|를|랑|하고|도|로|으로"
    pattern = re.compile(
        rf"(?<![0-9a-z가-힣]){re.escape(alias_key)}"
        rf"(?=(?:{particles})?(?:[^0-9a-z가-힣]|$))"
    )
    match = pattern.search(normalized)
    return match.start() if match is not None else None


def resolve_menu_aliases(
    text: str,
    definitions: Iterable[MenuAliasDefinition],
) -> tuple[MenuAliasDefinition, ...]:
    """발화에 포함된 메뉴 별칭을 등장 순서대로 해석한다."""
    matches: dict[str, tuple[int, list[MenuAliasDefinition]]] = {}
    for definition in definitions:
        alias_key = _search_key(definition.alias)
        position = _alias_position(text, definition.alias)
        if alias_key and position is not None:
            matches.setdefault(alias_key, (position, []))[1].append(definition)

    resolved: list[tuple[int, MenuAliasDefinition]] = []
    for _, (position, candidates) in matches.items():
        interpretations = {
            (candidate.target_item_id, candidate.temperature) for candidate in candidates
        }
        if len(interpretations) > 1:
            raise AmbiguousMenuAliasError(
                candidates[0].alias,
                (candidate.target_item_id for candidate in candidates),
            )
        resolved.append((position, candidates[0]))

    return tuple(definition for _, definition in sorted(resolved, key=lambda item: item[0]))
