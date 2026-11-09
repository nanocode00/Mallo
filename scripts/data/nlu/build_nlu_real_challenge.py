"""Build the versioned, contract-only Mallo real-use NLU challenge set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.eval.nlu.challenge_evaluator import ChallengeEvaluator

from adapters.nlu.qwen_training_data import canonical_json

ROOT = Path(__file__).resolve().parents[3]
DEFAULT = ROOT / "data/nlu/challenges/mallo-real-v1.jsonl"


def cmd(menu_id: str, quantity: int | None, temperature: str | None = None, intent: str = "ADD_ITEM") -> dict:
    return {"intent": intent, "target_item_id": menu_id if intent == "ADD_ITEM" else None, "category_id": None, "quantity": quantity, "temperature": temperature, "query_tags": None, "detail_fields": None, "options": None}


def cart(menu_id: str, quantity: int = 1, temperature: str | None = "iced") -> dict:
    return {"menu_id": menu_id, "quantity": quantity, "temperature": temperature, "options": {"size": None, "extra_shots": None, "caffeine": None, "syrup_pumps": None, "ice_amount": None}}


def records() -> list[dict]:
    rows: list[dict] = []
    def add(category, utterance, expected=None, *, before=None, behavioral=None, scored=True):
        rows.append({"sample_id": f"mallo_real_v1_{len(rows)+1:03d}", "input": {"utterance": utterance, "cart_before": before or []}, "output": {"type": "commands" if expected is not None else "unsupported", "value": expected}, "metadata": {"category": category, "scored": scored, "behavioral": behavioral, "source": "mallo_real_v1", "contract_status": "supported" if scored else "unsupported_by_current_contract"}})
    # A: canonical names, plausible STT substitutions, and official aliases.
    for text, mid, qty, temp in [
        ("카페라테 한 잔 주세요", "cafe_latte", 1, None), ("카페라트 두 잔 주세요", "cafe_latte", 2, None),
        ("자몽에이드 하나 주세요", "grapefruit_ade", 1, None), ("자몽이도 하나 주세요", "grapefruit_ade", 1, None),
        ("자몽레이드 한 잔 주세요", "grapefruit_ade", 1, None), ("아이스 바닐라라떼 하나 주세요", "vanilla_latte", 1, "iced"),
        ("바스크 치즈케이크 하나 주세요", "basque_cheesecake", 1, None), ("바스크 치즈 케이크 두 개 주세요", "basque_cheesecake", 2, None),
        ("케모마일티 한 잔 주세요", "chamomile_tea", 1, None), ("캐모마일티 두 잔 주세요", "chamomile_tea", 2, None),
        ("아이스 밀크티 한 잔 주세요", "milk_tea", 1, "iced"), ("아아 두 잔 주세요", "americano", 2, "iced"),
        ("뜨아 한 잔 주세요", "americano", 1, "hot"), ("아라 하나 주세요", "cafe_latte", 1, "iced"), ("아바라 두 잔 주세요", "vanilla_latte", 2, "iced"),
    ]: add("alias_stt_confusion", text, [cmd(mid, qty, temp)])
    # B: Korean native digits, Arabic digits, and drink/dessert counters.
    for text, mid, qty, temp in [
        ("아이스 아메리카노 한 잔 주세요", "americano", 1, "iced"), ("아이스 아메리카노 두 잔 주세요", "americano", 2, "iced"),
        ("아이스 아메리카노 2잔 주세요", "americano", 2, "iced"), ("아이스 아메리카노 두 개 주세요", "americano", 2, "iced"),
        ("아메리카노 세 잔 주세요", "americano", 3, None), ("바스크 치즈 케이크 세 개 주세요", "basque_cheesecake", 3, None),
    ]: add("quantity_expression", text, [cmd(mid, qty, temp)])
    # C: all commands retain utterance order; no cross-item quantity borrowing.
    add("multi_item", "카페라떼 두 잔, 아이스티 하나, 크로플 아이스크림 한 개 주세요", [cmd("cafe_latte", 2), cmd("iced_tea", 1), cmd("croffle_icecream", 1)])
    add("multi_item", "아메리카노 세 잔하고 카페라떼 하나 주세요", [cmd("americano", 3), cmd("cafe_latte", 1)])
    add("multi_item", "아이스 아메리카노 두 잔이랑 따뜻한 카페라떼 한 잔 주세요", [cmd("americano", 2, "iced"), cmd("cafe_latte", 1, "hot")])
    add("multi_item", "아이스티 하나랑 바스크 치즈 케이크 두 개 주세요", [cmd("iced_tea", 1), cmd("basque_cheesecake", 2)])
    add("multi_item", "자몽에이드 하나, 밀크티 두 잔, 크로플 아이스크림 세 개 주세요", [cmd("grapefruit_ade", 1), cmd("milk_tea", 2), cmd("croffle_icecream", 3)])
    # D: expected is an ADD_ITEM, never a reconstructed cart mutation.
    add("existing_cart_add", "카페라떼 두 잔 추가해 주세요", [cmd("cafe_latte", 2)], before=[cart("americano")])
    add("existing_cart_add", "아이스티도 하나 주세요", [cmd("iced_tea", 1)], before=[cart("cafe_latte", temperature="hot")])
    add("existing_cart_add", "자몽에이드 하나 더 주세요", [cmd("grapefruit_ade", 1)], before=[cart("americano"), cart("basque_cheesecake", temperature=None)])
    # E: schema has order confirmation, but has no payment-method field.
    for text in ("결제해 주세요", "결제할게요", "주문할게요", "이대로 결제해 줘", "이걸로 주문할게요"):
        add("confirm_order", text, [cmd("", None, intent="CONFIRM_ORDER")], before=[cart("americano")])
    # F: pass means no MISSING_FIELD.temperature; default itself is deliberately unscored.
    for text in ("아메리카노 한 잔 주세요", "카페라떼 하나 주세요", "밀크티 두 잔 주세요", "바닐라라떼 하나 추가해 주세요"):
        add("temperature_no_question", text, [], behavioral="temperature_no_question")
    for text in ("흔금으로 결제할게요", "카도로 결제할게요", "쌈쑹으로 결제할게요"):
        add("payment_method_stt_confusion", text, None, before=[cart("americano")], scored=False)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT)
    args = parser.parse_args()
    rows = records()
    evaluator = ChallengeEvaluator()
    # Fail early when menu/schema drift invalidates any scored expectation.
    for row in rows:
        if row["metadata"]["scored"] and row["metadata"].get("behavioral") is None:
            assert evaluator.score(row, canonical_json(row["output"]["value"]))["schema_valid"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")
    print(f"{len(rows)} cases -> {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
