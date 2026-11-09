from __future__ import annotations

from typing import Protocol

from domain.tts_result import TTSResult


class TTSFailure(RuntimeError):
    """TTS 합성 또는 출력 실패 시 발생하는 예외"""

    pass


class TTS(Protocol):
    def synthesize(self, text: str, level: int = 0) -> TTSResult | None: ...

