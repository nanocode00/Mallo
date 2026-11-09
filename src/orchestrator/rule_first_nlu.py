"""Narrow deterministic fast path before the existing NLU backend."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace

from config.settings import load_menu
from domain.intents import Intent
from domain.models import BeverageOptions, Cart, FulfillmentType, OrderCommand, OrderCommandError, OrderCommandErrorCode, Temperature
from interfaces.nlu import NLU, NLUResult


_QUANTITIES = {
    "한": 1, "하나": 1, "한개": 1, "한잔": 1, "한컵": 1,
    "두": 2, "둘": 2, "두개": 2, "두잔": 2, "두컵": 2,
    "세": 3, "셋": 3, "세개": 3, "세잔": 3, "세컵": 3,
    "네": 4, "네개": 4, "네잔": 4, "네컵": 4,
    "다섯": 5, "다섯개": 5, "다섯잔": 5, "다섯컵": 5,
}
_FULFILLMENT_ENDING = r"(?:해(?:주세요|줘)|할(?:게요|게|래요|래)|(?:게요|게|래요|래)|요)?"
_TAKEOUT_PATTERNS = (
    re.compile(rf"포장(?:을)?(?:으로)?{_FULFILLMENT_ENDING}"),
    re.compile(rf"테이크아웃{_FULFILLMENT_ENDING}"),
    re.compile(rf"(?:가져|들고|가지고)갈{_FULFILLMENT_ENDING}"),
    re.compile(rf"포장(?:해)?갈{_FULFILLMENT_ENDING}"),
    re.compile(rf"포장해서(?:먹을|갈){_FULFILLMENT_ENDING}"),
    re.compile(r"포장하고싶어"),
)
_DINE_IN_PATTERNS = (
    re.compile(rf"(?:매장(?:에서)?|여기서|안에서)(?:먹을|먹고갈|먹기|이용할|이용){_FULFILLMENT_ENDING}"),
    re.compile(rf"먹고갈{_FULFILLMENT_ENDING}"),
)
_DINE_IN_DIRECT = frozenset({"매장", "매장에서", "매장이용", "매장에서이용", "매장에서주문", "매장으로할게", "매장으로할게요"})
_DANGEROUS_EVIDENCE = {
    Intent.UNDO: ("취소", "되돌려", "방금거취소"),
    Intent.REMOVE_ITEM: ("빼", "삭제", "제거", "취소"),
    Intent.CONFIRM_ORDER: (
        "주문확인", "주문확정", "주문진행", "이대로주문", "이대로할",
    ),
    Intent.REQUEST_REPEAT: ("다시말", "다시들려", "다시들어"),
    Intent.REQUEST_SLOWER: ("천천히", "느리게", "속도", "더천천히"),
    Intent.SELECT_PAYMENT_METHOD: ("카드", "삼성페이", "카카오페이", "현금"),
    Intent.CANCEL: (
        "전체취소", "전부취소", "모두취소", "다취소", "전부빼", "다비워", "싹비워",
        "전체주문취소", "전부주문취소", "모두주문취소",
        "장바구니전체취소", "장바구니전부취소", "장바구니모두취소",
        "장바구니비워", "장바구니비우", "장바구니비도", "장바구니비소",
        "장바구니다빼", "장바구니다삭제", "장바구니전부빼",
    ),
    Intent.RESET_ORDER: ("처음부터", "다시처음부터"),
}
_COMPREHENSION_SIGNALS = frozenset({
    "못알아들었어", "못알아들었어요", "잘못들었어", "잘못들었어요",
    "뭐라고", "뭐라고요", "무슨말이야", "무슨말이에요",
    "다시설명해줘", "다시설명해주세요", "다시안내해줘", "다시안내해주세요",
    "이해가안돼", "이해가안돼요", "이해못했어", "이해못했어요",
    "잘모르겠어", "잘모르겠어요",
})
_GARBLED_TWO = frozenset({
    "도전", "투자", "투은잔", "투자안", "투잔", "두전", "두자",
})
_ICED_TEMPERATURE_CUES = ("아이스", "아이소", "아이시", "아이수", "에이스", "차가운", "차갑게", "시원하게", "시원한")
_HOT_TEMPERATURE_CUES = ("따뜻", "뜨겁게", "뜨거운")
_TEMPERATURE_CUES = (
    "아이스로", "아이스요", "아이스", "에이스로", "에이스요", "에이스", "아이소로", "아이소요", "아이소",
    "아이시로", "아이시요", "아이시", "아이수로", "아이수요", "아이수",
    "차가운걸로", "차가운", "차갑게요", "차갑게",
    "시원한걸로", "시원한", "시원하게요", "시원하게",
    "따뜻하게요", "따뜻하게", "따뜻한걸로", "따뜻한거로", "따뜻한거", "따뜻한",
    "뜨겁게요", "뜨겁게", "뜨거운걸로", "뜨거운거로", "뜨거운거", "뜨거운", "걸로",
)
_LEADING_FILLER_RE = re.compile(
    r"^(?:(?:어|음|아|그|저)(?:[\s.,…~-]+|$))+",
)
_OPTION_CHANGE_CUES = ("바꿔", "변경", "넣어", "빼")
_PAYMENT_METHODS = (
    ("삼성페이", "samsung"),
    ("카카오페이", "kakao"),
    ("신용카드", "card"),
    ("체크카드", "card"),
    ("카드", "card"),
    ("현금", "cash"),
)
_PAYMENT_RETRY_MESSAGE = "결제수단을 다시 말씀해 주세요."
# Category query: colloquial alias → canonical category_id.
_CATEGORY_QUERY_ALIASES: dict[str, str] = {
    "차": "tea", "티": "tea",
    "논커피": "non_coffee", "넌커피": "non_coffee",
    "커피": "coffee",
    "디저트": "dessert",
}
# '뭐있어' / '뭐있어요' / '에뭐있어' etc. after a category keyword.
_CATEGORY_QUERY_PARTICLES = ("에는", "에", "은", "는")
_CATEGORY_QUERY_CUES = frozenset({
    "뭐있어", "뭐있어요", "뭐있나요", "뭐있나", "뭐있죠", "뭐가있어", "뭐가있어요", "뭐가있나요", "뭐가있죠", "어떤거있어", "어떤거있어요",
    "종류", "메뉴", "알려줘", "알려주세요", "보여줘", "보여주세요",
    "종류알려줘", "종류알려주세요", "종류보여줘", "종류보여주세요",
    "메뉴알려줘", "메뉴알려주세요", "메뉴보여줘", "메뉴보여주세요",
})
_ITEM_REMOVE_CUES = ("빼", "삭제", "제거", "취소")
_CART_QUERY_SCOPES = ("장바구니", "현재주문", "주문한거", "담은거")
_CART_QUERY_CUES = ("보여", "볼래", "확인", "뭐담았", "뭐들어")
# Self-correction: '아니' (optionally '아니요/아니야/아니라') splits the
# utterance.  Only the segment after the LAST correction marker is used.
_SELF_CORRECTION_RE = re.compile(r"\s*아니(?:요|야|라|고|다)?\s+")
_MENU_CORRECTION_RE = re.compile(r"\s+말고\s+")
_QUANTITY_PHRASE_RE = re.compile(
    r"(?:한|두|세|네|다섯|하나|둘|셋|[1-9][0-9]*)\s*(?:잔|개|컵)?\s*$"
)


def _compact(text: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFC", text).casefold() if character.isalnum())


def _strip_polite_ending(compact: str) -> str:
    """Remove only a terminal polite/quantity ending from an otherwise exact reply."""
    return re.sub(r"(?:해주세요|해줘|할게요|할게|할래요|할래|주세요|줘|주소|도|요|죠)$", "", compact)


def _strip_reply_suffix(compact: str) -> str:
    return re.sub(r"(?:을|를|이)?(?:만)?(?:으로|로)?$", "", _strip_polite_ending(compact))


def _quantity(text: str, *, allow_garbled_two: bool = False) -> int | None:
    compact = _compact(text)
    # Clarification replies often retain a polite ending ("두 잔 주세요").
    # Accept only an entire quantity reply plus that ending; never use a
    # substring match that could turn an unrelated STT fragment into quantity.
    compact = _strip_reply_suffix(compact)
    quantity = _QUANTITIES.get(compact)
    if quantity is not None:
        return quantity
    if allow_garbled_two:
        if compact in _GARBLED_TWO:
            return 2
        for token in _GARBLED_TWO:
            if compact == token * 2:
                return 2
    numeric = re.fullmatch(r"([1-9][0-9]*)(?:잔|개|컵)?", compact)
    if numeric is not None:
        return int(numeric.group(1))
    # STT can duplicate a short quantity token (for example, "세잔 세잔").
    # It is one requested quantity when every repeated token resolves equally.
    for token, candidate in _QUANTITIES.items():
        if compact == token * 2:
            return candidate
    return None


def _category_query_id(compact: str) -> str | None:
    """Resolve only an explicit category name plus a menu-query cue."""
    aliases = sorted(
        _CATEGORY_QUERY_ALIASES.items(),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    for alias, category_id in aliases:
        if not compact.startswith(alias):
            continue
        suffix = compact.removeprefix(alias)
        for particle in ("중에", *_CATEGORY_QUERY_PARTICLES):
            if suffix.startswith(particle):
                suffix = suffix.removeprefix(particle)
                break
        if suffix in _CATEGORY_QUERY_CUES:
            return category_id
    return None


def _temperature_from_compact(compact: str) -> Temperature | None:
    iced_positions = [compact.rfind(cue) for cue in _ICED_TEMPERATURE_CUES if cue in compact]
    hot_positions = [compact.rfind(cue) for cue in _HOT_TEMPERATURE_CUES if cue in compact]
    has_iced = bool(iced_positions)
    has_hot = bool(hot_positions)
    if has_iced == has_hot:
        if "말고" not in compact or not has_iced:
            return None
        return Temperature.ICED if max(iced_positions) > max(hot_positions) else Temperature.HOT
    return Temperature.ICED if has_iced else Temperature.HOT


def _apply_self_correction(
    text: str,
    *,
    has_pending_add: bool,
    menu_keys: tuple[str, ...],
) -> str:
    """Keep the correction while retaining menu context when it is omitted.

    A correction may repeat the whole order (``아이스 아메리카노 아니 따뜻한
    아메리카노 한 잔``) or correct only its last slot (``아메리카노 한 잔 아니
    두 잔``).  A pending question has all prior slots already, so its final
    segment is always sufficient.
    """
    parts = _SELF_CORRECTION_RE.split(text)
    if len(parts) == 1 or not parts[-1].strip():
        return text
    corrected = parts[-1].strip()
    if has_pending_add:
        return corrected
    if any(menu_key in _compact(corrected) for menu_key in menu_keys):
        return corrected
    prefix = parts[0].strip()
    # The right side corrects a trailing count; remove only that count from
    # the left side and retain its menu/temperature context.
    preserved = _QUANTITY_PHRASE_RE.sub("", prefix).strip()
    return f"{preserved} {corrected}".strip()


def _apply_menu_correction(text: str, *, menu_keys: tuple[str, ...]) -> str:
    """Apply ``A 말고 B`` only to an unambiguous non-destructive menu swap."""
    parts = _MENU_CORRECTION_RE.split(text)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return text
    before, corrected = (part.strip() for part in parts)
    if any(cue in _compact(text) for cue in _ITEM_REMOVE_CUES):
        return text
    before_compact = _compact(before)
    corrected_compact = _compact(corrected)
    before_menus = [key for key in menu_keys if key in before_compact]
    corrected_menus = [key for key in menu_keys if key in corrected_compact]
    if len(before_menus) != 1 or len(corrected_menus) != 1:
        return text
    if _quantity(corrected) is not None:
        return corrected
    quantity_match = _QUANTITY_PHRASE_RE.search(before)
    if quantity_match is None:
        return corrected
    return f"{corrected} {quantity_match.group(0)}"


@dataclass(frozen=True)
class PendingAdd:
    target_item_id: str
    quantity: int | None
    temperature: Temperature | None
    missing_field: str
    fulfillment_type: FulfillmentType | None = None
    options: BeverageOptions | None = None


class RuleFirstNLU:
    """Use rules only for unambiguous common turns; otherwise delegate unchanged."""

    def __init__(self, fallback: NLU) -> None:
        self._fallback = fallback
        self._menu_by_key = {_compact(item.name): item for item in load_menu()}
        for alias, item_id in (
            ("카페라타", "cafe_latte"),
            ("카페라테", "cafe_latte"),
            ("카페라트에", "cafe_latte"),
            ("케모마일티", "chamomile_tea"),
        ):
            target = self._menu_by_id(item_id)
            if target is not None:
                self._menu_by_key[_compact(alias)] = target
        self._category_ids = frozenset(item.category_id for item in self._menu_by_key.values())
        self._pending_add: PendingAdd | None = None
        self.last_source: str | None = None

    def reset_session(self) -> None:
        self._pending_add = None
        self.last_source = None

    def parse(self, text: str, current_order_state: Cart) -> NLUResult:
        cleaned_text = _LEADING_FILLER_RE.sub("", text.strip()).strip()
        if cleaned_text:
            text = cleaned_text
        text = _apply_self_correction(
            text,
            has_pending_add=self._pending_add is not None,
            menu_keys=tuple(self._menu_by_key),
        )
        text = _apply_menu_correction(text, menu_keys=tuple(self._menu_by_key))
        compact = _compact(text)
        compact = re.sub(r"^(?:어|음)+", "", compact)
        # Category query: particle choice must not change a clear query.
        category_id = _category_query_id(compact)
        if category_id is not None:
            self._pending_add = None
            self.last_source = "rule_category_query"
            return [OrderCommand.create(Intent.QUERY_MENU, category_id=category_id)]
        # This is an intentionally narrow semantic fast path: unlike an NLU
        # failure, it says that the user did not understand the preceding
        # system guidance. It remains an OrderCommand intent to the pipeline.
        if compact in _COMPREHENSION_SIGNALS:
            self._pending_add = None
            self.last_source = "rule_request_clarification"
            return [OrderCommand.create(Intent.REQUEST_CLARIFICATION)]
        # Caffeine data remains readable in the catalog, but decaf is not an
        # order option in this product release. Handle the full expression
        # before a fallback can reinterpret it as a menu-detail question.
        if "디카페인" in compact:
            self.last_source = "rule_decaf_out_of_scope"
            return OrderCommandError(
                code=OrderCommandErrorCode.UNSUPPORTED_UTTERANCE,
                message="디카페인 옵션은 현재 제공하지 않습니다.",
            )
        if self._pending_add is not None and self._is_temperature_reply(compact):
            pending = self._pending_add
            pending = replace(
                pending,
                temperature=self._pending_temperature(compact),
                missing_field=("quantity" if pending.quantity is None else ""),
            )
            if pending.quantity is None:
                self._pending_add = pending
                self.last_source = "rule_pending_quantity"
                return self._missing_quantity_error(pending.target_item_id)
            self._pending_add = None
            self.last_source = "rule_pending_temperature"
            add = OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id=pending.target_item_id,
                quantity=pending.quantity,
                temperature=pending.temperature,
                options=pending.options,
            )
            if pending.fulfillment_type is not None:
                return [
                    OrderCommand.create(
                        Intent.SET_FULFILLMENT,
                        fulfillment_type=pending.fulfillment_type,
                    ),
                    add,
                ]
            return [add]
        quantity = _quantity(
            text,
            allow_garbled_two=(
                self._pending_add is not None
                and (self._pending_add.missing_field == "quantity" or self._pending_add.quantity is None)
            ),
        )
        if self._pending_add is not None and quantity is not None:
            pending = self._pending_add
            pending = replace(
                pending,
                quantity=quantity,
                missing_field="",
            )
            menu_item = self._menu_by_id(pending.target_item_id)
            if menu_item is not None and self._requires_temperature(menu_item) and pending.temperature is None:
                self._pending_add = replace(pending, missing_field="temperature")
                self.last_source = "rule_pending_temperature"
                return self._missing_temperature_error()
            self._pending_add = None
            self.last_source = "rule_pending_quantity"
            add = OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id=pending.target_item_id,
                quantity=pending.quantity,
                temperature=pending.temperature,
                options=pending.options,
            )
            if pending.fulfillment_type is not None:
                return [
                    OrderCommand.create(
                        Intent.SET_FULFILLMENT,
                        fulfillment_type=pending.fulfillment_type,
                    ),
                    add,
                ]
            return [add]

        if self._is_no_change_reply(compact):
            self._pending_add = None
            self.last_source = "rule_no_change"
            return [OrderCommand.create(Intent.QUERY_CART)]
        if self._is_cart_query(compact):
            self._pending_add = None
            self.last_source = "rule_cart_query"
            return [OrderCommand.create(Intent.QUERY_CART)]
        if self._is_reset_order(compact):
            self._pending_add = None
            self.last_source = "rule_reset_order"
            return [OrderCommand.create(Intent.RESET_ORDER)]
        if self._is_undo_order(compact):
            self._pending_add = None
            self.last_source = "rule_undo_order"
            return [OrderCommand.create(Intent.UNDO)]
        result = self._parse_menu_remove(compact)
        if result is not None:
            self._pending_add = None
            self.last_source = "rule_menu_remove"
            return [result]
        if self._is_cancel_order(compact):
            self._pending_add = None
            self.last_source = "rule_cancel_order"
            return [OrderCommand.create(Intent.CANCEL)]
        if self._is_confirm_order(compact) and not (
            current_order_state.confirmed and self._is_payment_progress_confirm(compact)
        ):
            self._pending_add = None
            self.last_source = "rule_confirm_order"
            return [OrderCommand.create(Intent.CONFIRM_ORDER)]
        if self._is_repeat_request(compact):
            self.last_source = "rule_request_repeat"
            return [OrderCommand.create(Intent.REQUEST_REPEAT)]
        if self._is_slower_request(compact):
            self.last_source = "rule_request_slower"
            return [OrderCommand.create(Intent.REQUEST_SLOWER)]
        if current_order_state.confirmed:
            payment_method = self._payment_method(compact)
            if payment_method is not None:
                self.last_source = "rule_payment_method"
                return [
                    OrderCommand.create(
                        Intent.SELECT_PAYMENT_METHOD,
                        target_item_id=payment_method,
                    )
                ]
        fulfillment = self._fulfillment(compact)
        if fulfillment is not None:
            if self._pending_add is not None:
                self._pending_add = replace(self._pending_add, fulfillment_type=fulfillment)
            self.last_source = "rule_fulfillment"
            return [OrderCommand.create(Intent.SET_FULFILLMENT, fulfillment_type=fulfillment)]

        fulfillment, compact_without_fulfillment = self._embedded_fulfillment(compact)
        if fulfillment is not None:
            result = self._parse_menu_add(compact_without_fulfillment, fulfillment)
            if result is not None:
                self._pending_add = None
                self.last_source = "rule_menu_add_with_fulfillment"
                if current_order_state.items:
                    return [result]
                return [
                    OrderCommand.create(Intent.SET_FULFILLMENT, fulfillment_type=fulfillment),
                    result,
                    OrderCommand.create(Intent.CONFIRM_ORDER),
                ]
            if self._pending_add is not None:
                return self._pending_error()
            menu_matches = [(key, item) for key, item in self._menu_by_key.items() if key in compact_without_fulfillment]
            if len(menu_matches) == 1:
                menu_key, item = menu_matches[0]
                temperature = self._temperature_in_order(compact_without_fulfillment)
                if temperature not in item.temperature_options:
                    temperature = None
                self._pending_add = PendingAdd(item.id, None, temperature, "quantity", fulfillment)
                self.last_source = "rule_pending_missing_quantity"
                return self._missing_quantity_error(item.id)

        result = self._parse_menu_add(compact)
        if result is not None:
            self._pending_add = None
            self.last_source = "rule_menu_add"
            return [result]
        result = self._parse_quantity_delta_add(compact, current_order_state)
        if result is not None:
            self._pending_add = None
            self.last_source = "rule_quantity_add"
            return result if isinstance(result, OrderCommandError) else [result]
        result = self._parse_quantity_update(compact, current_order_state)
        if result is not None:
            self._pending_add = None
            self.last_source = "rule_quantity_update"
            return [result]
        result = self._parse_partial_temperature_update(compact, current_order_state)
        if result is not None:
            self._pending_add = None
            self.last_source = "rule_partial_temperature_update"
            return result if isinstance(result, OrderCommandError) else [result]
        if self._pending_add is not None:
            return self._pending_error()

        menu_matches = [
            (key, item) for key, item in self._menu_by_key.items() if key in compact
        ]
        if len(menu_matches) == 1:
            menu_key, item = menu_matches[0]
            temperature = self._temperature_in_order(compact)
            if temperature is not None and temperature not in item.temperature_options:
                temperature = None
            remainder = compact.replace(menu_key, "", 1)
            for cue in _TEMPERATURE_CUES:
                remainder = remainder.replace(cue, "", 1)
            remainder = remainder.replace("말고", "", 1)
            remainder_without_request = re.sub(
                r"(?:주세요|해줘|줘|주소|도|주문할게요|주문해)$", "", remainder,
            )
            quantity = _quantity(remainder_without_request, allow_garbled_two=True)
            if remainder_without_request == "":
                self._pending_add = PendingAdd(item.id, None, temperature, "quantity", fulfillment)
                self.last_source = "rule_pending_missing_quantity"
                return self._missing_quantity_error(item.id)

        result = self._fallback.parse(text, current_order_state)
        if isinstance(result, OrderCommandError):
            self.last_source = "qwen_fallback"
            if current_order_state.confirmed:
                return replace(result, message=_PAYMENT_RETRY_MESSAGE)
            return result
        if isinstance(result, list):
            result = self._canonicalize_category_tag_queries(result)
            if any(
                command.options is not None and command.options.caffeine is not None
                for command in result
            ):
                self.last_source = "guard_blocked_decaf"
                return OrderCommandError(
                    code=OrderCommandErrorCode.UNSUPPORTED_UTTERANCE,
                    message="디카페인 옵션은 현재 제공하지 않습니다.",
                )
            dangerous = next(
                (command.intent for command in result if command.intent in _DANGEROUS_EVIDENCE),
                None,
            )
            if dangerous is not None and not any(cue in compact for cue in _DANGEROUS_EVIDENCE[dangerous]):
                self.last_source = "guard_blocked"
                message = (
                    _PAYMENT_RETRY_MESSAGE
                    if current_order_state.confirmed
                    else "메뉴 주문이나 장바구니 변경 요청을 다시 말씀해 주세요."
                )
                return OrderCommandError(code=OrderCommandErrorCode.UNSUPPORTED_UTTERANCE, message=message)
            if any(
                command.intent is Intent.UPDATE_OPTION for command in result
            ) and not any(cue in compact for cue in _OPTION_CHANGE_CUES):
                self.last_source = "guard_blocked_option_update"
                return OrderCommandError(
                    code=OrderCommandErrorCode.UNSUPPORTED_UTTERANCE,
                    message="바꿀 메뉴와 변경 내용을 다시 말씀해 주세요.",
                )
            add_commands = [
                command for command in result
                if command.intent is Intent.ADD_ITEM and command.target_item_id
            ]
            if len(add_commands) == 1:
                cmd = add_commands[0]
                item = self._menu_by_id(cmd.target_item_id)
                if item is not None and self._requires_temperature(item):
                    user_temp = self._temperature_in_order(compact)
                    # A valid backend command can carry an approved spoken
                    # alias (for example "아아" or "뜨라") that this narrow
                    # rule layer intentionally does not enumerate.  Keep that
                    # backend temperature unless the user supplied an explicit
                    # full temperature cue we can verify and correct.
                    if user_temp is not None and cmd.temperature != user_temp:
                        result = [
                            replace(c, temperature=user_temp) if c is cmd else c
                            for c in result
                        ]
            # A fallback can identify an otherwise unhandled menu phrase, but
            # its omission of temperature must enter the same clarification
            # state as the deterministic menu path.  Restrict this to one
            # standalone ADD so a mixed or multi-item response cannot invent
            # a target for the next short temperature reply.
            if len(result) == 1:
                command = result[0]
                item = self._menu_by_id(command.target_item_id) if (
                    command.intent is Intent.ADD_ITEM and command.target_item_id is not None
                ) else None
                if (
                    item is not None
                    and self._requires_temperature(item)
                    and command.temperature is None
                ):
                    self._pending_add = PendingAdd(
                        target_item_id=command.target_item_id,
                        quantity=command.quantity,
                        temperature=None,
                        missing_field=("temperature" if command.quantity is not None else "quantity"),
                        fulfillment_type=command.fulfillment_type,
                        options=command.options,
                    )
                    self.last_source = "rule_pending_temperature"
                    return self._pending_error()
        self.last_source = "qwen_fallback"
        return result

    def _canonicalize_category_tag_queries(
        self,
        commands: list[OrderCommand],
    ) -> list[OrderCommand]:
        """Repair only Qwen's unambiguous category-as-single-tag query shape."""
        canonical: list[OrderCommand] = []
        for command in commands:
            tags = command.query_tags
            if (
                command.intent is Intent.QUERY_MENU
                and command.category_id is None
                and tags is not None
                and len(tags) == 1
                and tags[0] in self._category_ids
            ):
                canonical.append(replace(command, category_id=tags[0], query_tags=None))
            else:
                canonical.append(command)
        return canonical

    def _parse_menu_add(
        self,
        compact: str,
        fulfillment_type: FulfillmentType | None = None,
    ) -> OrderCommand | None:
        menu_matches = [(key, item) for key, item in self._menu_by_key.items() if key in compact]
        if len(menu_matches) != 1:
            return None
        menu_key, item = menu_matches[0]
        temperature = self._temperature_in_order(compact)
        if temperature is not None and temperature not in item.temperature_options:
            temperature = None
        remainder = self._strip_menu_particle(compact.replace(menu_key, "", 1))
        for cue in _TEMPERATURE_CUES:
            remainder = remainder.replace(cue, "", 1)
        remainder = remainder.replace("말고", "", 1)
        quantity_text = re.sub(r"(?:주세요|해줘|줘|주소|도|주문할게요|주문해|추가해|추가)$", "", remainder)
        quantity_text = re.sub(r"더$", "", quantity_text)
        quantity = _quantity(quantity_text, allow_garbled_two=True)
        if quantity is None:
            return None
        if self._requires_temperature(item) and temperature is None:
            self._pending_add = PendingAdd(item.id, quantity, None, "temperature", fulfillment_type)
            self.last_source = "rule_pending_temperature"
            return None
        return OrderCommand.create(Intent.ADD_ITEM, target_item_id=item.id, quantity=quantity, temperature=temperature)

    def _parse_quantity_delta_add(
        self,
        compact: str,
        current_order_state: Cart,
    ) -> OrderCommand | OrderCommandError | None:
        if not current_order_state.items:
            return None
        if any(cue in compact for cue in ("바꿔", "변경")):
            return None

        stripped = re.sub(r"(?:을|를)?(?:주세요|줘|주소|도|해줘|해주세요|요)$", "", compact)
        m = re.fullmatch(r"(.+?)(?:더추가|더|추가)", stripped)
        if not m:
            return None

        prefix = m.group(1)
        quantity = _quantity(prefix, allow_garbled_two=True)
        if quantity is None:
            return None

        if len(current_order_state.items) != 1:
            return OrderCommandError(
                code=OrderCommandErrorCode.AMBIGUOUS_TARGET,
                message="추가할 메뉴 이름을 함께 말씀해 주세요.",
                field="target_item_id",
            )

        target_item = current_order_state.items[0]
        return OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id=target_item.menu_id,
            quantity=quantity,
            temperature=target_item.temperature,
            options=target_item.options,
        )

    def _parse_menu_remove(self, compact: str) -> OrderCommand | None:
        """Turn an explicit menu cancellation into a targeted removal.

        Whole-cart cancellation stays in ``_is_cancel_order``.  Here a menu
        name is required, so a Qwen full-CANCEL misclassification cannot clear
        unrelated cart lines.
        """
        if not any(cue in compact for cue in _ITEM_REMOVE_CUES):
            return None
        if any(cue in compact for cue in ("담고", "추가하고", "주문하고", "그리고")):
            return None
        menu_matches = [
            (key, item) for key, item in self._menu_by_key.items() if key in compact
        ]
        if len(menu_matches) != 1:
            return None
        _, item = menu_matches[0]
        temperature = self._temperature_in_order(compact)
        if temperature is not None and temperature not in item.temperature_options:
            return None
        return OrderCommand.create(
            Intent.REMOVE_ITEM,
            target_item_id=item.id,
            temperature=temperature,
        )

    def _parse_quantity_update(
        self, compact: str, current_order_state: Cart
    ) -> OrderCommand | None:
        if not any(cue in compact for cue in ("바꿔", "변경")):
            return None
        menu_matches = [(key, item) for key, item in self._menu_by_key.items() if key in compact]
        if len(menu_matches) != 1:
            return None
        menu_key, item = menu_matches[0]
        temperature = self._temperature_in_order(compact)
        # "아이스 ... 따뜻하게 바꿔" names the current source temperature
        # and a different destination.  Let the partial-temperature handler
        # below move only the requested quantity instead of rewriting a line.
        if temperature is None and any(cue in compact for cue in _ICED_TEMPERATURE_CUES) and any(
            cue in compact for cue in _HOT_TEMPERATURE_CUES
        ):
            return None
        if temperature is not None and temperature not in item.temperature_options:
            temperature = None
        # "아이스 아메리카노 세 잔으로 바꿔" changes the count when the
        # existing line is already iced.  If the requested temperature differs,
        # leave it to the partial temperature-change parser below.
        if temperature is not None and current_order_state.items and not any(
            cart_item.menu_id == item.id and cart_item.temperature is temperature
            for cart_item in current_order_state.items
        ):
            return None
        remainder = compact.replace(menu_key, "", 1)
        for cue in (
            "아이스로", "아이스요", "아이스", "아이소로", "아이소요", "아이소",
            "아이시로", "아이시요", "아이시", "아이수로", "아이수요", "아이수",
            "차가운걸로", "차가운", "차갑게요", "차갑게",
            "따뜻하게요", "따뜻하게", "따뜻한걸로", "따뜻한",
            "뜨겁게요", "뜨겁게", "뜨거운걸로", "뜨거운", "걸로",
        ):
            remainder = remainder.replace(cue, "", 1)
        quantity_text = re.sub(r"(?:으로|로)?(?:바꿔|변경)(?:줘|주세요|주소|도)?$", "", remainder)
        quantity = _quantity(quantity_text, allow_garbled_two=True)
        if quantity is None:
            return None
        return OrderCommand.create(
            Intent.UPDATE_QUANTITY,
            target_item_id=item.id,
            quantity=quantity,
            temperature=temperature,
        )

    def _parse_partial_temperature_update(
        self, compact: str, current_order_state: Cart,
    ) -> OrderCommand | OrderCommandError | None:
        """Resolve only explicit, partial hot/iced changes from the current cart.

        A quantity on UPDATE_OPTION means the number of drinks to move to the
        requested temperature.  It deliberately does not infer a target when
        more than one menu is in the cart.
        """
        if not current_order_state.items or not any(cue in compact for cue in ("바꿔", "변경", "해줘")):
            return None
        temperature = self._requested_change_temperature(compact)
        quantity = self._quantity_in_change(compact)
        if temperature is None or quantity is None:
            return None

        explicit_menu_ids = {
            item.id for key, item in self._menu_by_key.items() if key in compact
        }
        if len(explicit_menu_ids) > 1:
            return self._ambiguous_temperature_change_error()
        if explicit_menu_ids:
            target_item_id = explicit_menu_ids.pop()
        else:
            cart_menu_ids = {item.menu_id for item in current_order_state.items}
            if len(cart_menu_ids) != 1:
                return self._ambiguous_temperature_change_error()
            target_item_id = next(iter(cart_menu_ids))

        menu_item = self._menu_by_id(target_item_id)
        if menu_item is None or temperature not in menu_item.temperature_options:
            return None
        if len(menu_item.temperature_options) != 2:
            return None
        return OrderCommand.create(
            Intent.UPDATE_OPTION,
            target_item_id=target_item_id,
            quantity=quantity,
            temperature=temperature,
        )

    @staticmethod
    def _quantity_in_change(compact: str) -> int | None:
        candidates = {
            quantity for token, quantity in _QUANTITIES.items()
            if len(token) > 1 and token in compact
        }
        candidates.update(
            _QUANTITIES[token]
            for token in ("한", "두", "세", "네", "다섯")
            if re.search(rf"{token}(?:잔|개|컵)", compact)
        )
        candidates.update(int(value) for value in re.findall(r"(?<![0-9])([1-9][0-9]*)(?:잔|개)?", compact))
        return next(iter(candidates)) if len(candidates) == 1 else None

    @staticmethod
    def _requested_change_temperature(compact: str) -> Temperature | None:
        cues = (
            (Temperature.ICED, ("아이스", "차가운", "차갑게", "시원하게", "시원한")),
            (Temperature.HOT, ("따뜻하게", "따뜻한", "뜨겁게", "뜨거운")),
        )
        matches = [
            (compact.rfind(cue), temperature)
            for temperature, temperature_cues in cues
            for cue in temperature_cues
            if cue in compact
        ]
        return max(matches, default=(-1, None))[1]

    @staticmethod
    def _ambiguous_temperature_change_error() -> OrderCommandError:
        return OrderCommandError(
            code=OrderCommandErrorCode.AMBIGUOUS_TARGET,
            message="어떤 메뉴의 온도를 바꿀지 메뉴 이름을 함께 말씀해 주세요.",
            field="target_item_id",
        )

    @staticmethod
    def _payment_method(compact: str) -> str | None:
        for phrase, method in _PAYMENT_METHODS:
            if phrase in compact:
                return method
        return None

    @staticmethod
    def _fulfillment(compact: str) -> FulfillmentType | None:
        if compact in _DINE_IN_DIRECT or any(pattern.fullmatch(compact) for pattern in _DINE_IN_PATTERNS):
            return FulfillmentType.DINE_IN
        if any(pattern.fullmatch(compact) for pattern in _TAKEOUT_PATTERNS):
            return FulfillmentType.TAKEOUT
        return None

    @staticmethod
    def _embedded_fulfillment(compact: str) -> tuple[FulfillmentType | None, str]:
        # Fulfillment is a phrase inside an order utterance.  Only remove a
        # phrase the same semantic matcher recognizes when it stands alone.
        matches: list[tuple[int, FulfillmentType, re.Match[str]]] = []
        for fulfillment, patterns in (
            (FulfillmentType.TAKEOUT, _TAKEOUT_PATTERNS),
            (FulfillmentType.DINE_IN, _DINE_IN_PATTERNS),
        ):
            for pattern in patterns:
                match = pattern.search(compact)
                if match is not None:
                    matches.append((len(match.group()), fulfillment, match))
        if matches:
            _, fulfillment, match = max(matches, key=lambda candidate: candidate[0])
            return fulfillment, compact[:match.start()] + compact[match.end():]
        for phrase in sorted(_DINE_IN_DIRECT, key=len, reverse=True):
            if phrase in compact and compact != phrase:
                return FulfillmentType.DINE_IN, compact.replace(phrase, "", 1)
        return None, compact

    @staticmethod
    def _temperature(compact: str) -> Temperature | None:
        return _temperature_from_compact(compact)

    @staticmethod
    def _temperature_in_order(compact: str) -> Temperature | None:
        return _temperature_from_compact(compact)

    @classmethod
    def _pending_temperature(cls, compact: str) -> Temperature | None:
        normalized = re.sub(r"(?:걸|거)$", "", _strip_reply_suffix(compact))
        if normalized in {"아이스", "아이소", "아이시", "아이수", "에이스", "차갑게", "차가운", "차가운걸", "차가운거", "시원하게", "시원한", "시원한걸", "시원한거", "따뜻", "따뜻하게", "따뜻한", "따뜻한걸", "따뜻한거", "뜨겁게", "뜨거운", "뜨거운걸", "뜨거운거"}:
            return cls._temperature_in_order(normalized)
        return None

    @classmethod
    def _is_temperature_reply(cls, compact: str) -> bool:
        return cls._pending_temperature(compact) is not None

    @staticmethod
    def _is_reset_order(compact: str) -> bool:
        return compact in {"처음부터", "다시처음부터", "다시할래"} or (
            "처음부터" in compact
            and any(cue in compact for cue in ("다시", "시작", "할게", "할래"))
        )

    @staticmethod
    def _is_undo_order(compact: str) -> bool:
        return compact in {"방금거취소", "방금거취소해줘", "되돌려", "되돌려줘", "원래대로"}

    @staticmethod
    def _is_cancel_order(compact: str) -> bool:
        return compact in {
            "전체취소", "전체취소해줘", "전체취소해주세요", "전체취소할게요",
            "전부취소", "전부취소해줘", "전부취소해주세요", "전부취소할게요",
            "장바구니비워줘", "장바구니비워", "장바구니비도", "장바구니비워주세요", "장바구니비소",
            "장바구니취소", "장바구니취소해줘", "장바구니취소해주세요",
        } or (
            "장바구니" in compact and any(cue in compact for cue in (
                "비워", "비도", "비우", "비소", "취소", "비어",
                "다빼", "다삭제", "전부빼",
            ))
        ) or (
            "취소" in compact and any(scope in compact for scope in ("전체", "전부", "모두"))
        ) or (
            any(cue in compact for cue in ("다취소", "전부빼", "다비워", "싹비워"))
        ) or (
            any(scope in compact for scope in ("장바구니", "담은거", "주문한거"))
            and any(all_cue in compact for all_cue in ("다", "전부", "전체", "모두", "싹"))
            and any(action in compact for action in ("빼", "비워", "비우", "취소", "삭제"))
        )

    @staticmethod
    def _is_confirm_order(compact: str) -> bool:
        core = _strip_polite_ending(compact)
        if core in {"주문확인", "주문확정", "주문진행", "이대로주문"}:
            return True
        if RuleFirstNLU._is_payment_progress_confirm(compact):
            return True
        return core == "이대로" and compact != core

    @staticmethod
    def _is_payment_progress_confirm(compact: str) -> bool:
        """Recognize a complete payment-progress commitment, never a bare noun."""
        core = _strip_polite_ending(compact)
        return core in {"결제", "결제진행"} and compact != core

    @staticmethod
    def _is_cart_query(compact: str) -> bool:
        return compact in {"뭐담았어", "뭐들어있어"} or (
            any(scope in compact for scope in _CART_QUERY_SCOPES)
            and any(cue in compact for cue in _CART_QUERY_CUES)
        )

    @staticmethod
    def _is_repeat_request(compact: str) -> bool:
        return any(cue in compact for cue in ("다시말", "다시들려", "다시들어", "한번더"))

    @staticmethod
    def _is_slower_request(compact: str) -> bool:
        return "천천히" in compact or "느리게" in compact

    @staticmethod
    def _is_no_change_reply(compact: str) -> bool:
        return compact in {
            "변경할거없어", "변경할거없어요", "변경할게없어", "변경할게없어요",
            "없어", "없어요", "괜찮아", "괜찮아요",
        }

    @staticmethod
    def _missing_temperature_error() -> OrderCommandError:
        return OrderCommandError(
            code=OrderCommandErrorCode.MISSING_FIELD,
            message="따뜻하게 드릴까요, 아이스로 드릴까요?",
            field="temperature",
        )

    def _missing_quantity_error(self, target_item_id: str) -> OrderCommandError:
        item = self._menu_by_id(target_item_id)
        name = item.name if item is not None else "메뉴"
        return OrderCommandError(
            code=OrderCommandErrorCode.MISSING_FIELD,
            message=f"{name}의 수량을 말씀해 주세요.",
            field="quantity",
        )

    def _pending_error(self) -> OrderCommandError:
        assert self._pending_add is not None
        if self._pending_add.missing_field == "quantity":
            return self._missing_quantity_error(self._pending_add.target_item_id)
        return self._missing_temperature_error()

    def _menu_by_id(self, target_item_id: str):
        return next(
            (item for item in self._menu_by_key.values() if item.id == target_item_id),
            None,
        )

    @staticmethod
    def _strip_menu_particle(remainder: str) -> str:
        """Accept only a direct post-menu Korean particle before the order slots."""
        slot_start = r"(?:한|하나|두|둘|세|셋|네|다섯|[1-9]|아이스|아이소|아이시|아이수|차가운|차갑게|시원|따뜻|뜨겁)"
        return re.sub(rf"^(?:도|는|은|을|를)(?={slot_start})", "", remainder, count=1)

    @staticmethod
    def _requires_temperature(item) -> bool:
        return len(item.temperature_options) > 1
