from __future__ import annotations

from sidecars.nlu_server import NLUSidecarApp
from sidecars.stt_server import _warmup_audio


class _FakeNLU:
    merged_model_path = "fake-model"
    load_latency_ms = 0.0

    def __init__(self) -> None:
        self.calls = []

    def parse(self, text, cart):
        self.calls.append((text, cart))
        return []


def test_stt_warmup_audio_is_in_memory_pcm_wav() -> None:
    audio = _warmup_audio()
    assert audio.startswith(b"RIFF")
    assert b"WAVE" in audio[:16]
    assert len(audio) > 32_000


def test_nlu_warmup_uses_normal_parse_path_with_empty_cart() -> None:
    fake = _FakeNLU()
    app = NLUSidecarApp(fake)  # type: ignore[arg-type]

    result = app.warmup()

    assert result["ok"] is True
    assert app.warmed is True
    assert fake.calls[0][0] == "아메리카노 한 잔 주세요"
    assert fake.calls[0][1].items == []
