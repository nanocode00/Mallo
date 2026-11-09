from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from domain.models import Cart, ErrorCode


class SessionStatus(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    CONFIRMING = "CONFIRMING"
    CLARIFYING = "CLARIFYING"
    PAYMENT = "PAYMENT"
    SESSION_END = "SESSION_END"


@dataclass
class SessionState:
    """Minimal GUI 및 전체 세션 상태를 표현하는 도메인 모델."""

    status: SessionStatus = SessionStatus.IDLE
    cart: Cart = field(default_factory=Cart)
    last_response: str = "안녕하세요! 말로(Mallo) 카페입니다. 매장에서 드시나요, 포장하시나요?"
    tts_level: int = 0
    error_code: ErrorCode | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "cart": {
                "fulfillment_type": (
                    self.cart.fulfillment_type.value
                    if self.cart.fulfillment_type is not None
                    else None
                ),
                "items": [
                    {
                        "menu_id": item.menu_id,
                        "quantity": item.quantity,
                        "temperature": item.temperature.value if item.temperature else None,
                        "unit_price": item.unit_price,
                        "options": item.options.to_dict(),
                        "total_price": item.total_price,
                    }
                    for item in self.cart.items
                ],
                "total_price": self.cart.total_price,
            },
            "last_response": self.last_response,
            "tts_level": self.tts_level,
            "error_code": self.error_code.value if self.error_code else None,
        }
