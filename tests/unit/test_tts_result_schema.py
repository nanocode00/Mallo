from __future__ import annotations

import base64
import pytest
from jsonschema import ValidationError

from adapters.tts.mock_tts import MockTTS
from domain.models import TTSLevel, TTSResult
from interfaces.tts import TTS, TTSFailure
from utils.schema_validation import validate_tts_result


def test_basic_tts_result_schema_valid() -> None:
    """기본 필드만 포함된 TTSResult가 JSON 스키마를 만족해야 한다 (AC-01)."""
    result = TTSResult(text="아메리카노 두 잔을 담았습니다.", level=0, sample_rate=24000)

    validate_tts_result(result)

    serialized = result.to_dict()
    assert serialized["text"] == "아메리카노 두 잔을 담았습니다."
    assert serialized["level"] == 0
    assert serialized["sample_rate"] == 24000
    assert serialized["duration_ms"] is None
    assert serialized["latency_ms"] is None
    assert serialized["audio_base64"] is None


def test_full_tts_result_metadata_and_base64() -> None:
    """오디오 바이트, duration, latency가 포함된 경우 Base64 직렬화와 스키마 검증이 성공해야 한다 (AC-02)."""
    audio_data = b"RIFF-WAVE-MOCK-AUDIO-DATA"
    result = TTSResult(
        text="따뜻한 카페라떼 한 잔을 담았습니다.",
        level=TTSLevel.LEVEL_1_SLOW_PAUSE,
        sample_rate=24000,
        duration_ms=2100.5,
        latency_ms=180.2,
        audio=audio_data,
    )

    validate_tts_result(result)

    serialized = result.to_dict()
    assert serialized["text"] == "따뜻한 카페라떼 한 잔을 담았습니다."
    assert serialized["level"] == 1
    assert serialized["duration_ms"] == 2100.5
    assert serialized["latency_ms"] == 180.2
    assert serialized["audio_base64"] == base64.b64encode(audio_data).decode("utf-8")


@pytest.mark.parametrize("invalid_level", [-1, 3, 99])
def test_tts_result_rejects_invalid_level(invalid_level: int) -> None:
    """0, 1, 2 이외의 level 값은 거부되어야 한다 (AC-03)."""
    invalid_data = {
        "text": "안내 문장",
        "level": invalid_level,
        "sample_rate": 24000,
    }

    with pytest.raises(ValidationError):
        validate_tts_result(invalid_data)


def test_tts_result_rejects_low_sample_rate() -> None:
    """sample_rate가 8000Hz 미만인 경우 거부되어야 한다 (AC-04)."""
    invalid_data = {
        "text": "안내 문장",
        "level": 0,
        "sample_rate": 4000,
    }

    with pytest.raises(ValidationError):
        validate_tts_result(invalid_data)


def test_tts_result_rejects_extra_fields() -> None:
    """정의되지 않은 추가 필드가 포함된 경우 거부되어야 한다 (AC-05)."""
    invalid_data = {
        "text": "안내 문장",
        "level": 0,
        "sample_rate": 24000,
        "pitch_shift": 1.2,
    }

    with pytest.raises(ValidationError):
        validate_tts_result(invalid_data)


def test_mock_tts_returns_valid_tts_result() -> None:
    """MockTTS가 TTSResult를 반환하고 스키마를 만족해야 한다."""
    tts: TTS = MockTTS()
    result = tts.synthesize("테스트 문장", level=2)

    assert isinstance(result, TTSResult)
    assert result.text == "테스트 문장"
    assert result.level == 2
    validate_tts_result(result)


def test_tts_failure_exception() -> None:
    """TTSFailure 예외가 정상적으로 발생해야 한다."""
    tts = MockTTS(should_fail=True)

    with pytest.raises(TTSFailure) as exc_info:
        tts.synthesize("실패 테스트")

    assert "Mock TTS failed" in str(exc_info.value)
