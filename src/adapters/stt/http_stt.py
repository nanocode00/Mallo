from __future__ import annotations

import json
import urllib.request

from domain.stt_result import STTResult
from interfaces.stt import STTFailure


class HTTPClientSTT:
    """STT 사이드카(stt_sidecar_server.py)를 호출하는 클라이언트 어댑터.

    메인 서버 프로세스와 STT 추론 프로세스를 분리해 transformers 버전 충돌
    (whisper-medium: 5.x vs MeloTTS: 4.27)과 Windows cuDNN 공존 문제를 회피한다.
    """

    def __init__(self, url: str = "http://127.0.0.1:8001/transcribe", timeout: int = 120) -> None:
        self.url = url
        self.timeout = timeout

    def transcribe(self, audio: bytes, language: str = "ko") -> STTResult:
        try:
            req = urllib.request.Request(self.url, data=audio, method="POST")
            req.add_header("Content-Type", "application/octet-stream")
            req.add_header("X-Language", language)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            raise STTFailure(f"STT sidecar 호출 실패: {exc}") from exc

        if not data.get("ok", False):
            raise STTFailure(str(data.get("error", "STT sidecar 오류")))
        return STTResult(
            text=data.get("text", ""),
            duration_ms=data.get("duration_ms"),
        )
