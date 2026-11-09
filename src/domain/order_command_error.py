from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class OrderCommandErrorCode(str, Enum):
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    UNKNOWN_INTENT = "UNKNOWN_INTENT"
    MISSING_FIELD = "MISSING_FIELD"
    MIXED_INTENT = "MIXED_INTENT"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    UNSUPPORTED_UTTERANCE = "UNSUPPORTED_UTTERANCE"


@dataclass(frozen=True)
class OrderCommandError:
    code: OrderCommandErrorCode
    message: str
    retryable: bool = True
    command_index: int | None = None
    field: str | None = None
    candidates: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "command_index": self.command_index,
            "field": self.field,
            "candidates": list(self.candidates) if self.candidates is not None else None,
            "retryable": self.retryable,
        }
