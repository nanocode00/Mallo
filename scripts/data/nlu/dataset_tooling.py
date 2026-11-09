"""NLU CSV를 검증하고 학습용 JSONL로 재현 가능하게 변환한다."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from domain.errors import MIXED_INTENT_USER_MESSAGE
from domain.intents import Intent
from domain.mixed_intent import (
    SEQUENTIAL_CART_MUTATION_INTENTS,
    is_supported_sequential_intents,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CSV_PATH = REPOSITORY_ROOT / "data/nlu/raw/nlu-orders.csv"
DEFAULT_MENU_PATH = REPOSITORY_ROOT / "src/config/menu.json"
DEFAULT_ERROR_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/order-command-error.schema.json"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "data/nlu/processed"

CSV_COLUMNS = (
    "sample_id",
    "raw_utterance",
    "utterance",
    "cart_before_json",
    "label_type",
    "label_group",
    "label_json",
    "menu_version",
    "paraphrase_group_id",
    "source",
    "split",
    "review_status",
    "reviewer",
    "notes",
)
SEMANTIC_FIELDS = {
    "intent",
    "target_item_id",
    "category_id",
    "quantity",
    "temperature",
    "query_tags",
    "detail_fields",
    "options",
}
OPTION_FIELDS = {"size", "extra_shots", "caffeine", "syrup_pumps", "ice_amount"}
DETAIL_FIELDS = {
    "description",
    "price",
    "sweetness",
    "caffeine",
    "milk",
    "temperature",
}
ERROR_FIELDS = {"code", "message", "command_index", "field", "candidates", "retryable"}
ERROR_LABELS = {
    "MISSING_FIELD",
    "AMBIGUOUS_TARGET",
    "MIXED_INTENT",
    "UNSUPPORTED_UTTERANCE",
}
SOURCES = {"human", "template", "llm_synthetic"}
SPLITS = ("train", "validation", "test")
REVIEW_STATUSES = {"pending", "approved", "rejected"}
SAMPLE_ID_PATTERN = re.compile(r"^nlu_[0-9]{6}$")

TARGET_COUNTS = {
    "ADD_ITEM": (320, 40, 40),
    "REMOVE_ITEM": (208, 26, 26),
    "UPDATE_QUANTITY": (280, 35, 35),
    "UPDATE_OPTION": (240, 30, 30),
    "QUERY_MENU": (200, 25, 25),
    "QUERY_CART": (144, 18, 18),
    "CONFIRM_ORDER": (144, 18, 18),
    "CANCEL": (112, 14, 14),
    "UNDO": (144, 18, 18),
    "REQUEST_REPEAT": (96, 12, 12),
    "REQUEST_SLOWER": (96, 12, 12),
    "REQUEST_DEFAULT_SPEED": (96, 12, 12),
    "MISSING_FIELD": (96, 12, 12),
    "AMBIGUOUS_TARGET": (96, 12, 12),
    "MIXED_INTENT": (64, 8, 8),
    "UNSUPPORTED_UTTERANCE": (64, 8, 8),
}


class DatasetValidationError(ValueError):
    """CSV 행 또는 전체 데이터셋 계약 위반."""


@dataclass(frozen=True)
class DatasetRow:
    line_number: int
    values: dict[str, str]
    cart_before: list[dict[str, Any]]
    label: list[dict[str, Any]] | dict[str, Any]

    def to_jsonl_record(self) -> dict[str, Any]:
        return {
            "sample_id": self.values["sample_id"],
            "input": {
                "utterance": self.values["utterance"],
                "cart_before": self.cart_before,
            },
            "output": {
                "type": self.values["label_type"],
                "value": self.label,
            },
            "metadata": {
                "label_group": self.values["label_group"],
                "menu_version": self.values["menu_version"],
                "source": self.values["source"],
                "split": self.values["split"],
            },
        }


def normalize_utterance(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).strip().split())


def _korean_and_particle(word: str) -> str:
    syllable_index = ord(word[-1]) - ord("가")
    has_final_consonant = (
        0 <= syllable_index <= ord("힣") - ord("가")
        and syllable_index % 28 != 0
    )
    return "과" if has_final_consonant else "와"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DatasetValidationError(f"JSON 객체가 필요합니다: {path}")
    return payload


def _require_text(values: dict[str, str], field: str) -> str:
    value = values[field].strip()
    if not value:
        raise DatasetValidationError(f"{field} 값이 비어 있습니다")
    return value


def _parse_json_field(values: dict[str, str], field: str) -> Any:
    try:
        return json.loads(values[field])
    except json.JSONDecodeError as error:
        raise DatasetValidationError(f"{field} JSON 오류: {error.msg}") from error


def _validate_cart(
    cart: Any, menus: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    if not isinstance(cart, list):
        raise DatasetValidationError("cart_before_json은 배열이어야 합니다")
    seen: set[tuple[str, Any, str]] = set()
    for item in cart:
        if not isinstance(item, dict) or set(item) != {
            "menu_id",
            "quantity",
            "temperature",
            "options",
        }:
            raise DatasetValidationError("Cart 항목 필드 오류")
        menu_id = item["menu_id"]
        if menu_id not in menus:
            raise DatasetValidationError(f"Cart의 공식 Menu ID 오류: {menu_id}")
        quantity = item["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise DatasetValidationError("Cart 수량은 1 이상의 정수여야 합니다")
        temperature = item["temperature"]
        if temperature not in {"hot", "iced", None}:
            raise DatasetValidationError(f"Cart 온도 오류: {temperature}")
        options = menus[menu_id]["temperature_options"]
        if (options and temperature not in options) or (not options and temperature is not None):
            raise DatasetValidationError(f"Cart 메뉴 온도 정책 오류: {menu_id}")
        beverage_options = _validate_beverage_options(
            item["options"],
            menus[menu_id],
            temperature,
            allow_empty=True,
        )
        key = (
            menu_id,
            temperature,
            json.dumps(beverage_options, ensure_ascii=False, sort_keys=True),
        )
        if key in seen:
            raise DatasetValidationError(f"Cart 메뉴·온도·옵션 중복: {menu_id}")
        seen.add(key)
    return cart


def _validate_quantity(value: Any, *, required: bool) -> None:
    if value is None and not required:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DatasetValidationError("quantity는 1 이상의 정수여야 합니다")


def _validate_temperature(
    menu_id: str, temperature: Any, menus: dict[str, dict[str, Any]], *, required: bool
) -> None:
    options = menus[menu_id]["temperature_options"]
    if temperature is None:
        if required:
            raise DatasetValidationError(f"temperature가 필요합니다: {menu_id}")
        return
    if options:
        if temperature not in options:
            raise DatasetValidationError(f"메뉴 온도 정책 오류: {menu_id}")
    elif temperature is not None:
        raise DatasetValidationError(f"온도를 사용하지 않는 메뉴입니다: {menu_id}")


def _validate_beverage_options(
    value: Any,
    menu: dict[str, Any],
    temperature: Any,
    *,
    allow_empty: bool,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) not in (OPTION_FIELDS, OPTION_FIELDS - {"size"}):
        raise DatasetValidationError("options는 옵션 의미 필드 4개 또는 5개를 포함해야 합니다")
    if not allow_empty and all(option is None for option in value.values()):
        raise DatasetValidationError("options의 하위 필드가 모두 null일 수 없습니다")

    size = value.get("size")
    if size not in {"small", "medium", "large", None}:
        raise DatasetValidationError("size 옵션 값 오류")
    extra_shots = value["extra_shots"]
    syrup_pumps = value["syrup_pumps"]
    for name, option in (
        ("extra_shots", extra_shots),
        ("syrup_pumps", syrup_pumps),
    ):
        if option is not None and (
            isinstance(option, bool)
            or not isinstance(option, int)
            or option < 0
        ):
            raise DatasetValidationError(f"{name}는 0 이상의 정수 또는 null이어야 합니다")
    if value["caffeine"] not in {"regular", "decaf", None}:
        raise DatasetValidationError("caffeine 옵션 값 오류")
    if value["ice_amount"] not in {"none", "less", "normal", "more", None}:
        raise DatasetValidationError("ice_amount 옵션 값 오류")

    policy = menu["option_policy"]
    if size is not None and not policy["size_supported"]:
        raise DatasetValidationError("메뉴의 사이즈 옵션 정책 오류")
    if extra_shots is not None and not policy["shot_supported"]:
        raise DatasetValidationError("메뉴의 샷 옵션 정책 오류")
    if value["caffeine"] is not None and not policy["decaf_available"]:
        raise DatasetValidationError("메뉴의 디카페인 옵션 정책 오류")
    if syrup_pumps is not None and not policy["syrup_supported"]:
        raise DatasetValidationError("메뉴의 시럽 옵션 정책 오류")
    if value["ice_amount"] is not None and (
        not policy["ice_amount_available"]
        or (temperature is not None and temperature != "iced")
    ):
        raise DatasetValidationError("얼음 양은 ICED 메뉴에서만 사용할 수 있습니다")
    return value


def _validate_command(
    command: Any,
    menus: dict[str, dict[str, Any]],
    category_ids: set[str],
    tag_ids: set[str],
) -> str:
    if not isinstance(command, dict) or set(command) != SEMANTIC_FIELDS:
        raise DatasetValidationError("Command는 의미 필드 8개만 포함해야 합니다")
    try:
        intent = Intent(command["intent"])
    except (TypeError, ValueError) as error:
        raise DatasetValidationError(f"지원하지 않는 Intent: {command.get('intent')}") from error

    target = command["target_item_id"]
    category = command["category_id"]
    quantity = command["quantity"]
    temperature = command["temperature"]
    query_tags = command["query_tags"]
    detail_fields = command["detail_fields"]
    options = command["options"]

    if query_tags is not None:
        if (
            not isinstance(query_tags, list)
            or not 1 <= len(query_tags) <= 8
            or len(set(query_tags)) != len(query_tags)
            or any(tag not in tag_ids for tag in query_tags)
        ):
            raise DatasetValidationError("query_tags는 등록된 표준 태그의 중복 없는 배열이어야 합니다")

    if detail_fields is not None:
        if (
            not isinstance(detail_fields, list)
            or not 1 <= len(detail_fields) <= len(DETAIL_FIELDS)
            or len(set(detail_fields)) != len(detail_fields)
            or any(field not in DETAIL_FIELDS for field in detail_fields)
        ):
            raise DatasetValidationError("detail_fields는 지원 상세 항목의 중복 없는 배열이어야 합니다")

    target_required = intent in {
        Intent.ADD_ITEM,
        Intent.REMOVE_ITEM,
        Intent.UPDATE_QUANTITY,
        Intent.UPDATE_OPTION,
    }
    if target_required and target not in menus:
        raise DatasetValidationError(f"공식 Menu ID 오류: {target}")
    if target is not None and target not in menus:
        raise DatasetValidationError(f"공식 Menu ID 오류: {target}")
    if category is not None and category not in category_ids:
        raise DatasetValidationError(f"공식 Category ID 오류: {category}")

    if intent is Intent.ADD_ITEM:
        if category is not None:
            raise DatasetValidationError("ADD_ITEM category_id는 null이어야 합니다")
        _validate_quantity(quantity, required=True)
        _validate_temperature(target, temperature, menus, required=bool(menus[target]["temperature_options"]))
        _validate_beverage_options(
            options,
            menus[target],
            temperature,
            allow_empty=False,
        )
    elif intent is Intent.REMOVE_ITEM:
        if category is not None:
            raise DatasetValidationError("REMOVE_ITEM category_id는 null이어야 합니다")
        _validate_quantity(quantity, required=False)
        _validate_temperature(target, temperature, menus, required=False)
    elif intent is Intent.UPDATE_QUANTITY:
        if category is not None:
            raise DatasetValidationError("UPDATE_QUANTITY category_id는 null이어야 합니다")
        _validate_quantity(quantity, required=True)
        _validate_temperature(target, temperature, menus, required=False)
    elif intent is Intent.UPDATE_OPTION:
        if category is not None or quantity is not None:
            raise DatasetValidationError("UPDATE_OPTION의 category_id와 quantity는 null이어야 합니다")
        if temperature is None and options is None:
            raise DatasetValidationError("UPDATE_OPTION에는 temperature 또는 options가 필요합니다")
        _validate_temperature(target, temperature, menus, required=False)
        _validate_beverage_options(
            options,
            menus[target],
            temperature,
            allow_empty=False,
        )
    elif intent is Intent.QUERY_MENU:
        if quantity is not None or temperature is not None:
            raise DatasetValidationError("QUERY_MENU의 quantity와 temperature는 null이어야 합니다")
        if target is not None and (category is not None or query_tags is not None):
            raise DatasetValidationError("QUERY_MENU의 특정 메뉴 조회와 조건 검색은 함께 사용할 수 없습니다")
        if detail_fields is not None and target is None:
            raise DatasetValidationError("QUERY_MENU 상세 질문에는 target_item_id가 필요합니다")
    elif any(
        value is not None
        for value in (
            target,
            category,
            quantity,
            temperature,
            query_tags,
            detail_fields,
            options,
        )
    ):
        raise DatasetValidationError(f"{intent.value}의 의미 필드는 모두 null이어야 합니다")

    if intent is not Intent.QUERY_MENU and query_tags is not None:
        raise DatasetValidationError(f"{intent.value}의 query_tags는 null이어야 합니다")
    if intent is not Intent.QUERY_MENU and detail_fields is not None:
        raise DatasetValidationError(f"{intent.value}의 detail_fields는 null이어야 합니다")
    if intent not in {Intent.ADD_ITEM, Intent.UPDATE_OPTION} and options is not None:
        raise DatasetValidationError(f"{intent.value}의 options는 null이어야 합니다")
    return intent.value


def _validate_commands(
    label: Any,
    label_group: str,
    cart: list[dict[str, Any]],
    menus: dict[str, dict[str, Any]],
    category_ids: set[str],
    tag_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(label, list) or not 1 <= len(label) <= 10:
        raise DatasetValidationError("commands Label은 길이 1~10의 배열이어야 합니다")
    intents = [
        Intent(_validate_command(command, menus, category_ids, tag_ids))
        for command in label
    ]
    if len(set(intents)) == 1:
        if intents[0].value != label_group:
            raise DatasetValidationError("Command Intent와 label_group이 일치하지 않습니다")
        if intents[0] is not Intent.ADD_ITEM and len(label) != 1:
            raise DatasetValidationError("ADD_ITEM 외 단일 Intent는 Command 하나만 허용합니다")
        return label

    if label_group != intents[0].value:
        raise DatasetValidationError("혼합 Command label_group은 첫 Intent여야 합니다")
    if not is_supported_sequential_intents(intents):
        raise DatasetValidationError("지원하지 않는 혼합 Command 조합입니다")
    _validate_sequential_cart_context(label, cart)
    return label


def _validate_sequential_cart_context(
    label: list[dict[str, Any]],
    cart: list[dict[str, Any]],
) -> None:
    for command in label:
        intent = Intent(command["intent"])
        if intent not in SEQUENTIAL_CART_MUTATION_INTENTS:
            continue
        target = command["target_item_id"]
        if intent is Intent.ADD_ITEM:
            continue

        candidates = [item for item in cart if item["menu_id"] == target]
        if intent is not Intent.UPDATE_OPTION and command["temperature"] is not None:
            candidates = [
                item
                for item in candidates
                if item["temperature"] == command["temperature"]
            ]
        if len(candidates) != 1:
            raise DatasetValidationError(
                f"혼합 Command 대상이 Cart에서 하나로 식별되지 않습니다: {target}"
            )


def _menu_name_from_utterance(utterance: str, menus: dict[str, dict[str, Any]]) -> str | None:
    names = [menu["name"] for menu in menus.values() if menu["name"] in utterance]
    return names[0] if len(names) == 1 else None


def _validate_error(
    label: Any,
    label_group: str,
    utterance: str,
    cart: list[dict[str, Any]],
    menus: dict[str, dict[str, Any]],
    validator: Draft202012Validator,
) -> dict[str, Any]:
    if not isinstance(label, dict) or set(label) != ERROR_FIELDS:
        raise DatasetValidationError("Error Label은 OrderCommandError 전체 필드를 포함해야 합니다")
    errors = sorted(validator.iter_errors(label), key=lambda error: list(error.path))
    if errors:
        raise DatasetValidationError(f"OrderCommandError Schema 오류: {errors[0].message}")
    if label["code"] != label_group or label_group not in ERROR_LABELS:
        raise DatasetValidationError("오류 code와 label_group이 일치하지 않습니다")
    if label["retryable"] is not True:
        raise DatasetValidationError("P0 학습 오류의 retryable은 true여야 합니다")

    code = label["code"]
    field = label["field"]
    candidates = label["candidates"]
    message = label["message"]
    menu_name = _menu_name_from_utterance(utterance, menus)
    if code == "MISSING_FIELD":
        if field not in {"temperature", "quantity", "target_item_id"}:
            raise DatasetValidationError("MISSING_FIELD의 field 오류")
        if field == "temperature":
            if menu_name is None or candidates != ["hot", "iced"]:
                raise DatasetValidationError("온도 누락 메뉴명 또는 candidates 오류")
            expected = f"{menu_name}의 온도를 따뜻한 걸 원하시나요, 차가운 걸 원하시나요?"
        elif field == "quantity":
            if menu_name is None or candidates is not None:
                raise DatasetValidationError("수량 누락 메뉴명 또는 candidates 오류")
            expected = f"{menu_name}의 수량을 말씀해 주세요."
        else:
            if candidates is not None:
                raise DatasetValidationError("메뉴 누락 candidates는 null이어야 합니다")
            expected = "어떤 메뉴를 원하시나요?"
    elif code == "AMBIGUOUS_TARGET":
        if field == "temperature":
            hot_iced_ids = {
                item["menu_id"]
                for item in cart
                if {entry["temperature"] for entry in cart if entry["menu_id"] == item["menu_id"]}
                >= {"hot", "iced"}
            }
            if len(hot_iced_ids) != 1 or candidates != ["hot", "iced"]:
                raise DatasetValidationError("온도 모호성 Cart 또는 candidates 오류")
            name = menus[next(iter(hot_iced_ids))]["name"]
            particle = _korean_and_particle(name)
            expected = f"따뜻한 {name}{particle} 차가운 {name} 중 어떤 메뉴를 변경하시나요?"
        elif field == "target_item_id":
            if not isinstance(candidates, list) or len(candidates) < 2 or any(
                candidate not in menus for candidate in candidates
            ):
                raise DatasetValidationError("대상 모호성 candidates 오류")
            cart_menu_ids = {item["menu_id"] for item in cart}
            if not set(candidates).issubset(cart_menu_ids):
                raise DatasetValidationError("대상 모호성 candidates가 Cart와 일치하지 않습니다")
            expected = "어떤 메뉴를 변경하시나요? 메뉴 이름을 말씀해 주세요."
        else:
            raise DatasetValidationError("AMBIGUOUS_TARGET의 field 오류")
    elif code == "MIXED_INTENT":
        if any(value is not None for value in (label["command_index"], field, candidates)):
            raise DatasetValidationError("MIXED_INTENT 선택 필드는 null이어야 합니다")
        expected = MIXED_INTENT_USER_MESSAGE
    else:
        if any(value is not None for value in (label["command_index"], field, candidates)):
            raise DatasetValidationError("UNSUPPORTED_UTTERANCE 선택 필드는 null이어야 합니다")
        expected = "죄송합니다. 메뉴 이름과 수량을 다시 말씀해 주세요."
    if message != expected:
        raise DatasetValidationError(f"고정 message Template 오류: {message}")
    return label


def _parse_row(
    line_number: int,
    values: dict[str, str],
    menu_version: str,
    menus: dict[str, dict[str, Any]],
    category_ids: set[str],
    tag_ids: set[str],
    error_validator: Draft202012Validator,
) -> DatasetRow:
    if None in values:
        raise DatasetValidationError("CSV Header보다 많은 열이 있습니다")
    sample_id = _require_text(values, "sample_id")
    if not SAMPLE_ID_PATTERN.fullmatch(sample_id):
        raise DatasetValidationError("sample_id 형식은 nlu_000001이어야 합니다")
    raw_utterance = _require_text(values, "raw_utterance")
    utterance = _require_text(values, "utterance")
    if utterance != normalize_utterance(utterance):
        raise DatasetValidationError("utterance에 NFC·공백 정제가 필요합니다")
    cart = _validate_cart(_parse_json_field(values, "cart_before_json"), menus)

    label_type = _require_text(values, "label_type")
    label_group = _require_text(values, "label_group")
    label = _parse_json_field(values, "label_json")
    if values["menu_version"] != menu_version:
        raise DatasetValidationError("menu_version이 Menu DB와 일치하지 않습니다")
    if values["source"] not in SOURCES:
        raise DatasetValidationError(f"source 오류: {values['source']}")
    if values["split"] not in SPLITS:
        raise DatasetValidationError(f"split 오류: {values['split']}")
    if values["review_status"] not in REVIEW_STATUSES:
        raise DatasetValidationError(f"review_status 오류: {values['review_status']}")
    if values["review_status"] == "approved" and not values["reviewer"].strip():
        raise DatasetValidationError("approved 행에는 reviewer가 필요합니다")
    _require_text(values, "paraphrase_group_id")

    if label_type == "commands":
        if label_group not in {intent.value for intent in Intent}:
            raise DatasetValidationError(f"Command label_group 오류: {label_group}")
        label = _validate_commands(
            label, label_group, cart, menus, category_ids, tag_ids
        )
    elif label_type == "error":
        label = _validate_error(label, label_group, utterance, cart, menus, error_validator)
    else:
        raise DatasetValidationError(f"label_type 오류: {label_type}")
    return DatasetRow(line_number, values, cart, label)


def _validate_cross_rows(rows: list[DatasetRow], mode: str) -> None:
    sample_ids: set[str] = set()
    content_keys: set[tuple[str, str, str]] = set()
    group_splits: dict[str, str] = {}
    add_item_semantics = {}
    remove_item_semantics = {}
    update_quantity_semantics = {}
    update_option_semantics = {}
    query_menu_semantics = {}
    for row in rows:
        sample_id = row.values["sample_id"]
        if sample_id in sample_ids:
            raise DatasetValidationError(f"sample_id 중복: {sample_id}")
        sample_ids.add(sample_id)
        content_key = (
            row.values["utterance"],
            json.dumps(row.cart_before, ensure_ascii=False, sort_keys=True),
            json.dumps(row.label, ensure_ascii=False, sort_keys=True),
        )
        if content_key in content_keys:
            raise DatasetValidationError(f"발화·Context·Label 완전 중복: {sample_id}")
        content_keys.add(content_key)
        group_id = row.values["paraphrase_group_id"]
        split = row.values["split"]
        if group_id in group_splits and group_splits[group_id] != split:
            raise DatasetValidationError(f"paraphrase_group_id Split 누수: {group_id}")
        group_splits[group_id] = split
        if row.values["label_group"] == "ADD_ITEM":
            assignment = (group_id, split)
            if add_item_semantics.setdefault(content_key[1:], assignment) != assignment:
                raise DatasetValidationError("ADD_ITEM 의미 그룹 불일치 또는 Split 누수")
        if row.values["label_group"] == "REMOVE_ITEM":
            assignment = (group_id, split)
            if remove_item_semantics.setdefault(content_key[1:], assignment) != assignment:
                raise DatasetValidationError("REMOVE_ITEM 의미 그룹 불일치 또는 Split 누수")
        if row.values["label_group"] == "UPDATE_QUANTITY":
            assignment = (group_id, split)
            if update_quantity_semantics.setdefault(content_key[1:], assignment) != assignment:
                raise DatasetValidationError("UPDATE_QUANTITY 의미 그룹 불일치 또는 Split 누수")
        if row.values["label_group"] == "UPDATE_OPTION":
            assignment = (group_id, split)
            if update_option_semantics.setdefault(content_key[1:], assignment) != assignment:
                raise DatasetValidationError("UPDATE_OPTION 의미 그룹 불일치 또는 Split 누수")
        if row.values["label_group"] == "QUERY_MENU":
            assignment = (group_id, split)
            if query_menu_semantics.setdefault(content_key[1:], assignment) != assignment:
                raise DatasetValidationError("QUERY_MENU 의미 그룹 불일치 또는 Split 누수")

    if mode == "final":
        if any(row.values["review_status"] != "approved" for row in rows):
            raise DatasetValidationError("final 모드는 모든 행이 approved여야 합니다")
        actual = Counter((row.values["label_group"], row.values["split"]) for row in rows)
        expected = Counter(
            {(group, split): counts[index] for group, counts in TARGET_COUNTS.items() for index, split in enumerate(SPLITS)}
        )
        if actual != expected:
            raise DatasetValidationError("final 목표 Label Group·Split 분포와 일치하지 않습니다")


def load_and_validate(
    csv_path: Path,
    menu_path: Path = DEFAULT_MENU_PATH,
    error_schema_path: Path = DEFAULT_ERROR_SCHEMA_PATH,
    *,
    mode: str = "draft",
) -> list[DatasetRow]:
    if mode not in {"draft", "final"}:
        raise ValueError("mode는 draft 또는 final이어야 합니다")
    menu_payload = _load_json(menu_path)
    menu_version = str(menu_payload["version"])
    menus = {item["id"]: item for item in menu_payload["items"]}
    category_ids = {category["id"] for category in menu_payload["categories"]}
    tag_ids = {definition["id"] for definition in menu_payload["tag_definitions"]}
    error_validator = Draft202012Validator(_load_json(error_schema_path))

    errors: list[str] = []
    rows: list[DatasetRow] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise DatasetValidationError("CSV Header가 기준과 정확히 일치하지 않습니다")
        for line_number, values in enumerate(reader, start=2):
            try:
                rows.append(
                    _parse_row(
                        line_number,
                        values,
                        menu_version,
                        menus,
                        category_ids,
                        tag_ids,
                        error_validator,
                    )
                )
            except (DatasetValidationError, KeyError, TypeError) as error:
                errors.append(f"{line_number}행: {error}")
    if errors:
        raise DatasetValidationError("\n".join(errors))
    _validate_cross_rows(rows, mode)
    return rows


def validation_report(rows: list[DatasetRow], mode: str) -> dict[str, Any]:
    approved = [row for row in rows if row.values["review_status"] == "approved"]
    return {
        "status": "PASS",
        "mode": mode,
        "rows": len(rows),
        "approved_rows": len(approved),
        "label_groups": dict(sorted(Counter(row.values["label_group"] for row in rows).items())),
        "sources": dict(sorted(Counter(row.values["source"] for row in rows).items())),
        "splits": dict(sorted(Counter(row.values["split"] for row in rows).items())),
    }


def write_jsonl(rows: list[DatasetRow], output_dir: Path) -> dict[str, Path]:
    approved = [row for row in rows if row.values["review_status"] == "approved"]
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=".nlu-jsonl-", dir=output_dir.parent))
    try:
        temporary_paths: dict[str, Path] = {}
        for split in SPLITS:
            path = temporary_dir / f"{split}.jsonl"
            selected = [row for row in approved if row.values["split"] == split]
            with path.open("w", encoding="utf-8", newline="\n") as target:
                for row in selected:
                    target.write(json.dumps(row.to_jsonl_record(), ensure_ascii=False, separators=(",", ":")))
                    target.write("\n")
            parsed = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            if len(parsed) != len(selected):
                raise RuntimeError(f"생성 JSONL 행 수 오류: {split}")
            temporary_paths[split] = path

        output_dir.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, Path] = {}
        for split in SPLITS:
            destination = output_dir / f"{split}.jsonl"
            os.replace(temporary_paths[split], destination)
            outputs[split] = destination
        return outputs
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


def build_dataset(
    csv_path: Path,
    output_dir: Path,
    menu_path: Path = DEFAULT_MENU_PATH,
    error_schema_path: Path = DEFAULT_ERROR_SCHEMA_PATH,
    *,
    mode: str = "draft",
) -> tuple[list[DatasetRow], dict[str, Path]]:
    rows = load_and_validate(csv_path, menu_path, error_schema_path, mode=mode)
    return rows, write_jsonl(rows, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="NLU CSV 검증 및 JSONL 생성")
    parser.add_argument("action", choices=("validate", "build"))
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--menu", type=Path, default=DEFAULT_MENU_PATH)
    parser.add_argument("--error-schema", type=Path, default=DEFAULT_ERROR_SCHEMA_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=("draft", "final"), default="draft")
    args = parser.parse_args()
    if args.action == "build":
        rows, outputs = build_dataset(
            args.csv, args.output_dir, args.menu, args.error_schema, mode=args.mode
        )
        report = {**validation_report(rows, args.mode), "outputs": {key: str(value) for key, value in outputs.items()}}
    else:
        rows = load_and_validate(args.csv, args.menu, args.error_schema, mode=args.mode)
        report = validation_report(rows, args.mode)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
