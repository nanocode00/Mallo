from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


MIXED_INTENT_USER_MESSAGE = (
    "사용자의 주문을 이해하지 못했습니다. "
    "한 번에 하나씩 주문해 주시면 감사하겠습니다."
)
MIXED_INTENT_EXECUTION_FAILURE_MESSAGE = (
    "사용자의 주문을 이해하지 못했습니다. 다시 말씀해 주시거나 "
    "한 번에 하나씩 주문해 주시면 감사하겠습니다."
)


class ErrorModule(str, Enum):
    AUDIO = "audio"
    STT = "stt"
    NLU = "nlu"
    ORDER_ENGINE = "order_engine"
    TTS = "tts"
    SYSTEM = "system"


class ErrorCode(str, Enum):
    # AUDIO
    AUDIO_RECORD_FAILED = "AUDIO_RECORD_FAILED"

    # STT
    EMPTY_INPUT = "EMPTY_INPUT"
    STT_FAILED = "STT_FAILED"

    # NLU
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    UNKNOWN_INTENT = "UNKNOWN_INTENT"
    MISSING_FIELD = "MISSING_FIELD"
    MIXED_INTENT = "MIXED_INTENT"
    UNSUPPORTED_UTTERANCE = "UNSUPPORTED_UTTERANCE"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    INVALID_COMMAND = "INVALID_COMMAND"

    # ORDER ENGINE
    MENU_NOT_FOUND = "MENU_NOT_FOUND"
    INVALID_OPTION = "INVALID_OPTION"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    EMPTY_CART = "EMPTY_CART"
    CART_ITEM_NOT_FOUND = "CART_ITEM_NOT_FOUND"

    # TTS
    TTS_FAILED = "TTS_FAILED"

    # SYSTEM
    INTERNAL_SYSTEM_ERROR = "INTERNAL_SYSTEM_ERROR"


@dataclass(frozen=True)
class ErrorResponse:
    error_code: ErrorCode
    module: ErrorModule
    message: str
    user_message: str
    retryable: bool
    recovery_hint: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "error_code": self.error_code.value,
            "module": self.module.value,
            "message": self.message,
            "user_message": self.user_message,
            "recovery_hint": self.recovery_hint,
            "retryable": self.retryable,
        }
        if self.details:
            data["details"] = self.details
        return data


# 기본 에러 메타데이터 테이블 (ErrorCode -> (module, default_message, default_user_message, default_recovery_hint, retryable))
_DEFAULT_ERROR_METADATA: dict[
    ErrorCode,
    tuple[ErrorModule, str, str, str | None, bool],
] = {
    ErrorCode.AUDIO_RECORD_FAILED: (
        ErrorModule.AUDIO,
        "Audio recording or input device failure.",
        "마이크 입력을 확인할 수 없습니다. 다시 시도해 주세요.",
        "마이크 버튼을 누르고 다시 말씀해 주세요.",
        True,
    ),
    ErrorCode.EMPTY_INPUT: (
        ErrorModule.STT,
        "No speech or input detected.",
        "주문을 말씀해 주세요.",
        "예: '따뜻한 아메리카노 한 잔 주세요'",
        True,
    ),
    ErrorCode.STT_FAILED: (
        ErrorModule.STT,
        "STT transcription failed.",
        "음성을 정확히 인식하지 못했습니다. 다시 말씀해 주세요.",
        "마이크 가까이에서 천천히 말씀해 주세요.",
        True,
    ),
    ErrorCode.INVALID_JSON: (
        ErrorModule.NLU,
        "NLU output is not valid JSON.",
        "주문을 처리할 수 없습니다. 다시 말씀해 주세요.",
        "메뉴 이름과 수량을 다시 말씀해 주세요.",
        True,
    ),
    ErrorCode.SCHEMA_ERROR: (
        ErrorModule.NLU,
        "NLU output does not satisfy the OrderCommand schema.",
        "주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요.",
        "메뉴 이름, 수량, 온도를 함께 말씀해 주세요.",
        True,
    ),
    ErrorCode.UNKNOWN_INTENT: (
        ErrorModule.NLU,
        "NLU produced an unknown intent.",
        "지원하지 않는 요청입니다.",
        "메뉴 주문이나 장바구니 변경 요청을 말씀해 주세요.",
        True,
    ),
    ErrorCode.MISSING_FIELD: (
        ErrorModule.NLU,
        "A required OrderCommand field is missing.",
        "주문에 필요한 정보가 부족합니다.",
        "메뉴 이름, 수량, 온도를 함께 말씀해 주세요.",
        True,
    ),
    ErrorCode.MIXED_INTENT: (
        ErrorModule.NLU,
        "More than one intent was included in one command batch.",
        MIXED_INTENT_USER_MESSAGE,
        "각 요청을 한 문장씩 나누어 말씀해 주세요.",
        True,
    ),
    ErrorCode.UNSUPPORTED_UTTERANCE: (
        ErrorModule.NLU,
        "Utterance is out of domain or cannot be parsed.",
        "죄송합니다. 요청하신 내용을 이해하지 못했습니다.",
        "메뉴 이름과 수량을 말씀해 주세요.",
        True,
    ),
    ErrorCode.AMBIGUOUS_TARGET: (
        ErrorModule.NLU,
        "Target item or option is ambiguous.",
        "어떤 메뉴를 변경할지 명확하지 않습니다.",
        "따뜻한 음료인지 차가운 음료인지 함께 말씀해 주세요.",
        True,
    ),
    ErrorCode.INVALID_COMMAND: (
        ErrorModule.NLU,
        "Invalid or malformed order command schema.",
        "주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요.",
        "메뉴와 수량을 다시 말씀해 주세요.",
        True,
    ),
    ErrorCode.MENU_NOT_FOUND: (
        ErrorModule.ORDER_ENGINE,
        "Requested item is not available in the menu catalog.",
        "메뉴판에 없는 메뉴입니다. 메뉴를 다시 확인해 주세요.",
        "아메리카노, 카페라떼 등 메뉴판의 이름을 말씀해 주세요.",
        True,
    ),
    ErrorCode.INVALID_OPTION: (
        ErrorModule.ORDER_ENGINE,
        "Unsupported option or temperature for this menu.",
        "해당 메뉴에서 선택할 수 없는 옵션입니다.",
        "메뉴의 지원 온도를 확인해 주세요.",
        True,
    ),
    ErrorCode.INVALID_QUANTITY: (
        ErrorModule.ORDER_ENGINE,
        "Invalid quantity requested (must be 1 or greater).",
        "수량은 1잔 이상으로 말씀해 주세요.",
        "'한 잔', '두 잔'처럼 말씀해 주세요.",
        True,
    ),
    ErrorCode.EMPTY_CART: (
        ErrorModule.ORDER_ENGINE,
        "Cart is empty for this operation.",
        "장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.",
        "원하시는 메뉴를 말씀해 주세요.",
        True,
    ),
    ErrorCode.CART_ITEM_NOT_FOUND: (
        ErrorModule.ORDER_ENGINE,
        "Target item does not exist in cart.",
        "장바구니에 해당 메뉴가 없습니다.",
        "현재 담긴 메뉴를 확인해 주세요.",
        True,
    ),
    ErrorCode.TTS_FAILED: (
        ErrorModule.TTS,
        "TTS synthesis or audio playback failed.",
        "음성 안내 출력 중 오류가 발생했습니다. 화면을 확인해 주세요.",
        "화면의 주문 내역을 확인해 주세요.",
        False,
    ),
    ErrorCode.INTERNAL_SYSTEM_ERROR: (
        ErrorModule.SYSTEM,
        "Unexpected internal system error.",
        "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        "잠시 후 다시 말씀해 주세요.",
        False,
    ),
}


def get_default_error_response(
    error_code: ErrorCode,
    details: dict[str, Any] | None = None,
) -> ErrorResponse:
    """ErrorCode에 대한 기본 ErrorResponse를 생성합니다."""
    module, msg, user_msg, hint, retryable = _DEFAULT_ERROR_METADATA.get(
        error_code,
        (
            ErrorModule.SYSTEM,
            f"Unknown error: {error_code.value}",
            "오류가 발생했습니다. 다시 시도해 주세요.",
            None,
            False,
        ),
    )
    return ErrorResponse(
        error_code=error_code,
        module=module,
        message=msg,
        user_message=user_msg,
        recovery_hint=hint,
        retryable=retryable,
        details=details or {},
    )


def create_error_response(
    error_code: ErrorCode,
    message: str | None = None,
    user_message: str | None = None,
    recovery_hint: str | None = None,
    retryable: bool | None = None,
    details: dict[str, Any] | None = None,
    module: ErrorModule | None = None,
) -> ErrorResponse:
    """커스텀 메시지나 힌트를 오버라이드하여 ErrorResponse를 생성합니다."""
    default = get_default_error_response(error_code, details=details)
    return ErrorResponse(
        error_code=error_code,
        module=module if module is not None else default.module,
        message=message if message is not None else default.message,
        user_message=user_message if user_message is not None else default.user_message,
        recovery_hint=recovery_hint if recovery_hint is not None else default.recovery_hint,
        retryable=retryable if retryable is not None else default.retryable,
        details=details if details is not None else default.details,
    )
