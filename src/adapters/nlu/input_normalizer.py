"""Conservative Korean NLU input normalization with diagnostics.

This module intentionally returns text, never a menu ID or an OrderCommand.  The
model and the existing OrderCommand contract remain the semantic authority.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedNLUInput:
    original_text: str
    normalized_text: str
    replacements: tuple[tuple[str, str], ...]


# These are observed transcription confusions, not full-sentence challenge rules.
_MENU_ALIASES = (
    ("카페라테", "카페라떼"),
    ("카페라트", "카페라떼"),
    ("자몽이도", "자몽에이드"),
    ("자몽레이드", "자몽에이드"),
    ("케모마일티", "캐모마일티"),
    ("바스크 치즈케이크", "바스크 치즈 케이크"),
    ("넌커피", "논커피"),
)
_COUNTER_NUMBERS = (("하나", "1"), ("한", "1"), ("둘", "2"), ("두", "2"), ("셋", "3"), ("세", "3"))
_COUNTERS = "잔|개|컵"
_REQUEST_OR_SEPARATOR = r"(?:주세요|줘|주문|추가|부탁|더|그리고|이랑|랑|하고|,|$)"


def _replace_menu_aliases(text: str, replacements: list[tuple[str, str]]) -> str:
    for alias, canonical in _MENU_ALIASES:
        # Do not rewrite a substring embedded in a longer Korean/Latin word.
        pattern = re.compile(rf"(?<![0-9A-Za-z가-힣]){re.escape(alias)}(?![0-9A-Za-z가-힣])")
        text, count = pattern.subn(canonical, text)
        replacements.extend((alias, canonical) for _ in range(count))
    return text


def _replace_quantities(text: str, replacements: list[tuple[str, str]]) -> str:
    for source, target in _COUNTER_NUMBERS:
        pattern = re.compile(rf"{re.escape(source)}\s*({_COUNTERS})")
        text, count = pattern.subn(lambda match: f"{target}{match.group(1)}", text)
        replacements.extend((source, target) for _ in range(count))

    # Counter-less colloquial quantities are accepted only in request/list contexts,
    # avoiding substitutions in ordinary prose such as product descriptions.
    for source, target in (("하나", "1개"), ("둘", "2개"), ("셋", "3개")):
        pattern = re.compile(rf"{re.escape(source)}(?=\s*{_REQUEST_OR_SEPARATOR})")
        text, count = pattern.subn(target, text)
        replacements.extend((source, target) for _ in range(count))
    return text


def normalize_nlu_input(text: str) -> NormalizedNLUInput:
    """Normalize only approved menu and quantity surface forms."""

    original = text
    normalized = unicodedata.normalize("NFC", text)
    replacements: list[tuple[str, str]] = []
    normalized = _replace_menu_aliases(normalized, replacements)
    normalized = _replace_quantities(normalized, replacements)
    return NormalizedNLUInput(original, normalized, tuple(replacements))
