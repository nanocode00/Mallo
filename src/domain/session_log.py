from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from domain.models import Cart, OrderResult


class SessionLogEventType(str, Enum):
    SESSION_START = "SESSION_START"
    ORDER_INTERACTION = "ORDER_INTERACTION"
    TTS_SPEED_CONTROL = "TTS_SPEED_CONTROL"
    ERROR_RECOVERY = "ERROR_RECOVERY"
    ORDER_CONFIRM = "ORDER_CONFIRM"
    PAYMENT_COMPLETE = "PAYMENT_COMPLETE"
    SESSION_RESET = "SESSION_RESET"


class SessionGroup(str, Enum):
    GROUP_A_TOUCH = "Group_A_Touch"
    GROUP_B_FIXED_VOICE = "Group_B_FixedVoice"
    GROUP_C_MALLO = "Group_C_Mallo"


@dataclass
class SessionLogEvent:
    """하나의 인터랙션 이벤트를 ``schemas/session-log.schema.json`` 형식으로 기록한다."""

    session_id: str
    participant_id: str
    group: SessionGroup
    timestamp: str
    event_type: SessionLogEventType
    step_index: int
    is_success: bool

    task_id: str | None = None
    audio_input_duration_seconds: float | None = None
    stt_transcription: str | None = None
    stt_confidence: float | None = None
    nlu_intent: str | None = None
    nlu_source: str | None = None
    order_commands: list[dict[str, Any]] | None = None
    order_state_before: dict[str, Any] | None = None
    order_state_after: dict[str, Any] | None = None
    tts_level: int | None = None
    response_text: str | None = None
    tts_output_text: str | None = None
    latencies: dict[str, float] | None = None
    error_code: str | None = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def cart_to_state(cart: Cart) -> dict[str, Any]:
        return {
            "fulfillment_type": (
                cart.fulfillment_type.value
                if cart.fulfillment_type is not None
                else None
            ),
            "confirmed": cart.confirmed,
            "total_price": cart.total_price,
            "items": [
                {
                    "menu_id": item.menu_id,
                    "quantity": item.quantity,
                    "temperature": (
                        item.temperature.value
                        if item.temperature is not None
                        else None
                    ),
                    "options": item.options.to_dict(),
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                }
                for item in cart.items
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "group": self.group.value,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "task_id": self.task_id,
            "step_index": self.step_index,
            "audio_input_duration_seconds": self.audio_input_duration_seconds,
            "stt_transcription": self.stt_transcription,
            "stt_confidence": self.stt_confidence,
            "nlu_intent": self.nlu_intent,
            "nlu_source": self.nlu_source,
            "order_commands": self.order_commands,
            "order_state_before": self.order_state_before,
            "order_state_after": self.order_state_after,
            "tts_level": self.tts_level,
            "response_text": self.response_text,
            "tts_output_text": self.tts_output_text,
            "latencies": self.latencies,
            "error_code": self.error_code,
            "is_success": self.is_success,
        }


__all__ = ["SessionLogEvent", "SessionLogEventType", "SessionGroup"]
