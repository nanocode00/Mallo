from __future__ import annotations

import pytest
from jsonschema import ValidationError

from domain.models import (
    Cart,
    ErrorCode,
    ErrorModule,
    ErrorResponse,
    OrderResult,
    create_error_response,
    get_default_error_response,
)
from utils.schema_validation import validate_error_response


def test_all_error_codes_have_valid_default_response() -> None:
    """모든 ErrorCode에 대해 get_default_error_response()가 스키마를 만족해야 한다 (AC-01, AC-02)."""
    for code in ErrorCode:
        response = get_default_error_response(code)

        assert isinstance(response, ErrorResponse)
        assert response.error_code == code
        assert isinstance(response.module, ErrorModule)
        assert len(response.user_message.strip()) > 0
        assert isinstance(response.retryable, bool)

        # JSON Schema 검증
        validate_error_response(response)


def test_mixed_intent_has_single_request_guidance() -> None:
    response = get_default_error_response(ErrorCode.MIXED_INTENT)

    assert response.user_message == (
        "사용자의 주문을 이해하지 못했습니다. "
        "한 번에 하나씩 주문해 주시면 감사하겠습니다."
    )
    assert response.recovery_hint == "각 요청을 한 문장씩 나누어 말씀해 주세요."


def test_create_error_response_override() -> None:
    """커스텀 메시지, 복구 힌트, 세부정보 오버라이드가 정상 동작해야 한다 (AC-03)."""
    custom = create_error_response(
        ErrorCode.MISSING_FIELD,
        user_message="아메리카노의 온도를 말씀해 주세요.",
        recovery_hint="'따뜻한 아메리카노' 또는 '아이스 아메리카노'라고 말씀해 주세요.",
        details={"target_item_id": "americano", "options": ["hot", "iced"]},
    )

    assert custom.error_code == ErrorCode.MISSING_FIELD
    assert custom.module == ErrorModule.NLU
    assert custom.user_message == "아메리카노의 온도를 말씀해 주세요."
    assert custom.recovery_hint == "'따뜻한 아메리카노' 또는 '아이스 아메리카노'라고 말씀해 주세요."
    assert custom.details == {"target_item_id": "americano", "options": ["hot", "iced"]}
    assert custom.retryable is True

    # JSON Schema 검증
    validate_error_response(custom)


def test_validate_error_response_rejects_missing_required_fields() -> None:
    """필수 필드가 누락된 경우 ValidationError가 발생해야 한다."""
    invalid_data = {
        "error_code": "EMPTY_INPUT",
        # module 누락
        "message": "no speech",
        "user_message": "주문을 말씀해 주세요.",
        "retryable": True,
    }

    with pytest.raises(ValidationError):
        validate_error_response(invalid_data)


def test_validate_error_response_rejects_unknown_error_code() -> None:
    """정의되지 않은 error_code는 거부되어야 한다."""
    invalid_data = {
        "error_code": "UNKNOWN_CUSTOM_ERROR",
        "module": "system",
        "message": "something failed",
        "user_message": "오류 발생",
        "retryable": False,
    }

    with pytest.raises(ValidationError):
        validate_error_response(invalid_data)


def test_validate_error_response_rejects_extra_fields() -> None:
    """정의되지 않은 임의의 추가 필드가 최상위에 있으면 거부되어야 한다."""
    invalid_data = {
        "error_code": "EMPTY_INPUT",
        "module": "stt",
        "message": "no speech",
        "user_message": "주문을 말씀해 주세요.",
        "retryable": True,
        "unexpected_field": 123,
    }

    with pytest.raises(ValidationError):
        validate_error_response(invalid_data)


def test_order_result_failure_factory() -> None:
    """OrderResult.failure 팩토리 메서드가 ErrorResponse와 연동되어 동작해야 한다 (AC-04)."""
    error = get_default_error_response(ErrorCode.MENU_NOT_FOUND)
    cart = Cart()

    result = OrderResult.failure(error, cart=cart)

    assert result.success is False
    assert result.error_code == ErrorCode.MENU_NOT_FOUND
    assert result.error_response == error
    assert result.response_text == error.user_message
    assert result.cart == cart


def test_error_response_to_dict_structure() -> None:
    """to_dict() 직렬화가 기대하는 키와 값 구조를 반환해야 한다."""
    error = ErrorResponse(
        error_code=ErrorCode.AUDIO_RECORD_FAILED,
        module=ErrorModule.AUDIO,
        message="Mic disconnected",
        user_message="마이크를 확인해 주세요.",
        recovery_hint="마이크 연결 후 다시 시도해 주세요.",
        retryable=True,
        details={"device_id": "mic-0"},
    )
    serialized = error.to_dict()

    assert serialized["error_code"] == "AUDIO_RECORD_FAILED"
    assert serialized["module"] == "audio"
    assert serialized["message"] == "Mic disconnected"
    assert serialized["user_message"] == "마이크를 확인해 주세요."
    assert serialized["recovery_hint"] == "마이크 연결 후 다시 시도해 주세요."
    assert serialized["retryable"] is True
    assert serialized["details"] == {"device_id": "mic-0"}
