from __future__ import annotations

from domain.tts_result import TTSResult
from sidecars.tts_server import TTSSidecarApp


class _FakeTTS:
    def __init__(self) -> None:
        self.calls = []

    def synthesize(self, text: str, level: int) -> TTSResult:
        self.calls.append((text, level))
        return TTSResult(text=text, level=level, sample_rate=44100, audio=b"RIFF")


def test_tts_sidecar_warms_with_actual_synthesis_and_serializes_result() -> None:
    fake = _FakeTTS()
    app = TTSSidecarApp(fake)  # type: ignore[arg-type]

    warmup = app.warmup()
    payload = app.synthesize({"text": "안내", "level": 2})

    assert warmup["ok"] is True
    assert app.warmed is True
    assert fake.calls == [("준비되었습니다.", 0), ("안내", 2)]
    assert payload["ok"] is True
    assert payload["audio_base64"] == "UklGRg=="


def test_tts_sidecar_rejects_invalid_request_without_synthesis() -> None:
    fake = _FakeTTS()
    app = TTSSidecarApp(fake)  # type: ignore[arg-type]

    assert app.synthesize({"text": "안내", "level": "slow"}) == {"ok": False, "error": "level은 정수여야 합니다."}
    assert fake.calls == []
