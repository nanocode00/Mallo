from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class TTSLevel(IntEnum):
    LEVEL_0_DEFAULT = 0
    LEVEL_1_SLOW_PAUSE = 1
    LEVEL_2_CONCISE_EMPHASIS = 2


@dataclass(frozen=True)
class TTSResult:
    text: str
    level: int = 0
    sample_rate: int = 24000
    duration_ms: float | None = None
    latency_ms: float | None = None
    audio: bytes | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "level": int(self.level),
            "sample_rate": self.sample_rate,
            "duration_ms": self.duration_ms,
            "latency_ms": self.latency_ms,
            "audio_base64": (
                base64.b64encode(self.audio).decode("utf-8")
                if self.audio is not None
                else None
            ),
        }
