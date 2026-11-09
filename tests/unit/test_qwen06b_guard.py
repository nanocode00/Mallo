from __future__ import annotations

from adapters.nlu.qwen06b_guard import repair_qwen06b_payload
from adapters.nlu.qwen06b_nlu import Qwen06BNLU


def command(
    intent: str,
    *,
    target_item_id=None,
    quantity=None,
    temperature=None,
    options=None,
):
    return {
        "intent": intent,
        "target_item_id": target_item_id,
        "category_id": None,
        "quantity": quantity,
        "temperature": temperature,
        "query_tags": None,
        "detail_fields": None,
        "options": options,
    }


def error(code: str, *, field=None):
    return {
        "code": code,
        "message": "다시 말씀해 주세요.",
        "command_index": None,
        "field": field,
        "candidates": None,
        "retryable": True,
    }


def options(**overrides):
    value = {
        "size": None,
        "extra_shots": None,
        "caffeine": None,
        "syrup_pumps": None,
        "ice_amount": None,
    }
    value.update(overrides)
    return value


def cart(menu_id: str, temperature: str = "hot"):
    return [
        {
            "menu_id": menu_id,
            "quantity": 1,
            "temperature": temperature,
            "options": options(),
        }
    ]


def test_repairs_missing_temperature_in_single_update_option():
    payload = [
        command(
            "UPDATE_OPTION",
            target_item_id="milk_tea",
            temperature=None,
            options=options(size="medium"),
        )
    ]

    repaired = repair_qwen06b_payload(
        "밀크티 차갑게 바꾼 다음 크기는 중간으로 해 줘",
        cart("milk_tea"),
        payload,
    )

    assert repaired[0]["temperature"] == "iced"
    assert repaired[0]["options"]["size"] == "medium"


def test_recovers_explicit_size_and_syrup_update_from_unsupported_error():
    repaired = repair_qwen06b_payload(
        "카페라떼 라지로 바꾸고 시럽 한 번만 넣어 주세요",
        cart("cafe_latte", "iced"),
        error("UNSUPPORTED_UTTERANCE"),
    )

    assert repaired == [
        command(
            "UPDATE_OPTION",
            target_item_id="cafe_latte",
            options=options(size="large", syrup_pumps=1),
        )
    ]


def test_recovers_explicit_temperature_add_from_false_missing_field():
    repaired = repair_qwen06b_payload(
        "따뜻한 아메리카노 한 잔 주세요",
        [],
        error("MISSING_FIELD", field="quantity"),
    )

    assert repaired == [
        command(
            "ADD_ITEM",
            target_item_id="americano",
            quantity=1,
            temperature="hot",
            options=None,
        )
    ]


def test_recovers_missing_temperature_add_without_inventing_a_default():
    payload = error("MISSING_FIELD", field="temperature")
    repaired = repair_qwen06b_payload("아메리카노 한 잔 주세요", [], payload)
    assert repaired == [
        command(
            "ADD_ITEM",
            target_item_id="americano",
            quantity=1,
            temperature=None,
            options=None,
        )
    ]


def test_recovers_new_cart_item_as_add_not_update():
    repaired = repair_qwen06b_payload(
        "아이스티도 하나 주세요",
        cart("americano"),
        [command("UPDATE_QUANTITY", target_item_id="americano", quantity=2, temperature="hot")],
    )

    assert repaired == [
        command(
            "ADD_ITEM",
            target_item_id="iced_tea",
            quantity=1,
            temperature=None,
            options=None,
        )
    ]


def test_recovers_normalized_alias_add_from_unsupported_error():
    repaired = repair_qwen06b_payload(
        "카페라떼 1잔 주세요",
        [],
        error("UNSUPPORTED_UTTERANCE"),
    )

    assert repaired == [command("ADD_ITEM", target_item_id="cafe_latte", quantity=1, temperature=None)]


def test_recovers_explicit_iced_add_from_temperature_ambiguity():
    repaired = repair_qwen06b_payload(
        "아이스 아메리카노 1잔 주세요",
        [],
        error("AMBIGUOUS_TARGET", field="temperature"),
    )

    assert repaired == [command("ADD_ITEM", target_item_id="americano", quantity=1, temperature="iced")]


def test_recovers_non_temperature_menu_from_false_temperature_ambiguity():
    repaired = repair_qwen06b_payload(
        "바스크 치즈 케이크 1개 주세요",
        [],
        error("AMBIGUOUS_TARGET", field="temperature"),
    )

    assert repaired == [command("ADD_ITEM", target_item_id="basque_cheesecake", quantity=1, temperature=None)]


def test_does_not_recover_single_add_from_size_ambiguity():
    payload = error("AMBIGUOUS_TARGET", field="size")

    repaired = repair_qwen06b_payload(
        "아이스 아메리카노 한 잔 주세요",
        [],
        payload,
    )

    assert repaired == payload


def test_recovers_complete_three_item_add_from_invalid_json():
    repaired = repair_qwen06b_payload(
        "카페라떼 2잔, 아이스티 1개, 크로플 아이스크림 1개 주세요",
        [],
        {"code": "INVALID_JSON"},
    )

    assert [(row["target_item_id"], row["quantity"], row["temperature"]) for row in repaired] == [
        ("cafe_latte", 2, None), ("iced_tea", 1, None), ("croffle_icecream", 1, None),
    ]


def test_parse_prediction_recovers_truncated_three_item_add():
    result, repaired = Qwen06BNLU.parse_prediction(
        '[{"intent":"ADD_ITEM","target_item_id":"cafe_latte"',
        text="카페라떼 2잔, 아이스티 1개, 크로플 아이스크림 1개 주세요",
        cart_before=[],
    )

    assert [
        (command.target_item_id, command.quantity, command.temperature.value if command.temperature else None)
        for command in result
    ] == [
        ("cafe_latte", 2, None), ("iced_tea", 1, None), ("croffle_icecream", 1, None),
    ]
    assert [(row["target_item_id"], row["quantity"], row["temperature"]) for row in repaired] == [
        ("cafe_latte", 2, None), ("iced_tea", 1, None), ("croffle_icecream", 1, None),
    ]


def test_does_not_recover_partial_multi_add_from_invalid_json():
    payload = {"code": "INVALID_JSON"}
    repaired = repair_qwen06b_payload("카페라떼 2잔, 아이스티 주세요", [], payload)

    assert repaired == payload


def test_clear_control_plus_mutation_is_mixed_intent():
    repaired = repair_qwen06b_payload(
        "아이스 아메리카노 하나 추가하고 주문 취소해 줘",
        [],
        [command("ADD_ITEM", target_item_id="americano", quantity=1, temperature="iced")],
    )

    assert repaired["code"] == "MIXED_INTENT"


def test_recovers_valid_multi_add_from_false_mixed_intent():
    repaired = repair_qwen06b_payload(
        "따뜻한 바닐라라떼 한 잔이랑 아이스 밀크티 두 잔 주세요",
        [],
        error("MIXED_INTENT"),
    )

    assert repaired == [
        command(
            "ADD_ITEM",
            target_item_id="vanilla_latte",
            quantity=1,
            temperature="hot",
            options=None,
        ),
        command(
            "ADD_ITEM",
            target_item_id="milk_tea",
            quantity=2,
            temperature="iced",
            options=None,
        ),
    ]


def test_does_not_rewrite_ambiguous_pronoun_error():
    payload = error("AMBIGUOUS_TARGET")
    repaired = repair_qwen06b_payload(
        "저거 큰 사이즈로 바꿔 줘",
        cart("americano"),
        payload,
    )
    assert repaired == payload
