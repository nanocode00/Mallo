from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.models import OrderResult
from domain.stt_result import STTResult
from domain.tts_result import TTSResult


@dataclass(frozen=True)
class VoiceInteractionResult:
    """음성 입출력 전체 파이프라인의 처리 결과."""

    stt_result: STTResult
    order_result: OrderResult
    tts_result: TTSResult | None = None

    # --- Latency (ms) ---
    stt_latency_ms: float = 0.0
    nlu_latency_ms: float = 0.0
    agent_latency_ms: float = 0.0
    tts_latency_ms: float = 0.0
    total_e2e_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stt": self.stt_result.to_dict(),
            "order": {
                "success": self.order_result.success,
                "response_text": self.order_result.response_text,
                "error_code": (
                    self.order_result.error_code.value
                    if self.order_result.error_code is not None
                    else None
                ),
                "cart": {
                    "total_price": self.order_result.cart.total_price,
                    "items": [
                        {
                            "menu_id": item.menu_id,
                            "quantity": item.quantity,
                            "temperature": (
                                item.temperature.value
                                if item.temperature is not None
                                else None
                            ),
                            "unit_price": item.unit_price,
                            "total_price": item.total_price,
                        }
                        for item in self.order_result.cart.items
                    ],
                },
            },
            "tts": self.tts_result.to_dict() if self.tts_result is not None else None,
            "latency": {
                "stt_ms": round(self.stt_latency_ms, 1),
                "nlu_ms": round(self.nlu_latency_ms, 1),
                "agent_ms": round(self.agent_latency_ms, 1),
                "tts_ms": round(self.tts_latency_ms, 1),
                "total_e2e_ms": round(self.total_e2e_latency_ms, 1),
            },
        }
