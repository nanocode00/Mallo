from __future__ import annotations

import json

from adapters.logging.file_interaction_logger import FileInteractionLogger
from app.service import build_mock_service
from domain.models import Cart
from utils.schema_validation import validate_session_log


def _read_events(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_end_to_end_pipeline_logs_interactions(tmp_path) -> None:
    path = tmp_path / "e2e.jsonl"
    service = build_mock_service(logger=FileInteractionLogger(path))

    service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    service.handle_audio(b"audio", Cart())
    service.handle_text("천천히 말해 주세요", Cart())
    service.reset_session()
    service.handle_text("따뜻한 카페라떼 한 잔 주세요", Cart())

    events = _read_events(path)
    types = [e["event_type"] for e in events]
    assert "ORDER_INTERACTION" in types
    assert "TTS_SPEED_CONTROL" in types
    assert "SESSION_RESET" in types
    for event in events:
        validate_session_log(event)
