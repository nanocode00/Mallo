from __future__ import annotations

from collections.abc import Callable
import re

from adapters.nlu.menu_alias_resolver import (
    AmbiguousMenuAliasError,
    resolve_menu_aliases,
)
from adapters.nlu.menu_detail_resolver import resolve_menu_detail_query
from adapters.nlu.menu_tag_resolver import resolve_menu_query_tags
from config.settings import (
    load_menu,
    load_menu_alias_definitions,
    load_menu_tag_definitions,
)
from domain.intents import Intent
from domain.models import (
    BeverageOptions,
    BeverageSize,
    Cart,
    CartItem,
    IceAmount,
    OrderCommand,
    OrderCommandError,
    OrderCommandErrorCode,
    Temperature,
    FulfillmentType,
)
from interfaces.nlu import NLUResult


class MockNLU:
    _MENU_QUERY_MARKERS = ("있", "알려", "보여", "추천", "뭐", "어떤")
    _MENU_DETAIL_QUERY_MARKERS = (
        "뭐",
        "설명",
        "알려",
        "어떤",
        "돼",
        "되나요",
        "가능",
        "가격",
        "얼마",
        "카페인",
        "단맛",
        "당도",
        "달아",
        "우유",
    )
    _NON_ADD_MARKERS = ("삭제", "빼", "바꿔", "변경", "얼마", "어떤", "알려", "보여")
    _TEA_CATEGORY_QUERY = re.compile(r"차\s*(?:는|종류|메뉴).*(?:있|알려|보여|추천|뭐|어떤)")

    def parse(self, text: str, current_order_state: Cart) -> NLUResult:
        if any(value in text for value in ("포장", "테이크아웃", "가져갈")):
            return [OrderCommand.create(Intent.SET_FULFILLMENT, fulfillment_type=FulfillmentType.TAKEOUT)]
        if any(value in text for value in ("매장에서", "매장 이용", "먹고 갈")):
            return [OrderCommand.create(Intent.SET_FULFILLMENT, fulfillment_type=FulfillmentType.DINE_IN)]
        # E-08 데모 시나리오(Happy Path) 전용 발화 — 리허설 결정성 보장.
        # Order Engine은 턴당 단일 Intent만 허용하므로 "하나는 아이스로" 식의
        # 분리(REMOVE+ADD)는 불가능. Turn 4는 전체 아이스 변경으로 정렬함(E-08 참고).
        if text == "아메리카노 따뜻한 거 두 잔이랑 바스크 치즈 케이크 하나 주세요":
            return [
                self._add("americano", 2, Temperature.HOT),
                self._add("basque_cheesecake", 1, None),
            ]
        if text == "아메리카노를 아이스로 바꿔줘":
            return [
                OrderCommand.create(
                    Intent.UPDATE_OPTION,
                    target_item_id="americano",
                    temperature=Temperature.ICED,
                )
            ]
        try:
            alias_matches = resolve_menu_aliases(text, load_menu_alias_definitions())
        except AmbiguousMenuAliasError as error:
            return OrderCommandError(
                code=OrderCommandErrorCode.AMBIGUOUS_TARGET,
                message="어떤 메뉴를 말씀하시는지 메뉴 이름을 다시 말씀해 주세요.",
                field="target_item_id",
                candidates=error.candidates,
            )
        requested_size = self._size_from_text(text)
        official_matches = tuple(item for item in load_menu() if item.name in text)

        if text == "아이스 아메리카노 두 잔 주세요":
            return [self._add("americano", 2, Temperature.ICED)]
        if text == "따뜻한 카페라떼 한 잔 주세요":
            return [self._add("cafe_latte", 1, Temperature.HOT)]
        if text == "바스크 치즈 케이크 한 개 주세요":
            return [self._add("basque_cheesecake", 1, None)]
        if text == "아샷추 한 잔 주세요":
            return [
                self._add(
                    "iced_tea",
                    1,
                    Temperature.ICED,
                    BeverageOptions(extra_shots=1),
                )
            ]
        if text == "아바샷 한 잔 주세요":
            return [
                self._add(
                    "vanilla_latte",
                    1,
                    Temperature.ICED,
                    BeverageOptions(extra_shots=1),
                )
            ]
        if text in ("아이스 아메리카노 두 잔이랑 따뜻한 카페라떼 한 잔 주세요", "아이스 아메리카노 두 잔, 따뜻한 카페라떼 한 잔 주세요"):
            return [
                self._add("americano", 2, Temperature.ICED),
                self._add("cafe_latte", 1, Temperature.HOT),
            ]
        if text == "아이스 아메리카노 한 잔이랑 아이스 아메리카노 두 잔 주세요":
            return [self._add("americano", 3, Temperature.ICED)]
        if text == "아이스 아메리카노 한 잔이랑 따뜻한 아메리카노 한 잔 주세요":
            return [
                self._add("americano", 1, Temperature.ICED),
                self._add("americano", 1, Temperature.HOT),
            ]
        if text in {
            "아이스 카페라떼 빼고 아이스 아메리카노 한 잔 넣어 줘",
            "아이스 카페라떼를 취소해 주고 아이스 아메리카노를 넣어 줘",
        }:
            return [
                OrderCommand.create(
                    Intent.REMOVE_ITEM,
                    target_item_id="cafe_latte",
                    temperature=Temperature.ICED,
                ),
                self._add("americano", 1, Temperature.ICED),
            ]
        if text == "밀크티 두 잔으로 바꾸고 현재 주문도 알려 줘":
            milk_tea_items = [
                item for item in current_order_state.items if item.menu_id == "milk_tea"
            ]
            if len(milk_tea_items) != 1:
                return OrderCommandError(
                    code=OrderCommandErrorCode.AMBIGUOUS_TARGET,
                    message="변경할 밀크티를 확인하지 못했습니다.",
                    field="target_item_id",
                )
            return [
                OrderCommand.create(
                    Intent.UPDATE_QUANTITY,
                    target_item_id="milk_tea",
                    quantity=2,
                    temperature=milk_tea_items[0].temperature,
                ),
                OrderCommand.create(Intent.QUERY_CART),
            ]
        if text == "아이스 아메리카노 한 잔 더 주세요":
            current_quantity = sum(
                item.quantity
                for item in current_order_state.items
                if item.menu_id == "americano"
                and item.temperature is Temperature.ICED
            )
            return [
                OrderCommand.create(
                    Intent.UPDATE_QUANTITY,
                    target_item_id="americano",
                    quantity=current_quantity + 1,
                    temperature=Temperature.ICED,
                )
            ]
        if text == "아이스 아메리카노 삭제해 주세요":
            return [
                OrderCommand.create(
                    Intent.REMOVE_ITEM,
                    target_item_id="americano",
                    temperature=Temperature.ICED,
                )
            ]
        if text == "아이스 아메리카노 세 잔으로 바꿔 주세요":
            return [
                OrderCommand.create(
                    Intent.UPDATE_QUANTITY,
                    target_item_id="americano",
                    quantity=3,
                    temperature=Temperature.ICED,
                )
            ]
        if text == "아메리카노를 따뜻하게 바꿔 주세요":
            return [
                OrderCommand.create(
                    Intent.UPDATE_OPTION,
                    target_item_id="americano",
                    temperature=Temperature.HOT,
                )
            ]
        if text in {"카페라떼에 샷을 더 넣어줘", "라떼에 샷을 더 넣어줘"}:
            return self._update_cart_option(
                current_order_state,
                {"cafe_latte", "vanilla_latte", "matcha_latte"},
                self._add_one_shot,
            )
        if text == "시럽 넣어줘":
            return self._update_cart_option(
                current_order_state,
                None,
                self._add_one_syrup,
            )
        if text == "얼음 조금 넣어줘":
            return self._update_cart_option(
                current_order_state,
                None,
                lambda _: BeverageOptions(ice_amount=IceAmount.LESS),
            )
        if requested_size is not None:
            quantity = self._quantity_from_text(text)
            if quantity is not None and not any(
                marker in text for marker in self._NON_ADD_MARKERS
            ):
                if len(alias_matches) == 1:
                    match = alias_matches[0]
                    return [
                        self._add(
                            match.target_item_id,
                            quantity,
                            match.temperature,
                            BeverageOptions(size=requested_size),
                        )
                    ]
                if len(official_matches) == 1:
                    return [
                        self._add(
                            official_matches[0].id,
                            quantity,
                            self._temperature_from_text(text),
                            BeverageOptions(size=requested_size),
                        )
                    ]
            candidate_ids = {
                *(match.target_item_id for match in alias_matches),
                *(item.id for item in official_matches),
            } or None
            return self._update_cart_option(
                current_order_state,
                candidate_ids,
                lambda _: BeverageOptions(size=requested_size),
            )
        if text in ("전체 메뉴 알려 주세요", "전체 메뉴 보여줘", "메뉴 뭐 있어?", "메뉴 알려줘"):
            return [OrderCommand.create(Intent.QUERY_MENU)]
        if text == "커피 메뉴 알려 주세요":
            return [OrderCommand.create(Intent.QUERY_MENU, category_id="coffee")]
        if text == "현재 주문 알려 주세요":
            return [OrderCommand.create(Intent.QUERY_CART)]
        if text == "주문 확정할게요":
            return [OrderCommand.create(Intent.CONFIRM_ORDER)]
        if text == "전체 주문 취소해 주세요":
            return [OrderCommand.create(Intent.CANCEL)]
        if text in {
            "방금 거 취소해 주세요",
            "방금 한 거 되돌려 주세요",
            "마지막 변경 취소해 주세요",
        }:
            return [OrderCommand.create(Intent.UNDO)]
        if text == "다시 말해 주세요":
            return [OrderCommand.create(Intent.REQUEST_REPEAT)]
        if text == "천천히 말해 주세요":
            return [OrderCommand.create(Intent.REQUEST_SLOWER)]
        if text == "기본 속도로 말해 주세요":
            return [OrderCommand.create(Intent.REQUEST_DEFAULT_SPEED)]
        if "천천히" in text or "느리" in text:
            return [OrderCommand.create(Intent.REQUEST_SLOWER)]
        if "결제" in text or "주문 확정" in text:
            return [OrderCommand.create(Intent.CONFIRM_ORDER)]

        detail_query = resolve_menu_detail_query(text, load_menu())
        if detail_query is not None and any(
            marker in text for marker in self._MENU_DETAIL_QUERY_MARKERS
        ):
            target_item_id, detail_fields = detail_query
            return [
                OrderCommand.create(
                    Intent.QUERY_MENU,
                    target_item_id=target_item_id,
                    detail_fields=detail_fields,
                )
            ]

        quantity = self._quantity_from_text(text)
        is_add_request = quantity is not None and not any(
            marker in text for marker in self._NON_ADD_MARKERS
        )
        if is_add_request and len(alias_matches) == 1:
            match = alias_matches[0]
            options = (
                BeverageOptions(size=requested_size)
                if requested_size is not None
                else None
            )
            return [self._add(match.target_item_id, quantity, match.temperature, options)]
        if is_add_request and len(official_matches) == 1:
            options = (
                BeverageOptions(size=requested_size)
                if requested_size is not None
                else None
            )
            return [
                self._add(
                    official_matches[0].id,
                    quantity,
                    self._temperature_from_text(text),
                    options,
                )
            ]

        if self._TEA_CATEGORY_QUERY.search(text):
            return [OrderCommand.create(Intent.QUERY_MENU, category_id="tea")]

        query_tags = resolve_menu_query_tags(text, load_menu_tag_definitions())
        if query_tags and any(marker in text for marker in self._MENU_QUERY_MARKERS):
            return [OrderCommand.create(Intent.QUERY_MENU, query_tags=query_tags)]

        return OrderCommandError(
            code=OrderCommandErrorCode.UNSUPPORTED_UTTERANCE,
            message="지원하지 않는 주문입니다.",
        )

    @staticmethod
    def _quantity_from_text(text: str) -> int | None:
        numeric = re.search(r"([1-9][0-9]*)\s*(?:잔|개)", text)
        if numeric:
            return int(numeric.group(1))
        number_words = (
            ("한", 1),
            ("하나", 1),
            ("두", 2),
            ("둘", 2),
            ("세", 3),
            ("셋", 3),
        )
        for token, quantity in number_words:
            if re.search(rf"{token}\s*(?:잔|개)", text):
                return quantity
        bare_number_words = (("하나", 1), ("둘", 2), ("셋", 3))
        for token, quantity in bare_number_words:
            if re.search(rf"(?:^|\s){token}(?=$|[\s?!,.])", text):
                return quantity
        return None

    @staticmethod
    def _size_from_text(text: str) -> BeverageSize | None:
        normalized = text.lower()
        patterns = (
            (BeverageSize.SMALL, ("스몰", "small", "작은 사이즈", "작게")),
            (BeverageSize.MEDIUM, ("미디엄", "medium", "중간 사이즈")),
            (BeverageSize.LARGE, ("라지", "large", "큰 사이즈", "크게")),
        )
        for size, aliases in patterns:
            if any(alias in normalized for alias in aliases):
                return size
        return None

    @staticmethod
    def _temperature_from_text(text: str) -> Temperature | None:
        if any(token in text for token in ("아이스", "차가운", "시원한")):
            return Temperature.ICED
        if any(token in text for token in ("따뜻", "뜨거", "핫")):
            return Temperature.HOT
        return None

    @staticmethod
    def _add(
        target_item_id: str,
        quantity: int,
        temperature: Temperature | None,
        options: BeverageOptions | None = None,
    ) -> OrderCommand:
        return OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id=target_item_id,
            quantity=quantity,
            temperature=temperature,
            options=options,
        )

    @staticmethod
    def _add_one_shot(item: CartItem) -> BeverageOptions:
        current = item.options.extra_shots or 0
        if current >= 3:
            raise ValueError("샷은 최대 3회까지 추가할 수 있습니다.")
        return BeverageOptions(extra_shots=current + 1)

    @staticmethod
    def _add_one_syrup(item: CartItem) -> BeverageOptions:
        current = item.options.syrup_pumps or 0
        if current >= 3:
            raise ValueError("시럽은 최대 3회까지 추가할 수 있습니다.")
        return BeverageOptions(syrup_pumps=current + 1)

    @staticmethod
    def _update_cart_option(
        cart: Cart,
        candidate_ids: set[str] | None,
        build_options: Callable[[CartItem], BeverageOptions],
    ) -> NLUResult:
        candidates = [
            item
            for item in cart.items
            if candidate_ids is None or item.menu_id in candidate_ids
        ]
        if not candidates:
            return OrderCommandError(
                code=OrderCommandErrorCode.MISSING_FIELD,
                message="옵션을 변경할 메뉴를 먼저 장바구니에 담아 주세요.",
                field="target_item_id",
            )
        if len(candidates) > 1:
            return OrderCommandError(
                code=OrderCommandErrorCode.AMBIGUOUS_TARGET,
                message="어떤 메뉴의 옵션을 변경할지 메뉴 이름을 말씀해 주세요.",
                field="target_item_id",
                candidates=tuple(dict.fromkeys(item.menu_id for item in candidates)),
            )
        try:
            options = build_options(candidates[0])
        except ValueError as error:
            return OrderCommandError(
                code=OrderCommandErrorCode.UNSUPPORTED_UTTERANCE,
                message=str(error),
            )
        return [
            OrderCommand.create(
                Intent.UPDATE_OPTION,
                target_item_id=candidates[0].menu_id,
                options=options,
            )
        ]
