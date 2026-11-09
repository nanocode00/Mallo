from __future__ import annotations

import base64
import json
import urllib.request

from domain.tts_result import TTSResult
from interfaces.tts import TTSFailure


class HTTPClientTTS:
    """MeloTTS sidecar를 호출하는 TTS 어댑터."""

    def __init__(
        self,
        url: str = "http://127.0.0.1:8003/synthesize",
        timeout: int = 120,
    ) -> None:
        self.url = url
        self.timeout = timeout

    def synthesize(self, text: str, level: int = 0) -> TTSResult:
        body = json.dumps({"text": text, "level": level}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST")
        request.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except Exception as error:  # noqa: BLE001
            raise TTSFailure(f"TTS sidecar 호출 실패: {error}") from error

        if not isinstance(payload, dict) or not payload.get("ok", False):
            detail = payload.get("error", "TTS sidecar 오류") if isinstance(payload, dict) else "응답 형식 오류"
            raise TTSFailure(str(detail))
        try:
            audio_base64 = payload["audio_base64"]
            return TTSResult(
                text=str(payload["text"]),
                level=int(payload["level"]),
                sample_rate=int(payload["sample_rate"]),
                duration_ms=payload.get("duration_ms"),
                latency_ms=payload.get("latency_ms"),
                audio=base64.b64decode(audio_base64, validate=True),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TTSFailure("TTS sidecar 응답을 해석할 수 없습니다.") from error
