from __future__ import annotations

import pytest

from adapters.nlu.mock_nlu import MockNLU
from adapters.stt.mock_stt import MockSTT
from adapters.tts.mock_tts import MockTTS
from app.service import MalloService, build_mock_service
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import Cart, ErrorCode, FulfillmentType, OrderCommand, Temperature
from domain.voice_interaction import VoiceInteractionResult
from interfaces.stt import STTFailure


def test_end_to_end_audio_ordering_flow() -> None:
    stt = MockSTT(canned_text="아이스 아메리카노 두 잔 주세요")
    tts = MockTTS()
    service = MalloService(
        nlu=MockNLU(),
        agent=ConversationAgent(load_menu()),
        tts=tts,
        stt=stt,
    )

    cart = Cart()
    interaction = service.handle_audio(b"audio_bytes_1", cart)

    assert isinstance(interaction, VoiceInteractionResult)
    assert interaction.stt_result.text == "아이스 아메리카노 두 잔 주세요"
    assert interaction.order_result.success is True
    assert len(interaction.order_result.cart.items) == 1
    assert interaction.order_result.cart.items[0].menu_id == "americano"
    assert interaction.order_result.cart.items[0].quantity == 2
    assert interaction.order_result.cart.items[0].temperature == Temperature.ICED
    assert interaction.order_result.cart.total_price == 9400

    # TTS synthesis verification
    assert interaction.tts_result is not None
    assert interaction.tts_result.level == 0
    assert interaction.tts_result.text == "아이스 아메리카노 두 잔을 담았습니다."
    assert interaction.tts_result.audio.startswith(b"RIFF")


def test_text_fulfillment_temperature_clarification_and_reset_flow() -> None:
    service = build_mock_service()

    fulfillment = service.handle_text("매장에서", Cart())
    clarification = service.handle_text("아메리카노 하나 주세요", fulfillment.cart)
    completed = service.handle_text("아이스로", clarification.cart)
    reset = service.handle_text("취소하고 처음부터 다시 하고 싶어", completed.cart)

    assert fulfillment.success is True
    assert fulfillment.cart.fulfillment_type is FulfillmentType.DINE_IN
    assert clarification.success is False
    assert clarification.error_code is ErrorCode.MISSING_FIELD
    assert clarification.cart.items == []
    assert completed.success is True
    assert completed.cart.items[0].temperature is Temperature.ICED
    assert reset.success is True
    assert reset.cart == Cart()


@pytest.mark.parametrize("transcript", ["아", "마치 마치 마치 마치", "마치마치마치마치"])
def test_noise_like_stt_transcript_does_not_reach_nlu(transcript: str) -> None:
    stt = MockSTT(canned_text=transcript, confidence=0.92)
    tts = MockTTS()
    service = MalloService(
        nlu=MockNLU(),
        agent=ConversationAgent(load_menu()),
        tts=tts,
        stt=stt,
    )

    interaction = service.handle_audio(b"noise", Cart())

    assert interaction.order_result.success is False
    assert interaction.order_result.error_code is ErrorCode.UNSUPPORTED_UTTERANCE
    assert interaction.order_result.response_text == "잘 듣지 못했습니다. 다시 말씀해 주세요."
    assert interaction.order_result.cart.items == []
    assert tts.calls == [("잘 듣지 못했습니다. 다시 말씀해 주세요.", 0)]


@pytest.mark.parametrize("menu_id, temperature, expected", [
    ("grapefruit_ade", Temperature.ICED, "자몽에이드를 장바구니에 담았습니다."),
    ("iced_tea", Temperature.ICED, "아이스티를 장바구니에 담았습니다."),
    ("americano", Temperature.ICED, "아이스 아메리카노를 장바구니에 담았습니다."),
    ("cafe_latte", Temperature.HOT, "따뜻한 카페라떼를 장바구니에 담았습니다."),
    ("basque_cheesecake", None, "바스크 치즈 케이크를 장바구니에 담았습니다."),
])
def test_touch_commands_keep_temperature_but_speak_the_card_name(
    menu_id: str, temperature: Temperature, expected: str,
) -> None:
    service = MalloService(
        nlu=MockNLU(), agent=ConversationAgent(load_menu()), tts=MockTTS(), stt=MockSTT(),
    )
    result = service.handle_commands(
        [OrderCommand.create(Intent.ADD_ITEM, target_item_id=menu_id, quantity=1, temperature=temperature)], Cart(),
    )

    assert result.success is True
    assert result.cart.items[0].temperature is temperature
    assert result.response_text == expected



def test_end_to_end_audio_adaptive_tts_flow() -> None:
    stt = MockSTT(canned_text="아이스 아메리카노 두 잔 주세요")
    tts = MockTTS()
    service = MalloService(
        nlu=MockNLU(),
        agent=ConversationAgent(load_menu()),
        tts=tts,
        stt=stt,
    )

    cart = Cart()
    # 1) Initial order at Level 0
    int1 = service.handle_audio(b"audio_1", cart)
    assert int1.order_result.success is True
    assert service.tts_level == 0
    cart = int1.order_result.cart

    # 2) User says "천천히 말해 주세요" -> Level 1 (slower + pause marker)
    stt.canned_text = "천천히 말해 주세요"
    int2 = service.handle_audio(b"audio_2", cart)
    assert int2.order_result.success is True
    assert service.tts_level == 1
    assert int2.tts_result is not None
    assert int2.tts_result.level == 1
    assert int2.tts_result.text == "아이스 아메리카노 두 잔을 담았습니다."

    # 3) User says "다시 말해 주세요" -> Level 1 유지
    stt.canned_text = "다시 말해 주세요"
    int3 = service.handle_audio(b"audio_3", cart)
    assert int3.order_result.success is True
    assert service.tts_level == 1
    assert int3.tts_result is not None
    assert int3.tts_result.level == 1

    # 4) User says "기본 속도로 말해 주세요" -> Level 0 reset
    stt.canned_text = "기본 속도로 말해 주세요"
    int4 = service.handle_audio(b"audio_4", cart)
    assert int4.order_result.success is True
    assert service.tts_level == 0
    assert int4.tts_result is not None
    assert int4.tts_result.level == 0


def test_end_to_end_empty_audio_handling() -> None:
    service = build_mock_service()
    cart = Cart()

    interaction = service.handle_audio(b"", cart)

    assert interaction.order_result.success is False
    assert interaction.order_result.error_code == ErrorCode.EMPTY_INPUT
    assert interaction.tts_result is not None
    assert interaction.tts_result.text == interaction.order_result.response_text


def test_end_to_end_stt_failure_handling() -> None:
    service = build_mock_service(stt_should_fail=True)
    cart = Cart()

    interaction = service.handle_audio(b"noisy_unintelligible_audio", cart)

    assert interaction.order_result.success is False
    assert interaction.order_result.error_code == ErrorCode.UNSUPPORTED_UTTERANCE
    assert "음성을 인식하지 못했습니다" in interaction.order_result.response_text
    assert interaction.tts_result is not None
    assert interaction.tts_result.text == interaction.order_result.response_text


def test_end_to_end_tts_failure_handling() -> None:
    service = build_mock_service(tts_should_fail=True)
    cart = Cart()

    interaction = service.handle_audio(b"audio_bytes", cart)

    assert interaction.order_result.success is False
    assert interaction.order_result.error_code == ErrorCode.TTS_FAILED
    assert interaction.tts_result is None
