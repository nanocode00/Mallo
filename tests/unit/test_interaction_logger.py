from __future__ import annotations

import json

from adapters.logging.file_interaction_logger import FileInteractionLogger
from app.service import build_mock_service
from domain.models import Cart
from domain.session_log import (
    SessionGroup,
    SessionLogEvent,
    SessionLogEventType,
)
from interfaces.interaction_logger import InteractionLogger, NullInteractionLogger
from utils.schema_validation import validate_session_log


def _read_events(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_session_log_event_matches_schema() -> None:
    event = SessionLogEvent(
        session_id="sess_20260819_000000_abc",
        participant_id="P01",
        group=SessionGroup.GROUP_C_MALLO,
        timestamp=SessionLogEvent.now_iso(),
        event_type=SessionLogEventType.ORDER_INTERACTION,
        step_index=1,
        is_success=True,
        stt_transcription="아이스 아메리카노 두 잔 주세요",
        nlu_intent="ADD_ITEM",
        order_commands=[],
        order_state_after={"total_price": 9400, "items": []},
        tts_level=0,
        response_text="아이스 아메리카노 두 잔을 담았습니다.",
        latencies={
            "stt_seconds": 0.42,
            "nlu_seconds": 0.1,
            "order_engine_seconds": 0.05,
            "tts_seconds": 0.2,
            "total_e2e_seconds": 0.77,
        },
    )
    assert event.to_dict()["event_type"] == "ORDER_INTERACTION"
    validate_session_log(event)


def test_file_logger_writes_one_jsonl_per_event(tmp_path) -> None:
    path = tmp_path / "session.jsonl"
    logger = FileInteractionLogger(path)

    for i in range(3):
        logger.log_event(
            SessionLogEvent(
                session_id="s1",
                participant_id="P01",
                group=SessionGroup.GROUP_C_MALLO,
                timestamp=SessionLogEvent.now_iso(),
                event_type=SessionLogEventType.ORDER_INTERACTION,
                step_index=i,
                is_success=True,
            )
        )

    events = _read_events(path)
    assert len(events) == 3
    assert events[0]["step_index"] == 0
    assert events[2]["session_id"] == "s1"


def test_null_logger_is_noop() -> None:
    logger: InteractionLogger = NullInteractionLogger()
    event = SessionLogEvent(
        session_id="s1",
        participant_id="P01",
        group=SessionGroup.GROUP_C_MALLO,
        timestamp=SessionLogEvent.now_iso(),
        event_type=SessionLogEventType.ORDER_INTERACTION,
        step_index=0,
        is_success=True,
    )
    logger.log_event(event)  # should not raise


def test_pipeline_logs_order_interaction_on_text(tmp_path) -> None:
    path = tmp_path / "log.jsonl"
    service = build_mock_service(logger=FileInteractionLogger(path))

    result = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())

    assert result.success
    events = _read_events(path)
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "ORDER_INTERACTION"
    assert event["is_success"] is True
    assert event["stt_transcription"] == "아이스 아메리카노 두 잔 주세요"
    assert event["nlu_intent"] == "ADD_ITEM"
    assert event["nlu_source"] == "rule_menu_add"
    assert event["tts_level"] == 0
    assert event["response_text"] == result.response_text
    assert event["order_state_after"]["total_price"] == 9400
    assert event["order_state_after"]["items"][0]["menu_id"] == "americano"
    assert event["tts_output_text"] == result.response_text
    validate_session_log(event)


def test_one_shot_payload_is_final_but_debug_log_keeps_command_trace(tmp_path) -> None:
    path = tmp_path / "log.jsonl"
    service = build_mock_service(logger=FileInteractionLogger(path))

    result = service.handle_text("아이스 아메리카노 한 잔 포장해주세요", Cart())

    event = _read_events(path)[0]
    assert result.response_text == "포장 주문입니다. 총 결제 금액은 4,700원입니다. 결제를 진행해 주세요."
    assert event["response_text"] == (
        "포장으로 설정했습니다. 아이스 아메리카노 한 잔을 담았습니다. "
        "포장 주문입니다. 총 결제 금액은 4,700원입니다. 결제를 진행해 주세요."
    )
    assert [command["intent"] for command in event["order_commands"]] == [
        "SET_FULFILLMENT", "ADD_ITEM", "CONFIRM_ORDER",
    ]
    assert event["tts_output_text"] == (
        "포장 주문입니다. 총 결제 금액은 사천칠백원입니다. 결제를 진행해 주세요."
    )


def test_pipeline_logs_error_recovery_for_empty_input(tmp_path) -> None:
    path = tmp_path / "log.jsonl"
    service = build_mock_service(logger=FileInteractionLogger(path))

    result = service.handle_text("   ", Cart())

    assert not result.success
    events = _read_events(path)
    assert len(events) == 1
    assert events[0]["event_type"] == "ERROR_RECOVERY"
    assert events[0]["is_success"] is False
    assert events[0]["error_code"] == "EMPTY_INPUT"
    validate_session_log(events[0])


def test_pipeline_logs_tts_speed_control(tmp_path) -> None:
    path = tmp_path / "log.jsonl"
    service = build_mock_service(logger=FileInteractionLogger(path))

    service.handle_text("천천히 말해 주세요", Cart())

    events = _read_events(path)
    assert events[0]["event_type"] == "TTS_SPEED_CONTROL"
    assert events[0]["nlu_intent"] == "REQUEST_SLOWER"


def test_pipeline_logs_latencies_on_audio(tmp_path) -> None:
    path = tmp_path / "log.jsonl"
    service = build_mock_service(logger=FileInteractionLogger(path))

    service.handle_audio(b"dummy-audio-bytes", Cart())

    events = _read_events(path)
    assert len(events) == 1
    latencies = events[0]["latencies"]
    assert latencies is not None
    assert set(latencies.keys()) == {
        "stt_seconds",
        "nlu_seconds",
        "agent_seconds",
        "order_engine_seconds",
        "tts_seconds",
        "total_e2e_seconds",
    }
    assert latencies["total_e2e_seconds"] >= 0
    assert events[0]["audio_input_duration_seconds"] is not None
    assert events[0]["stt_confidence"] == 0.98
    assert events[0]["order_state_before"]["items"] == []
    assert events[0]["tts_output_text"] == "아이스 아메리카노 두 잔을 담았습니다."


def test_pipeline_logs_session_reset_and_rotates_session_id(tmp_path) -> None:
    path = tmp_path / "log.jsonl"
    service = build_mock_service(logger=FileInteractionLogger(path))

    service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    first_session_id = _read_events(path)[0]["session_id"]

    service.reset_session()
    service.handle_text("따뜻한 카페라떼 한 잔 주세요", Cart())

    events = _read_events(path)
    types = [e["event_type"] for e in events]
    assert "SESSION_RESET" in types
    reset_event = next(e for e in events if e["event_type"] == "SESSION_RESET")
    assert reset_event["session_id"] == first_session_id

    new_session_id = events[-1]["session_id"]
    assert new_session_id != first_session_id
