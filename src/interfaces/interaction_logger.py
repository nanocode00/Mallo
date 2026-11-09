from __future__ import annotations

from typing import Protocol

from domain.session_log import SessionLogEvent


class InteractionLogger(Protocol):
    """인터랙션 이벤트를 평가 가능한 형태로 기록하는 로거 계약."""

    def log_event(self, event: SessionLogEvent) -> None: ...


class NullInteractionLogger:
    """로깅이 불필요한 경우 사용하는 no-op 로거 (기존 동작 보존)."""

    def log_event(self, event: SessionLogEvent) -> None:
        return None


__all__ = ["InteractionLogger", "NullInteractionLogger"]
