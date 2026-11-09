"""Build a deterministic, leakage-safe focused NLU challenge set.

This is a synthetic contract stress suite, not a pristine generalization holdout.
It never reads train/validation/test examples and refuses to overwrite a frozen set
unless --force is given explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.eval.nlu.model_evaluator import NLUEvaluator

from adapters.nlu.qwen_training_data import canonical_json

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "data/nlu/challenges/focused-v1.jsonl"
MENU_PATH = ROOT / "src/config/menu.json"


def options(*, size=None, extra_shots=None, caffeine=None, syrup_pumps=None, ice_amount=None):
    return {
        "size": size,
        "extra_shots": extra_shots,
        "caffeine": caffeine,
        "syrup_pumps": syrup_pumps,
        "ice_amount": ice_amount,
    }


def cart_item(menu_id: str, *, quantity: int = 1, temperature=None, opts=None) -> dict[str, Any]:
    return {
        "menu_id": menu_id,
        "quantity": quantity,
        "temperature": temperature,
        "options": opts if opts is not None else options(),
    }


def command(
    intent: str,
    *,
    target_item_id=None,
    category_id=None,
    quantity=None,
    temperature=None,
    query_tags=None,
    detail_fields=None,
    opts=None,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "target_item_id": target_item_id,
        "category_id": category_id,
        "quantity": quantity,
        "temperature": temperature,
        "query_tags": query_tags,
        "detail_fields": detail_fields,
        "options": opts,
    }


def error_value(code: str, message: str, *, field=None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "command_index": None,
        "field": field,
        "candidates": None,
        "retryable": True,
    }


def build_records() -> list[dict[str, Any]]:
    menu = json.loads(MENU_PATH.read_text(encoding="utf-8"))
    names = {row["id"]: row["name"] for row in menu["items"]}
    menu_version = menu["version"]
    rows: list[dict[str, Any]] = []

    def add(scenario: str, utterance: str, cart: list[dict[str, Any]], value: Any, *, output_type="commands", label=None):
        sample_id = f"focus_v1_{len(rows)+1:04d}"
        rows.append(
            {
                "sample_id": sample_id,
                "input": {"utterance": utterance, "cart_before": cart},
                "output": {"type": output_type, "value": value},
                "metadata": {
                    "label_group": label or (value[0]["intent"] if output_type == "commands" else value["code"]),
                    "menu_version": menu_version,
                    "source": "focused_challenge_v1",
                    "scenario": scenario,
                },
            }
        )

    dual_temp = ["americano", "cafe_latte", "vanilla_latte", "matcha_latte", "milk_tea", "chamomile_tea"]
    coffee_shot = ["americano", "cafe_latte", "vanilla_latte"]

    # 24: same intent, multiple fields. These are the key static-cache regression class.
    for menu_id in dual_temp:
        name = names[menu_id]
        for utterance in (
            f"{name} 아이스로 바꾸고 미디엄 사이즈로 해 주세요",
            f"{name} 차갑게 바꾼 다음 크기는 중간으로 해 줘",
        ):
            add(
                "same_item_multi_option",
                utterance,
                [cart_item(menu_id, temperature="hot", opts=options(size="small"))],
                [command("UPDATE_OPTION", target_item_id=menu_id, temperature="iced", opts=options(size="medium"))],
            )
    for menu_id in coffee_shot:
        name = names[menu_id]
        for utterance in (
            f"{name} 아이스로 바꾸고 샷 두 번 넣어 줘요",
            f"{name} 차갑게 하고 샷은 두 개 추가해 줘",
        ):
            add(
                "same_item_multi_option",
                utterance,
                [cart_item(menu_id, temperature="hot")],
                [command("UPDATE_OPTION", target_item_id=menu_id, temperature="iced", opts=options(extra_shots=2))],
            )
    for menu_id in dual_temp:
        name = names[menu_id]
        add(
            "same_item_multi_option",
            f"{name} 라지로 바꾸고 시럽 한 번만 넣어 주세요",
            [cart_item(menu_id, temperature="iced", opts=options(size="small", syrup_pumps=0))],
            [command("UPDATE_OPTION", target_item_id=menu_id, opts=options(size="large", syrup_pumps=1))],
        )

    # 12: explicit-temperature add requests.
    for menu_id in dual_temp:
        name = names[menu_id]
        add("add_explicit_temperature", f"따뜻한 {name} 한 잔 주세요", [], [command("ADD_ITEM", target_item_id=menu_id, quantity=1, temperature="hot")])
        add("add_explicit_temperature", f"아이스 {name} 두 잔 주세요", [], [command("ADD_ITEM", target_item_id=menu_id, quantity=2, temperature="iced")])

    # 6: missing temperature on a menu that needs a temperature choice.
    for menu_id in dual_temp:
        add(
            "missing_temperature",
            f"{names[menu_id]} 한 잔 주세요",
            [],
            error_value("MISSING_FIELD", "온도를 선택해 주세요.", field="temperature"),
            output_type="error",
            label="MISSING_FIELD",
        )

    # 8: pronoun / underspecified target with multiple cart candidates.
    ambiguous_carts = [
        [cart_item("americano", temperature="iced"), cart_item("cafe_latte", temperature="hot")],
        [cart_item("vanilla_latte", temperature="hot"), cart_item("milk_tea", temperature="iced")],
        [cart_item("matcha_latte", temperature="iced"), cart_item("chamomile_tea", temperature="hot")],
        [cart_item("americano", temperature="hot"), cart_item("basque_cheesecake")],
    ]
    for cart in ambiguous_carts:
        for utterance in ("그거 하나 빼 주세요", "저거 큰 사이즈로 바꿔 줘"):
            add(
                "ambiguous_target",
                utterance,
                cart,
                error_value("AMBIGUOUS_TARGET", "수정할 메뉴를 하나로 특정해 주세요."),
                output_type="error",
                label="AMBIGUOUS_TARGET",
            )

    # 8: named target among several cart items.
    target_cases = [
        ("americano", "아메리카노 두 잔으로 바꿔 주세요", command("UPDATE_QUANTITY", target_item_id="americano", quantity=2)),
        ("cafe_latte", "카페라떼는 아이스로 바꿔 줘", command("UPDATE_OPTION", target_item_id="cafe_latte", temperature="iced", opts=options())),
        ("vanilla_latte", "바닐라라떼만 빼 주세요", command("REMOVE_ITEM", target_item_id="vanilla_latte")),
        ("milk_tea", "밀크티 라지로 바꿔 주세요", command("UPDATE_OPTION", target_item_id="milk_tea", opts=options(size="large"))),
        ("matcha_latte", "말차라떼 세 잔으로 바꿔 줘", command("UPDATE_QUANTITY", target_item_id="matcha_latte", quantity=3)),
        ("chamomile_tea", "캐모마일티는 따뜻하게 바꿔 줘", command("UPDATE_OPTION", target_item_id="chamomile_tea", temperature="hot", opts=options())),
        ("grapefruit_ade", "자몽에이드 빼 주세요", command("REMOVE_ITEM", target_item_id="grapefruit_ade")),
        ("iced_tea", "아이스티 두 잔으로 해 줘", command("UPDATE_QUANTITY", target_item_id="iced_tea", quantity=2)),
    ]
    rich_cart = [
        cart_item("americano", temperature="hot"),
        cart_item("cafe_latte", temperature="hot"),
        cart_item("vanilla_latte", temperature="hot"),
        cart_item("milk_tea", temperature="iced"),
        cart_item("matcha_latte", temperature="iced"),
        cart_item("chamomile_tea", temperature="iced"),
        cart_item("grapefruit_ade", temperature="iced"),
        cart_item("iced_tea", temperature="iced"),
    ]
    for _, utterance, expected in target_cases:
        add("named_target_in_busy_cart", utterance, rich_cart, [expected])

    # 8: genuinely mixed control + mutation requests.
    mixed = [
        "아이스 아메리카노 하나 추가하고 주문 취소해 줘",
        "카페라떼 빼고 주문 확정해 줘",
        "밀크티 두 잔으로 바꾸고 처음으로 돌아가 줘",
        "아이스티 하나 추가하고 방금 말 다시 해 줘",
        "바닐라라떼 빼고 말하는 속도 느리게 해 줘",
        "아메리카노 세 잔으로 바꾸고 주문 취소해 줘",
        "말차라떼 따뜻하게 바꾸고 주문 확정해 주세요",
        "캐모마일티 하나 추가하고 기본 말하기 속도로 해 줘",
    ]
    mixed_cart = [cart_item("cafe_latte", temperature="hot"), cart_item("milk_tea", temperature="iced"), cart_item("vanilla_latte", temperature="hot"), cart_item("americano", temperature="iced"), cart_item("matcha_latte", temperature="iced")]
    for utterance in mixed:
        add(
            "genuine_mixed_intent",
            utterance,
            mixed_cart,
            error_value("MIXED_INTENT", "사용자의 주문을 이해하지 못했습니다. 한 번에 하나씩 주문해 주시면 감사하겠습니다."),
            output_type="error",
            label="MIXED_INTENT",
        )

    # 16: quantity / remove under named target.
    quantity_targets = ["americano", "cafe_latte", "vanilla_latte", "milk_tea", "matcha_latte", "chamomile_tea", "grapefruit_ade", "iced_tea"]
    for index, menu_id in enumerate(quantity_targets, start=2):
        cart = [cart_item(menu_id, quantity=1, temperature="iced" if menu_id not in {"cafe_latte", "vanilla_latte"} else "hot")]
        add("quantity_update", f"{names[menu_id]} {index}잔으로 바꿔 주세요", cart, [command("UPDATE_QUANTITY", target_item_id=menu_id, quantity=index)])
        add("remove_named_item", f"{names[menu_id]}는 빼 주세요", cart, [command("REMOVE_ITEM", target_item_id=menu_id)])

    # 8: valid ordered multi-command add requests.
    multi_pairs = [
        ("americano", "iced", "cafe_latte", "hot"),
        ("vanilla_latte", "hot", "milk_tea", "iced"),
        ("matcha_latte", "iced", "chamomile_tea", "hot"),
        ("americano", "hot", "vanilla_latte", "iced"),
        ("cafe_latte", "iced", "milk_tea", "hot"),
        ("matcha_latte", "hot", "americano", "iced"),
        ("chamomile_tea", "iced", "cafe_latte", "hot"),
        ("milk_tea", "hot", "vanilla_latte", "iced"),
    ]
    temp_ko = {"hot": "따뜻한", "iced": "아이스"}
    for first, first_temp, second, second_temp in multi_pairs:
        add(
            "valid_multi_command",
            f"{temp_ko[first_temp]} {names[first]} 한 잔이랑 {temp_ko[second_temp]} {names[second]} 두 잔 주세요",
            [],
            [
                command("ADD_ITEM", target_item_id=first, quantity=1, temperature=first_temp),
                command("ADD_ITEM", target_item_id=second, quantity=2, temperature=second_temp),
            ],
            label="ADD_ITEM+ADD_ITEM",
        )

    # 12: menu queries covering tags, categories and details.
    query_cases = [
        ("카페인 없는 메뉴 알려줘", command("QUERY_MENU", query_tags=["caffeine_free"])),
        ("상큼한 음료 뭐 있어?", command("QUERY_MENU", query_tags=["refreshing"])),
        ("커피 메뉴 보여 주세요", command("QUERY_MENU", category_id="coffee")),
        ("티 종류 보여 줘", command("QUERY_MENU", category_id="tea")),
        ("디저트 메뉴 알려 주세요", command("QUERY_MENU", category_id="dessert")),
        ("아메리카노 가격 알려 줘", command("QUERY_MENU", target_item_id="americano", detail_fields=["price"])),
        ("밀크티 카페인 들어 있어?", command("QUERY_MENU", target_item_id="milk_tea", detail_fields=["caffeine"])),
        ("바닐라라떼 얼마나 달아?", command("QUERY_MENU", target_item_id="vanilla_latte", detail_fields=["sweetness"])),
        ("캐모마일티 설명해 줘", command("QUERY_MENU", target_item_id="chamomile_tea", detail_fields=["description"])),
        ("차가운 메뉴만 알려 줘", command("QUERY_MENU", query_tags=["iced"])),
        ("우유 없는 메뉴 뭐 있어?", command("QUERY_MENU", query_tags=["milk_free"])),
        ("부드러운 메뉴 추천해 줘", command("QUERY_MENU", query_tags=["creamy"])),
    ]
    for utterance, expected in query_cases:
        add("query_menu", utterance, [], [expected])

    # 14: control/session intents, two phrasings each.
    controls = [
        ("REQUEST_REPEAT", ["다시 말해 주세요", "방금 말 한 번 더 해 줘"]),
        ("REQUEST_SLOWER", ["좀 천천히 말해 주세요", "말하는 속도 느리게 해 줘"]),
        ("REQUEST_DEFAULT_SPEED", ["말하기 속도 원래대로 해 줘", "기본 속도로 돌아가 줘"]),
        ("QUERY_CART", ["지금 뭐 담겨 있어?", "주문 내역 보여 주세요"]),
        ("CONFIRM_ORDER", ["이대로 주문할게요", "주문 확정해 주세요"]),
        ("CANCEL", ["주문 취소할게요", "전부 취소해 주세요"]),
        ("UNDO", ["방금 거 되돌려 줘", "아까 변경한 거 취소해 줘"]),
    ]
    control_cart = [cart_item("americano", temperature="iced")]
    for intent, utterances in controls:
        for utterance in utterances:
            add("control_intent", utterance, control_cart, [command(intent)])

    # 8: unsupported single-domain requests.
    unsupported = [
        "오늘 날씨 알려 줘",
        "택시 불러 주세요",
        "와이파이 비밀번호 뭐예요",
        "노래 한 곡 틀어 줘",
        "휴대폰 충전할 수 있어요?",
        "화장실 어디예요",
        "주식 가격 알려 줘",
        "내일 알람 맞춰 줘",
    ]
    for utterance in unsupported:
        add(
            "unsupported_utterance",
            utterance,
            [],
            error_value("UNSUPPORTED_UTTERANCE", "지원하지 않는 요청입니다."),
            output_type="error",
            label="UNSUPPORTED_UTTERANCE",
        )

    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    lowered = str(args.output).lower()
    if "test" in lowered:
        raise ValueError("focused challenge 경로에 'test'를 사용하지 않습니다")
    manifest_path = args.output.with_suffix(".manifest.json")
    if args.output.exists() and not args.force:
        if not manifest_path.exists():
            raise FileExistsError(f"frozen challenge는 있으나 manifest가 없습니다: {args.output}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual = sha256_file(args.output)
        if actual != manifest.get("sha256"):
            raise RuntimeError("frozen challenge SHA256 mismatch")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    records = build_records()
    evaluator = NLUEvaluator()
    sample_ids = [row["sample_id"] for row in records]
    if len(sample_ids) != len(set(sample_ids)):
        raise RuntimeError("duplicate sample_id")
    for row in records:
        expected = row["output"]["value"]
        if not evaluator._schema_valid(expected):  # intentional build-time contract assertion
            raise RuntimeError(f"invalid gold schema: {row['sample_id']} {canonical_json(expected)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(canonical_json(row) + "\n" for row in records), encoding="utf-8")
    scenario_counts = Counter(row["metadata"]["scenario"] for row in records)
    manifest = {
        "version": "focused-v1",
        "kind": "synthetic_contract_stress",
        "pristine_generalization_holdout": False,
        "sample_count": len(records),
        "sha256": sha256_file(args.output),
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "test_split_opened": False,
        "notes": [
            "Generated only from the public NLU contract/menu schema and hand-authored templates.",
            "No train/validation/test example file is read by this builder.",
            "Use this for focused candidate comparison, not as a pristine final generalization estimate.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
