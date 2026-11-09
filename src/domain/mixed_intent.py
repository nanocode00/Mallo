from __future__ import annotations

from collections.abc import Sequence

from domain.intents import Intent
from domain.models import OrderCommand


MAX_SEQUENTIAL_CART_MUTATIONS = 2
ONE_SHOT_ORDER_INTENTS = (
    Intent.SET_FULFILLMENT,
    Intent.ADD_ITEM,
    Intent.CONFIRM_ORDER,
)
SEQUENTIAL_CART_MUTATION_INTENTS = frozenset(
    {
        Intent.ADD_ITEM,
        Intent.REMOVE_ITEM,
        Intent.UPDATE_QUANTITY,
        Intent.UPDATE_OPTION,
        Intent.SET_FULFILLMENT,
    }
)


def is_supported_sequential_batch(commands: Sequence[OrderCommand]) -> bool:
    """안전하게 순차 실행할 수 있는 혼합 Intent 배열인지 판정한다."""
    intents = [command.intent for command in commands]
    if not is_supported_sequential_intents(intents):
        return False

    query_positions = [
        index
        for index, command in enumerate(commands)
        if command.intent is Intent.QUERY_CART
    ]
    if query_positions and any(
        value is not None
        for value in (
            commands[-1].target_item_id,
            commands[-1].category_id,
            commands[-1].quantity,
            commands[-1].temperature,
            commands[-1].query_tags,
            commands[-1].detail_fields,
            commands[-1].options,
        )
    ):
        return False

    return True


def is_supported_sequential_intents(intents: Sequence[Intent]) -> bool:
    if tuple(intents) == ONE_SHOT_ORDER_INTENTS:
        return True
    if len(set(intents)) <= 1:
        return False

    query_positions = [
        index for index, intent in enumerate(intents) if intent is Intent.QUERY_CART
    ]
    if len(query_positions) > 1:
        return False
    if query_positions and query_positions[0] != len(intents) - 1:
        return False

    mutation_intents = intents[:-1] if query_positions else intents
    if not 1 <= len(mutation_intents) <= MAX_SEQUENTIAL_CART_MUTATIONS:
        return False
    return all(
        intent in SEQUENTIAL_CART_MUTATION_INTENTS for intent in mutation_intents
    )
