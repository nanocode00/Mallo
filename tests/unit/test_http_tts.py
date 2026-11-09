from __future__ import annotations

import base64
import json
import urllib.request

from adapters.tts.http_tts import HTTPClientTTS


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self.payload


def test_http_tts_returns_audio_and_level(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response({"ok": True, "text": "안녕하세요", "level": 1, "sample_rate": 44100, "duration_ms": 100.0, "latency_ms": 20.0, "audio_base64": base64.b64encode(b"RIFFfake").decode()})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = HTTPClientTTS(timeout=7).synthesize("안녕하세요", level=1)

    assert captured == {"body": {"text": "안녕하세요", "level": 1}, "timeout": 7}
    assert result.audio == b"RIFFfake"
    assert result.sample_rate == 44100
    assert result.level == 1
