from __future__ import annotations

import pytest

from adapters.stt.mock_stt import MockSTT
from domain.stt_result import STTResult
from interfaces.stt import STTFailure


def test_mock_stt_transcription_success() -> None:
    stt = MockSTT(canned_text="따뜻한 라떼 한 잔 주세요")
    result = stt.transcribe(b"fake_audio_bytes")

    assert isinstance(result, STTResult)
    assert result.text == "따뜻한 라떼 한 잔 주세요"
    assert result.confidence == 0.98
    assert result.duration_ms == 1200.0
    assert result.language == "ko"
    assert result.is_final is True
    assert stt.calls == [b"fake_audio_bytes"]


def test_mock_stt_transcription_failure() -> None:
    stt = MockSTT(should_fail=True)
    with pytest.raises(STTFailure, match="Mock STT transcription failed"):
        stt.transcribe(b"invalid_audio")
