import csv
import json
from pathlib import Path

import pytest

from scripts.data.nlu import dataset_tooling
from scripts.data.nlu.dataset_tooling import (
    CSV_COLUMNS,
    DatasetValidationError,
    TARGET_COUNTS,
    build_dataset,
    load_and_validate,
    write_jsonl,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MENU_PATH = REPOSITORY_ROOT / "src/config/menu.json"
ERROR_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/order-command-error.schema.json"
TEMPLATE_PATH = REPOSITORY_ROOT / "data/nlu/raw/nlu-orders.csv"


def command_label(**overrides: object) -> list[dict[str, object]]:
    command: dict[str, object] = {
        "intent": "ADD_ITEM",
        "target_item_id": "americano",
        "category_id": None,
        "quantity": 2,
        "temperature": "iced",
        "query_tags": None,
        "detail_fields": None,
        "options": None,
    }
    command.update(overrides)
    return [command]


def valid_row(sample_id: str = "nlu_000001", **overrides: str) -> dict[str, str]:
    row = {
        "sample_id": sample_id,
        "raw_utterance": "아이스 아메리카노 두 잔 주세요",
        "utterance": "아이스 아메리카노 두 잔 주세요",
        "cart_before_json": "[]",
        "label_type": "commands",
        "label_group": "ADD_ITEM",
        "label_json": json.dumps(command_label(), ensure_ascii=False),
        "menu_version": "1.3",
        "paraphrase_group_id": f"group_{sample_id}",
        "source": "human",
        "split": "train",
        "review_status": "approved",
        "reviewer": "reviewer-a",
        "notes": "",
    }
    row.update(overrides)
    return row


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def validate(path: Path, *, mode: str = "draft"):
    return load_and_validate(path, MENU_PATH, ERROR_SCHEMA_PATH, mode=mode)


def test_dataset_passes_final_after_unsupported_utterance_review() -> None:
    rows = validate(TEMPLATE_PATH)

    assert len(rows) == 3000
    assert sum(row.values["split"] == "train" for row in rows) == 2400
    assert sum(row.values["split"] == "validation" for row in rows) == 300
    assert sum(row.values["split"] == "test" for row in rows) == 300
    assert all(row.values["source"] == "llm_synthetic" for row in rows)
    approved = [row for row in rows if row.values["review_status"] == "approved"]
    reviewed = [
        row
        for row in rows
        if 201 <= int(row.values["sample_id"].removeprefix("nlu_")) <= 571
    ]
    remove_reviewed = [row for row in rows if row.values["label_group"] == "REMOVE_ITEM"]
    quantity_reviewed = [
        row for row in rows if row.values["label_group"] == "UPDATE_QUANTITY"
    ]
    option_reviewed = [row for row in rows if row.values["label_group"] == "UPDATE_OPTION"]
    query_menu_reviewed = [row for row in rows if row.values["label_group"] == "QUERY_MENU"]
    query_cart_reviewed = [row for row in rows if row.values["label_group"] == "QUERY_CART"]
    expanded_remove = [
        row
        for row in remove_reviewed
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 572
    ]
    assert len(approved) == 3000
    assert all(row.values["reviewer"] for row in approved)
    assert all("검수 필요" not in row.values["notes"] for row in approved)
    assert len(reviewed) == 371
    assert all(row.values["label_group"] == "ADD_ITEM" for row in reviewed)
    assert all(row.values["review_status"] == "approved" for row in reviewed)
    assert all(row.values["reviewer"] == "Padong47" for row in reviewed)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in reviewed)
    assert len(remove_reviewed) == 260
    assert len(expanded_remove) == 243
    assert all(row.values["review_status"] == "approved" for row in expanded_remove)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded_remove)
    assert len(quantity_reviewed) == 350
    assert sum(row.values["reviewer"] == "Padong47" for row in quantity_reviewed) == 326
    assert all(row.values["review_status"] == "approved" for row in quantity_reviewed)
    assert len(option_reviewed) == 300
    assert sum(row.values["reviewer"] == "Padong47" for row in option_reviewed) == 280
    assert all(row.values["review_status"] == "approved" for row in option_reviewed)
    assert len(query_menu_reviewed) == 250
    assert all(row.values["reviewer"] == "Padong47" for row in query_menu_reviewed)
    assert len(query_cart_reviewed) == 180
    assert sum(row.values["reviewer"] == "Padong47" for row in query_cart_reviewed) == 168
    assert len(validate(TEMPLATE_PATH, mode="final")) == 3000


def test_query_cart_expansion_reaches_target_with_real_cart_contexts() -> None:
    rows = validate(TEMPLATE_PATH)
    query_cart = [row for row in rows if row.values["label_group"] == "QUERY_CART"]
    expanded = [
        row for row in query_cart
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 1654
    ]

    assert len(query_cart) == 180
    assert len(expanded) == 168
    assert sum(row.values["split"] == "train" for row in query_cart) == 144
    assert sum(row.values["split"] == "validation" for row in query_cart) == 18
    assert sum(row.values["split"] == "test" for row in query_cart) == 18
    assert all(row.cart_before for row in expanded)
    assert len({row.values["cart_before_json"] for row in expanded}) >= 20
    assert sum(len(row.cart_before) > 1 for row in expanded) >= 50
    assert sum(
        any(
            item["options"].get("size") in {"medium", "large"}
            or any(item["options"].get(field) is not None for field in (
                "extra_shots", "caffeine", "syrup_pumps", "ice_amount"
            ))
            for item in row.cart_before
        )
        for row in expanded
    ) >= 50
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)


def test_confirm_order_expansion_reaches_target_with_real_cart_contexts() -> None:
    rows = validate(TEMPLATE_PATH)
    confirm_order = [row for row in rows if row.values["label_group"] == "CONFIRM_ORDER"]
    expanded = [
        row for row in confirm_order
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 1822
    ]
    expected_label = command_label(
        intent="CONFIRM_ORDER",
        target_item_id=None,
        category_id=None,
        quantity=None,
        temperature=None,
        query_tags=None,
        detail_fields=None,
        options=None,
    )

    assert len(confirm_order) == 180
    assert len(expanded) == 168
    assert tuple(
        sum(row.values["split"] == split for row in confirm_order)
        for split in ("train", "validation", "test")
    ) == (144, 18, 18)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (134, 17, 17)
    assert all(row.cart_before for row in expanded)
    assert len({row.values["cart_before_json"] for row in expanded}) >= 20
    assert sum(len(row.cart_before) > 1 for row in expanded) >= 50
    assert sum(
        any(any(value is not None for value in item["options"].values()) for item in row.cart_before)
        for row in expanded
    ) >= 50
    assert all(row.label == expected_label for row in expanded)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())


def test_cancel_expansion_reaches_target_with_real_cart_contexts() -> None:
    rows = validate(TEMPLATE_PATH)
    cancel = [row for row in rows if row.values["label_group"] == "CANCEL"]
    expanded = [
        row for row in cancel
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 1990
    ]
    expected_label = command_label(
        intent="CANCEL",
        target_item_id=None,
        category_id=None,
        quantity=None,
        temperature=None,
        query_tags=None,
        detail_fields=None,
        options=None,
    )

    assert len(cancel) == 140
    assert len(expanded) == 131
    assert tuple(
        sum(row.values["split"] == split for row in cancel)
        for split in ("train", "validation", "test")
    ) == (112, 14, 14)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (105, 13, 13)
    assert all(row.cart_before for row in expanded)
    assert len({row.values["cart_before_json"] for row in expanded}) >= 20
    assert sum(len(row.cart_before) > 1 for row in expanded) >= 40
    assert all(row.label == expected_label for row in expanded)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())


def test_undo_expansion_reaches_target_with_real_cart_contexts() -> None:
    rows = validate(TEMPLATE_PATH)
    undo = [row for row in rows if row.values["label_group"] == "UNDO"]
    expanded = [
        row for row in undo
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 2121
    ]
    expected_label = command_label(
        intent="UNDO",
        target_item_id=None,
        category_id=None,
        quantity=None,
        temperature=None,
        query_tags=None,
        detail_fields=None,
        options=None,
    )

    assert len(undo) == 180
    assert len(expanded) == 168
    assert tuple(
        sum(row.values["split"] == split for row in undo)
        for split in ("train", "validation", "test")
    ) == (144, 18, 18)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (134, 17, 17)
    assert all(row.cart_before for row in expanded)
    assert len({row.values["cart_before_json"] for row in expanded}) >= 20
    assert sum(len(row.cart_before) > 1 for row in expanded) >= 50
    assert all(row.label == expected_label for row in expanded)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)
    utterances = {row.values["utterance"] for row in expanded}
    assert "방금 잔 수를 바꾼 걸 없던 일로 해 주세요" in utterances
    assert "방금 잔 수 바꾼 걸 없던 일로 해 주세요" not in utterances

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())


def test_request_repeat_expansion_reaches_target_without_speed_overlap() -> None:
    rows = validate(TEMPLATE_PATH)
    request_repeat = [
        row for row in rows if row.values["label_group"] == "REQUEST_REPEAT"
    ]
    expanded = [
        row
        for row in request_repeat
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 2289
    ]
    expected_label = command_label(
        intent="REQUEST_REPEAT",
        target_item_id=None,
        category_id=None,
        quantity=None,
        temperature=None,
        query_tags=None,
        detail_fields=None,
        options=None,
    )

    assert len(request_repeat) == 120
    assert len(expanded) == 112
    assert tuple(
        sum(row.values["split"] == split for row in request_repeat)
        for split in ("train", "validation", "test")
    ) == (96, 12, 12)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (90, 11, 11)
    assert all(row.cart_before == [] for row in expanded)
    assert all(row.label == expected_label for row in expanded)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)
    utterances = {row.values["utterance"] for row in expanded}
    assert len(utterances) == 112
    assert "방금 말씀을 다시 해 주세요" in utterances
    assert "방금 안내를 다시 해 주세요" in utterances
    assert all(
        forbidden not in utterance
        for utterance in utterances
        for forbidden in ("말씀를", "안내을", "설명를", "내용는")
    )
    assert all(
        speed_word not in utterance
        for utterance in utterances
        for speed_word in ("천천히", "느리게", "속도")
    )

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())


def test_request_slower_expansion_reaches_target_without_repeat_overlap() -> None:
    rows = validate(TEMPLATE_PATH)
    request_slower = [
        row for row in rows if row.values["label_group"] == "REQUEST_SLOWER"
    ]
    expanded = [
        row
        for row in request_slower
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 2401
    ]
    expected_label = command_label(
        intent="REQUEST_SLOWER",
        target_item_id=None,
        category_id=None,
        quantity=None,
        temperature=None,
        query_tags=None,
        detail_fields=None,
        options=None,
    )

    assert len(request_slower) == 120
    assert len(expanded) == 112
    assert tuple(
        sum(row.values["split"] == split for row in request_slower)
        for split in ("train", "validation", "test")
    ) == (96, 12, 12)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (90, 11, 11)
    assert all(row.cart_before == [] for row in expanded)
    assert all(row.label == expected_label for row in expanded)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)
    utterances = {row.values["utterance"] for row in expanded}
    assert len(utterances) == 112
    assert "말씀 속도를 조금 낮춰 주세요" in utterances
    assert "안내를 너무 빨라요" not in utterances
    assert all(
        forbidden not in utterance
        for utterance in utterances
        for forbidden in ("말씀를", "안내을", "속도을", "목소리는 낮춰")
    )
    assert all(
        repeat_word not in utterance
        for utterance in utterances
        for repeat_word in ("다시", "한 번 더", "반복")
    )

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())


def test_request_default_speed_expansion_reaches_target_with_reset_markers() -> None:
    rows = validate(TEMPLATE_PATH)
    request_default_speed = [
        row for row in rows if row.values["label_group"] == "REQUEST_DEFAULT_SPEED"
    ]
    expanded = [
        row
        for row in request_default_speed
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 2513
    ]
    expected_label = command_label(
        intent="REQUEST_DEFAULT_SPEED",
        target_item_id=None,
        category_id=None,
        quantity=None,
        temperature=None,
        query_tags=None,
        detail_fields=None,
        options=None,
    )

    assert len(request_default_speed) == 120
    assert len(expanded) == 112
    assert tuple(
        sum(row.values["split"] == split for row in request_default_speed)
        for split in ("train", "validation", "test")
    ) == (96, 12, 12)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (90, 11, 11)
    assert all(row.cart_before == [] for row in expanded)
    assert all(row.label == expected_label for row in expanded)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)
    utterances = {row.values["utterance"] for row in expanded}
    assert len(utterances) == 112
    assert "말씀 속도를 원래 상태로 돌려 주세요" in utterances
    assert "기본 말하기 속도로 바꿔 주세요" in utterances
    reset_markers = (
        "원래", "기본", "보통", "평소", "정상", "표준", "초기", "처음",
        "일반", "기존", "평범", "평상시", "변경 전", "조절 전", "해제",
        "취소", "종료", "끝내", "변경하기 전", "바꾸기 전",
    )
    assert all(any(marker in utterance for marker in reset_markers) for utterance in utterances)
    assert all(
        repeat_word not in utterance
        for utterance in utterances
        for repeat_word in ("한 번 더", "반복해", "다시 들려")
    )

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())


def test_missing_field_expansion_reaches_target_without_slot_leakage() -> None:
    rows = validate(TEMPLATE_PATH)
    missing_field = [
        row for row in rows if row.values["label_group"] == "MISSING_FIELD"
    ]
    expanded = [
        row
        for row in missing_field
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 2625
    ]

    assert len(missing_field) == 120
    assert len(expanded) == 112
    assert tuple(
        sum(row.values["split"] == split for row in missing_field)
        for split in ("train", "validation", "test")
    ) == (96, 12, 12)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (90, 11, 11)
    assert all(row.cart_before == [] for row in expanded)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)
    assert len({row.values["utterance"] for row in expanded}) == 112

    by_field = {
        field: [row for row in expanded if row.label["field"] == field]
        for field in ("temperature", "quantity", "target_item_id")
    }
    assert {field: len(field_rows) for field, field_rows in by_field.items()} == {
        "temperature": 37,
        "quantity": 37,
        "target_item_id": 38,
    }
    temperature_words = ("따뜻", "뜨거", "핫", "차가", "아이스", "시원")
    quantity_words = ("한 잔", "두 잔", "세 잔", "네 잔", "다섯 잔", "하나", "두 개")
    menu_names = (
        "아메리카노", "카페라떼", "바닐라라떼", "자몽에이드", "말차라떼",
        "밀크티", "캐모마일티", "아이스티", "크로플 아이스크림",
        "바스크 치즈 케이크",
    )
    assert all(
        not any(word in row.values["utterance"] for word in temperature_words)
        for row in by_field["temperature"]
    )
    assert all(
        not any(word in row.values["utterance"] for word in quantity_words)
        for row in by_field["quantity"]
    )
    assert all(
        not any(menu in row.values["utterance"] for menu in menu_names)
        for row in by_field["target_item_id"]
    )
    assert all(
        any(word in row.values["utterance"] for word in temperature_words)
        and any(word in row.values["utterance"] for word in quantity_words)
        for row in by_field["target_item_id"]
    )
    assert all(
        forbidden not in row.values["utterance"]
        for row in expanded
        for forbidden in ("메뉴를", "음료를를", "잔을를", "케이크를를")
    )

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())


def test_ambiguous_target_expansion_reaches_target_with_cart_candidates() -> None:
    rows = validate(TEMPLATE_PATH)
    ambiguous = [
        row for row in rows if row.values["label_group"] == "AMBIGUOUS_TARGET"
    ]
    expanded = [
        row
        for row in ambiguous
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 2737
    ]

    assert len(ambiguous) == 120
    assert len(expanded) == 112
    assert tuple(
        sum(row.values["split"] == split for row in ambiguous)
        for split in ("train", "validation", "test")
    ) == (96, 12, 12)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (90, 11, 11)
    assert all(len(row.cart_before) == 2 for row in expanded)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)
    assert len({row.values["utterance"] for row in expanded}) == 112

    by_field = {
        field: [row for row in expanded if row.label["field"] == field]
        for field in ("temperature", "target_item_id")
    }
    assert {field: len(field_rows) for field, field_rows in by_field.items()} == {
        "temperature": 56,
        "target_item_id": 56,
    }
    temperature_words = ("따뜻", "뜨거", "핫", "차가", "아이스", "시원")
    assert all(
        row.label["candidates"] == ["hot", "iced"]
        and {item["temperature"] for item in row.cart_before} == {"hot", "iced"}
        and len({item["menu_id"] for item in row.cart_before}) == 1
        and not any(word in row.values["utterance"] for word in temperature_words)
        for row in by_field["temperature"]
    )
    menu_names = {
        item["id"]: item["name"]
        for item in json.loads(MENU_PATH.read_text(encoding="utf-8"))["items"]
    }
    assert all(
        set(row.label["candidates"])
        == {item["menu_id"] for item in row.cart_before}
        and not any(
            menu_names[candidate] in row.values["utterance"]
            for candidate in row.label["candidates"]
        )
        for row in by_field["target_item_id"]
    )
    ice_option_rows = [
        row for row in by_field["target_item_id"] if "얼음" in row.values["utterance"]
    ]
    assert len(ice_option_rows) == 6
    assert all(
        all(item["temperature"] == "iced" for item in row.cart_before)
        for row in ice_option_rows
    )
    assert all(
        forbidden not in row.values["utterance"]
        for row in expanded
        for forbidden in ("아메리카노을", "라떼을", "밀크티을", "메뉴를를", "수량을을")
    )

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())

    temperature_menu_splits: dict[str, set[str]] = {}
    for row in (row for row in ambiguous if row.label["field"] == "temperature"):
        menu_id = row.cart_before[0]["menu_id"]
        temperature_menu_splits.setdefault(menu_id, set()).add(row.values["split"])
    assert all(len(splits) == 1 for splits in temperature_menu_splits.values())

    def semantic_action(utterance: str) -> str:
        if "시럽" in utterance:
            if "없이" in utterance or "빼" in utterance:
                return "syrup_none"
            if "두" in utterance or "2" in utterance:
                return "syrup_2"
            return "syrup_1"
        if "샷" in utterance:
            return "shot_2" if "두" in utterance or "2" in utterance else "shot_1"
        if "디카페인" in utterance or "카페인" in utterance:
            return "caffeine_regular" if "일반" in utterance else "caffeine_decaf"
        if "사이즈" in utterance:
            if "큰" in utterance or "크게" in utterance:
                return "size_large"
            if "중간" in utterance:
                return "size_medium"
            return "size_small"
        if "얼음" in utterance:
            if "적게" in utterance or "조금" in utterance:
                return "ice_less"
            if "많이" in utterance or "많게" in utterance:
                return "ice_more"
            return "ice_normal"
        if any(marker in utterance for marker in ("빼", "삭제", "취소")):
            return "delete"
        quantity_markers = {
            "quantity_1": ("한 잔", "한 개", "하나", "한 잔"),
            "quantity_2": ("두 잔", "두 개"),
            "quantity_3": ("세 잔", "세 개"),
            "quantity_4": ("네 잔", "네 개"),
        }
        for quantity, markers in quantity_markers.items():
            if any(marker in utterance for marker in markers):
                return quantity
        return "delete"

    semantic_splits: dict[tuple[str, tuple[str, ...], str], set[str]] = {}
    for row in ambiguous:
        identity = (
            row.cart_before[0]["menu_id"],
        ) if row.label["field"] == "temperature" else tuple(row.label["candidates"])
        key = (row.label["field"], identity, semantic_action(row.values["utterance"]))
        semantic_splits.setdefault(key, set()).add(row.values["split"])
    leaking_semantics = {
        key: splits for key, splits in semantic_splits.items() if len(splits) != 1
    }
    assert not leaking_semantics, leaking_semantics


def test_mixed_intent_expansion_reaches_target_with_unsafe_combinations() -> None:
    rows = validate(TEMPLATE_PATH)
    mixed = [row for row in rows if row.values["label_group"] == "MIXED_INTENT"]
    expanded = [
        row
        for row in mixed
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 2849
    ]

    assert len(mixed) == 80
    assert len(expanded) == 77
    assert tuple(
        sum(row.values["split"] == split for row in mixed)
        for split in ("train", "validation", "test")
    ) == (64, 8, 8)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (63, 7, 7)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)
    assert len({row.values["utterance"] for row in expanded}) == 77
    assert all(
        row.label
        == {
            "code": "MIXED_INTENT",
            "message": "사용자의 주문을 이해하지 못했습니다. 한 번에 하나씩 주문해 주시면 감사하겠습니다.",
            "command_index": None,
            "field": None,
            "candidates": None,
            "retryable": True,
        }
        for row in expanded
    )
    unsafe_markers = (
        "결제", "확정", "전부 취소", "전체 주문", "되돌", "마지막 변경",
        "방금 변경", "방금 한 변경", "추천", "메뉴 종류", "다른 메뉴",
        "다시 말", "다시 들려", "한 번 더", "반복", "기본", "원래 말하기",
        "원래대로", "천천히", "느리게", "느린 속도",
    )
    missing_unsafe_markers = [
        row.values["sample_id"]
        for row in expanded
        if not any(marker in row.values["utterance"] for marker in unsafe_markers)
    ]
    assert not missing_unsafe_markers, missing_unsafe_markers
    assert all(
        any(marker in row.values["utterance"] for marker in ("하고", "고 ", "뒤", "다음", "까지"))
        for row in expanded
    )
    assert all(
        forbidden not in row.values["utterance"]
        for row in expanded
        for forbidden in ("주문을를", "메뉴을", "안내을", "속도을", "라떼을")
    )

    group_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_splits.setdefault(row.values["paraphrase_group_id"], set()).add(
            row.values["split"]
        )
    assert all(len(splits) == 1 for splits in group_splits.values())

    def intent_signature(utterance: str) -> frozenset[str]:
        intents = set()
        if any(marker in utterance for marker in ("담고", "담은", "추가한", "한 잔 추가")):
            intents.add("ADD_ITEM")
        if any(marker in utterance for marker in ("빼고", "삭제한", "주문에서 빼")):
            intents.add("REMOVE_ITEM")
        if any(marker in utterance for marker in ("수량", "잔으로")):
            intents.add("UPDATE_QUANTITY")
        if any(marker in utterance for marker in ("샷", "시럽", "얼음", "사이즈", "디카페인")):
            intents.add("UPDATE_OPTION")
        if "현재 주문" in utterance or "장바구니" in utterance:
            intents.add("QUERY_CART")
        if "추천" in utterance or "메뉴 종류" in utterance or "다른 메뉴" in utterance:
            intents.add("QUERY_MENU")
        if "결제" in utterance or "확정" in utterance:
            intents.add("CONFIRM_ORDER")
        if "전부 취소" in utterance or "전체 주문" in utterance:
            intents.add("CANCEL_ORDER")
        if any(marker in utterance for marker in ("되돌", "마지막 변경", "방금 변경", "방금 한 변경")):
            intents.add("UNDO")
        if any(marker in utterance for marker in ("다시 말", "다시 들려", "한 번 더", "반복")):
            intents.add("REQUEST_REPEAT")
        if "천천히" in utterance or "느리게" in utterance or "느린 속도" in utterance:
            intents.add("REQUEST_SLOWER")
        if "기본" in utterance or "원래 말하기" in utterance or "원래대로" in utterance:
            intents.add("REQUEST_DEFAULT_SPEED")
        return frozenset(intents)

    semantic_splits: dict[frozenset[str], set[str]] = {}
    for row in mixed:
        signature = intent_signature(row.values["utterance"])
        assert len(signature) >= 2, row.values["sample_id"]
        semantic_splits.setdefault(signature, set()).add(row.values["split"])
    leaking_semantics = {
        signature: splits
        for signature, splits in semantic_splits.items()
        if len(splits) != 1
    }
    assert not leaking_semantics, leaking_semantics


def test_unsupported_utterance_expansion_reaches_target_with_three_error_types() -> None:
    rows = validate(TEMPLATE_PATH)
    unsupported = [
        row for row in rows if row.values["label_group"] == "UNSUPPORTED_UTTERANCE"
    ]
    expanded = [
        row
        for row in unsupported
        if int(row.values["sample_id"].removeprefix("nlu_")) >= 2926
    ]

    assert len(unsupported) == 80
    assert len(expanded) == 75
    assert tuple(
        sum(row.values["split"] == split for row in unsupported)
        for split in ("train", "validation", "test")
    ) == (64, 8, 8)
    assert tuple(
        sum(row.values["split"] == split for row in expanded)
        for split in ("train", "validation", "test")
    ) == (61, 7, 7)
    assert all(row.values["raw_utterance"] == row.values["utterance"] for row in expanded)
    assert all(row.values["review_status"] == "approved" for row in expanded)
    assert all(row.values["reviewer"] == "Padong47" for row in expanded)
    assert all(row.values["notes"].endswith("사람 검수 완료") for row in expanded)
    assert len({row.values["utterance"] for row in expanded}) == 75
    assert all(
        row.label
        == {
            "code": "UNSUPPORTED_UTTERANCE",
            "message": "죄송합니다. 메뉴 이름과 수량을 다시 말씀해 주세요.",
            "command_index": None,
            "field": None,
            "candidates": None,
            "retryable": True,
        }
        for row in expanded
    )

    error_types = {
        error_type: [
            row
            for row in expanded
            if f"_{error_type}_" in row.values["paraphrase_group_id"]
        ]
        for error_type in ("off_domain", "unknown", "invalid")
    }
    assert {error_type: len(group) for error_type, group in error_types.items()} == {
        "off_domain": 25,
        "unknown": 25,
        "invalid": 25,
    }
    assert all(
        any(marker in row.values["utterance"] for marker in ("영 ", "0", "마이너스", "영하"))
        for row in error_types["invalid"]
    )
    assert all(
        forbidden not in row.values["utterance"]
        for row in expanded
        for forbidden in (
            "메뉴을", "수량을을", "라떼을", "케이크을", "아이스크림를",
            "주스을", "샌드위치을", "도넛을", "타코을",
        )
    )

    group_splits: dict[str, set[str]] = {}
    topic_splits: dict[str, set[str]] = {}
    for row in expanded:
        group_id = row.values["paraphrase_group_id"]
        split = row.values["split"]
        group_splits.setdefault(group_id, set()).add(split)
        topic = group_id.split("_", 2)[2]
        topic_splits.setdefault(topic, set()).add(split)
    assert all(len(splits) == 1 for splits in group_splits.values())
    assert all(len(splits) == 1 for splits in topic_splits.values())


def test_final_mode_accepts_exact_configured_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dataset_tooling, "TARGET_COUNTS", {"ADD_ITEM": (1, 0, 0)})
    rows = validate(write_csv(tmp_path / "dataset.csv", [valid_row()]), mode="final")
    assert len(rows) == 1


def test_target_distribution_is_3000_with_80_10_10_split() -> None:
    totals = tuple(sum(counts[index] for counts in TARGET_COUNTS.values()) for index in range(3))
    assert totals == (2400, 300, 300)
    assert TARGET_COUNTS["ADD_ITEM"] == (320, 40, 40)
    assert TARGET_COUNTS["REMOVE_ITEM"] == (208, 26, 26)
    assert TARGET_COUNTS["QUERY_CART"] == (144, 18, 18)
    assert TARGET_COUNTS["CONFIRM_ORDER"] == (144, 18, 18)
    assert TARGET_COUNTS["CANCEL"] == (112, 14, 14)
    assert TARGET_COUNTS["UNDO"] == (144, 18, 18)


@pytest.mark.parametrize(
    ("intent", "target", "category", "quantity", "temperature"),
    [
        ("ADD_ITEM", "americano", None, 2, "iced"),
        ("REMOVE_ITEM", "americano", None, None, "iced"),
        ("UPDATE_QUANTITY", "americano", None, 3, "iced"),
        ("UPDATE_OPTION", "americano", None, None, "hot"),
        ("QUERY_MENU", None, "coffee", None, None),
        ("QUERY_CART", None, None, None, None),
        ("CONFIRM_ORDER", None, None, None, None),
        ("CANCEL", None, None, None, None),
        ("UNDO", None, None, None, None),
        ("REQUEST_REPEAT", None, None, None, None),
        ("REQUEST_SLOWER", None, None, None, None),
        ("REQUEST_DEFAULT_SPEED", None, None, None, None),
    ],
)
def test_accepts_all_supported_intent_payloads(
    tmp_path: Path,
    intent: str,
    target: str | None,
    category: str | None,
    quantity: int | None,
    temperature: str | None,
) -> None:
    label = command_label(
        intent=intent,
        target_item_id=target,
        category_id=category,
        quantity=quantity,
        temperature=temperature,
    )
    row = valid_row(label_group=intent, label_json=json.dumps(label, ensure_ascii=False))
    assert len(validate(write_csv(tmp_path / "dataset.csv", [row]))) == 1


def test_accepts_safe_mixed_commands_grouped_by_first_intent(tmp_path: Path) -> None:
    cart = [
        {
            "menu_id": "cafe_latte",
            "quantity": 1,
            "temperature": "iced",
            "options": {
                "extra_shots": None,
                "caffeine": None,
                "syrup_pumps": None,
                "ice_amount": None,
            },
        }
    ]
    label = [
        command_label(
            intent="REMOVE_ITEM",
            target_item_id="cafe_latte",
            quantity=None,
            temperature="iced",
        )[0],
        command_label(
            intent="ADD_ITEM",
            target_item_id="americano",
            quantity=1,
            temperature="iced",
        )[0],
        command_label(
            intent="QUERY_CART",
            target_item_id=None,
            quantity=None,
            temperature=None,
        )[0],
    ]
    row = valid_row(
        cart_before_json=json.dumps(cart, ensure_ascii=False),
        label_group="REMOVE_ITEM",
        label_json=json.dumps(label, ensure_ascii=False),
    )

    assert len(validate(write_csv(tmp_path / "mixed.csv", [row]))) == 1


def test_rejects_mixed_change_target_missing_from_initial_cart(tmp_path: Path) -> None:
    label = [
        command_label(
            intent="ADD_ITEM",
            target_item_id="americano",
            quantity=1,
            temperature="iced",
        )[0],
        command_label(
            intent="UPDATE_QUANTITY",
            target_item_id="americano",
            quantity=2,
            temperature="iced",
        )[0],
    ]
    row = valid_row(
        label_group="ADD_ITEM",
        label_json=json.dumps(label, ensure_ascii=False),
    )

    with pytest.raises(DatasetValidationError, match="Cart에서 하나로 식별"):
        validate(write_csv(tmp_path / "mixed-missing-target.csv", [row]))


def test_build_writes_approved_row_without_runtime_request_id(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "dataset.csv", [valid_row()])
    rows, outputs = build_dataset(
        csv_path,
        tmp_path / "processed",
        MENU_PATH,
        ERROR_SCHEMA_PATH,
        mode="draft",
    )
    assert len(rows) == 1
    record = json.loads(outputs["train"].read_text(encoding="utf-8"))
    assert record["output"]["value"] == command_label()
    assert "request_id" not in record["output"]["value"][0]
    assert outputs["validation"].read_text(encoding="utf-8") == ""
    assert outputs["test"].read_text(encoding="utf-8") == ""


def test_final_dataset_build_is_complete_ordered_and_reproducible(tmp_path: Path) -> None:
    rows, first_outputs = build_dataset(
        TEMPLATE_PATH,
        tmp_path / "first",
        MENU_PATH,
        ERROR_SCHEMA_PATH,
        mode="final",
    )
    _, second_outputs = build_dataset(
        TEMPLATE_PATH,
        tmp_path / "second",
        MENU_PATH,
        ERROR_SCHEMA_PATH,
        mode="final",
    )

    assert len(rows) == 3000
    expected_counts = {"train": 2400, "validation": 300, "test": 300}
    for split, expected_count in expected_counts.items():
        first_bytes = first_outputs[split].read_bytes()
        assert first_bytes == second_outputs[split].read_bytes()
        records = [json.loads(line) for line in first_bytes.decode("utf-8").splitlines()]
        expected_ids = [
            row.values["sample_id"] for row in rows if row.values["split"] == split
        ]
        assert len(records) == expected_count
        assert [record["sample_id"] for record in records] == expected_ids
        assert all(set(record) == {"sample_id", "input", "output", "metadata"} for record in records)
        assert all(set(record["input"]) == {"utterance", "cart_before"} for record in records)
        assert all(set(record["output"]) == {"type", "value"} for record in records)
        assert all(
            set(record["metadata"]) == {"label_group", "menu_version", "source", "split"}
            for record in records
        )
        assert all(
            record["metadata"]["split"] == split
            for record in records
        )


def test_pending_row_is_valid_in_draft_but_not_generated(tmp_path: Path) -> None:
    row = valid_row(review_status="pending", reviewer="")
    rows = validate(write_csv(tmp_path / "dataset.csv", [row]))
    outputs = write_jsonl(rows, tmp_path / "processed")
    assert all(path.read_text(encoding="utf-8") == "" for path in outputs.values())


def test_rejects_unknown_menu_and_extra_command_field(tmp_path: Path) -> None:
    unknown = valid_row(
        label_json=json.dumps(command_label(target_item_id="unknown"), ensure_ascii=False)
    )
    extra_payload = command_label()
    extra_payload[0]["price"] = 4700
    extra = valid_row("nlu_000002", label_json=json.dumps(extra_payload, ensure_ascii=False))
    with pytest.raises(DatasetValidationError) as error:
        validate(write_csv(tmp_path / "dataset.csv", [unknown, extra]))
    assert "2행: 공식 Menu ID 오류" in str(error.value)
    assert "3행: Command는 의미 필드 8개" in str(error.value)


def test_accepts_supported_beverage_options_and_rejects_menu_policy(
    tmp_path: Path,
) -> None:
    valid = valid_row(
        label_json=json.dumps(
            command_label(
                options={
                    "size": "large",
                    "extra_shots": 1,
                    "caffeine": "decaf",
                    "syrup_pumps": 1,
                    "ice_amount": "less",
                }
            ),
            ensure_ascii=False,
        )
    )
    assert len(validate(write_csv(tmp_path / "valid-options.csv", [valid]))) == 1

    invalid = valid_row(
        label_json=json.dumps(
            command_label(
                target_item_id="basque_cheesecake",
                temperature=None,
                options={
                    "extra_shots": 1,
                    "caffeine": None,
                    "syrup_pumps": None,
                    "ice_amount": None,
                },
            ),
            ensure_ascii=False,
        )
    )
    with pytest.raises(DatasetValidationError, match="샷 옵션 정책"):
        validate(write_csv(tmp_path / "invalid-options.csv", [invalid]))


def test_cart_context_preserves_options_for_update_option(tmp_path: Path) -> None:
    cart = [
        {
            "menu_id": "americano",
            "quantity": 1,
            "temperature": "iced",
            "options": {
                "extra_shots": 1,
                "caffeine": None,
                "syrup_pumps": None,
                "ice_amount": None,
            },
        }
    ]
    label = command_label(
        intent="UPDATE_OPTION",
        quantity=None,
        temperature=None,
        options={
            "extra_shots": None,
            "caffeine": None,
            "syrup_pumps": 1,
            "ice_amount": None,
        },
    )
    row = valid_row(
        raw_utterance="시럽 한 번 넣어줘",
        utterance="시럽 한 번 넣어줘",
        cart_before_json=json.dumps(cart, ensure_ascii=False),
        label_group="UPDATE_OPTION",
        label_json=json.dumps(label, ensure_ascii=False),
    )

    parsed = validate(write_csv(tmp_path / "cart-options.csv", [row]))[0]

    assert parsed.cart_before == cart


def test_accepts_registered_query_tags_and_rejects_unknown_tag(tmp_path: Path) -> None:
    valid_label = command_label(
        intent="QUERY_MENU",
        target_item_id=None,
        category_id="tea",
        quantity=None,
        temperature=None,
        query_tags=["caffeine_free", "milk_free"],
    )
    valid = valid_row(
        label_group="QUERY_MENU",
        label_json=json.dumps(valid_label, ensure_ascii=False),
    )
    assert len(validate(write_csv(tmp_path / "valid.csv", [valid]))) == 1

    invalid_label = command_label(
        intent="QUERY_MENU",
        target_item_id=None,
        quantity=None,
        temperature=None,
        query_tags=["unknown_tag"],
    )
    invalid = valid_row(
        label_group="QUERY_MENU",
        label_json=json.dumps(invalid_label, ensure_ascii=False),
    )
    with pytest.raises(DatasetValidationError, match="query_tags"):
        validate(write_csv(tmp_path / "invalid.csv", [invalid]))


def test_accepts_menu_detail_fields_and_requires_target(tmp_path: Path) -> None:
    valid_label = command_label(
        intent="QUERY_MENU",
        target_item_id="cafe_latte",
        quantity=None,
        temperature=None,
        detail_fields=["caffeine", "milk"],
    )
    valid = valid_row(
        label_group="QUERY_MENU",
        label_json=json.dumps(valid_label, ensure_ascii=False),
    )
    assert len(validate(write_csv(tmp_path / "valid-detail.csv", [valid]))) == 1

    invalid_label = command_label(
        intent="QUERY_MENU",
        target_item_id=None,
        quantity=None,
        temperature=None,
        detail_fields=["price"],
    )
    invalid = valid_row(
        label_group="QUERY_MENU",
        label_json=json.dumps(invalid_label, ensure_ascii=False),
    )
    with pytest.raises(DatasetValidationError, match="target_item_id"):
        validate(write_csv(tmp_path / "invalid-detail.csv", [invalid]))


def test_rejects_temperature_missing_from_add_item(tmp_path: Path) -> None:
    row = valid_row(label_json=json.dumps(command_label(temperature=None), ensure_ascii=False))
    with pytest.raises(DatasetValidationError, match="temperature가 필요"):
        validate(write_csv(tmp_path / "dataset.csv", [row]))


@pytest.mark.parametrize(
    ("menu_name", "expected"),
    [("아메리카노", "와"), ("레몬", "과")],
)
def test_selects_korean_and_particle(menu_name: str, expected: str) -> None:
    assert dataset_tooling._korean_and_particle(menu_name) == expected


def test_accepts_fixed_temperature_error_message(tmp_path: Path) -> None:
    error_label = {
        "code": "MISSING_FIELD",
        "message": "아메리카노의 온도를 따뜻한 걸 원하시나요, 차가운 걸 원하시나요?",
        "command_index": 0,
        "field": "temperature",
        "candidates": ["hot", "iced"],
        "retryable": True,
    }
    row = valid_row(
        raw_utterance="아메리카노 한 잔 주세요",
        utterance="아메리카노 한 잔 주세요",
        label_type="error",
        label_group="MISSING_FIELD",
        label_json=json.dumps(error_label, ensure_ascii=False),
    )
    assert validate(write_csv(tmp_path / "dataset.csv", [row]))[0].label == error_label


def test_rejects_free_form_error_message(tmp_path: Path) -> None:
    error_label = {
        "code": "MISSING_FIELD",
        "message": "온도를 다시 말해 주세요.",
        "command_index": 0,
        "field": "temperature",
        "candidates": ["hot", "iced"],
        "retryable": True,
    }
    row = valid_row(
        raw_utterance="아메리카노 한 잔 주세요",
        utterance="아메리카노 한 잔 주세요",
        label_type="error",
        label_group="MISSING_FIELD",
        label_json=json.dumps(error_label, ensure_ascii=False),
    )
    with pytest.raises(DatasetValidationError, match="고정 message Template"):
        validate(write_csv(tmp_path / "dataset.csv", [row]))


def test_rejects_duplicate_and_split_leakage(tmp_path: Path) -> None:
    duplicate = valid_row("nlu_000002", paraphrase_group_id="other")
    with pytest.raises(DatasetValidationError, match="완전 중복"):
        validate(write_csv(tmp_path / "duplicate.csv", [valid_row(), duplicate]))

    second = valid_row(
        "nlu_000002",
        raw_utterance="아메리카노 두 잔 부탁해요",
        utterance="아메리카노 두 잔 부탁해요",
        paraphrase_group_id="different_semantic_group",
        split="test",
    )
    with pytest.raises(DatasetValidationError, match="Split 누수"):
        validate(write_csv(tmp_path / "leakage.csv", [valid_row(), second]))


def test_rejects_update_option_semantic_split_leakage(tmp_path: Path) -> None:
    cart = [{
        "menu_id": "americano",
        "quantity": 1,
        "temperature": "iced",
        "options": {
            "size": "small", "extra_shots": None, "caffeine": None,
            "syrup_pumps": None, "ice_amount": None,
        },
    }]
    label = command_label(
        intent="UPDATE_OPTION",
        quantity=None,
        temperature=None,
        options={
            "size": "medium", "extra_shots": None, "caffeine": None,
            "syrup_pumps": None, "ice_amount": None,
        },
    )
    common = {
        "cart_before_json": json.dumps(cart, ensure_ascii=False),
        "label_group": "UPDATE_OPTION",
        "label_json": json.dumps(label, ensure_ascii=False),
    }
    first = valid_row(raw_utterance="미디엄으로 바꿔 줘", utterance="미디엄으로 바꿔 줘", **common)
    second = valid_row(
        "nlu_000002",
        raw_utterance="중간 사이즈로 변경해 줘",
        utterance="중간 사이즈로 변경해 줘",
        paraphrase_group_id="other_update_option_group",
        split="test",
        **common,
    )

    with pytest.raises(DatasetValidationError, match="UPDATE_OPTION 의미 그룹"):
        validate(write_csv(tmp_path / "option-leakage.csv", [first, second]))


def test_rejects_query_menu_semantic_split_leakage(tmp_path: Path) -> None:
    label = command_label(
        intent="QUERY_MENU", target_item_id="americano", quantity=None,
        temperature=None, detail_fields=["price"],
    )
    common = {
        "label_group": "QUERY_MENU",
        "label_json": json.dumps(label, ensure_ascii=False),
    }
    first = valid_row(raw_utterance="아메리카노 가격 알려 주세요", utterance="아메리카노 가격 알려 주세요", **common)
    second = valid_row(
        "nlu_000002", raw_utterance="아메리카노 얼마예요", utterance="아메리카노 얼마예요",
        paraphrase_group_id="other_query_menu_group", split="test", **common,
    )

    with pytest.raises(DatasetValidationError, match="QUERY_MENU 의미 그룹"):
        validate(write_csv(tmp_path / "query-menu-leakage.csv", [first, second]))


def test_dataset_menu_names_use_correct_korean_particles() -> None:
    rows = validate(TEMPLATE_PATH)
    menu_names = [
        item["name"] for item in json.loads(MENU_PATH.read_text(encoding="utf-8"))["items"]
    ]
    pairs = (("은", "는"), ("이", "가"), ("을", "를"), ("과", "와"), ("이랑", "랑"))
    invalid = []
    for row in rows:
        for field in ("raw_utterance", "utterance"):
            for name in menu_names:
                index = ord(name[-1]) - ord("가")
                final = index % 28 if 0 <= index <= 11171 else 0
                particles = [vowel if final else consonant for consonant, vowel in pairs]
                particles.append("로" if final and final != 8 else "으로")
                invalid.extend(
                    f"{row.values['sample_id']}:{field}:{name}{particle}"
                    for particle in particles if f"{name}{particle}" in row.values[field]
                )
    assert invalid == []


def test_validation_failure_preserves_existing_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "processed"
    output.mkdir()
    for split in ("train", "validation", "test"):
        (output / f"{split}.jsonl").write_text(f"old-{split}", encoding="utf-8")
    invalid = valid_row(label_json=json.dumps(command_label(target_item_id="unknown")))
    csv_path = write_csv(tmp_path / "invalid.csv", [invalid])
    with pytest.raises(DatasetValidationError):
        build_dataset(csv_path, output, MENU_PATH, ERROR_SCHEMA_PATH)
    for split in ("train", "validation", "test"):
        assert (output / f"{split}.jsonl").read_text(encoding="utf-8") == f"old-{split}"


def test_repeated_build_is_byte_identical(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "dataset.csv", [valid_row()])
    output = tmp_path / "processed"
    _, first = build_dataset(csv_path, output, MENU_PATH, ERROR_SCHEMA_PATH)
    first_bytes = {split: path.read_bytes() for split, path in first.items()}
    _, second = build_dataset(csv_path, output, MENU_PATH, ERROR_SCHEMA_PATH)
    assert {split: path.read_bytes() for split, path in second.items()} == first_bytes
