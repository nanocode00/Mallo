from __future__ import annotations

from collections.abc import Iterable

from domain.intents import Intent
from domain.models import OrderCommand


CONFIRMATION_REQUIRED_INTENTS = frozenset(
    {
        Intent.REMOVE_ITEM,
        Intent.CONFIRM_ORDER,
        Intent.CANCEL,
    }
)


def requires_confirmation(commands: Iterable[OrderCommand]) -> bool:
    """NLU 출력과 분리된 Order Engine 확인 정책을 반환합니다."""
    return any(
        command.intent in CONFIRMATION_REQUIRED_INTENTS for command in commands
    )
