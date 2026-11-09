"""Conservative deterministic repairs for the selected Qwen3-0.6B NLU runtime.

The guard is intentionally narrow: it does not replace the model with a rule-based
NLU. It only repairs contract-stress failures where the utterance contains enough
explicit information to determine the missing command unambiguously.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from config.settings import load_menu, load_menu_alias_definitions
from domain.models import MenuItem


_OPTION_TEMPLATE = {
    "size": None,
    "extra_shots": None,
    "caffeine": None,
    "syrup_pumps": None,
    "ice_amount": None,
}

_NATIVE_NUMBERS = {
    "한": 1,
    "하나": 1,
    "두": 2,
    "둘": 2,
    "세": 3,
    "셋": 3,
    "네": 4,
    "넷": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}
_NUMBER_TOKEN = r"(?:\d+|한|하나|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟|아홉|열)"

_HOT_RE = re.compile(r"(?:따뜻|뜨겁|뜨거|핫)")
_ICED_RE = re.compile(r"(?:아이스(?!크림)|차갑|시원)")

_CONTROL_PATTERNS = (
    re.compile(r"주문\s*취소|취소해|취소해\s*줘"),
    re.compile(r"주문\s*확정|확정해|확정해\s*줘"),
    re.compile(r"처음으로\s*돌아|되돌려|실행\s*취소"),
    re.compile(r"다시\s*말|말\s*다시|방금.*다시|한\s*번\s*더\s*말"),
    re.compile(r"속도.*느리|천천히\s*말"),
    re.compile(r"기본.*속도|원래.*속도"),
)
_MUTATION_RE = re.compile(r"(?:추가|주세요|줘|빼|제외|삭제|바꾸|변경|해\s*줘)")
_UPDATE_RE = re.compile(r"(?:바꾸|변경|해\s*줘|해\s*주세요|넣어|추가해)")
_SINGLE_ADD_RE = re.compile(r"(?:주세요|주문해|추가해|추가하고|추가해\s*줘)")
_SINGLE_ADD_BLOCK_RE = re.compile(r"(?:바꾸|변경|빼|제외|삭제)")


@dataclass(frozen=True)
class MenuMention:
    start: int
    end: int
    menu_id: str
    forced_temperature: str | None = None


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _number_value(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        value = int(token)
        return value if value > 0 else None
    return _NATIVE_NUMBERS.get(token)


def _quantity_after(text: str) -> int | None:
    match = re.search(rf"({_NUMBER_TOKEN})\s*(?:잔|개|컵)", text)
    if match:
        return _number_value(match.group(1))
    # The runtime normalizer normally adds a counter. Keep this fallback so the
    # guard remains safe when called directly by a sidecar diagnostic.
    match = re.search(
        rf"({_NUMBER_TOKEN})(?=\s*(?:주세요|줘|주문|추가|부탁|더|그리고|이랑|랑|하고|,|$))",
        text,
    )
    return _number_value(match.group(1)) if match else None


def _count_for_marker(text: str, marker: str) -> int | None:
    patterns = (
        rf"{re.escape(marker)}(?:은|는)?\s*({_NUMBER_TOKEN})\s*(?:번|개|회|샷|펌프)?",
        rf"({_NUMBER_TOKEN})\s*(?:번|개|회|펌프)?\s*{re.escape(marker)}",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _number_value(match.group(1))
    return None


def _temperature_cue(text: str) -> str | None:
    hot = bool(_HOT_RE.search(text))
    iced = bool(_ICED_RE.search(text))
    if hot == iced:
        return None
    return "hot" if hot else "iced"


def _size_cue(text: str) -> str | None:
    matches: list[str] = []
    for value, pattern in (
        ("small", r"(?:스몰|작은\s*사이즈|소형)"),
        ("medium", r"(?:미디엄|중간\s*사이즈|중간으로|보통\s*사이즈)"),
        ("large", r"(?:라지|큰\s*사이즈|대형)"),
    ):
        if re.search(pattern, text):
            matches.append(value)
    return matches[0] if len(set(matches)) == 1 else None


def _option_cues(text: str) -> tuple[dict[str, Any], int]:
    options = dict(_OPTION_TEMPLATE)
    found = 0

    size = _size_cue(text)
    if size is not None:
        options["size"] = size
        found += 1

    shots = _count_for_marker(text, "샷")
    if shots is not None:
        options["extra_shots"] = shots
        found += 1

    syrup = _count_for_marker(text, "시럽")
    if syrup is not None:
        options["syrup_pumps"] = syrup
        found += 1

    ice_matches: list[str] = []
    for value, pattern in (
        ("none", r"얼음\s*(?:없이|빼고|없게)"),
        ("less", r"얼음\s*(?:적게|조금만|덜)"),
        ("more", r"얼음\s*(?:많이|가득|더)"),
        ("normal", r"얼음\s*(?:보통|기본)"),
    ):
        if re.search(pattern, text):
            ice_matches.append(value)
    if len(set(ice_matches)) == 1:
        options["ice_amount"] = ice_matches[0]
        found += 1

    return options, found


def _menu_mentions(
    text: str,
    *,
    menu: Iterable[MenuItem] | None = None,
) -> list[MenuMention]:
    normalized = _normalize(text)
    menu_items = tuple(menu or load_menu())
    matches: list[tuple[int, int, int, MenuMention]] = []

    for item in menu_items:
        surface = _normalize(item.name)
        start = normalized.find(surface)
        if start >= 0:
            mention = MenuMention(start, start + len(surface), item.id)
            matches.append((start, -len(surface), 0, mention))

    for definition in load_menu_alias_definitions():
        surface = _normalize(definition.alias)
        start = normalized.find(surface)
        if start >= 0:
            forced = definition.temperature.value if definition.temperature is not None else None
            mention = MenuMention(start, start + len(surface), definition.target_item_id, forced)
            matches.append((start, -len(surface), 1, mention))

    selected: list[MenuMention] = []
    occupied: list[tuple[int, int]] = []
    seen_ids_at_position: set[tuple[int, str]] = set()
    for _, _, _, mention in sorted(matches):
        key = (mention.start, mention.menu_id)
        if key in seen_ids_at_position:
            continue
        if any(not (mention.end <= left or mention.start >= right) for left, right in occupied):
            continue
        selected.append(mention)
        occupied.append((mention.start, mention.end))
        seen_ids_at_position.add(key)
    return sorted(selected, key=lambda row: row.start)


def _local_temperature(text: str, mention: MenuMention) -> str | None:
    if mention.forced_temperature is not None:
        return mention.forced_temperature
    prefix = text[max(0, mention.start - 12) : mention.start]
    # A cue belongs to the next menu only within its list clause.  In particular,
    # ``아이스티 ..., 크로플 아이스크림`` must not make the dessert iced.
    prefix = re.split(r"(?:,|그리고|이랑|랑|하고)", prefix)[-1]
    return _temperature_cue(prefix)


def _local_quantity(text: str, mention: MenuMention) -> int | None:
    suffix = text[mention.end : min(len(text), mention.end + 16)]
    return _quantity_after(suffix)


def _command(
    intent: str,
    *,
    target_item_id: str | None = None,
    quantity: int | None = None,
    temperature: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "target_item_id": target_item_id,
        "category_id": None,
        "quantity": quantity,
        "temperature": temperature,
        "query_tags": None,
        "detail_fields": None,
        "options": options,
    }


def _mixed_error() -> dict[str, Any]:
    return {
        "code": "MIXED_INTENT",
        "message": "사용자의 주문을 이해하지 못했습니다. 한 번에 하나씩 주문해 주시면 감사하겠습니다.",
        "command_index": None,
        "field": None,
        "candidates": None,
        "retryable": True,
    }


def _clear_control_plus_mutation(text: str, mentions: list[MenuMention]) -> bool:
    if not mentions or not _MUTATION_RE.search(text):
        return False
    return any(pattern.search(text) for pattern in _CONTROL_PATTERNS)


def _explicit_add_commands(text: str, mentions: list[MenuMention]) -> list[dict[str, Any]] | None:
    if not mentions:
        return None
    commands: list[dict[str, Any]] = []
    for mention in mentions:
        temperature = _local_temperature(text, mention)
        quantity = _local_quantity(text, mention)
        if quantity is None:
            return None
        commands.append(
            _command(
                "ADD_ITEM",
                target_item_id=mention.menu_id,
                quantity=quantity,
                temperature=temperature,
                options=None,
            )
        )
    return commands


def _looks_like_single_add_request(text: str) -> bool:
    return bool(_SINGLE_ADD_RE.search(text)) and not bool(_SINGLE_ADD_BLOCK_RE.search(text))


def _recover_update_option(
    text: str,
    cart_before: list[dict[str, Any]],
    mentions: list[MenuMention],
) -> list[dict[str, Any]] | None:
    if len(mentions) != 1 or not _UPDATE_RE.search(text):
        return None
    target = mentions[0].menu_id
    if sum(row.get("menu_id") == target for row in cart_before) != 1:
        return None

    temperature = _temperature_cue(text)
    options, option_count = _option_cues(text)
    if temperature is None and option_count == 0:
        return None
    return [
        _command(
            "UPDATE_OPTION",
            target_item_id=target,
            temperature=temperature,
            options=options,
        )
    ]


def _patch_single_update_option(
    text: str,
    command: dict[str, Any],
    mentions: list[MenuMention],
) -> dict[str, Any]:
    if command.get("intent") != "UPDATE_OPTION":
        return command
    target = command.get("target_item_id")
    if len(mentions) != 1 or mentions[0].menu_id != target:
        return command

    repaired = dict(command)
    explicit_temperature = _temperature_cue(text)
    if explicit_temperature is not None:
        repaired["temperature"] = explicit_temperature

    explicit_options, option_count = _option_cues(text)
    if option_count:
        existing = repaired.get("options")
        merged = dict(_OPTION_TEMPLATE)
        if isinstance(existing, dict):
            merged.update({key: existing.get(key) for key in _OPTION_TEMPLATE})
        for key, value in explicit_options.items():
            if value is not None:
                merged[key] = value
        repaired["options"] = merged
    return repaired


def repair_qwen06b_payload(
    text: str,
    cart_before: list[dict[str, Any]],
    payload: Any,
    *,
    menu: Iterable[MenuItem] | None = None,
) -> Any:
    """Apply only high-confidence deterministic repairs to one Qwen prediction."""

    normalized = _normalize(text)
    mentions = _menu_mentions(normalized, menu=menu)

    if _clear_control_plus_mutation(normalized, mentions):
        return _mixed_error()

    explicit_adds = _explicit_add_commands(normalized, mentions)

    if isinstance(payload, dict):
        code = payload.get("code")

        if (
            (
                code in {"MISSING_FIELD", "UNSUPPORTED_UTTERANCE"}
                or (code == "AMBIGUOUS_TARGET" and payload.get("field") == "temperature")
            )
            and explicit_adds is not None
            and len(explicit_adds) == 1
            and _looks_like_single_add_request(normalized)
        ):
            return explicit_adds

        if code in {"MIXED_INTENT", "INVALID_JSON"} and explicit_adds is not None and len(explicit_adds) >= 2 and _looks_like_single_add_request(normalized):
            return explicit_adds

        if code in {"MIXED_INTENT", "UNSUPPORTED_UTTERANCE", "MISSING_FIELD"}:
            recovered = _recover_update_option(normalized, cart_before, mentions)
            if recovered is not None:
                return recovered
        return payload

    if explicit_adds is not None and len(explicit_adds) >= 2 and _looks_like_single_add_request(normalized):
        return explicit_adds

    if (
        explicit_adds is not None
        and len(explicit_adds) == 1
        and _looks_like_single_add_request(normalized)
        and not any(row.get("menu_id") == explicit_adds[0]["target_item_id"] for row in cart_before)
    ):
        # An explicitly named menu absent from the cart is a new ADD_ITEM, even
        # if a small model mistakenly labels it as an update of another item.
        return explicit_adds

    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return [_patch_single_update_option(normalized, payload[0], mentions)]

    return payload
