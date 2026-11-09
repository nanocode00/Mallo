from __future__ import annotations

from adapters.nlu.input_normalizer import normalize_nlu_input
from adapters.nlu.qwen06b_guard import repair_qwen06b_payload


def test_normalizes_approved_stt_menu_confusions_and_preserves_original() -> None:
    normalized = normalize_nlu_input("카페라테 한 잔, 자몽레이드 하나, 케모마일티 두 잔 주세요")

    assert normalized.original_text == "카페라테 한 잔, 자몽레이드 하나, 케모마일티 두 잔 주세요"
    assert normalized.normalized_text == "카페라떼 1잔, 자몽에이드 1개, 캐모마일티 2잔 주세요"
    assert ("카페라테", "카페라떼") in normalized.replacements


def test_keeps_existing_official_aliases_and_normal_expression_intact() -> None:
    normalized = normalize_nlu_input("아아 두 잔과 카페라떼 3개 주세요")

    assert normalized.normalized_text == "아아 2잔과 카페라떼 3개 주세요"
    assert all(source != "아아" for source, _ in normalized.replacements)


def test_normalizes_basque_cheesecake_spacing_confusion():
    normalized = normalize_nlu_input("바스크 치즈케이크 하나 주세요")

    assert normalized.normalized_text == "바스크 치즈 케이크 1개 주세요"


def test_normalizes_non_coffee_stt_confusion_without_changing_other_words() -> None:
    normalized = normalize_nlu_input("넌커피 뭐 있어")

    assert normalized.normalized_text == "논커피 뭐 있어"
    assert ("넌커피", "논커피") in normalized.replacements


def test_generic_multi_add_keeps_menu_quantity_and_order() -> None:
    text = normalize_nlu_input(
        "카페라테 두 잔, 아이스티 하나, 크로플 아이스크림 한 개 주세요"
    ).normalized_text
    repaired = repair_qwen06b_payload(text, [], {"code": "MIXED_INTENT"})

    assert [(row["target_item_id"], row["quantity"], row["temperature"]) for row in repaired] == [
        ("cafe_latte", 2, None),
        ("iced_tea", 1, None),
        ("croffle_icecream", 1, None),
    ]
