from __future__ import annotations

from domain.stt_result import STTResult
from interfaces.stt import STTFailure


class MockSTT:
    """테스트용 Mock STT 어댑터."""

    def __init__(
        self,
        canned_text: str = "아이스 아메리카노 두 잔 주세요",
        should_fail: bool = False,
        confidence: float = 0.98,
        duration_ms: float = 1200.0,
    ) -> None:
        self.canned_text = canned_text
        self.should_fail = should_fail
        self.confidence = confidence
        self.duration_ms = duration_ms
        self.calls: list[bytes] = []

    def transcribe(self, audio: bytes, language: str = "ko") -> STTResult:
        if self.should_fail:
            raise STTFailure("Mock STT transcription failed")
        self.calls.append(audio)
        return STTResult(
            text=self.canned_text,
            confidence=self.confidence,
            duration_ms=self.duration_ms,
            language="ko",
            is_final=True,
        )
