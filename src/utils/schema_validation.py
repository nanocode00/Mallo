from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from domain.mixed_intent import is_supported_sequential_batch
from domain.models import (
    ErrorResponse,
    OrderCommand,
    OrderCommandError,
    STTResult,
    TTSResult,
)


ORDER_COMMAND_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "order-command.schema.json"
)
ORDER_COMMAND_ERROR_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "order-command-error.schema.json"
)
ERROR_RESPONSE_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "error-response.schema.json"
)
STT_RESULT_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "stt-result.schema.json"
)
TTS_RESULT_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "tts-result.schema.json"
)
SESSION_LOG_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "session-log.schema.json"
)


def validate_order_commands(
    commands: list[OrderCommand],
    schema_path: Path = ORDER_COMMAND_SCHEMA_PATH,
) -> None:
    if not isinstance(commands, list):
        raise ValidationError("NLU 출력은 OrderCommand 배열이어야 합니다.")

    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    serialized = [command.to_dict() for command in commands]
    Draft202012Validator(schema).validate(serialized)

    if (
        len({command.intent for command in commands}) > 1
        and not is_supported_sequential_batch(commands)
    ):
        raise ValidationError("지원하지 않는 혼합 Intent 조합입니다.")


def validate_order_command_error(
    error: OrderCommandError | dict,
    schema_path: Path = ORDER_COMMAND_ERROR_SCHEMA_PATH,
) -> None:
    """OrderCommandError 객체 또는 dict가 order-command-error JSON Schema를 준수하는지 검증합니다."""
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    serialized = error.to_dict() if isinstance(error, OrderCommandError) else error
    Draft202012Validator(schema).validate(serialized)


def validate_error_response(
    error_response: ErrorResponse | dict,
    schema_path: Path = ERROR_RESPONSE_SCHEMA_PATH,
) -> None:
    """ErrorResponse 객체 또는 dict가 error-response JSON Schema를 준수하는지 검증합니다."""
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    serialized = (
        error_response.to_dict()
        if isinstance(error_response, ErrorResponse)
        else error_response
    )
    Draft202012Validator(schema).validate(serialized)


def validate_stt_result(
    result: STTResult | dict,
    schema_path: Path = STT_RESULT_SCHEMA_PATH,
) -> None:
    """STTResult 객체 또는 dict가 stt-result JSON Schema를 준수하는지 검증합니다."""
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    serialized = result.to_dict() if isinstance(result, STTResult) else result
    Draft202012Validator(schema).validate(serialized)


def validate_tts_result(
    result: TTSResult | dict,
    schema_path: Path = TTS_RESULT_SCHEMA_PATH,
) -> None:
    """TTSResult 객체 또는 dict가 tts-result JSON Schema를 준수하는지 검증합니다."""
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    serialized = result.to_dict() if isinstance(result, TTSResult) else result
    Draft202012Validator(schema).validate(serialized)


def validate_session_log(
    event: dict | object,
    schema_path: Path = SESSION_LOG_SCHEMA_PATH,
) -> None:
    """SessionLogEvent 객체 또는 dict가 session-log JSON Schema를 준수하는지 검증합니다."""
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    serialized = event.to_dict() if hasattr(event, "to_dict") else event
    Draft202012Validator(schema).validate(serialized)


