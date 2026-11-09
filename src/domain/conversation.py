from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from domain.errors import (
    MIXED_INTENT_EXECUTION_FAILURE_MESSAGE,
    MIXED_INTENT_USER_MESSAGE,
)
from domain.intents import Intent
from domain.korean_normalizer import normalize_korean_text_for_tts
from domain.mixed_intent import (
    ONE_SHOT_ORDER_INTENTS,
    SEQUENTIAL_CART_MUTATION_INTENTS,
    is_supported_sequential_batch,
)
from domain.models import (
    BeverageSize,
    BeverageOptions,
    CaffeineOption,
    Cart,
    CartItem,
    ErrorCode,
    ErrorModule,
    FulfillmentType,
    IceAmount,
    MenuItem,
    MenuDetailField,
    OrderCommand,
    OrderResult,
    Temperature,
    create_error_response,
)

MAX_ITEM_QUANTITY = 5


class ConversationAgent:
    """결정론적 주문 관리 엔진 (Order Engine)."""

    _CART_MUTATION_INTENTS = frozenset(
        {
            Intent.ADD_ITEM,
            Intent.REMOVE_ITEM,
            Intent.UPDATE_QUANTITY,
            Intent.UPDATE_OPTION,
            Intent.CANCEL,
            Intent.SET_FULFILLMENT,
        }
    )

    _CATEGORY_NAMES = {
        "coffee": "커피",
        "non_coffee": "논커피",
        "tea": "티",
        "dessert": "디저트",
    }

    def __init__(self, menu: Iterable[MenuItem]) -> None:
        self._menu = {item.id: item for item in menu}
        self._undo_before: Cart | None = None
        self._undo_after: Cart | None = None

    def reset_session(self) -> None:
        self._undo_before = None
        self._undo_after = None

    def execute(self, commands: list[OrderCommand], cart: Cart) -> OrderResult:
        if not isinstance(commands, list) or not commands:
            return self._failure(cart, ErrorCode.INVALID_COMMAND, "주문을 처리할 수 없습니다.")

        if any(not isinstance(cmd, OrderCommand) for cmd in commands):
            return self._failure(cart, ErrorCode.INVALID_COMMAND, "주문을 처리할 수 없습니다.")

        intents = {cmd.intent for cmd in commands}
        if len(intents) > 1:
            if not is_supported_sequential_batch(commands):
                return self._failure(
                    cart, ErrorCode.MIXED_INTENT, MIXED_INTENT_USER_MESSAGE
                )
            return self._execute_sequential_batch(commands, cart)

        intent = commands[0].intent

        if intent is not Intent.QUERY_MENU and any(
            command.query_tags is not None or command.detail_fields is not None
            for command in commands
        ):
            return self._failure(
                cart,
                ErrorCode.INVALID_COMMAND,
                "메뉴 검색 조건은 메뉴 조회에서만 사용할 수 있습니다.",
            )

        if intent not in {Intent.ADD_ITEM, Intent.UPDATE_OPTION} and any(
            command.options is not None for command in commands
        ):
            return self._failure(
                cart,
                ErrorCode.INVALID_COMMAND,
                "음료 옵션은 메뉴 추가 또는 옵션 변경에서만 사용할 수 있습니다.",
            )

        if intent is Intent.UNDO:
            return self._execute_undo(commands, cart)
        if intent is Intent.ADD_ITEM:
            result = self._execute_add_item(commands, cart)
        elif intent is Intent.REMOVE_ITEM:
            result = self._execute_remove_item(commands, cart)
        elif intent is Intent.UPDATE_QUANTITY:
            result = self._execute_update_quantity(commands, cart)
        elif intent is Intent.UPDATE_OPTION:
            result = self._execute_update_option(commands, cart)
        elif intent is Intent.QUERY_MENU:
            result = self._execute_query_menu(commands, cart)
        elif intent is Intent.QUERY_CART:
            result = self._execute_query_cart(cart)
        elif intent is Intent.CONFIRM_ORDER:
            result = self._execute_confirm_order(cart)
        elif intent is Intent.SELECT_PAYMENT_METHOD:
            result = self._execute_select_payment_method(commands, cart)
        elif intent is Intent.SET_FULFILLMENT:
            result = self._execute_set_fulfillment(commands, cart)
        elif intent is Intent.CANCEL:
            result = self._execute_cancel()
        elif intent is Intent.RESET_ORDER:
            result = self._execute_reset_order()
        else:
            result = self._failure(
                cart, ErrorCode.UNSUPPORTED_UTTERANCE, "지원되지 않는 요청입니다."
            )

        if (
            result.success
            and intent in self._CART_MUTATION_INTENTS
            and result.cart != cart
        ):
            self._undo_before = cart.copy()
            self._undo_after = result.cart.copy()
        if result.success and intent in self._CART_MUTATION_INTENTS:
            result.cart.confirmed = False
        return result

    def _execute_sequential_batch(
        self,
        commands: list[OrderCommand],
        cart: Cart,
    ) -> OrderResult:
        """허용된 혼합 Intent를 발화 순서대로 원자적으로 실행한다."""
        previous_undo_before = self._undo_before
        previous_undo_after = self._undo_after

        for command in commands:
            if command.intent not in SEQUENTIAL_CART_MUTATION_INTENTS or command.intent in {
                Intent.SET_FULFILLMENT,
                Intent.CONFIRM_ORDER,
            }:
                continue
            if not self._is_identifiable_mixed_target(command, cart):
                return self._failure(
                    cart,
                    ErrorCode.AMBIGUOUS_TARGET,
                    MIXED_INTENT_EXECUTION_FAILURE_MESSAGE,
                )

        working_cart = cart.copy()
        responses: list[str] = []
        for command in commands:
            result = self.execute([command], working_cart)
            if not result.success:
                self._undo_before = previous_undo_before
                self._undo_after = previous_undo_after
                return self._failure(
                    cart,
                    result.error_code or ErrorCode.INVALID_COMMAND,
                    MIXED_INTENT_EXECUTION_FAILURE_MESSAGE,
                )
            working_cart = result.cart
            responses.append(result.response_text)

        if working_cart != cart:
            self._undo_before = cart.copy()
            self._undo_after = working_cart.copy()
        else:
            self._undo_before = previous_undo_before
            self._undo_after = previous_undo_after

        combined_response = " ".join(responses)
        is_one_shot_order = (
            tuple(command.intent for command in commands) == ONE_SHOT_ORDER_INTENTS
        )
        return OrderResult(
            success=True,
            cart=working_cart,
            response_text=(
                responses[-1]
                if is_one_shot_order
                else combined_response
            ),
            debug_response_text=combined_response if is_one_shot_order else None,
        )

    def _is_identifiable_mixed_target(
        self,
        command: OrderCommand,
        initial_cart: Cart,
    ) -> bool:
        if command.target_item_id is None:
            return False

        menu_item = self._menu.get(command.target_item_id)
        if menu_item is None:
            return False
        if command.intent is Intent.ADD_ITEM:
            return True

        candidates = [
            item
            for item in initial_cart.items
            if item.menu_id == command.target_item_id
        ]
        if not candidates:
            return False
        if command.intent is not Intent.UPDATE_OPTION and command.temperature is not None:
            candidates = [
                item for item in candidates if item.temperature is command.temperature
            ]
        return len(candidates) == 1

    def _execute_undo(
        self,
        commands: list[OrderCommand],
        cart: Cart,
    ) -> OrderResult:
        command = commands[0]
        if len(commands) != 1 or any(
            value is not None
            for value in (
                command.target_item_id,
                command.category_id,
                command.quantity,
                command.temperature,
                command.query_tags,
                command.detail_fields,
                command.options,
            )
        ):
            return self._failure(
                cart,
                ErrorCode.INVALID_COMMAND,
                "실행취소 요청 형식을 다시 확인해 주세요.",
            )

        if self._undo_before is None or self._undo_after is None:
            return self._failure(
                cart,
                ErrorCode.INVALID_COMMAND,
                "실행 취소할 장바구니 변경이 없습니다.",
            )
        if cart != self._undo_after:
            self.reset_session()
            return self._failure(
                cart,
                ErrorCode.INVALID_COMMAND,
                "현재 장바구니가 변경되어 이전 작업을 취소할 수 없습니다.",
            )

        restored_cart = self._undo_before.copy()
        self.reset_session()
        summary = self._execute_query_cart(restored_cart).response_text
        return OrderResult(
            success=True,
            cart=restored_cart,
            response_text=f"방금 변경을 취소했습니다. {summary}",
        )

    def _execute_query_menu(
        self, commands: list[OrderCommand], cart: Cart
    ) -> OrderResult:
        if len(commands) != 1:
            return self._failure(
                cart, ErrorCode.INVALID_COMMAND, "한 번에 하나의 메뉴 조회만 요청해 주세요."
            )

        command = commands[0]
        if command.quantity is not None or command.temperature is not None:
            return self._failure(
                cart, ErrorCode.INVALID_COMMAND, "메뉴 조회 조건을 다시 확인해 주세요."
            )
        if command.target_item_id is not None and (
            command.category_id is not None or command.query_tags is not None
        ):
            return self._failure(
                cart,
                ErrorCode.INVALID_COMMAND,
                "특정 메뉴 조회와 조건 검색은 나누어서 말씀해 주세요.",
            )
        if command.detail_fields is not None and command.target_item_id is None:
            return self._failure(
                cart,
                ErrorCode.INVALID_COMMAND,
                "상세 정보를 확인할 메뉴 이름을 말씀해 주세요.",
            )

        if command.target_item_id is not None:
            menu_item = self._menu.get(command.target_item_id)
            if menu_item is None:
                return self._failure(
                    cart, ErrorCode.MENU_NOT_FOUND, "메뉴를 찾을 수 없습니다."
                )
            return OrderResult(
                success=True,
                cart=cart.copy(),
                response_text=self._menu_detail(menu_item, command.detail_fields),
            )

        menu_items = list(self._menu.values())
        if command.category_id is not None:
            menu_items = [
                item for item in menu_items if item.category_id == command.category_id
            ]
            if not menu_items:
                return self._failure(
                    cart, ErrorCode.MENU_NOT_FOUND, "카테고리를 찾을 수 없습니다."
                )
            category_name = self._CATEGORY_NAMES.get(
                command.category_id, command.category_id
            )
            prefix = f"{category_name} 메뉴는"
        elif command.query_tags is None:
            # 전체 메뉴도 화면과 음성이 공유하는 category 기반 canonical
            # 문장으로 구성한다. 별도 "전체 메뉴는" 머리말은 만들지 않는다.
            category_sentences: list[str] = []
            for category_id, category_name in self._CATEGORY_NAMES.items():
                category_items = [
                    item for item in menu_items if item.category_id == category_id
                ]
                if not category_items:
                    continue
                category_summary = ", ".join(
                    f"{item.name} {item.base_price:,}원" for item in category_items
                )
                category_sentences.append(
                    f"{category_name} 메뉴는 {category_summary}입니다."
                )
            return OrderResult(
                success=True,
                cart=cart.copy(),
                response_text=" ".join(category_sentences),
            )
        else:
            prefix = "조건에 맞는 메뉴는"

        if command.query_tags is not None:
            requested_tags = set(command.query_tags)
            known_tags = {tag for item in self._menu.values() for tag in item.tags}
            if not requested_tags.issubset(known_tags):
                return self._failure(
                    cart,
                    ErrorCode.INVALID_OPTION,
                    "지원하지 않는 메뉴 검색 조건입니다.",
                )
            menu_items = [
                item for item in menu_items if requested_tags.issubset(item.tags)
            ]
            if not menu_items:
                return self._failure(
                    cart,
                    ErrorCode.MENU_NOT_FOUND,
                    "조건에 맞는 메뉴를 찾을 수 없습니다.",
                )
            prefix = (
                f"조건에 맞는 {category_name} 메뉴는"
                if command.category_id is not None
                else "조건에 맞는 메뉴는"
            )

        menu_summary = ", ".join(
            f"{item.name} {item.base_price:,}원" for item in menu_items
        )
        return OrderResult(
            success=True,
            cart=cart.copy(),
            response_text=f"{prefix} {menu_summary}입니다.",
        )

    @classmethod
    def _menu_detail(
        cls,
        menu_item: MenuItem,
        detail_fields: tuple[MenuDetailField, ...] | None,
    ) -> str:
        if detail_fields is not None:
            return " ".join(
                cls._menu_detail_field(menu_item, field) for field in detail_fields
            )

        options = set(menu_item.temperature_options)
        if options == {Temperature.HOT, Temperature.ICED}:
            temperature_text = " 따뜻하게 또는 아이스로 주문할 수 있습니다."
        elif options == {Temperature.ICED}:
            temperature_text = " 아이스로 주문할 수 있습니다."
        elif options == {Temperature.HOT}:
            temperature_text = " 따뜻하게 주문할 수 있습니다."
        else:
            temperature_text = ""
        return (
            f"{menu_item.name}는 {menu_item.base_price:,}원입니다."
            f"{temperature_text}"
        )

    @staticmethod
    def _menu_detail_field(
        menu_item: MenuItem,
        field: MenuDetailField,
    ) -> str:
        if field is MenuDetailField.DESCRIPTION:
            return f"{menu_item.name}는 {menu_item.description}입니다."
        if field is MenuDetailField.PRICE:
            return f"{menu_item.name} 가격은 {menu_item.base_price:,}원입니다."
        if field is MenuDetailField.SWEETNESS:
            sweetness = next(
                (tag for tag in menu_item.tags if tag.startswith("sweetness_")),
                None,
            )
            label = {
                "sweetness_low": "당도가 낮은 편입니다.",
                "sweetness_medium": "당도는 보통입니다.",
                "sweetness_high": "당도가 높은 편입니다.",
            }.get(sweetness, "단맛 정보가 없습니다.")
            return f"{menu_item.name}는 {label}"
        if field is MenuDetailField.CAFFEINE:
            label = (
                "카페인이 없습니다."
                if "caffeine_free" in menu_item.tags
                else "카페인이 있습니다."
            )
            return f"{menu_item.name}에는 {label}"
        if field is MenuDetailField.MILK:
            label = (
                "우유가 들어가지 않습니다."
                if "milk_free" in menu_item.tags
                else "우유가 들어갑니다."
            )
            return f"{menu_item.name}에는 {label}"

        options = set(menu_item.temperature_options)
        if options == {Temperature.HOT, Temperature.ICED}:
            label = "따뜻하게 또는 아이스로 주문할 수 있습니다."
        elif options == {Temperature.ICED}:
            label = "아이스로 주문할 수 있습니다."
        elif options == {Temperature.HOT}:
            label = "따뜻하게 주문할 수 있습니다."
        else:
            label = "온도 선택이 없습니다."
        return f"{menu_item.name}는 {label}"

    def _execute_add_item(
        self, commands: list[OrderCommand], cart: Cart
    ) -> OrderResult:
        validated_commands: list[tuple[OrderCommand, MenuItem]] = []

        for command in commands:
            if command.target_item_id is None or command.category_id is not None:
                return self._failure(
                    cart, ErrorCode.INVALID_COMMAND, "주문을 처리할 수 없습니다."
                )

            menu_item = self._menu.get(command.target_item_id)
            if menu_item is None:
                return self._failure(
                    cart, ErrorCode.MENU_NOT_FOUND, "메뉴를 찾을 수 없습니다."
                )

            if command.quantity is None or command.quantity <= 0:
                return self._failure(
                    cart, ErrorCode.INVALID_QUANTITY, "수량을 다시 확인해 주세요."
                )
            if command.quantity > MAX_ITEM_QUANTITY:
                return self._quantity_limit_failure(cart)

            command = self._normalize_add_temperature(command, menu_item)
            temperature_error = self._validate_temperature(command, menu_item)
            if temperature_error is not None:
                return self._failure(cart, *temperature_error)

            option_error = self._validate_beverage_options(
                command.options,
                menu_item,
                command.temperature,
            )
            if option_error is not None:
                return self._failure(cart, *option_error)

            normalized_options = self._apply_option_changes(
                BeverageOptions(),
                command.options,
            )
            validated_commands.append(
                (
                    replace(
                        command,
                        options=(
                            normalized_options
                            if not normalized_options.is_empty
                            else None
                        ),
                    ),
                    menu_item,
                )
            )

        normalized_commands = self._merge_duplicate_commands(
            [command for command, _ in validated_commands]
        )
        validated_commands = [
            (command, self._menu[command.target_item_id])
            for command in normalized_commands
            if command.target_item_id is not None
        ]

        for command, _ in validated_commands:
            assert command.target_item_id is not None
            assert command.quantity is not None
            existing_quantity = sum(
                item.quantity
                for item in cart.items
                if item.menu_id == command.target_item_id
                and item.temperature == command.temperature
                and item.options == (command.options or BeverageOptions())
            )
            if existing_quantity + command.quantity > MAX_ITEM_QUANTITY:
                return self._quantity_limit_failure(cart)

        new_cart = cart.copy()
        response_items = []
        option_responses = []
        for command, menu_item in validated_commands:
            self._set_cart_quantity(new_cart, command, menu_item)
            response_items.append(
                f"{self._response_temperature_label(command.temperature, menu_item)}{menu_item.name} "
                f"{self._quantity_label(command.quantity)}{menu_item.unit}"
            )
            option_summary = self._option_summary(command.options)
            if option_summary:
                option_responses.append(
                    f"{menu_item.name} 옵션은 {option_summary}입니다."
                )

        last_phrase = response_items[-1]
        particle = self._korean_particle(last_phrase, "을를")
        response_text = f"{', '.join(response_items)}{particle} 담았습니다."
        if option_responses:
            response_text = f"{response_text} {' '.join(option_responses)}"
        return OrderResult(
            success=True,
            cart=new_cart,
            response_text=response_text,
        )

    def _execute_remove_item(
        self, commands: list[OrderCommand], cart: Cart
    ) -> OrderResult:
        command = commands[0]
        if command.target_item_id is None:
            return self._failure(cart, ErrorCode.INVALID_COMMAND, "삭제할 메뉴를 지정해 주세요.")

        menu_item = self._menu.get(command.target_item_id)
        if menu_item is None:
            return self._failure(cart, ErrorCode.MENU_NOT_FOUND, "메뉴를 찾을 수 없습니다.")

        new_cart = cart.copy()
        target_indices = [
            index
            for index, item in enumerate(new_cart.items)
            if item.menu_id == command.target_item_id
            and (command.temperature is None or item.temperature == command.temperature)
        ]
        if not target_indices:
            return self._failure(
                cart, ErrorCode.MENU_NOT_FOUND, "장바구니에 해당 메뉴가 없습니다."
            )
        if len(target_indices) > 1:
            return self._failure(
                cart,
                ErrorCode.AMBIGUOUS_TARGET,
                "옵션이 다른 같은 메뉴가 여러 개입니다. 삭제할 메뉴의 옵션을 함께 말씀해 주세요.",
            )

        removed_item = new_cart.items.pop(target_indices[0])
        target_name = f"{self._response_temperature_label(removed_item.temperature, menu_item)}{menu_item.name}"
        particle = self._korean_particle(target_name, "을를")
        return OrderResult(
            success=True,
            cart=new_cart,
            response_text=f"{target_name}{particle} 장바구니에서 삭제했습니다.",
        )

    def _execute_update_quantity(
        self, commands: list[OrderCommand], cart: Cart
    ) -> OrderResult:
        command = commands[0]
        if command.target_item_id is None:
            return self._failure(cart, ErrorCode.INVALID_COMMAND, "수정할 메뉴를 지정해 주세요.")

        if command.quantity is None or command.quantity <= 0:
            return self._failure(
                cart, ErrorCode.INVALID_QUANTITY, "수량을 다시 확인해 주세요."
            )
        if command.quantity > MAX_ITEM_QUANTITY:
            return self._quantity_limit_failure(cart)

        menu_item = self._menu.get(command.target_item_id)
        if menu_item is None:
            return self._failure(cart, ErrorCode.MENU_NOT_FOUND, "메뉴를 찾을 수 없습니다.")

        new_cart = cart.copy()
        target_indices = [
            index
            for index, item in enumerate(new_cart.items)
            if item.menu_id == command.target_item_id
            and (command.temperature is None or item.temperature == command.temperature)
        ]
        if not target_indices:
            return self._failure(
                cart, ErrorCode.MENU_NOT_FOUND, "장바구니에 해당 메뉴가 없습니다."
            )
        if len(target_indices) > 1:
            return self._failure(
                cart,
                ErrorCode.AMBIGUOUS_TARGET,
                "옵션이 다른 같은 메뉴가 여러 개입니다. 변경할 메뉴의 옵션을 함께 말씀해 주세요.",
            )

        target_index = target_indices[0]
        existing = new_cart.items[target_index]
        new_cart.items[target_index] = CartItem(
            menu_id=existing.menu_id,
            quantity=command.quantity,
            temperature=existing.temperature,
            unit_price=existing.unit_price,
            options=existing.options,
        )

        target_name = f"{self._response_temperature_label(existing.temperature, menu_item)}{menu_item.name}"
        particle = self._korean_particle(target_name, "을를")
        qty_unit = f"{self._quantity_label(command.quantity)}{menu_item.unit}".strip()
        dir_particle = self._korean_particle(qty_unit, "으로")

        return OrderResult(
            success=True,
            cart=new_cart,
            response_text=f"{target_name}{particle} {qty_unit}{dir_particle} 변경했습니다.",
        )

    def _execute_update_option(
        self, commands: list[OrderCommand], cart: Cart
    ) -> OrderResult:
        command = commands[0]
        if command.target_item_id is None or (
            command.temperature is None and command.options is None
        ):
            return self._failure(
                cart, ErrorCode.INVALID_COMMAND, "변경할 메뉴와 옵션을 지정해 주세요."
            )
        if command.options is not None and command.options.is_empty:
            return self._failure(
                cart, ErrorCode.INVALID_COMMAND, "변경할 음료 옵션을 말씀해 주세요."
            )

        menu_item = self._menu.get(command.target_item_id)
        if menu_item is None:
            return self._failure(cart, ErrorCode.MENU_NOT_FOUND, "메뉴를 찾을 수 없습니다.")

        new_cart = cart.copy()
        target_indices = [
            index
            for index, item in enumerate(new_cart.items)
            if item.menu_id == command.target_item_id
        ]
        if not target_indices:
            return self._failure(
                cart, ErrorCode.MENU_NOT_FOUND, "장바구니에 해당 메뉴가 없습니다."
            )
        is_partial_temperature_change = (
            command.quantity is not None
            and command.temperature is not None
            and command.options is None
        )
        if is_partial_temperature_change and len(target_indices) > 1:
            source_indices = [
                index
                for index in target_indices
                if new_cart.items[index].temperature is not command.temperature
            ]
            if len(source_indices) == 1:
                target_indices = source_indices
        if len(target_indices) > 1:
            return self._failure(
                cart,
                ErrorCode.AMBIGUOUS_TARGET,
                "같은 메뉴가 여러 개입니다. 변경할 메뉴의 온도와 옵션을 함께 말씀해 주세요.",
            )

        target_index = target_indices[0]
        existing = new_cart.items[target_index]
        if is_partial_temperature_change and (
            command.quantity is None
            or command.quantity <= 0
            or command.quantity > existing.quantity
        ):
            return self._failure(
                cart, ErrorCode.INVALID_QUANTITY, "수량을 다시 확인해 주세요."
            )
        new_temperature = command.temperature or existing.temperature
        temperature_error = self._validate_temperature(
            replace(command, temperature=new_temperature),
            menu_item,
        )
        if temperature_error is not None:
            return self._failure(cart, *temperature_error)
        option_error = self._validate_beverage_options(
            command.options,
            menu_item,
            new_temperature,
        )
        if option_error is not None:
            return self._failure(cart, *option_error)
        new_options = self._apply_option_changes(existing.options, command.options)

        if is_partial_temperature_change and command.quantity < existing.quantity:
            moving_quantity = command.quantity
            new_cart.items[target_index] = CartItem(
                menu_id=existing.menu_id,
                quantity=existing.quantity - moving_quantity,
                temperature=existing.temperature,
                unit_price=existing.unit_price,
                options=existing.options,
            )
        else:
            moving_quantity = existing.quantity
            new_cart.items.pop(target_index)
        # 만약 변경할 온도와 동일한 항목이 이미 있으면 수량 합산
        for idx, item in enumerate(new_cart.items):
            if (
                item.menu_id == command.target_item_id
                and item.temperature == new_temperature
                and item.options == new_options
            ):
                if item.quantity + moving_quantity > MAX_ITEM_QUANTITY:
                    return self._quantity_limit_failure(cart)
                new_cart.items[idx] = CartItem(
                    menu_id=item.menu_id,
                    quantity=item.quantity + moving_quantity,
                    temperature=new_temperature,
                    unit_price=self._unit_price(menu_item, new_options),
                    options=item.options,
                )
                break
        else:
            new_cart.items.append(
                CartItem(
                    menu_id=existing.menu_id,
                    quantity=moving_quantity,
                    temperature=new_temperature,
                    unit_price=self._unit_price(menu_item, new_options),
                    options=new_options,
                )
            )

        particle = self._korean_particle(menu_item.name, "을를")
        if command.options is None:
            temp_str = (
                "따뜻한 음료"
                if new_temperature is Temperature.HOT
                else "아이스 음료"
            )
            response_text = f"{menu_item.name}{particle} {temp_str}로 변경했습니다."
        else:
            changes = self._option_change_summary(command.options)
            if command.temperature is not None:
                temperature_change = (
                    "따뜻한 음료"
                    if new_temperature is Temperature.HOT
                    else "아이스 음료"
                )
                changes = f"{temperature_change}, {changes}"
            response_text = f"{menu_item.name}{particle} {changes} 변경했습니다."
        return OrderResult(
            success=True,
            cart=new_cart,
            response_text=response_text,
        )

    def _execute_query_cart(self, cart: Cart) -> OrderResult:
        if not cart.items:
            return OrderResult(
                success=True,
                cart=cart.copy(),
                response_text="장바구니가 비어 있습니다.",
            )

        items_desc = []
        for item in cart.items:
            menu = self._menu.get(item.menu_id)
            name = menu.name if menu else item.menu_id
            unit = menu.unit if menu else "개"
            temp = self._response_temperature_label(item.temperature, menu)
            qty = self._quantity_label(item.quantity)
            description = f"{temp}{name} {qty}{unit}".strip()
            option_summary = self._option_summary(item.options)
            if option_summary:
                description = f"{description}, 옵션은 {option_summary}"
            items_desc.append(description)

        last_item = items_desc[-1]
        particle = self._korean_particle(last_item, "이가")
        fulfillment = self._fulfillment_label(cart.fulfillment_type)
        fulfillment_text = f"{fulfillment} 주문으로 " if fulfillment else ""
        return OrderResult(
            success=True,
            cart=cart.copy(),
            response_text=(
                f"{fulfillment_text}현재 {', '.join(items_desc)}{particle} 담겨 있으며, "
                f"총 {cart.total_price:,}원입니다."
            ),
        )

    def _execute_confirm_order(self, cart: Cart) -> OrderResult:
        if not cart.items:
            return self._failure(
                cart, ErrorCode.INVALID_COMMAND, "장바구니가 비어 있어 주문을 확정할 수 없습니다."
            )
        if cart.fulfillment_type is None:
            return self._failure(cart, ErrorCode.INVALID_COMMAND, "매장 이용 또는 포장을 먼저 선택해 주세요.")
        confirmed = cart.copy()
        confirmed.confirmed = True

        option_items = []
        for item in cart.items:
            option_summary = self._option_summary(item.options)
            if option_summary:
                menu = self._menu.get(item.menu_id)
                name = menu.name if menu else item.menu_id
                option_items.append(f"{name}은 {option_summary}")
        option_text = (
            f"주문 옵션은 {'; '.join(option_items)}입니다."
            if option_items
            else ""
        )
        fulfillment = self._fulfillment_label(cart.fulfillment_type)
        fulfillment_text = f"{fulfillment} 주문입니다." if fulfillment else ""
        payment_text = (
            f"총 결제 금액은 {cart.total_price:,}원입니다. 결제를 진행해 주세요."
        )
        return OrderResult(
            success=True,
            cart=confirmed,
            response_text=" ".join(
                text for text in (fulfillment_text, option_text, payment_text) if text
            ),
        )

    @staticmethod
    def _execute_select_payment_method(
        commands: list[OrderCommand], cart: Cart
    ) -> OrderResult:
        command = commands[0]
        method_labels = {
            "card": "카드",
            "samsung": "삼성페이",
            "kakao": "카카오페이",
            "cash": "현금",
        }
        if (
            len(commands) != 1
            or command.target_item_id not in method_labels
            or any(
                value is not None
                for value in (
                    command.category_id,
                    command.quantity,
                    command.temperature,
                    command.query_tags,
                    command.detail_fields,
                    command.options,
                    command.fulfillment_type,
                )
            )
        ):
            return ConversationAgent._failure(
                cart, ErrorCode.INVALID_COMMAND, "결제수단을 다시 말씀해 주세요."
            )
        if not cart.items:
            return ConversationAgent._failure(
                cart, ErrorCode.INVALID_COMMAND, "장바구니가 비어 있습니다."
            )
        if cart.fulfillment_type is None:
            return ConversationAgent._failure(
                cart, ErrorCode.INVALID_COMMAND, "매장 이용 또는 포장을 먼저 선택해 주세요."
            )
        if not cart.confirmed:
            return ConversationAgent._failure(
                cart, ErrorCode.INVALID_COMMAND, "주문을 먼저 확정해 주세요."
            )
        return OrderResult(
            success=True,
            cart=cart.copy(),
            response_text=f"{method_labels[command.target_item_id]} 결제를 선택했습니다. 주문이 완료되었습니다.",
        )

    @staticmethod
    def _execute_cancel() -> OrderResult:
        return OrderResult(
            success=True,
            cart=Cart(),
            response_text="주문이 모두 취소되었습니다.",
        )

    def _execute_reset_order(self) -> OrderResult:
        """Clear the whole voice-order session; this is deliberately not undo."""
        self.reset_session()
        return OrderResult(
            success=True,
            cart=Cart(),
            response_text="주문을 처음부터 다시 시작합니다. 매장 이용 또는 포장을 선택해 주세요.",
        )

    @staticmethod
    def _execute_set_fulfillment(commands: list[OrderCommand], cart: Cart) -> OrderResult:
        if len(commands) != 1 or commands[0].fulfillment_type is None:
            return ConversationAgent._failure(cart, ErrorCode.INVALID_COMMAND, "매장 이용 또는 포장을 선택해 주세요.")
        updated = cart.copy()
        updated.fulfillment_type = commands[0].fulfillment_type
        updated.confirmed = False
        label = "매장 이용" if updated.fulfillment_type is FulfillmentType.DINE_IN else "포장"
        return OrderResult(True, updated, f"{label}으로 설정했습니다.")

    @staticmethod
    def _set_cart_quantity(
        cart: Cart,
        command: OrderCommand,
        menu_item: MenuItem,
    ) -> None:
        assert command.target_item_id is not None
        assert command.quantity is not None
        for index, item in enumerate(cart.items):
            if (
                item.menu_id == command.target_item_id
                and item.temperature == command.temperature
                and item.options == (command.options or BeverageOptions())
            ):
                cart.items[index] = CartItem(
                    menu_id=item.menu_id,
                    # ADD_ITEM is an incremental request.  UPDATE_QUANTITY is
                    # the only intent that replaces an existing quantity.
                    quantity=item.quantity + command.quantity,
                    temperature=item.temperature,
                    unit_price=item.unit_price,
                    options=item.options,
                )
                break
        else:
            cart.items.append(
                CartItem(
                    menu_id=command.target_item_id,
                    quantity=command.quantity,
                    temperature=command.temperature,
                    unit_price=ConversationAgent._unit_price(
                        menu_item, command.options or BeverageOptions()
                    ),
                    options=command.options or BeverageOptions(),
                )
            )

    def _quantity_limit_failure(self, cart: Cart) -> OrderResult:
        return self._failure(
            cart,
            ErrorCode.INVALID_QUANTITY,
            f"메뉴별 수량은 최대 {MAX_ITEM_QUANTITY}개까지 주문할 수 있습니다.",
        )

    @staticmethod
    def _normalize_add_temperature(
        command: OrderCommand,
        menu_item: MenuItem,
    ) -> OrderCommand:
        """Apply the only catalog-defined temperature default (a single option).

        Dual-temperature drinks deliberately have no default.  They must be
        clarified before an item can reach the cart.
        """
        if command.temperature is None and len(menu_item.temperature_options) == 1:
            return replace(command, temperature=menu_item.temperature_options[0])
        return command

    @staticmethod
    def _validate_temperature(
        command: OrderCommand,
        menu_item: MenuItem,
    ) -> tuple[ErrorCode, str] | None:
        if command.temperature is None:
            if len(menu_item.temperature_options) > 1:
                return (
                    ErrorCode.MISSING_FIELD,
                    "따뜻하게 드릴까요, 아이스로 드릴까요?",
                )
            return None
        if command.temperature not in menu_item.temperature_options:
            if not menu_item.temperature_options and command.temperature is None:
                return None
            return ErrorCode.INVALID_OPTION, "선택할 수 없는 온도입니다."
        return None

    @staticmethod
    def _merge_duplicate_commands(commands: list[OrderCommand]) -> list[OrderCommand]:
        merged: list[OrderCommand] = []
        positions: dict[
            tuple[str | None, Temperature | None, BeverageOptions | None], int
        ] = {}

        for command in commands:
            key = (command.target_item_id, command.temperature, command.options)
            if key not in positions:
                positions[key] = len(merged)
                merged.append(command)
                continue

            index = positions[key]
            previous = merged[index]
            if previous.quantity is None or command.quantity is None:
                merged[index] = replace(previous, quantity=None)
            else:
                merged[index] = replace(
                    previous,
                    quantity=previous.quantity + command.quantity,
                )

        return merged

    @staticmethod
    def _validate_beverage_options(
        options: BeverageOptions | None,
        menu_item: MenuItem,
        temperature: Temperature | None,
    ) -> tuple[ErrorCode, str] | None:
        if options is None:
            return None
        policy = menu_item.option_policy
        if options.size is not None and not policy.size_supported:
            return ErrorCode.INVALID_OPTION, "이 메뉴는 사이즈 변경을 지원하지 않습니다."
        if options.extra_shots is not None and (
            not policy.shot_supported
        ):
            return ErrorCode.INVALID_OPTION, "이 메뉴는 요청한 샷 옵션을 지원하지 않습니다."
        if options.caffeine is not None and not policy.decaf_available:
            return ErrorCode.INVALID_OPTION, "이 메뉴는 디카페인 변경을 지원하지 않습니다."
        if options.syrup_pumps is not None and (
            not policy.syrup_supported
        ):
            return ErrorCode.INVALID_OPTION, "이 메뉴는 요청한 시럽 옵션을 지원하지 않습니다."
        if options.ice_amount is not None and (
            not policy.ice_amount_available or temperature is not Temperature.ICED
        ):
            return ErrorCode.INVALID_OPTION, "얼음 양은 아이스 음료에서만 변경할 수 있습니다."
        return None

    @staticmethod
    def _apply_option_changes(
        current: BeverageOptions,
        changes: BeverageOptions | None,
    ) -> BeverageOptions:
        if changes is None:
            return current.normalized()
        return BeverageOptions(
            size=(changes.size if changes.size is not None else current.size),
            extra_shots=(
                changes.extra_shots
                if changes.extra_shots is not None
                else current.extra_shots
            ),
            caffeine=(
                changes.caffeine
                if changes.caffeine is not None
                else current.caffeine
            ),
            syrup_pumps=(
                changes.syrup_pumps
                if changes.syrup_pumps is not None
                else current.syrup_pumps
            ),
            ice_amount=(
                changes.ice_amount
                if changes.ice_amount is not None
                else current.ice_amount
            ),
        ).normalized()

    @staticmethod
    def _option_summary(options: BeverageOptions | None) -> str:
        if options is None:
            return ""
        labels = []
        if options.size is not None:
            labels.append(
                {
                    BeverageSize.SMALL: "스몰 사이즈",
                    BeverageSize.MEDIUM: "미디엄 사이즈",
                    BeverageSize.LARGE: "라지 사이즈",
                }[options.size]
            )
        if options.extra_shots:
            labels.append(f"추가 샷 {options.extra_shots}회")
        if options.caffeine is CaffeineOption.DECAF:
            labels.append("디카페인")
        if options.syrup_pumps:
            labels.append(f"시럽 {options.syrup_pumps}회")
        if options.ice_amount is not None:
            labels.append(
                {
                    IceAmount.NONE: "얼음 없음",
                    IceAmount.LESS: "얼음 적게",
                    IceAmount.NORMAL: "얼음 보통",
                    IceAmount.MORE: "얼음 많이",
                }[options.ice_amount]
            )
        return ", ".join(labels)

    @staticmethod
    def _option_change_summary(options: BeverageOptions) -> str:
        labels = []
        if options.size is not None:
            labels.append(
                {
                    BeverageSize.SMALL: "스몰 사이즈로",
                    BeverageSize.MEDIUM: "미디엄 사이즈로",
                    BeverageSize.LARGE: "라지 사이즈로",
                }[options.size]
            )
        if options.extra_shots is not None:
            labels.append(f"추가 샷을 {options.extra_shots}회로")
        if options.caffeine is not None:
            labels.append(
                "디카페인으로"
                if options.caffeine is CaffeineOption.DECAF
                else "일반 카페인으로"
            )
        if options.syrup_pumps is not None:
            labels.append(f"시럽을 {options.syrup_pumps}회로")
        if options.ice_amount is not None:
            labels.append(
                {
                    IceAmount.NONE: "얼음 없이",
                    IceAmount.LESS: "얼음을 적게 넣도록",
                    IceAmount.NORMAL: "얼음을 보통으로",
                    IceAmount.MORE: "얼음을 많이 넣도록",
                }[options.ice_amount]
            )
        return ", ".join(labels)

    @staticmethod
    def _unit_price(menu_item: MenuItem, options: BeverageOptions) -> int:
        adjustment = {
            None: 0,
            BeverageSize.SMALL: -500,
            BeverageSize.MEDIUM: 0,
            BeverageSize.LARGE: 500,
        }[options.size]
        return menu_item.base_price + adjustment

    @staticmethod
    def _fulfillment_label(value: FulfillmentType | None) -> str:
        return {
            FulfillmentType.DINE_IN: "매장 이용",
            FulfillmentType.TAKEOUT: "포장",
            None: "",
        }[value]

    @staticmethod
    def _failure(cart: Cart, code: ErrorCode, message: str) -> OrderResult:
        err = create_error_response(
            code,
            module=ErrorModule.ORDER_ENGINE,
            user_message=message,
        )
        return OrderResult(False, cart.copy(), message, code, error_response=err)

    @staticmethod
    def _quantity_label(quantity: int) -> str:
        return {1: "한 ", 2: "두 "}.get(quantity, f"{quantity}")

    @staticmethod
    def _temperature_label(temperature: Temperature | None) -> str:
        return {
            Temperature.HOT: "따뜻한 ",
            Temperature.ICED: "아이스 ",
            None: "",
        }[temperature]

    @classmethod
    def _response_temperature_label(
        cls, temperature: Temperature | None, menu_item: MenuItem,
    ) -> str:
        """Keep the stored temperature, but do not speak an inherent menu temperature."""
        if len(menu_item.temperature_options) == 1:
            return ""
        return cls._temperature_label(temperature)

    @staticmethod
    def _korean_particle(word: str, particle_type: str = "을를") -> str:
        """한글 받침 유무에 따른 올바른 조사를 반환합니다."""
        if not word:
            return ""
        last_char = word.strip()[-1]
        if "가" <= last_char <= "힣":
            jong = (ord(last_char) - ord("가")) % 28
            has_jongseong = jong > 0
            if particle_type == "을를":
                return "을" if has_jongseong else "를"
            elif particle_type == "이가":
                return "이" if has_jongseong else "가"
            elif particle_type == "은는":
                return "은" if has_jongseong else "는"
            elif particle_type == "으로":
                return "로" if (jong == 0 or jong == 8) else "으로"
        return "를"
