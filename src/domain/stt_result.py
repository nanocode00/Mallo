from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class STTResult:
    text: str
    confidence: float | None = None
    duration_ms: float | None = None
    language: str = "ko"
    alternatives: tuple[str, ...] = field(default_factory=tuple)
    is_final: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "language": self.language,
            "alternatives": list(self.alternatives),
            "is_final": self.is_final,
        }
