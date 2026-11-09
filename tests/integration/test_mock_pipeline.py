from __future__ import annotations

from dataclasses import dataclass

import pytest

from adapters.nlu.mock_nlu import MockNLU
from adapters.tts.mock_tts import MockTTS
from app.service import MalloService
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import (
    BeverageOptions,
    CaffeineOption,
    Cart,
    CartItem,
    ErrorCode,
    IceAmount,
    OrderCommand,
    OrderCommandError,
    OrderCommandErrorCode,
    OrderResult,
    Temperature,
)
from utils.schema_validation import validate_order_commands


def build_service(*, tts: MockTTS | None = None) -> tuple[MalloService, MockTTS]:
    mock_tts = tts or MockTTS()
    service = MalloService(
        nlu=MockNLU(),
        agent=ConversationAgent(load_menu()),
        tts=mock_tts,
    )
    return service, mock_tts


def test_normal_order_calls_tts_once() -> None:
    service, tts = build_service()

    result = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())

    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700)
    ]
    assert result.cart.total_price == 9400
    assert tts.calls == [("아이스 아메리카노 두 잔을 담았습니다.", 0)]


@pytest.mark.parametrize(
    ("text", "menu_id", "temperature"),
    [
        ("아아 두 잔 주세요", "americano", Temperature.ICED),
        ("뜨아 두 잔 주세요", "americano", Temperature.HOT),
        ("아라 두 잔 주세요", "cafe_latte", Temperature.ICED),
        ("뜨라 두 잔 주세요", "cafe_latte", Temperature.HOT),
        ("아바라 두 잔 주세요", "vanilla_latte", Temperature.ICED),
        ("뜨바라 두 잔 주세요", "vanilla_latte", Temperature.HOT),
    ],
)
def test_approved_menu_alias_adds_official_menu(
    text: str,
    menu_id: str,
    temperature: Temperature,
) -> None:
    service, tts = build_service()

    result = service.handle_text(text, Cart())

    assert result.success is True
    assert result.cart.items[0].menu_id == menu_id
    assert result.cart.items[0].temperature is temperature
    assert result.cart.items[0].quantity == 2
    assert tts.calls == [(result.response_text, 0)]


@pytest.mark.parametrize("text", ["아초 두 잔 주세요", "아돌라 두 잔 주세요"])
def test_alias_for_missing_menu_is_not_supported(text: str) -> None:
    service, _ = build_service()

    result = service.handle_text(text, Cart())

    assert result.error_code is ErrorCode.UNSUPPORTED_UTTERANCE


def test_mixed_intent_error_uses_canonical_guidance() -> None:
    class MixedIntentNLU:
        def parse(self, text: str, current_order_state: Cart) -> OrderCommandError:
            del text, current_order_state
            return OrderCommandError(
                code=OrderCommandErrorCode.MIXED_INTENT,
                message="이전 안내 문구",
            )

    tts = MockTTS()
    service = MalloService(
        nlu=MixedIntentNLU(),
        agent=ConversationAgent(load_menu()),
        tts=tts,
    )

    result = service.handle_text("아메리카노를 담고 라떼는 빼 주세요", Cart())

    assert result.error_code is ErrorCode.MIXED_INTENT
    assert result.response_text == (
        "사용자의 주문을 이해하지 못했습니다. "
        "한 번에 하나씩 주문해 주시면 감사하겠습니다."
    )
    assert result.error_response is not None
    assert result.error_response.user_message == result.response_text


def test_multiple_menu_utterance_is_processed_together() -> None:
    service, tts = build_service()

    result = service.handle_text(
        "아이스 아메리카노 두 잔이랑 따뜻한 카페라떼 한 잔 주세요",
        Cart(),
    )

    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700),
        CartItem("cafe_latte", 1, Temperature.HOT, 5200),
    ]
    assert result.cart.total_price == 14600
    assert tts.calls == [
        (
            "아이스 아메리카노 두 잔, 따뜻한 카페라떼 한 잔을 담았습니다.",
            0,
        )
    ]


def test_safe_mixed_order_runs_in_spoken_order() -> None:
    service, tts = build_service()
    cart = Cart([CartItem("cafe_latte", 1, Temperature.ICED, 5200)])

    result = service.handle_text(
        "아이스 카페라떼 빼고 아이스 아메리카노 한 잔 넣어 줘",
        cart,
    )

    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 1, Temperature.ICED, 4700)
    ]
    assert result.response_text.index("삭제했습니다") < result.response_text.index("담았습니다")
    assert tts.calls == [(result.response_text, 0)]


def test_safe_mixed_order_may_query_updated_cart_last() -> None:
    service, _ = build_service()
    cart = Cart([CartItem("milk_tea", 1, Temperature.HOT, 4500)])

    result = service.handle_text(
        "밀크티 두 잔으로 바꾸고 현재 주문도 알려 줘",
        cart,
    )

    assert result.success is True
    assert result.cart.items[0].quantity == 2
    assert result.response_text.index("변경했습니다") < result.response_text.index("현재")


def test_decaf_order_is_out_of_scope_and_preserves_cart() -> None:
    service, _ = build_service()

    result = service.handle_text(
        "아이스 아메리카노 한 잔 디카페인으로 주세요",
        Cart(),
    )

    assert result.success is False
    assert result.cart == Cart()


@pytest.mark.parametrize(
    ("text", "menu_id"),
    [
        ("아샷추 한 잔 주세요", "iced_tea"),
        ("아바샷 한 잔 주세요", "vanilla_latte"),
    ],
)
def test_option_alias_adds_iced_drink_with_one_shot(
    text: str,
    menu_id: str,
) -> None:
    service, _ = build_service()

    result = service.handle_text(text, Cart())

    assert result.success is True
    assert result.cart.items[0].menu_id == menu_id
    assert result.cart.items[0].temperature is Temperature.ICED
    assert result.cart.items[0].options.extra_shots == 1


def test_short_option_phrases_update_single_cart_item() -> None:
    service, _ = build_service()
    cart = Cart([CartItem("cafe_latte", 1, Temperature.ICED, 5200)])

    shot = service.handle_text("라떼에 샷을 더 넣어줘", cart)
    syrup = service.handle_text("시럽 넣어줘", shot.cart)
    ice = service.handle_text("얼음 조금 넣어줘", syrup.cart)

    assert ice.cart.items[0].options == BeverageOptions(
        extra_shots=1,
        syrup_pumps=1,
        ice_amount=IceAmount.LESS,
    )


def test_decaf_option_update_is_out_of_scope_and_preserves_existing_item() -> None:
    service, _ = build_service()
    cart = Cart([CartItem("americano", 1, Temperature.ICED, 4700)])

    result = service.handle_text("아메리카노 디카페인으로 줘", cart)

    assert result.success is False
    assert result.cart == cart


def test_short_option_phrase_without_cart_target_is_rejected() -> None:
    service, _ = build_service()

    result = service.handle_text("시럽 넣어줘", Cart())

    assert result.error_code is ErrorCode.MISSING_FIELD


def test_option_alias_for_missing_menu_is_not_supported() -> None:
    service, _ = build_service()

    result = service.handle_text("아초샷 한 잔 주세요", Cart())

    assert result.error_code is ErrorCode.UNSUPPORTED_UTTERANCE


def test_one_more_uses_current_state_and_outputs_final_quantity() -> None:
    service, _ = build_service()
    cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)])

    result = service.handle_text("아이스 아메리카노 한 잔 더 주세요", cart)

    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 3, Temperature.ICED, 4700)
    ]


def test_duplicate_menu_in_one_utterance_is_merged() -> None:
    service, _ = build_service()

    result = service.handle_text(
        "아이스 아메리카노 한 잔이랑 아이스 아메리카노 두 잔 주세요",
        Cart(),
    )

    assert result.cart.items == [
        CartItem("americano", 3, Temperature.ICED, 4700)
    ]


def test_same_menu_with_different_temperatures_stays_separate() -> None:
    service, _ = build_service()

    result = service.handle_text(
        "아이스 아메리카노 한 잔이랑 따뜻한 아메리카노 한 잔 주세요",
        Cart(),
    )

    assert result.cart.items == [
        CartItem("americano", 1, Temperature.ICED, 4700),
        CartItem("americano", 1, Temperature.HOT, 4700),
    ]
    assert result.cart.total_price == 9400


def test_empty_input_speaks_retry_guidance() -> None:
    service, tts = build_service()

    result = service.handle_text("  ", Cart())

    assert result.error_code is ErrorCode.EMPTY_INPUT
    assert tts.calls == [(result.response_text, 0)]


def test_tts_failure_keeps_validated_cart() -> None:
    service, _ = build_service(tts=MockTTS(should_fail=True))

    result = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())

    assert result.error_code is ErrorCode.TTS_FAILED
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700)
    ]


def test_same_input_is_deterministic() -> None:
    results = []
    for _ in range(10):
        service, _ = build_service()
        results.append(service.handle_text("아이스 아메리카노 두 잔 주세요", Cart()))

    assert all(result == results[0] for result in results)


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    [
        ("아이스 아메리카노 두 잔 주세요", Intent.ADD_ITEM),
        ("아이스 아메리카노 삭제해 주세요", Intent.REMOVE_ITEM),
        ("아이스 아메리카노 세 잔으로 바꿔 주세요", Intent.UPDATE_QUANTITY),
        ("아메리카노를 따뜻하게 바꿔 주세요", Intent.UPDATE_OPTION),
        ("커피 메뉴 알려 주세요", Intent.QUERY_MENU),
        ("현재 주문 알려 주세요", Intent.QUERY_CART),
        ("주문 확정할게요", Intent.CONFIRM_ORDER),
        ("전체 주문 취소해 주세요", Intent.CANCEL),
        ("방금 거 취소해 주세요", Intent.UNDO),
        ("다시 말해 주세요", Intent.REQUEST_REPEAT),
        ("천천히 말해 주세요", Intent.REQUEST_SLOWER),
        ("기본 속도로 말해 주세요", Intent.REQUEST_DEFAULT_SPEED),
    ],
)
def test_mock_nlu_represents_all_trd_intents(
    text: str,
    expected_intent: Intent,
) -> None:
    commands = MockNLU().parse(text, Cart())

    validate_order_commands(commands)
    assert len(commands) == 1
    assert commands[0].intent is expected_intent


def test_query_menu_uses_category_id() -> None:
    commands = MockNLU().parse("커피 메뉴 알려 주세요", Cart())

    assert commands[0].category_id == "coffee"
    assert commands[0].target_item_id is None


@pytest.mark.parametrize("text", ["안 단 거 있어요?", "당도가 낮은 거 있어요?"])
def test_menu_condition_aliases_return_same_results(text: str) -> None:
    service, tts = build_service()

    result = service.handle_text(text, Cart())

    assert result.success is True
    assert result.response_text == (
        "조건에 맞는 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, "
        "캐모마일티 3,700원입니다."
    )
    assert tts.calls == [(
        "조건에 맞는 메뉴는 아메리카노 사천칠백원, 카페라떼 오천이백원, "
        "캐모마일티 삼천칠백원입니다.",
        0,
    )]


def test_multiple_menu_conditions_are_combined_with_and() -> None:
    service, _ = build_service()

    result = service.handle_text(
        "카페인 없고 우유 안 들어간 차가운 거 보여줘",
        Cart(),
    )

    assert result.success is True
    assert result.response_text == (
        "조건에 맞는 메뉴는 자몽에이드 3,500원, 캐모마일티 3,700원입니다."
    )


def test_menu_description_question_returns_only_description() -> None:
    service, _ = build_service()

    result = service.handle_text("아메리카노는 어떤 음료야?", Cart())

    assert result.success is True
    assert result.response_text == "아메리카노는 에스프레소에 물을 더한 커피입니다."


def test_menu_multiple_detail_question_preserves_utterance_order() -> None:
    service, _ = build_service()

    result = service.handle_text(
        "카페라떼에 우유하고 카페인이 있어?",
        Cart(),
    )

    assert result.success is True
    assert result.response_text == (
        "카페라떼에는 우유가 들어갑니다. 카페라떼에는 카페인이 있습니다."
    )


def test_undo_utterance_restores_last_cart_change() -> None:
    service, _ = build_service()
    added = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())

    undone = service.handle_text("방금 거 취소해 주세요", added.cart)

    assert undone.success is True
    assert undone.cart.items == []
    assert undone.response_text.startswith("방금 변경을 취소했습니다.")


def test_service_reset_clears_undo_history() -> None:
    service, _ = build_service()
    added = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    service.reset_session()

    result = service.handle_text("방금 거 취소해 주세요", added.cart)

    assert result.error_code is ErrorCode.INVALID_COMMAND
    assert result.cart == added.cart


def test_request_repeat_replays_last_response_at_current_level() -> None:
    service, tts = build_service()
    ordered = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())

    repeated = service.handle_text("다시 말해 주세요", ordered.cart)

    assert repeated.success is True
    assert repeated.cart == ordered.cart
    assert repeated.response_text == ordered.response_text
    assert service.tts_level == 0
    assert tts.calls[-1] == (
        ordered.response_text,
        0,
    )


def test_slower_level_is_kept_for_following_order() -> None:
    service, tts = build_service()
    first = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())

    service.handle_text("천천히 말해 주세요", first.cart)
    second = service.handle_text("따뜻한 카페라떼 한 잔 주세요", first.cart)

    assert service.tts_level == 1
    assert second.success is True
    assert tts.calls[-1] == (
        "따뜻한 카페라떼 한 잔을 담았습니다.",
        1,
    )


def test_default_speed_replays_last_response_at_level_zero() -> None:
    service, tts = build_service()
    ordered = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    service.handle_text("천천히 말해 주세요", ordered.cart)

    result = service.handle_text("기본 속도로 말해 주세요", ordered.cart)

    assert result.response_text == ordered.response_text
    assert service.tts_level == 0
    assert tts.calls[-1] == (ordered.response_text, 0)


def test_first_repeat_uses_greeting_and_reset_restores_session() -> None:
    service, tts = build_service()

    result = service.handle_text("다시 말해 주세요", Cart())

    assert "안녕하세요" in result.response_text
    assert service.tts_level == 0
    service.reset_session()
    assert service.tts_level == 0
    assert "안녕하세요" in service.last_response
    assert tts.calls[-1][1] == 0


@dataclass
class ReplacementNLU:
    received_state: Cart | None = None

    def parse(self, text: str, current_order_state: Cart) -> list[OrderCommand]:
        del text
        self.received_state = current_order_state
        return [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="americano",
                quantity=1,
                temperature=Temperature.HOT,
            )
        ]


@dataclass
class ReplacementAgent:
    calls: int = 0

    def execute(self, commands: list[OrderCommand], cart: Cart) -> OrderResult:
        self.calls += 1
        return ConversationAgent(load_menu()).execute(commands, cart)


def test_protocol_implementations_are_replaceable() -> None:
    tts = MockTTS()
    agent = ReplacementAgent()
    nlu = ReplacementNLU()
    service = MalloService(nlu=nlu, agent=agent, tts=tts)
    initial_cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)])

    result = service.handle_text("대체 구현", initial_cart)

    assert nlu.received_state == initial_cart
    assert nlu.received_state is not initial_cart
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700),
        CartItem("americano", 1, Temperature.HOT, 4700),
    ]
    assert agent.calls == 1
    assert len(tts.calls) == 1


@dataclass
class StateMutatingNLU:
    def parse(self, text: str, current_order_state: Cart) -> list[OrderCommand]:
        del text
        current_order_state.items.append(
            CartItem("cafe_latte", 99, Temperature.HOT, 5200)
        )
        return [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="americano",
                quantity=1,
                temperature=Temperature.HOT,
            )
        ]


def test_nlu_state_copy_cannot_mutate_original_cart() -> None:
    service = MalloService(
        nlu=StateMutatingNLU(),
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
    )
    initial_cart = Cart([CartItem("americano", 2, Temperature.ICED, 4700)])

    result = service.handle_text("현재 주문 상태를 참고한 주문", initial_cart)

    assert initial_cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700)
    ]
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700),
        CartItem("americano", 1, Temperature.HOT, 4700),
    ]


@dataclass
class InvalidSchemaNLU:
    def parse(self, text: str, current_order_state: Cart) -> list[OrderCommand]:
        del text, current_order_state
        return [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="",
                quantity=1,
                temperature=Temperature.HOT,
            )
        ]


def test_invalid_nlu_schema_is_rejected_before_order_engine() -> None:
    tts = MockTTS()
    agent = ReplacementAgent()
    service = MalloService(nlu=InvalidSchemaNLU(), agent=agent, tts=tts)

    result = service.handle_text("잘못된 구조", Cart())

    assert result.error_code is ErrorCode.SCHEMA_ERROR
    assert result.error_response is not None
    assert result.error_response.error_code == ErrorCode.SCHEMA_ERROR
    assert result.cart.items == []
    assert agent.calls == 0
    assert tts.calls == [(result.response_text, 0)]
