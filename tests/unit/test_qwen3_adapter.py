from __future__ import annotations

import numpy as np
from unittest.mock import MagicMock

import pytest

from adapters.tts.qwen3_adapter import Qwen3TTSAdapter
from domain.tts_result import TTSResult
from interfaces.tts import TTSFailure


def test_qwen3_adapter_empty_text() -> None:
    adapter = Qwen3TTSAdapter()
    result = adapter.synthesize("", level=0)

    assert isinstance(result, TTSResult)
    assert result.text == ""
    assert result.audio == b""
    assert result.duration_ms == 0.0


def test_qwen3_adapter_synthesize_success() -> None:
    adapter = Qwen3TTSAdapter(speaker="calm_friendly")

    mock_model = MagicMock()
    mock_wav = np.zeros(24000, dtype=np.float32)
    mock_model.generate_custom_voice.return_value = ([mock_wav], 24000)
    adapter._model = mock_model

    result = adapter.synthesize("안녕하세요", level=0)

    assert isinstance(result, TTSResult)
    assert result.sample_rate == 24000
    assert result.duration_ms == 1000.0
    assert result.audio is not None
    assert len(result.audio) > 0
    mock_model.generate_custom_voice.assert_called_with(
        text="안녕하세요",
        speaker="calm_friendly",
        max_new_tokens=300,
    )


def test_qwen3_adapter_synthesize_failure() -> None:
    adapter = Qwen3TTSAdapter()
    mock_model = MagicMock()
    mock_model.generate_custom_voice.side_effect = RuntimeError("Qwen generation error")
    adapter._model = mock_model

    with pytest.raises(TTSFailure, match="Qwen3-TTS 음성 합성 실패"):
        adapter.synthesize("테스트", level=0)
