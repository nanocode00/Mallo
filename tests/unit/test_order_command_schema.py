import json
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, ValidationError

from domain.confirmation_policy import requires_confirmation
from domain.intents import Intent
from domain.models import (
    BeverageSize,
    BeverageOptions,
    BeverageSize,
    CaffeineOption,
    IceAmount,
    OrderCommand,
    Temperature,
)
from utils.schema_validation import validate_order_commands


ROOT = Path(__file__).parents[2]
SCHEMA_PATH = ROOT / "schemas" / "order-command.schema.json"


def load_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def command_for(intent: Intent) -> OrderCommand:
    if intent is Intent.ADD_ITEM:
        return OrderCommand.create(
            intent,
            target_item_id="americano",
            quantity=2,
            temperature=Temperature.ICED,
        )
    if intent is Intent.REMOVE_ITEM:
        return OrderCommand.create(
            intent,
            target_item_id="americano",
            temperature=Temperature.ICED,
        )
    if intent is Intent.UPDATE_QUANTITY:
        return OrderCommand.create(
            intent,
            target_item_id="americano",
            quantity=3,
            temperature=Temperature.ICED,
        )
    if intent is Intent.UPDATE_OPTION:
        return OrderCommand.create(
            intent,
            target_item_id="americano",
            temperature=Temperature.HOT,
        )
    if intent is Intent.QUERY_MENU:
        return OrderCommand.create(intent, category_id="coffee")
    if intent is Intent.SELECT_PAYMENT_METHOD:
        return OrderCommand.create(intent, target_item_id="card")
    return OrderCommand.create(intent)


def test_valid_order_command_array_passes_schema() -> None:
    commands = [
        command_for(Intent.ADD_ITEM),
        OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id="cafe_latte",
            quantity=1,
            temperature=Temperature.HOT,
        ),
    ]

    validate_order_commands(commands)


def test_all_fifteen_intents_are_supported_by_schema() -> None:
    assert len(Intent) == 15

    for intent in Intent:
        validate_order_commands([command_for(intent)])


def test_request_id_is_auto_generated_uuid4_per_command() -> None:
    first = command_for(Intent.ADD_ITEM)
    second = command_for(Intent.ADD_ITEM)

    assert UUID(first.request_id).version == 4
    assert UUID(second.request_id).version == 4
    assert first.request_id != second.request_id


def test_all_common_fields_are_present_and_unused_fields_are_null() -> None:
    command = OrderCommand.create(Intent.QUERY_CART).to_dict()

    assert command == {
        "request_id": command["request_id"],
        "intent": "QUERY_CART",
        "target_item_id": None,
        "category_id": None,
        "quantity": None,
        "temperature": None,
        "query_tags": None,
        "detail_fields": None,
            "options": None,
            "fulfillment_type": None,
    }


def test_set_fulfillment_is_schema_valid() -> None:
    command = OrderCommand.create(Intent.SET_FULFILLMENT, fulfillment_type="takeout")
    validate_order_commands([command])
    assert command.to_dict()["fulfillment_type"] == "takeout"


def test_nlu_payload_gets_runtime_request_id() -> None:
    payload = {
        "intent": "ADD_ITEM",
        "target_item_id": "americano",
        "category_id": None,
        "quantity": 2,
        "temperature": "iced",
        "query_tags": None,
        "detail_fields": None,
        "options": None,
    }

    command = OrderCommand.from_nlu_payload(payload)

    assert UUID(command.request_id).version == 4
    assert "request_id" not in payload
    validate_order_commands([command])


def test_nlu_payload_rejects_runtime_owned_fields() -> None:
    payload = {
        "request_id": "model-generated-id",
        "intent": "QUERY_CART",
        "target_item_id": None,
        "category_id": None,
        "quantity": None,
        "temperature": None,
        "query_tags": None,
        "detail_fields": None,
        "options": None,
    }

    with pytest.raises(ValueError):
        OrderCommand.from_nlu_payload(payload)


def test_query_menu_can_use_category_id() -> None:
    command = OrderCommand.create(Intent.QUERY_MENU, category_id="coffee")

    validate_order_commands([command])
    assert command.category_id == "coffee"
    assert command.target_item_id is None


def test_query_menu_can_use_tag_filters() -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        category_id="tea",
        query_tags=("caffeine_free", "milk_free"),
    )

    validate_order_commands([command])
    assert command.to_dict()["query_tags"] == ["caffeine_free", "milk_free"]


def test_query_tags_reject_duplicates() -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        query_tags=("milk_free", "milk_free"),
    )

    with pytest.raises(ValidationError):
        validate_order_commands([command])


def test_query_menu_can_request_multiple_detail_fields() -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        target_item_id="cafe_latte",
        detail_fields=("caffeine", "milk"),
    )

    validate_order_commands([command])
    assert command.to_dict()["detail_fields"] == ["caffeine", "milk"]


def test_detail_fields_reject_duplicates() -> None:
    command = OrderCommand.create(
        Intent.QUERY_MENU,
        target_item_id="americano",
        detail_fields=("price", "price"),
    )

    with pytest.raises(ValidationError):
        validate_order_commands([command])


def test_beverage_options_round_trip_and_schema() -> None:
    command = OrderCommand.create(
        Intent.ADD_ITEM,
        target_item_id="americano",
        quantity=1,
        temperature=Temperature.ICED,
        options=BeverageOptions(
            size=BeverageSize.LARGE,
            extra_shots=1,
            caffeine=CaffeineOption.DECAF,
            syrup_pumps=2,
            ice_amount=IceAmount.LESS,
        ),
    )

    validate_order_commands([command])
    assert command.to_dict()["options"] == {
        "size": "large",
        "extra_shots": 1,
        "caffeine": "decaf",
        "syrup_pumps": 2,
        "ice_amount": "less",
    }


def test_beverage_options_reject_extra_field() -> None:
    invalid = command_for(Intent.ADD_ITEM).to_dict()
    invalid["options"] = {
        "size": None,
        "extra_shots": 1,
        "caffeine": None,
        "syrup_pumps": None,
        "ice_amount": None,
        "whipped_cream": True,
    }

    with pytest.raises(ValidationError):
        Draft202012Validator(load_schema()).validate([invalid])


def test_size_enum_round_trip_and_schema() -> None:
    command = OrderCommand.create(
        Intent.ADD_ITEM,
        target_item_id="americano",
        quantity=1,
        temperature=Temperature.ICED,
        options=BeverageOptions(size=BeverageSize.LARGE),
    )

    validate_order_commands([command])
    assert command.to_dict()["options"]["size"] == "large"


def test_confirmation_policy_is_owned_by_order_engine() -> None:
    for intent in Intent:
        assert requires_confirmation([command_for(intent)]) is (
            intent
            in {
                Intent.REMOVE_ITEM,
                Intent.CONFIRM_ORDER,
                Intent.CANCEL,
            }
        )


def test_confirmation_policy_does_not_change_order_command_output() -> None:
    command = command_for(Intent.REMOVE_ITEM)

    assert requires_confirmation([command]) is True
    assert "confirmation_required" not in command.to_dict()


def test_extra_field_is_rejected() -> None:
    invalid = [
        {
            **command_for(Intent.ADD_ITEM).to_dict(),
            "size": "large",
        }
    ]

    with pytest.raises(ValidationError):
        Draft202012Validator(load_schema()).validate(invalid)


def test_missing_common_field_is_rejected() -> None:
    invalid_command = command_for(Intent.ADD_ITEM).to_dict()
    del invalid_command["category_id"]

    with pytest.raises(ValidationError):
        Draft202012Validator(load_schema()).validate([invalid_command])


def test_single_object_instead_of_array_is_rejected() -> None:
    invalid = command_for(Intent.ADD_ITEM).to_dict()

    with pytest.raises(ValidationError):
        Draft202012Validator(load_schema()).validate(invalid)


def test_empty_command_array_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(load_schema()).validate([])


def test_safe_mixed_intents_are_accepted_by_contract_validator() -> None:
    commands = [
        command_for(Intent.ADD_ITEM),
        command_for(Intent.REMOVE_ITEM),
    ]

    validate_order_commands(commands)


def test_unsafe_mixed_intents_are_rejected_by_contract_validator() -> None:
    commands = [
        command_for(Intent.ADD_ITEM),
        command_for(Intent.CONFIRM_ORDER),
    ]

    with pytest.raises(ValidationError):
        validate_order_commands(commands)
