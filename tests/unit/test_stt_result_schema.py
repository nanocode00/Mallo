from __future__ import annotations

import pytest
from jsonschema import ValidationError

from domain.models import STTResult
from interfaces.stt import STT, STTFailure
from utils.schema_validation import validate_stt_result


def test_basic_stt_result_schema_valid() -> None:
    """기본 필드만 포함된 STTResult가 JSON 스키마를 만족해야 한다 (AC-01)."""
    result = STTResult(text="아이스 아메리카노 두 잔 주세요")

    validate_stt_result(result)

    serialized = result.to_dict()
    assert serialized["text"] == "아이스 아메리카노 두 잔 주세요"
    assert serialized["confidence"] is None
    assert serialized["duration_ms"] is None
    assert serialized["language"] == "ko"
    assert serialized["alternatives"] == []
    assert serialized["is_final"] is True


def test_full_stt_result_metadata_valid() -> None:
    """confidence, duration_ms, alternatives 메타데이터가 포함된 경우 정상 검증되어야 한다 (AC-02)."""
    result = STTResult(
        text="아이스 아메리카노 두 잔 주세요",
        confidence=0.96,
        duration_ms=1250.5,
        language="ko",
        alternatives=("아이스 아메리카노 두잔", "아이스 아메리카노 2잔"),
        is_final=True,
    )

    validate_stt_result(result)

    serialized = result.to_dict()
    assert serialized["text"] == "아이스 아메리카노 두 잔 주세요"
    assert serialized["confidence"] == 0.96
    assert serialized["duration_ms"] == 1250.5
    assert serialized["language"] == "ko"
    assert serialized["alternatives"] == ["아이스 아메리카노 두잔", "아이스 아메리카노 2잔"]
    assert serialized["is_final"] is True


@pytest.mark.parametrize("invalid_confidence", [-0.1, 1.1, 2.0])
def test_stt_result_rejects_invalid_confidence(invalid_confidence: float) -> None:
    """confidence 범위가 0.0~1.0을 벗어난 경우 거부되어야 한다 (AC-03)."""
    invalid_data = {
        "text": "아메리카노",
        "confidence": invalid_confidence,
        "language": "ko",
        "is_final": True,
    }

    with pytest.raises(ValidationError):
        validate_stt_result(invalid_data)


def test_stt_result_rejects_negative_duration() -> None:
    """duration_ms가 음수인 경우 거부되어야 한다 (AC-04)."""
    invalid_data = {
        "text": "아메리카노",
        "duration_ms": -100.0,
        "language": "ko",
        "is_final": True,
    }

    with pytest.raises(ValidationError):
        validate_stt_result(invalid_data)


def test_stt_result_rejects_extra_fields() -> None:
    """정의되지 않은 추가 필드가 포함된 경우 거부되어야 한다 (AC-05)."""
    invalid_data = {
        "text": "아메리카노",
        "language": "ko",
        "is_final": True,
        "raw_tokens": [102, 340, 512],
    }

    with pytest.raises(ValidationError):
        validate_stt_result(invalid_data)


def test_stt_failure_exception() -> None:
    """STTFailure 예외가 정상적으로 발생하고 포획되어야 한다."""
    class FailingSTT:
        def transcribe(self, audio: bytes) -> STTResult:
            del audio
            raise STTFailure("Audio device decoding failed")

    stt: STT = FailingSTT()

    with pytest.raises(STTFailure) as exc_info:
        stt.transcribe(b"invalid_audio")

    assert "Audio device decoding failed" in str(exc_info.value)
