"""Level-specific canonical response realization.

The order engine owns the semantic result.  This module is the only place that
may turn that result into a more listenable Level 2 canonical response; the
TTS transformer must only pronounce numbers and split that canonical text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Iterable, Mapping

from domain.intents import Intent
from domain.models import Cart, MenuItem, OrderCommand, OrderResult, Temperature


@dataclass(frozen=True)
class RealizedResponse:
    """One canonical response and its authoritative display segmentation."""

    text: str
    display_segments: tuple[str, ...] | None = None


class AdaptiveResponseRealizer:
    """Rebuild only proven semantic shapes for the Level 2 listening mode.

    Unknown, option-bearing, or failed responses deliberately keep the order
    engine's canonical response.  That makes the fallback lossless instead of
    trying to infer semantics from a completed Korean sentence.
    """

    _CATEGORY_NAMES = {
        "coffee": "커피",
        "non_coffee": "논커피",
        "tea": "티",
        "dessert": "디저트",
    }
    _QUANTITIES = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯"}

    def __init__(self, menu_by_id: Mapping[str, MenuItem]) -> None:
        self._menu_by_id = dict(menu_by_id)

    def realize(
        self,
        result: OrderResult,
        commands: Iterable[OrderCommand],
        *,
        level: int,
    ) -> RealizedResponse:
        if not result.success:
            return RealizedResponse(result.response_text)

        command_list = tuple(commands)
        add_text = self._realize_add(command_list, level=level)
        if add_text:
            return RealizedResponse(
                add_text,
                self._sentence_segments(add_text) if level == 2 else None,
            )
        if level != 2:
            return RealizedResponse(result.response_text)
        text = (
            self._realize_menu(command_list)
            or self._realize_cart(command_list, result.cart)
            or self._realize_update_then_add(command_list)
            or result.response_text
        )
        # An L2 rebuild is intentionally sentence-based: each sentence can be
        # one display segment while the TTS layer may still subdivide only its
        # own canonical text when necessary.
        return RealizedResponse(text, self._sentence_segments(text))

    def _realize_add(self, commands: tuple[OrderCommand, ...], *, level: int) -> str | None:
        if len(commands) < 2 or any(command.intent is not Intent.ADD_ITEM for command in commands):
            return None
        if any(command.options is not None and not command.options.is_empty for command in commands):
            return None
        phrases = [self._command_item_phrase(command) for command in commands]
        if any(phrase is None for phrase in phrases):
            return None
        item_phrases = [phrase for phrase in phrases if phrase]
        if level == 2:
            return " ".join(f"{phrase}입니다." for phrase in item_phrases) + " 장바구니에 담았습니다."
        return f"{'과 '.join(item_phrases[:-1])}과 {item_phrases[-1]}{self._object_particle(item_phrases[-1])} 장바구니에 담았습니다."

    def _realize_menu(self, commands: tuple[OrderCommand, ...]) -> str | None:
        if len(commands) != 1:
            return None
        command = commands[0]
        if command.intent is not Intent.QUERY_MENU or command.query_tags is not None:
            return None
        if command.category_id is None:
            category_ids = tuple(self._CATEGORY_NAMES)
        elif command.category_id in self._CATEGORY_NAMES:
            category_ids = (command.category_id,)
        else:
            return None

        sentences: list[str] = []
        for category_id in category_ids:
            items = [item for item in self._menu_by_id.values() if item.category_id == category_id]
            if not items:
                continue
            sentences.append(f"{self._CATEGORY_NAMES[category_id]} 메뉴입니다.")
            sentences.extend(
                f"{item.name}{self._subject_particle(item.name)} {item.base_price:,}원입니다."
                for item in items
            )
        return " ".join(sentences) or None

    def _realize_cart(self, commands: tuple[OrderCommand, ...], cart: Cart) -> str | None:
        if len(commands) != 1 or commands[0].intent is not Intent.QUERY_CART or not cart.items:
            return None
        if any(not item.options.is_empty for item in cart.items):
            return None
        sentences: list[str] = []
        if cart.fulfillment_type is not None:
            sentences.append("매장 이용 주문입니다." if cart.fulfillment_type.value == "dine_in" else "포장 주문입니다.")
        for item in cart.items:
            phrase = self._cart_item_phrase(item.menu_id, item.quantity, item.temperature)
            if phrase is None:
                return None
            sentences.append(f"{phrase}입니다.")
        sentences.append(f"총 결제 금액은 {cart.total_price:,}원입니다.")
        return " ".join(sentences)

    def _realize_update_then_add(self, commands: tuple[OrderCommand, ...]) -> str | None:
        if len(commands) != 2 or {command.intent for command in commands} != {Intent.UPDATE_OPTION, Intent.ADD_ITEM}:
            return None
        update = next(command for command in commands if command.intent is Intent.UPDATE_OPTION)
        add = next(command for command in commands if command.intent is Intent.ADD_ITEM)
        if update.options is not None or update.temperature is None:
            return None
        item = self._menu_by_id.get(update.target_item_id or "")
        add_phrase = self._command_item_phrase(add)
        if item is None or add_phrase is None or (add.options is not None and not add.options.is_empty):
            return None
        particle = self._object_particle(item.name)
        temperature = "따뜻한 음료" if update.temperature is Temperature.HOT else "아이스 음료"
        return f"{item.name}{particle} {temperature}로 변경했습니다. {add_phrase}을 추가했습니다."

    def _command_item_phrase(self, command: OrderCommand) -> str | None:
        if command.target_item_id is None or command.quantity is None or command.quantity < 1:
            return None
        return self._cart_item_phrase(command.target_item_id, command.quantity, command.temperature)

    def _cart_item_phrase(self, menu_id: str, quantity: int, temperature: Temperature | None) -> str | None:
        item = self._menu_by_id.get(menu_id)
        if item is None:
            return None
        temperature_prefix = ""
        if len(item.temperature_options) > 1:
            temperature_prefix = {
                Temperature.HOT: "따뜻한 ",
                Temperature.ICED: "아이스 ",
                None: "",
            }[temperature]
        quantity_text = self._QUANTITIES.get(quantity, str(quantity))
        return f"{temperature_prefix}{item.name} {quantity_text} {item.unit}"

    @staticmethod
    def _object_particle(word: str) -> str:
        last = word[-1]
        if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28:
            return "을"
        return "를"

    @staticmethod
    def _subject_particle(word: str) -> str:
        last = word[-1]
        if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28:
            return "은"
        return "는"

    @staticmethod
    def _sentence_segments(text: str) -> tuple[str, ...]:
        segments = tuple(
            part.strip()
            for part in re.split(r"(?<=[.?!])\s+", text)
            if part.strip()
        )
        return segments or (text,)
