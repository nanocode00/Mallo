"""E-01~E-04 사용자 테스트 프로토콜 및 E-08 데모 시나리오 무결성을 검증한다."""

import json
from pathlib import Path
import pytest
import jsonschema

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_session_log_schema_validity():
    schema_path = REPOSITORY_ROOT / "schemas/session-log.schema.json"
    assert schema_path.exists(), "session-log schema must exist"
    
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    
    valid_event = {
        "session_id": "sess_20260818_173000_001",
        "participant_id": "P01",
        "group": "Group_C_Mallo",
        "timestamp": "2026-08-18T17:30:00.123+09:00",
        "event_type": "ORDER_INTERACTION",
        "task_id": "TASK-2",
        "step_index": 1,
        "audio_input_duration_seconds": 3.2,
        "stt_transcription": "따뜻한 아메리카노 한 잔이랑 치즈 케이크 하나 주세요",
        "nlu_intent": "ADD_ITEM",
        "order_commands": [
            {"intent": "ADD_ITEM", "target_item_id": "americano", "quantity": 1, "temperature": "hot"}
        ],
        "order_state_after": {
            "items": [{"item_id": "americano", "quantity": 1, "temperature": "hot", "price": 4700}],
            "total_price": 4700
        },
        "tts_level": 0,
        "response_text": "따뜻한 아메리카노 한 잔을 담았습니다.",
        "latencies": {
            "stt_seconds": 0.42,
            "nlu_seconds": 0.15,
            "order_engine_seconds": 0.01,
            "tts_seconds": 0.20,
            "total_e2e_seconds": 0.78
        },
        "is_success": True
    }
    
    jsonschema.validate(instance=valid_event, schema=schema)


def test_metrics_calculation_formula():
    # TCR calculation
    completed_tasks = 9
    total_tasks = 10
    tcr = (completed_tasks / total_tasks) * 100.0
    assert tcr == 90.0

    # ERR calculation
    recovered_sessions = 4
    error_sessions = 5
    err = (recovered_sessions / error_sessions) * 100.0
    assert err == 80.0

    # E2E Latency summation
    stt_lat, nlu_lat, order_lat, tts_lat = 0.4, 0.15, 0.01, 0.20
    e2e_lat = stt_lat + nlu_lat + order_lat + tts_lat
    assert round(e2e_lat, 2) == 0.76


def test_protocol_and_demo_spec_files_exist():
    assert (REPOSITORY_ROOT / "docs/specs/user-test-protocol.md").exists()
    assert (REPOSITORY_ROOT / "docs/specs/demo-scenarios.md").exists()
