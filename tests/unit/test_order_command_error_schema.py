from __future__ import annotations

import pytest
from jsonschema import ValidationError

from domain.models import OrderCommandError, OrderCommandErrorCode
from utils.schema_validation import validate_order_command_error


def test_valid_order_command_errors() -> None:
    """모든 정의된 OrderCommandErrorCode로 생성한 에러는 스키마를 만족해야 한다 (AC-01)."""
    for code in OrderCommandErrorCode:
        err = OrderCommandError(
            code=code,
            message="테스트 오류 메시지입니다.",
            retryable=True,
        )
        validate_order_command_error(err)


def test_order_command_error_with_optional_fields() -> None:
    """command_index, field, candidates 등 선택 필드가 포함된 경우 정상 검증되어야 한다 (AC-02)."""
    err = OrderCommandError(
        code=OrderCommandErrorCode.MISSING_FIELD,
        message="아메리카노의 온도를 말씀해 주세요.",
        retryable=True,
        command_index=0,
        field="temperature",
        candidates=("hot", "iced"),
    )

    validate_order_command_error(err)

    serialized = err.to_dict()
    assert serialized["code"] == "MISSING_FIELD"
    assert serialized["message"] == "아메리카노의 온도를 말씀해 주세요."
    assert serialized["command_index"] == 0
    assert serialized["field"] == "temperature"
    assert serialized["candidates"] == ["hot", "iced"]
    assert serialized["retryable"] is True


def test_order_command_error_missing_required_fields() -> None:
    """필수 필드(code, message, retryable) 누락 시 ValidationError가 발생해야 한다 (AC-03)."""
    invalid_data = {
        "code": "MISSING_FIELD",
        "retryable": True,
        # message 누락
    }

    with pytest.raises(ValidationError):
        validate_order_command_error(invalid_data)


def test_order_command_error_rejects_extra_fields() -> None:
    """스키마에 정의되지 않은 추가 필드가 포함되면 거부되어야 한다 (AC-04)."""
    invalid_data = {
        "code": "INVALID_JSON",
        "message": "JSON 파싱 오류",
        "retryable": True,
        "unexpected_extra_field": "disallowed",
    }

    with pytest.raises(ValidationError):
        validate_order_command_error(invalid_data)


def test_order_command_error_rejects_negative_index() -> None:
    """command_index가 음수인 경우 거부되어야 한다 (AC-05)."""
    invalid_data = {
        "code": "MISSING_FIELD",
        "message": "필드 누락",
        "retryable": True,
        "command_index": -1,
    }

    with pytest.raises(ValidationError):
        validate_order_command_error(invalid_data)


def test_order_command_error_rejects_unknown_code() -> None:
    """정의되지 않은 code는 거부되어야 한다."""
    invalid_data = {
        "code": "NOT_AN_ERROR_CODE",
        "message": "알 수 없는 에러",
        "retryable": True,
    }

    with pytest.raises(ValidationError):
        validate_order_command_error(invalid_data)
