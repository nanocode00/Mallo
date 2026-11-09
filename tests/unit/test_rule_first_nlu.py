from __future__ import annotations

import pytest

from adapters.tts.mock_tts import MockTTS
from app.service import MalloService, build_mock_service
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import BeverageOptions, CaffeineOption, Cart, CartItem, FulfillmentType, OrderCommand, Temperature
from domain.order_command_error import OrderCommandError, OrderCommandErrorCode
from orchestrator.rule_first_nlu import RuleFirstNLU


class FallbackNLU:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[str] = []

    def parse(self, text: str, current_order_state: Cart):
        del current_order_state
        self.calls.append(text)
        return self.result


def _service_with_fallback(fallback: FallbackNLU) -> MalloService:
    return MalloService(
        nlu=fallback,
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
    )


@pytest.mark.parametrize("text", ["케모마일티 한 잔 주세요", "캐모마일티 한 잔 주세요"])
def test_chamomile_temperature_clarification_completes_without_fallback(text: str) -> None:
    fallback = FallbackNLU([])
    service = _service_with_fallback(fallback)

    prompt = service.handle_text(text, Cart())
    completed = service.handle_text("차가운 걸로", prompt.cart)

    assert prompt.error_response.details["field"] == "temperature"
    assert completed.success is True
    assert completed.cart.items == [CartItem("chamomile_tea", 1, Temperature.ICED, 3700)]
    assert fallback.calls == []


def test_menu_particle_after_americano_keeps_temperature_clarification_path() -> None:
    fallback = FallbackNLU([])
    service = _service_with_fallback(fallback)

    prompt = service.handle_text("아메리카노도 두 잔 주세요", Cart())
    completed = service.handle_text("아이스로", prompt.cart)

    assert prompt.error_response.details["field"] == "temperature"
    assert completed.success is True
    assert completed.cart.items == [CartItem("americano", 2, Temperature.ICED, 4700)]
    assert fallback.calls == []


def test_fallback_single_temperature_missing_add_keeps_slots_for_hot_reply() -> None:
    fallback = FallbackNLU([
        OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id="cafe_latte",
            quantity=2,
            options=BeverageOptions(extra_shots=1),
            fulfillment_type=FulfillmentType.TAKEOUT,
        )
    ])
    service = _service_with_fallback(fallback)

    prompt = service.handle_text("fallback latte phrase", Cart())
    completed = service.handle_text("따뜻한 걸로", prompt.cart)

    assert prompt.error_response.details["field"] == "temperature"
    assert completed.success is True
    assert completed.cart.fulfillment_type is FulfillmentType.TAKEOUT
    assert completed.cart.items == [
        CartItem("cafe_latte", 2, Temperature.HOT, 5200, BeverageOptions(extra_shots=1))
    ]
    assert fallback.calls == ["fallback latte phrase"]


@pytest.mark.parametrize(
    "fallback_result",
    [
        [OrderCommand.create(Intent.ADD_ITEM, target_item_id="unknown_menu", quantity=1)],
        [
            OrderCommand.create(Intent.ADD_ITEM, target_item_id="americano", quantity=1),
            OrderCommand.create(Intent.ADD_ITEM, target_item_id="cafe_latte", quantity=1),
        ],
    ],
)
def test_fallback_non_single_resolvable_add_does_not_create_temperature_pending(fallback_result) -> None:
    fallback = FallbackNLU(fallback_result)
    nlu = RuleFirstNLU(fallback)

    nlu.parse("fallback-only phrase", Cart())
    nlu.parse("따뜻한 걸로", Cart())

    assert fallback.calls == ["fallback-only phrase", "따뜻한 걸로"]


def test_fallback_ambiguous_error_does_not_create_temperature_pending() -> None:
    fallback = FallbackNLU(OrderCommandError(
        code=OrderCommandErrorCode.AMBIGUOUS_TARGET,
        message="메뉴를 다시 말씀해 주세요.",
        field="target_item_id",
    ))
    nlu = RuleFirstNLU(fallback)

    nlu.parse("fallback-only phrase", Cart())
    nlu.parse("따뜻한 걸로", Cart())

    assert fallback.calls == ["fallback-only phrase", "따뜻한 걸로"]


def test_category_query_what_is_available_uses_rule_path() -> None:
    fallback = FallbackNLU([])

    result = RuleFirstNLU(fallback).parse("차는 뭐가 있죠?", Cart())

    assert result[0].intent is Intent.QUERY_MENU
    assert result[0].category_id == "tea"
    assert fallback.calls == []


def test_pending_iced_americano_keeps_slots_for_quantity_only_follow_up() -> None:
    fallback = FallbackNLU([])
    nlu = RuleFirstNLU(fallback)

    first = nlu.parse("아이스 아메리카노", Cart())
    second = nlu.parse("하나", Cart())

    assert isinstance(first, OrderCommandError)
    assert first.code is OrderCommandErrorCode.MISSING_FIELD
    assert isinstance(second, list)
    assert second[0].intent is Intent.ADD_ITEM
    assert second[0].target_item_id == "americano"
    assert second[0].quantity == 1
    assert second[0].temperature.value == "iced"
    assert fallback.calls == []


def test_pending_americano_one_cup_requires_temperature_before_add() -> None:
    nlu = RuleFirstNLU(FallbackNLU([]))
    nlu.parse("아메리카노", Cart())

    result = nlu.parse("한잔", Cart())

    assert isinstance(result, OrderCommandError)
    assert result.field == "temperature"


def test_pending_follow_up_executes_with_preserved_iced_menu_slots() -> None:
    service = build_mock_service()
    missing = service.handle_text("아이스 아메리카노", Cart())

    completed = service.handle_text("하나", missing.cart)

    assert completed.success is True
    assert completed.cart.items[0].menu_id == "americano"
    assert completed.cart.items[0].quantity == 1
    assert completed.cart.items[0].temperature.value == "iced"


def test_fulfillment_during_pending_add_preserves_menu_slots() -> None:
    nlu = RuleFirstNLU(FallbackNLU([]))
    nlu.parse("아이스 아메리카노", Cart())

    fulfillment = nlu.parse("포장할게요", Cart())
    completed = nlu.parse("하나", Cart())

    assert fulfillment[0].intent is Intent.SET_FULFILLMENT
    assert fulfillment[0].fulfillment_type.value == "takeout"
    assert [command.intent for command in completed] == [
        Intent.SET_FULFILLMENT,
        Intent.ADD_ITEM,
    ]
    assert completed[0].fulfillment_type is FulfillmentType.TAKEOUT
    assert completed[1].target_item_id == "americano"
    assert completed[1].temperature.value == "iced"


def test_pending_quantity_reapplies_takeout_for_iced_americano_without_confirmation() -> None:
    service = build_mock_service()

    pending = service.handle_text("아이스 아메리카노 포장할게요", Cart())
    completed = service.handle_text("하나", pending.cart)

    assert pending.success is False
    assert completed.success is True
    assert completed.cart.fulfillment_type is FulfillmentType.TAKEOUT
    assert completed.cart.confirmed is False
    assert completed.cart.items == [CartItem("americano", 1, Temperature.ICED, 4700)]


def test_pending_quantity_reapplies_takeout_for_grapefruit_ade_without_confirmation() -> None:
    service = build_mock_service()

    pending = service.handle_text("자몽에이드 포장할게요", Cart())
    completed = service.handle_text("두 잔", pending.cart)

    assert pending.success is False
    assert completed.success is True
    assert completed.cart.fulfillment_type is FulfillmentType.TAKEOUT
    assert completed.cart.confirmed is False
    assert completed.cart.items == [CartItem("grapefruit_ade", 2, Temperature.ICED, 3500)]


def test_pending_quantity_without_fulfillment_still_only_adds_item() -> None:
    nlu = RuleFirstNLU(FallbackNLU([]))

    nlu.parse("아이스 아메리카노", Cart())
    completed = nlu.parse("하나", Cart())

    assert [command.intent for command in completed] == [Intent.ADD_ITEM]


def test_pending_temperature_keeps_takeout_after_quantity_was_supplied() -> None:
    service = build_mock_service()

    pending = service.handle_text("카페라떼 두 잔 포장할게요", Cart())
    completed = service.handle_text("아이스로", pending.cart)

    assert pending.success is False
    assert completed.success is True
    assert completed.cart.fulfillment_type is FulfillmentType.TAKEOUT
    assert completed.cart.confirmed is False
    assert completed.cart.items == [CartItem("cafe_latte", 2, Temperature.ICED, 5200)]


def test_temperature_clarification_preserves_quantity_and_fulfillment() -> None:
    service = build_mock_service()

    missing = service.handle_text("아메리카노 하나 매장에서", Cart())
    completed = service.handle_text("아이스로", missing.cart)

    assert missing.success is False
    assert missing.response_text == "따뜻하게 드릴까요, 아이스로 드릴까요?"
    assert missing.cart.items == []
    assert completed.success is True
    assert completed.cart.fulfillment_type is FulfillmentType.DINE_IN
    assert completed.cart.items == [CartItem("americano", 1, Temperature.ICED, 4700)]


def test_pending_cafe_latte_quantity_then_temperature_adds_the_requested_item() -> None:
    service = build_mock_service()

    quantity_prompt = service.handle_text("카페라떼 주세요", Cart())
    temperature_prompt = service.handle_text("두 잔", quantity_prompt.cart)
    completed = service.handle_text("아이스로", temperature_prompt.cart)

    assert quantity_prompt.error_code is not None
    assert quantity_prompt.error_response.details["field"] == "quantity"
    assert temperature_prompt.error_response.details["field"] == "temperature"
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 2, Temperature.ICED, 5200)]


def test_pending_quantity_reply_with_polite_ending_keeps_menu_and_requests_temperature() -> None:
    service = build_mock_service()

    quantity_prompt = service.handle_text("카페라떼 주세요", Cart())
    temperature_prompt = service.handle_text("두 잔 주세요", quantity_prompt.cart)
    completed = service.handle_text("아이스로", temperature_prompt.cart)

    assert temperature_prompt.error_response.details["field"] == "temperature"
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 2, Temperature.ICED, 5200)]


def test_pending_cafe_latte_temperature_never_updates_existing_americano() -> None:
    service = build_mock_service()
    cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)])

    prompt = service.handle_text("카페라떼 한잔 주세요", cart)
    completed = service.handle_text("아이스로", prompt.cart)

    assert prompt.error_response.details["field"] == "temperature"
    assert completed.success is True
    assert completed.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700),
        CartItem("cafe_latte", 1, Temperature.ICED, 5200),
    ]


def test_pending_cafe_latte_temperature_then_adds_hot_item() -> None:
    service = build_mock_service()

    prompt = service.handle_text("카페라떼 한잔 주세요", Cart())
    completed = service.handle_text("따뜻하게", prompt.cart)

    assert prompt.error_response.details["field"] == "temperature"
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 1, Temperature.HOT, 5200)]


def test_cafe_latte_with_hot_quantity_is_added_without_clarification() -> None:
    result = build_mock_service().handle_text("카페라떼 따뜻한 걸로 한잔", Cart())

    assert result.success is True
    assert result.cart.items == [CartItem("cafe_latte", 1, Temperature.HOT, 5200)]


@pytest.mark.parametrize(
    ("text", "quantity"),
    [
        ("아이스 아메리카노 한 잔 주세요", 1),
        ("아이스 아메리카노 2잔 주세요", 2),
        ("아이스 아메리카노 세잔 세잔 주세요", 3),
        ("아이스 아메리카노 5개 주세요", 5),
    ],
)
def test_order_quantity_forms_are_normalized(text: str, quantity: int) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert isinstance(result, list)
    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].quantity == quantity


def test_quantity_change_uses_the_same_normalization() -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(
        "아이스 아메리카노 세잔 세잔으로 바꿔 주세요", Cart(),
    )

    assert isinstance(result, list)
    assert result[0].intent is Intent.UPDATE_QUANTITY
    assert result[0].quantity == 3


@pytest.mark.parametrize(
    "text",
    ["아이스 아메리카노 한 잔 한 잔 주세요", "아이스 아메리카노 한잔 한잔 주세요"],
)
def test_stt_duplicated_quantity_is_one_requested_quantity(text: str) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].target_item_id == "americano"
    assert result[0].quantity == 1
    assert result[0].temperature is Temperature.ICED


def test_self_correction_replaces_quantity_without_losing_menu_context() -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse("아이스 아메리카노 한 잔 아니 두 잔", Cart())

    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].target_item_id == "americano"
    assert result[0].quantity == 2
    assert result[0].temperature is Temperature.ICED


def test_pending_temperature_question_accepts_corrected_quantity_and_keeps_prompt() -> None:
    nlu = RuleFirstNLU(FallbackNLU([]))
    prompt = nlu.parse("카페라떼 한 잔", Cart())
    corrected = nlu.parse("아니 두 잔으로", Cart())

    assert isinstance(prompt, OrderCommandError)
    assert prompt.field == "temperature"
    assert isinstance(corrected, OrderCommandError)
    assert corrected.field == "temperature"


def test_self_correction_uses_the_last_complete_menu_order() -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(
        "아이스 아메리카노 아니 따뜻한 아메리카노 한잔", Cart(),
    )

    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].target_item_id == "americano"
    assert result[0].quantity == 1
    assert result[0].temperature is Temperature.HOT


@pytest.mark.parametrize(
    ("text", "category_id"),
    [
        ("차 뭐 있어", "tea"), ("차에 뭐 있어", "tea"), ("티 뭐 있어", "tea"),
        ("논커피 뭐 있어", "non_coffee"), ("넌커피에 뭐 있어", "non_coffee"),
        ("차에는 뭐 있어", "tea"), ("커피는 뭐 있어", "coffee"),
        ("논커피에는 뭐 있어", "non_coffee"), ("커피 종류 알려줘", "coffee"),
        ("디저트 보여줘", "dessert"),
    ],
)
def test_colloquial_category_queries_use_canonical_category_id(text: str, category_id: str) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert result[0].intent is Intent.QUERY_MENU
    assert result[0].category_id == category_id


@pytest.mark.parametrize("text", ["변경할 거 없어", "변경할 거 없어요", "괜찮아요"])
def test_no_change_replies_cannot_cancel_the_cart(text: str) -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.CANCEL)])

    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert isinstance(result, list)
    assert result[0].intent is Intent.QUERY_CART
    assert fallback.calls == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("바닐라 라떼 아이스로 하나 주세요", CartItem("vanilla_latte", 1, Temperature.ICED, 3400)),
        ("자몽에이드 하나 추가", CartItem("grapefruit_ade", 1, Temperature.ICED, 3500)),
    ],
)
def test_explicit_new_menu_add_phrases_execute_without_option_update(
    text: str, expected: CartItem,
) -> None:
    result = build_mock_service().handle_text(text, Cart())

    assert result.success is True
    assert result.cart.items == [expected]


def test_empty_cart_complete_menu_order_with_fulfillment_confirms_in_one_batch() -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse("아이스 아메리카노 하나 포장하고 싶어", Cart())

    assert [command.intent for command in result] == [Intent.SET_FULFILLMENT, Intent.ADD_ITEM, Intent.CONFIRM_ORDER]
    assert result[1].target_item_id == "americano"
    assert result[1].temperature.value == "iced"
    assert result[1].quantity == 1


def test_one_shot_order_shows_and_speaks_only_the_final_payment_guidance() -> None:
    tts = MockTTS()
    service = MalloService(
        nlu=FallbackNLU([]),
        agent=ConversationAgent(load_menu()),
        tts=tts,
    )

    result = service.handle_text("아이스 아메리카노 한 잔 포장해주세요", Cart())

    assert result.success is True
    assert result.cart.confirmed is True
    assert result.response_text == (
        "포장 주문입니다. 총 결제 금액은 4,700원입니다. 결제를 진행해 주세요."
    )
    assert tts.calls == [(
        "포장 주문입니다. 총 결제 금액은 사천칠백원입니다. 결제를 진행해 주세요.",
        0,
    )]


def test_multi_turn_fulfillment_and_add_keep_their_existing_tts() -> None:
    tts = MockTTS()
    service = MalloService(
        nlu=FallbackNLU([]),
        agent=ConversationAgent(load_menu()),
        tts=tts,
    )

    fulfillment = service.handle_text("포장해주세요", Cart())
    added = service.handle_text("아이스 아메리카노 한 잔", fulfillment.cart)

    assert fulfillment.success is True
    assert added.success is True
    assert tts.calls == [
        ("포장으로 설정했습니다.", 0),
        ("아이스 아메리카노 한 잔을 담았습니다.", 0),
    ]


def test_payment_method_tts_remains_after_one_shot_order() -> None:
    tts = MockTTS()
    service = MalloService(
        nlu=FallbackNLU([]),
        agent=ConversationAgent(load_menu()),
        tts=tts,
    )

    ordered = service.handle_text("아이스 아메리카노 한 잔 포장해주세요", Cart())
    paid = service.handle_text("카드로 결제할게요", ordered.cart)

    assert paid.success is True
    assert tts.calls[-1] == ("카드 결제를 선택했습니다. 주문이 완료되었습니다.", 0)


@pytest.mark.parametrize(
    ("text", "fulfillment", "item", "quantity", "temperature"),
    [
        ("아이스 아메리카노 한 잔 포장해주세요", FulfillmentType.TAKEOUT, "americano", 1, Temperature.ICED),
        ("아이스 아메리카노 하나 포장해 주세요", FulfillmentType.TAKEOUT, "americano", 1, Temperature.ICED),
        ("아이스 아메리카노 하나 매장으로 할게요", FulfillmentType.DINE_IN, "americano", 1, Temperature.ICED),
        ("차가운 카페라떼 하나 포장해주세요", FulfillmentType.TAKEOUT, "cafe_latte", 1, Temperature.ICED),
        ("따뜻한 카페라트에 하나 포장해주세요", FulfillmentType.TAKEOUT, "cafe_latte", 1, Temperature.HOT),
        ("뜨거운 카페라떼 두 잔 매장에서 먹을게요", FulfillmentType.DINE_IN, "cafe_latte", 2, Temperature.HOT),
        ("아이스 아메리카노 하나 먹고갈게요", FulfillmentType.DINE_IN, "americano", 1, Temperature.ICED),
        ("뜨거운 카페라떼 두 잔 여기서 먹을게요", FulfillmentType.DINE_IN, "cafe_latte", 2, Temperature.HOT),
        ("아이스 아메리카노 하나 들고갈게요", FulfillmentType.TAKEOUT, "americano", 1, Temperature.ICED),
        ("차가운 카페라떼 하나 가져갈게요", FulfillmentType.TAKEOUT, "cafe_latte", 1, Temperature.ICED),
        ("아이스 아메리카노 하나 포장해갈게요", FulfillmentType.TAKEOUT, "americano", 1, Temperature.ICED),
    ],
)
def test_complete_embedded_fulfillment_orders_confirm_in_one_batch(
    text: str,
    fulfillment: FulfillmentType,
    item: str,
    quantity: int,
    temperature: Temperature,
) -> None:
    result = build_mock_service().handle_text(text, Cart())

    assert result.success is True
    assert result.cart.fulfillment_type is fulfillment
    assert result.cart.confirmed is True
    assert result.cart.items == [CartItem(item, quantity, temperature, result.cart.items[0].unit_price)]


@pytest.mark.parametrize(
    ("text", "fulfillment"),
    [
        ("포장해주세요", FulfillmentType.TAKEOUT),
        ("포장할게요", FulfillmentType.TAKEOUT),
        ("포장하고 싶어", FulfillmentType.TAKEOUT),
        ("포장으로 할게요", FulfillmentType.TAKEOUT),
        ("포장해 갈게요", FulfillmentType.TAKEOUT),
        ("매장으로 할게요", FulfillmentType.DINE_IN),
        ("매장에서 먹고 갈게요", FulfillmentType.DINE_IN),
        ("여기서 먹을게요", FulfillmentType.DINE_IN),
    ],
)
def test_standalone_fulfillment_phrases_keep_existing_selection_behavior(
    text: str,
    fulfillment: FulfillmentType,
) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert [command.intent for command in result] == [Intent.SET_FULFILLMENT]
    assert result[0].fulfillment_type is fulfillment


def test_standalone_eat_phrase_is_not_a_dine_in_alias() -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.QUERY_MENU)])

    result = RuleFirstNLU(fallback).parse("먹을게요", Cart())

    assert result[0].intent is Intent.QUERY_MENU
    assert fallback.calls == ["먹을게요"]


@pytest.mark.parametrize(
    "text",
    [
        "아이스 아메리카노 하나 먹고갈게요",
        "뜨거운 카페라떼 두 잔 여기서 먹을게요",
        "아이스 아메리카노 하나 들고갈게요",
        "차가운 카페라떼 하나 가져갈게요",
    ],
)
def test_existing_cart_natural_fulfillment_order_adds_without_auto_confirmation(text: str) -> None:
    cart = Cart(
        [CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.DINE_IN,
    )

    service = build_mock_service()
    result = service.handle_text(text, cart)

    assert result.success is True
    assert [command.intent for command in service.last_order_commands] == [Intent.ADD_ITEM]
    assert result.cart.fulfillment_type is FulfillmentType.DINE_IN
    assert result.cart.confirmed is False


@pytest.mark.parametrize(
    ("text", "fulfillment", "menu_id", "temperature", "quantity"),
    [
        ("아이스 아메리카노 하나 포장하고 싶어", "takeout", "americano", Temperature.ICED, 1),
        ("따뜻한 카페라떼 두 잔 매장에서 먹을게요", "dine_in", "cafe_latte", Temperature.HOT, 2),
    ],
)
def test_empty_cart_complete_menu_order_executes_and_confirms(
    text: str, fulfillment: str, menu_id: str, temperature: Temperature, quantity: int,
) -> None:
    result = build_mock_service().handle_text(text, Cart())

    assert result.success is True
    assert result.cart.fulfillment_type.value == fulfillment
    assert result.cart.items[0].menu_id == menu_id
    assert result.cart.items[0].temperature is temperature
    assert result.cart.items[0].quantity == quantity
    assert result.cart.confirmed is True


@pytest.mark.parametrize(
    ("text", "error_code"),
    [
        ("카페라떼 두 잔 포장할게요", OrderCommandErrorCode.MISSING_FIELD),
        ("아이스 아메리카노 포장할게요", OrderCommandErrorCode.MISSING_FIELD),
    ],
)
def test_incomplete_menu_order_with_fulfillment_keeps_pending_clarification(
    text: str, error_code: OrderCommandErrorCode,
) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert isinstance(result, OrderCommandError)
    assert result.code is error_code


def test_existing_cart_complete_menu_order_adds_only_without_confirmation() -> None:
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)], fulfillment_type=FulfillmentType.DINE_IN)

    result = RuleFirstNLU(FallbackNLU([])).parse("따뜻한 카페라떼 두 잔 포장할게요", cart)

    assert [command.intent for command in result] == [Intent.ADD_ITEM]
    assert result[0].target_item_id == "cafe_latte"
    assert result[0].temperature is Temperature.HOT


@pytest.mark.parametrize(
    ("text", "fulfillment"),
    [
        ("포장", "takeout"),
        ("포장할게요", "takeout"),
        ("매장", "dine_in"),
        ("매장에서", "dine_in"),
        ("매장에서 이용", "dine_in"),
        ("매장이용", "dine_in"),
        ("매장에서 주문", "dine_in"),
        ("매장에서 먹을게요", "dine_in"),
    ],
)
def test_explicit_fulfillment_bypasses_fallback(text: str, fulfillment: str) -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.UNDO)])
    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert isinstance(result, list)
    assert result[0].intent is Intent.SET_FULFILLMENT
    assert result[0].fulfillment_type.value == fulfillment
    assert fallback.calls == []


def test_standalone_eat_and_go_phrase_selects_dine_in() -> None:
    fallback = FallbackNLU([])

    result = RuleFirstNLU(fallback).parse("먹고 갈게요", Cart())

    assert result[0].intent is Intent.SET_FULFILLMENT
    assert result[0].fulfillment_type is FulfillmentType.DINE_IN
    assert fallback.calls == []


@pytest.mark.parametrize(
    "text",
    ["주문 확인할게", "주문 확인할게요", "주문 확정할게", "이대로 주문할게"],
)
def test_confirmation_phrases_bypass_fallback_and_guard(text: str) -> None:
    fallback = FallbackNLU([])

    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert result[0].intent is Intent.CONFIRM_ORDER
    assert fallback.calls == []


@pytest.mark.parametrize("text", ["확인할게", "확정할게", "이대로"])
def test_standalone_confirmation_phrase_cannot_execute_qwen_confirmation(text: str) -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.CONFIRM_ORDER)])

    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE
    assert fallback.calls == [text]


@pytest.mark.parametrize(
    ("text", "method"),
    [
        ("카드", "card"),
        ("카드를", "card"),
        ("카드로", "card"),
        ("카드로 할게", "card"),
        ("카드로 결제할게", "card"),
        ("카드로 결제할게요", "card"),
        ("카드 결제할게요", "card"),
        ("카드를 결정할게요", "card"),
        ("카드를 결제할게요", "card"),
        ("삼성페이로 결제할게", "samsung"),
        ("삼성페이로 결제할게요", "samsung"),
        ("카카오페이", "kakao"),
        ("카카오페이로 결제할게요", "kakao"),
        ("현금", "cash"),
        ("현금으로 할게", "cash"),
        ("현금으로 결제할게요", "cash"),
        ("현금 결정할게요", "cash"),
    ],
)
def test_confirmed_cart_payment_method_bypasses_fallback(text: str, method: str) -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.QUERY_MENU)])
    confirmed_cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.TAKEOUT,
        confirmed=True,
    )

    result = RuleFirstNLU(fallback).parse(text, confirmed_cart)

    assert isinstance(result, list)
    assert result[0].intent is Intent.SELECT_PAYMENT_METHOD
    assert result[0].target_item_id == method
    assert fallback.calls == []


def test_confirmed_cart_generic_payment_phrase_cannot_confirm_order() -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.CONFIRM_ORDER)])
    confirmed_cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.TAKEOUT,
        confirmed=True,
    )

    result = RuleFirstNLU(fallback).parse("결제할게요", confirmed_cart)

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE
    assert result.message == "결제수단을 다시 말씀해 주세요."
    assert fallback.calls == ["결제할게요"]


@pytest.mark.parametrize(
    "text",
    ["결제할게", "결제할게요", "결제 진행할게", "결제 진행할게요"],
)
def test_explicit_payment_progress_phrase_confirms_without_qwen_fallback(text: str) -> None:
    fallback = FallbackNLU([])

    result = RuleFirstNLU(fallback).parse(
        text,
        Cart(
            items=[CartItem("americano", 1, Temperature.ICED, 4700)],
            fulfillment_type=FulfillmentType.DINE_IN,
        ),
    )

    assert isinstance(result, list)
    assert [command.intent for command in result] == [Intent.CONFIRM_ORDER]
    assert fallback.calls == []


@pytest.mark.parametrize("text", ["결제", "결제 방법", "결제 방법 뭐 있어", "결제 어떻게 해"])
def test_bare_or_question_payment_phrase_never_bypasses_confirm_guard(text: str) -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.CONFIRM_ORDER)])

    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE
    assert fallback.calls == [text]


def test_confirmed_cart_guard_failure_uses_payment_method_retry_message() -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.CONFIRM_ORDER)])
    confirmed_cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.TAKEOUT,
        confirmed=True,
    )

    result = RuleFirstNLU(fallback).parse("결정할게요", confirmed_cart)

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE
    assert result.message == "결제수단을 다시 말씀해 주세요."


def test_confirmed_cart_payment_failure_surfaces_payment_retry_message() -> None:
    service = MalloService(
        nlu=FallbackNLU([OrderCommand.create(Intent.CONFIRM_ORDER)]),
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
    )
    confirmed_cart = Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.TAKEOUT,
        confirmed=True,
    )

    result = service.handle_text("결정할게요", confirmed_cart)

    assert result.success is False
    assert result.response_text == "결제수단을 다시 말씀해 주세요."


@pytest.mark.parametrize("category_id", ["coffee", "non_coffee", "tea", "dessert"])
def test_fallback_single_category_tag_is_canonicalized_to_category_query(category_id: str) -> None:
    fallback = FallbackNLU([
        OrderCommand.create(Intent.QUERY_MENU, query_tags=(category_id,))
    ])

    result = RuleFirstNLU(fallback).parse("fallback query", Cart())

    assert isinstance(result, list)
    assert result[0].intent is Intent.QUERY_MENU
    assert result[0].category_id == category_id
    assert result[0].query_tags is None
    assert fallback.calls == ["fallback query"]


def test_fallback_non_category_or_multi_tag_query_remains_unchanged() -> None:
    for tags in (("sweetness_low",), ("tea", "sweetness_low")):
        fallback = FallbackNLU([OrderCommand.create(Intent.QUERY_MENU, query_tags=tags)])

        result = RuleFirstNLU(fallback).parse("fallback query", Cart())

        assert isinstance(result, list)
        assert result[0].category_id is None
        assert result[0].query_tags == tags


@pytest.mark.parametrize(
    ("text", "menu_id", "temperature"),
    [
        ("아이스 아메리카노 하나 주세요", "americano", "iced"),
        ("따뜻한 카페라떼 한잔 주세요", "cafe_latte", "hot"),
    ],
)
def test_basic_menu_orders_use_catalog_fast_path(text: str, menu_id: str, temperature: str | None) -> None:
    fallback = FallbackNLU([])
    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert isinstance(result, list)
    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].target_item_id == menu_id
    assert result[0].quantity == 1
    assert (result[0].temperature.value if result[0].temperature else None) == temperature
    assert fallback.calls == []


def test_complex_utterance_uses_existing_qwen_fallback() -> None:
    expected = [OrderCommand.create(Intent.QUERY_CART)]
    fallback = FallbackNLU(expected)
    nlu = RuleFirstNLU(fallback)
    result = nlu.parse("현재 주문 알려 주세요", Cart())

    assert result == expected
    assert fallback.calls == ["현재 주문 알려 주세요"]
    assert nlu.last_source == "qwen_fallback"


def test_garbled_utterance_cannot_execute_qwen_undo_without_evidence() -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.UNDO)])
    nlu = RuleFirstNLU(fallback)
    result = nlu.parse("핸메이크 뒷배죠", Cart())

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE
    assert nlu.last_source == "guard_blocked"


def test_garbled_utterance_cannot_execute_qwen_slowdown_without_speed_words() -> None:
    nlu = RuleFirstNLU(FallbackNLU([OrderCommand.create(Intent.REQUEST_SLOWER)]))

    result = nlu.parse("보장", Cart())

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE
    assert nlu.last_source == "guard_blocked"


@pytest.mark.parametrize("text", ["디", "디카"])
def test_short_stt_fragment_cannot_execute_qwen_decaf_or_payment(text: str) -> None:
    fallback = FallbackNLU([
        OrderCommand.create(
            Intent.UPDATE_OPTION,
            target_item_id="americano",
            options=BeverageOptions(caffeine=CaffeineOption.DECAF),
        )
    ])
    nlu = RuleFirstNLU(fallback)

    decaf = nlu.parse(text, Cart([CartItem("americano", 1, Temperature.ICED, 4700)]))

    assert isinstance(decaf, OrderCommandError)
    assert decaf.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE
    assert nlu.last_source == "guard_blocked_decaf"

    payment = RuleFirstNLU(FallbackNLU([
        OrderCommand.create(Intent.SELECT_PAYMENT_METHOD, target_item_id="card")
    ])).parse(text, Cart(
        items=[CartItem("americano", 1, Temperature.ICED, 4700)],
        fulfillment_type=FulfillmentType.TAKEOUT,
        confirmed=True,
    ))
    assert isinstance(payment, OrderCommandError)
    assert payment.code is OrderCommandErrorCode.UNSUPPORTED_UTTERANCE


@pytest.mark.parametrize(
    ("text", "menu_id", "temperature"),
    [
        ("자몽에이드 하나 추가", "grapefruit_ade", None),
        ("바닐라 라떼 아이스로 하나 주세요", "vanilla_latte", "iced"),
    ],
)
def test_explicit_new_menu_quantity_wins_over_fallback_option_update(
    text: str, menu_id: str, temperature: str | None,
) -> None:
    fallback = FallbackNLU([
        OrderCommand.create(Intent.UPDATE_OPTION, target_item_id=menu_id, temperature=Temperature.ICED)
    ])

    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert isinstance(result, list)
    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].target_item_id == menu_id
    assert result[0].quantity == 1
    assert (result[0].temperature.value if result[0].temperature else None) == temperature
    assert fallback.calls == []


@pytest.mark.parametrize(
    "text",
    ["처음부터 다시할래", "처음부터 할래", "다시 처음부터", "취소하고 처음부터 다시 하고 싶어"],
)
def test_reset_order_bypasses_undo_fallback(text: str) -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.UNDO)])

    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert result[0].intent is Intent.RESET_ORDER
    assert fallback.calls == []


def test_qwen_temperature_guess_on_dual_temp_menu_is_discarded_for_pending_clarification() -> None:
    # Qwen guessed temperature="hot" for a 2-temperature menu when user did not specify temperature
    fallback = FallbackNLU([
        OrderCommand.create(Intent.ADD_ITEM, target_item_id="cafe_latte", quantity=1, temperature=Temperature.HOT)
    ])
    nlu = RuleFirstNLU(fallback)
    cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)])

    result = nlu.parse("카페라타 한잔 주세요", cart)

    assert isinstance(result, OrderCommandError)
    assert result.code is OrderCommandErrorCode.MISSING_FIELD
    assert result.field == "temperature"
    assert result.message == "따뜻하게 드릴까요, 아이스로 드릴까요?"
    assert nlu.last_source == "rule_pending_temperature"


@pytest.mark.parametrize(
    ("reply", "expected_temp"),
    [
        ("아이스", Temperature.ICED),
        ("아이스로", Temperature.ICED),
        ("아이스요", Temperature.ICED),
        ("따뜻하게", Temperature.HOT),
        ("따뜻하게요", Temperature.HOT),
        ("따뜻한 걸로", Temperature.HOT),
        ("아이소", Temperature.ICED),
        ("아이시", Temperature.ICED),
        ("아이수", Temperature.ICED),
    ],
)
def test_pending_temperature_reply_expressions(reply: str, expected_temp: Temperature) -> None:
    service = build_mock_service()
    prompt = service.handle_text("카페라떼 한잔 주세요", Cart())
    assert prompt.error_code is not None

    completed = service.handle_text(reply, prompt.cart)
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 1, expected_temp, 5200)]


def test_temperature_dialect_in_order_context() -> None:
    service = build_mock_service()
    result = service.handle_text("카페라떼 아이소 한 잔 주세요", Cart())

    assert result.success is True
    assert result.cart.items == [CartItem("cafe_latte", 1, Temperature.ICED, 5200)]


@pytest.mark.parametrize(
    ("phrase", "delta"),
    [
        ("두 잔 더", 2),
        ("한 잔 더", 1),
        ("두 개 더", 2),
        ("2잔 추가", 2),
    ],
)
def test_quantity_delta_add_deterministic(phrase: str, delta: int) -> None:
    service = build_mock_service()
    service.handle_text("아이스 카페라떼 두 잔 주세요", Cart())

    cart = Cart([CartItem("cafe_latte", 2, Temperature.ICED, 5200)])
    result = service.handle_text(phrase, cart)

    assert result.success is True
    assert result.cart.items[0].quantity == 2 + delta


def test_quantity_delta_add_respects_max_limit_5() -> None:
    service = build_mock_service()
    cart = Cart([CartItem("cafe_latte", 4, Temperature.ICED, 5200)])

    result = service.handle_text("두 잔 더", cart)

    assert result.success is False
    assert result.error_code is not None
    assert "최대 5개" in result.response_text
    assert cart.items[0].quantity == 4


def test_quantity_delta_add_with_multiple_cart_lines_requires_menu_name() -> None:
    service = build_mock_service()
    cart = Cart([
        CartItem("americano", 1, Temperature.ICED, 4700),
        CartItem("cafe_latte", 1, Temperature.HOT, 5200),
    ])

    result = service.handle_text("두 잔 더", cart)

    assert result.success is False
    assert result.error_code is not None
    assert result.error_code.value == "AMBIGUOUS_TARGET"
    assert result.cart == cart


def test_menu_cancel_becomes_targeted_remove_and_keeps_temperature_ambiguity() -> None:
    fallback = FallbackNLU([OrderCommand.create(Intent.CANCEL)])
    nlu = RuleFirstNLU(fallback)
    cart = Cart([
        CartItem("cafe_latte", 1, Temperature.HOT, 5200),
        CartItem("cafe_latte", 1, Temperature.ICED, 5200),
    ])

    commands = nlu.parse("카페라떼 취소해줘", cart)

    assert isinstance(commands, list)
    assert commands[0].intent is Intent.REMOVE_ITEM
    assert commands[0].target_item_id == "cafe_latte"
    assert commands[0].temperature is None
    assert fallback.calls == []

    result = MalloService(
        nlu=FallbackNLU([]), agent=ConversationAgent(load_menu()), tts=MockTTS(),
    ).handle_text("카페라떼 취소해줘", cart)
    assert result.success is False
    assert result.error_code.value == "AMBIGUOUS_TARGET"
    assert result.cart == cart


def test_explicit_whole_cart_cancel_still_executes() -> None:
    service = build_mock_service()
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])

    result = service.handle_text("장바구니 전부 취소해줘", cart)

    assert result.success is True
    assert result.cart.items == []


@pytest.mark.parametrize(
    ("text", "temperature"),
    [
        ("아이스 아메리카노 한 잔", Temperature.ICED),
        ("따뜻한 아메리카노 한 잔", Temperature.HOT),
    ],
)
def test_voice_one_shot_americano_preserves_explicit_temperature(
    text: str, temperature: Temperature,
) -> None:
    result = build_mock_service().interpret_voice_transcript(text, Cart())

    assert result.success is True
    assert result.error_code is None
    assert result.cart.items == [CartItem("americano", 1, temperature, 4700)]


@pytest.mark.parametrize("phrase", ["한 잔 주소", "한 잔 도"])
def test_quantity_dialect_in_pending_context(phrase: str) -> None:
    service = build_mock_service()
    prompt = service.handle_text("카페라떼", Cart())
    assert prompt.error_code is not None

    temp_prompt = service.handle_text(phrase, prompt.cart)
    assert temp_prompt.error_code is not None
    assert "따뜻하게 드릴까요" in temp_prompt.response_text

    completed = service.handle_text("아이스로", temp_prompt.cart)
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 1, Temperature.ICED, 5200)]


@pytest.mark.parametrize("phrase", ["아이스 아메리카노 한 잔 주소", "아이스 아메리카노 한 잔 도"])
def test_quantity_dialect_in_menu_order_context(phrase: str) -> None:
    service = build_mock_service()
    result = service.handle_text(phrase, Cart())

    assert result.success is True
    assert result.cart.items == [CartItem("americano", 1, Temperature.ICED, 4700)]


@pytest.mark.parametrize("phrase", ["장바구니 비도", "장바구니 비워", "전부 취소해줘"])
def test_clear_cart_dialect_cancels_cart_without_resetting_session(phrase: str) -> None:
    service = build_mock_service()
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])

    result = service.handle_text(phrase, cart)

    assert result.success is True
    assert result.cart.items == []
    assert "주문이 모두 취소되었습니다" in result.response_text


def test_clear_all_items_phrase_is_not_interpreted_as_single_item_remove() -> None:
    service = build_mock_service()
    cart = Cart([
        CartItem("americano", 1, Temperature.ICED, 4700),
        CartItem("cafe_latte", 1, Temperature.HOT, 5200),
    ])

    result = service.handle_text("장바구니에 있는 거 다 빼줘", cart)

    assert result.success is True
    assert result.cart.items == []


@pytest.mark.parametrize("phrase", ["처음부터 다시", "다시 처음부터", "처음부터 다시할래"])
def test_reset_order_resets_entire_session(phrase: str) -> None:
    service = build_mock_service()
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)], fulfillment_type=FulfillmentType.TAKEOUT)

    result = service.handle_text(phrase, cart)

    assert result.success is True
    assert result.cart.items == []
    assert "주문을 처음부터 다시 시작합니다" in result.response_text


@pytest.mark.parametrize(
    "phrase",
    ["도전", "투자", "투은잔", "투자안", "도전이요", "투자 주세요"],
)
def test_garbled_two_quantity_recovery_in_pending_context(phrase: str) -> None:
    service = build_mock_service()
    prompt = service.handle_text("카페라떼", Cart())
    assert prompt.error_code is not None

    temp_prompt = service.handle_text(phrase, prompt.cart)
    assert temp_prompt.error_code is not None
    assert "따뜻하게 드릴까요" in temp_prompt.response_text

    completed = service.handle_text("아이스", temp_prompt.cart)
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 2, Temperature.ICED, 5200)]


@pytest.mark.parametrize(
    "phrase",
    ["카페라떼 도전 주세요", "카페라떼 투자 주세요", "아이스 아메리카노 투은잔 주세요"],
)
def test_garbled_two_quantity_recovery_in_menu_order_context(phrase: str) -> None:
    service = build_mock_service()
    if "아메리카노" in phrase:
        result = service.handle_text(phrase, Cart())
        assert result.success is True
        assert result.cart.items == [CartItem("americano", 2, Temperature.ICED, 4700)]
    else:
        prompt = service.handle_text(phrase, Cart())
        assert prompt.error_code is not None
        assert "따뜻하게 드릴까요" in prompt.response_text
        assert prompt.cart.items == []
        completed = service.handle_text("아이스", prompt.cart)
        assert completed.success is True
        assert completed.cart.items == [CartItem("cafe_latte", 2, Temperature.ICED, 5200)]


@pytest.mark.parametrize(
    "text",
    [
        "포장을 할게요", "아이스 아메리카노 하나 포장을 할게요",
        "포장해 갈게요", "포장으로 할게요", "포장해서 갈게요", "포장으로",
    ],
)
def test_fulfillment_takeout_with_particle(text: str) -> None:
    nlu = RuleFirstNLU(FallbackNLU([]))
    result = nlu.parse(text, Cart())

    assert isinstance(result, list)
    fulfillment = next((c for c in result if c.intent is Intent.SET_FULFILLMENT), None)
    assert fulfillment is not None
    assert fulfillment.fulfillment_type is FulfillmentType.TAKEOUT


def test_requirement_a_cafe_latte_warm_with_polite_ending() -> None:
    service = build_mock_service()
    prompt = service.handle_text("카페라떼 한잔 주세요", Cart())
    assert prompt.error_code is not None
    assert "따뜻하게 드릴까요" in prompt.response_text
    assert prompt.cart.items == []

    completed = service.handle_text("따뜻하게 주세요", prompt.cart)
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 1, Temperature.HOT, 5200)]


def test_requirement_b_cafe_latte_iced_with_polite_ending() -> None:
    service = build_mock_service()
    prompt = service.handle_text("카페라떼 한잔 주세요", Cart())
    assert prompt.error_code is not None
    assert "따뜻하게 드릴까요" in prompt.response_text
    assert prompt.cart.items == []

    completed = service.handle_text("아이스로 주세요", prompt.cart)
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 1, Temperature.ICED, 5200)]


@pytest.mark.parametrize(
    "phrase",
    [
        "어..... 아메리카노 주세요",
        "음..... 아메리카노 주세요",
        "어... 아메리카노 주세요",
        "음... 아메리카노 주세요",
        "어 아메리카노 한잔 주세요",
    ],
)
def test_requirement_d_leading_fillers_normalized_to_menu_order(phrase: str) -> None:
    service = build_mock_service()
    result = service.handle_text(phrase, Cart())
    if "한잔" in phrase:
        assert result.error_code is not None
        assert "따뜻하게 드릴까요" in result.response_text
    else:
        assert result.error_code is not None
        assert "아메리카노의 수량을 말씀해 주세요" in result.response_text


@pytest.mark.parametrize(
    "reply",
    [
        "차갑게",
        "차갑게 해줘",
        "차갑게 주세요",
        "차가운 걸로",
        "차가운 걸로 주세요",
        "시원하게",
        "시원하게 해줘",
        "시원하게 주세요",
        "시원한 걸로",
        "시원한 걸로 주세요",
    ],
)
def test_pending_temperature_cold_and_cool_variations(reply: str) -> None:
    service = build_mock_service()
    prompt = service.handle_text("카페라떼 한잔 주세요", Cart())
    assert prompt.error_code is not None
    assert prompt.cart.items == []

    completed = service.handle_text(reply, prompt.cart)
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 1, Temperature.ICED, 5200)]


@pytest.mark.parametrize(
    "phrase",
    [
        "카페라떼 차갑게 한 잔 주세요",
        "카페라떼 차갑게 한 잔 해줘",
        "차갑게 카페라떼 한 잔 주세요",
        "카페라떼 시원하게 한 잔 주세요",
        "카페라떼 시원한 걸로 한 잔 주세요",
        "시원한 카페라떼 한 잔 주세요",
    ],
)
def test_menu_order_cold_and_cool_variations(phrase: str) -> None:
    service = build_mock_service()
    result = service.handle_text(phrase, Cart())
    assert result.success is True
    assert result.cart.items == [CartItem("cafe_latte", 1, Temperature.ICED, 5200)]


@pytest.mark.parametrize(
    "reply",
    [
        "뜨겁게",
        "뜨겁게 주세요",
        "뜨거운 걸로",
        "뜨거운 걸로 주세요",
        "뜨거운 거로",
        "뜨거운 거 주세요",
    ],
)
def test_pending_temperature_hot_variations(reply: str) -> None:
    service = build_mock_service()
    prompt = service.handle_text("카페라떼 한잔 주세요", Cart())
    assert prompt.error_code is not None
    assert prompt.cart.items == []

    completed = service.handle_text(reply, prompt.cart)
    assert completed.success is True
    assert completed.cart.items == [CartItem("cafe_latte", 1, Temperature.HOT, 5200)]


@pytest.mark.parametrize(
    "text",
    [
        "매장에서 먹을게", "매장에서 먹을래요", "매장에서 먹고갈래",
        "여기서 먹을게", "여기서 먹고갈래", "매장 이용할게",
        "매장 이용할래", "안에서 먹을게", "안에서 먹을래",
    ],
)
def test_dine_in_expression_family_requires_location_or_eat_and_go(text: str) -> None:
    fallback = FallbackNLU([])

    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert result[0].intent is Intent.SET_FULFILLMENT
    assert result[0].fulfillment_type is FulfillmentType.DINE_IN
    assert fallback.calls == []


@pytest.mark.parametrize("text", ["먹을게", "먹을래", "먹을래요"])
def test_bare_eat_expression_stays_ambiguous(text: str) -> None:
    fallback = FallbackNLU([])

    RuleFirstNLU(fallback).parse(text, Cart())

    assert fallback.calls == [text]


@pytest.mark.parametrize(
    "text",
    [
        "포장할래", "포장해주세요", "포장해줘", "가져갈게", "가져갈래",
        "들고갈게", "들고갈래", "테이크아웃할게", "테이크아웃할래",
        "가지고 갈게", "가지고 갈래",
    ],
)
def test_takeout_expression_family_uses_semantic_pattern(text: str) -> None:
    fallback = FallbackNLU([])

    result = RuleFirstNLU(fallback).parse(text, Cart())

    assert result[0].intent is Intent.SET_FULFILLMENT
    assert result[0].fulfillment_type is FulfillmentType.TAKEOUT
    assert fallback.calls == []


@pytest.mark.parametrize(
    ("reply", "temperature"),
    [
        ("아이스?", Temperature.ICED), ("아이소로", Temperature.ICED),
        ("아이시 걸로", Temperature.ICED), ("아이수 해주세요", Temperature.ICED),
        ("에이스요", Temperature.ICED), ("시원한 걸로", Temperature.ICED),
        ("따뜻한 걸로", Temperature.HOT), ("뜨겁게 해줘", Temperature.HOT),
        ("뜨거운 걸로요", Temperature.HOT),
    ],
)
def test_temperature_reply_family_normalizes_polite_endings(
    reply: str, temperature: Temperature,
) -> None:
    nlu = RuleFirstNLU(FallbackNLU([]))
    nlu.parse("카페라떼 한 잔", Cart())

    result = nlu.parse(reply, Cart())

    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].temperature is temperature


@pytest.mark.parametrize(
    ("quantity_text", "quantity"),
    [
        ("한", 1), ("한잔만", 1), ("1잔", 1), ("두", 2), ("두잔으로", 2),
        ("두잔 할게요", 2), ("3잔", 3), ("네 개", 4), ("다섯잔 주세요", 5),
        ("한 잔 한 잔", 1),
    ],
)
def test_quantity_expression_family_is_exact_after_safe_terminal_normalization(
    quantity_text: str, quantity: int,
) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(
        f"아이스 아메리카노 {quantity_text}", Cart(),
    )

    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].quantity == quantity
    assert result[0].temperature is Temperature.ICED


@pytest.mark.parametrize(
    ("text", "category_id"),
    [
        ("커피 중에 뭐가 있어?", "coffee"), ("논커피 메뉴 보여줘", "non_coffee"),
        ("넌커피는 어떤 거 있어", "non_coffee"), ("차 종류 보여줘", "tea"),
        ("티에는 뭐 있어?", "tea"), ("디저트 알려줘", "dessert"),
    ],
)
def test_category_query_expression_family_ignores_particles_and_punctuation(
    text: str, category_id: str,
) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert result[0].intent is Intent.QUERY_MENU
    assert result[0].category_id == category_id


@pytest.mark.parametrize(
    "text",
    ["장바구니 보여줘", "장바구니 볼래", "장바구니 확인할게", "뭐 담았어", "뭐 들어있어", "현재 주문 보여줘", "주문한 거 보여줘"],
)
def test_cart_query_expression_family_does_not_confirm_order(text: str) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert result[0].intent is Intent.QUERY_CART


@pytest.mark.parametrize(
    "text",
    ["장바구니 다 빼줘", "전부 빼줘", "다 비워줘", "싹 비워줘", "담은 거 다 빼줘", "주문한 거 다 취소해줘"],
)
def test_clear_cart_expression_family_requires_explicit_whole_scope(text: str) -> None:
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])

    result = build_mock_service().handle_text(text, cart)

    assert result.success is True
    assert result.cart.items == []


@pytest.mark.parametrize(
    "text",
    ["주문 확인할게", "주문 확정해주세요", "이대로 주문할게", "이대로 할게", "주문 진행해줘"],
)
def test_confirmation_expression_family_requires_order_context(text: str) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert result[0].intent is Intent.CONFIRM_ORDER


@pytest.mark.parametrize("text", ["방금 거 취소", "되돌려줘", "원래대로"])
def test_undo_expression_family_stays_distinct_from_cancel(text: str) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert result[0].intent is Intent.UNDO


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("다시 말해줘", Intent.REQUEST_REPEAT), ("다시 들려줘", Intent.REQUEST_REPEAT),
        ("한 번 더", Intent.REQUEST_REPEAT), ("좀 천천히", Intent.REQUEST_SLOWER),
        ("더 천천히", Intent.REQUEST_SLOWER), ("느리게", Intent.REQUEST_SLOWER),
    ],
)
def test_repeat_and_speed_expression_families(text: str, intent: Intent) -> None:
    result = RuleFirstNLU(FallbackNLU([])).parse(text, Cart())

    assert result[0].intent is intent


def test_menu_and_temperature_correction_preserve_safe_order_slots() -> None:
    menu = RuleFirstNLU(FallbackNLU([])).parse("아메리카노 한 잔 말고 카페라떼", Cart())
    temperature = RuleFirstNLU(FallbackNLU([])).parse(
        "아이스 아메리카노 한 잔 말고 따뜻한 걸로", Cart(),
    )

    assert isinstance(menu, OrderCommandError)
    assert menu.field == "temperature"
    assert isinstance(temperature, list)
    assert temperature[0].target_item_id == "americano"
    assert temperature[0].temperature is Temperature.HOT
