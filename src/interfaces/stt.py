from __future__ import annotations

from typing import Protocol

from domain.stt_result import STTResult


class STTFailure(RuntimeError):
    """STT 변환 실패 시 발생하는 예외"""

    pass


class STT(Protocol):
    def transcribe(
        self, audio: bytes, language: str = "ko"
    ) -> STTResult: ...
