from typing import Protocol

from domain.models import (
    Cart,
    ErrorCode,
    OrderCommand,
    OrderCommandError,
    OrderCommandErrorCode,
)


NLUResult = list[OrderCommand] | OrderCommandError


class NLUFailure(ValueError):
    """이전 예외 기반 NLU 구현을 위한 호환 계층입니다.

    새 NLU 구현은 예외 대신 ``OrderCommandError``를 반환해야 합니다.
    """

    def __init__(self, error: OrderCommandError | ErrorCode) -> None:
        if isinstance(error, ErrorCode):
            try:
                command_code = OrderCommandErrorCode(error.value)
            except ValueError:
                command_code = OrderCommandErrorCode.SCHEMA_ERROR
            error = OrderCommandError(
                code=command_code,
                message="주문을 처리할 수 없습니다. 다시 말씀해 주세요.",
            )
        self.error = error
        self.error_code = ErrorCode(error.code.value)
        super().__init__(error.code.value)


class NLU(Protocol):
    def parse(self, text: str, current_order_state: Cart) -> NLUResult: ...
