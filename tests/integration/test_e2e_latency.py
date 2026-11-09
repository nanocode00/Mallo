from __future__ import annotations

import json

from adapters.logging.file_interaction_logger import FileInteractionLogger
from app.service import build_mock_service
from domain.models import Cart
from utils.schema_validation import validate_session_log


def _read_events(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_audio_interaction_records_all_latency_stages() -> None:
    service = build_mock_service()

    result = service.handle_audio(b"dummy", Cart())

    for stage in ("stt_latency_ms", "nlu_latency_ms", "agent_latency_ms", "tts_latency_ms"):
        assert getattr(result, stage) >= 0
    assert result.total_e2e_latency_ms >= 0
    # E2E 지연은 가장 긴 모듈 지연 이상이어야 한다 (오버헤드 포함).
    longest_component = max(
        result.stt_latency_ms,
        result.nlu_latency_ms,
        result.agent_latency_ms,
        result.tts_latency_ms,
    )
    assert result.total_e2e_latency_ms >= longest_component


def test_e2e_latency_summary_runs() -> None:
    from app.service import build_mock_service
    from domain.models import Cart

    service = build_mock_service()
    totals: list[float] = []
    for _ in range(5):
        result = service.handle_audio(b"dummy", Cart())
        totals.append(result.total_e2e_latency_ms)

    assert all(lat >= 0 for lat in totals)
    assert max(totals) >= 0


def test_i07_log_records_latencies_for_audio(tmp_path) -> None:
    path = tmp_path / "log.jsonl"
    service = build_mock_service(logger=FileInteractionLogger(path))

    service.handle_audio(b"dummy", Cart())

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
    validate_session_log(events[0])
