from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from adapters.tts.melotts_adapter import MeloTTSAdapter
from domain.tts_result import TTSResult
from interfaces.tts import TTSFailure


def test_melotts_adapter_empty_text() -> None:
    adapter = MeloTTSAdapter()
    result = adapter.synthesize("", level=0)

    assert isinstance(result, TTSResult)
    assert result.text == ""
    assert result.audio == b""
    assert result.duration_ms == 0.0


def test_melotts_adapter_synthesize_level_speed_policy() -> None:
    adapter = MeloTTSAdapter()

    mock_model = MagicMock()
    mock_model.hps.data.spk2id = {"KR": 0}

    def fake_tts_to_file(text: str, speaker_id: int, output_path: str, speed: float = 1.0) -> None:
        Path(output_path).write_bytes(b"RIFF_FAKE_WAV_HEADER_DATA")

    mock_model.tts_to_file.side_effect = fake_tts_to_file
    adapter._model = mock_model

    with patch("soundfile.read", return_value=([0.1, 0.2, 0.3], 44100)):
        # Level 0 -> speed 1.0
        res0 = adapter.synthesize("안녕하세요", level=0)
        assert res0.level == 0
        assert res0.sample_rate == 44100
        assert res0.audio == b"RIFF_FAKE_WAV_HEADER_DATA"
        mock_model.tts_to_file.assert_called_with("안녕하세요", 0, pytest.approx(mock_model.tts_to_file.call_args[0][2]), speed=1.0)

        # Level 1 -> speed 0.85
        res1 = adapter.synthesize("안녕하세요", level=1)
        assert res1.level == 1
        assert mock_model.tts_to_file.call_args[1]["speed"] == 0.85

        # Level 2 -> speed 0.75
        res2 = adapter.synthesize("안녕하세요", level=2)
        assert res2.level == 2
        assert mock_model.tts_to_file.call_args[1]["speed"] == 0.75


def test_melotts_adapter_synthesize_failure() -> None:
    adapter = MeloTTSAdapter()
    mock_model = MagicMock()
    mock_model.tts_to_file.side_effect = RuntimeError("Synthesis CUDA OOM")
    adapter._model = mock_model

    with pytest.raises(TTSFailure, match="MeloTTS 음성 합성 실패"):
        adapter.synthesize("안녕하세요", level=0)
