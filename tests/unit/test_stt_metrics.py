import sys
from pathlib import Path

from scripts.eval.stt.metrics import (
    DEFAULT_KEYWORDS,
    aggregate_keyword_recall,
    compute_cer,
    compute_wer,
    corpus_cer,
    corpus_wer,
    keyword_accuracy,
    keyword_recall,
)


def test_compute_cer_is_zero_for_perfect_match() -> None:
    assert compute_cer("아메리카노 두 잔", "아메리카노 두 잔") == 0.0


def test_compute_cer_is_positive_for_mismatch() -> None:
    assert compute_cer("아메리카노 두 잔", "아메리카노 한 잔") > 0.0


def test_compute_wer_is_zero_for_perfect_match() -> None:
    assert compute_wer("아메리카노 두 잔", "아메리카노 두 잔") == 0.0


def test_compute_wer_is_positive_for_insertion() -> None:
    assert compute_wer("아메리카노", "아이스 아메리카노") > 0.0


def test_keyword_recall_is_zero_when_total_is_zero() -> None:
    result = keyword_recall(
        "평가 대상 없는 문장",
        "평가 대상 없는 문장",
        ["아메리카노"],
    )
    assert result["total"] == 0
    assert result["matched"] == 0
    assert result["recall"] == 0.0


def test_keyword_recall_is_one_when_all_matched() -> None:
    result = keyword_recall(
        "아이스 아메리카노 두 잔",
        "아이스 아메리카노 두 잔",
        DEFAULT_KEYWORDS["menu"],
    )
    assert result["matched"] == result["total"]
    assert result["recall"] == 1.0


def test_keyword_recall_counts_partial_match() -> None:
    result = keyword_recall(
        "아이스 아메리카노 두 잔",
        "따뜻한 아메리카노 두 잔",
        DEFAULT_KEYWORDS["option"],
    )
    assert result["total"] == 1
    assert result["matched"] == 0
    assert result["recall"] == 0.0


def test_keyword_recall_ignores_keywords_not_in_reference() -> None:
    result = keyword_recall(
        "바닐라라떼 한 잔",
        "바닐라라떼 한 잔",
        DEFAULT_KEYWORDS["menu"],
    )
    assert result["total"] == 1
    assert result["matched"] == 1


def test_keyword_recall_normalizes_spacing() -> None:
    result = keyword_recall(
        "카페 라떼",
        "카페라떼",
        DEFAULT_KEYWORDS["menu"],
    )
    assert result["recall"] == 1.0


def test_keyword_recall_normalizes_case() -> None:
    result = keyword_recall(
        "ICE 아메리카노",
        "ice 아메리카노",
        ["ICE"],
    )
    assert result["recall"] == 1.0


def test_keyword_recall_reports_missed_keywords() -> None:
    result = keyword_recall(
        "아이스 아메리카노",
        "따뜻한 아메리카노",
        DEFAULT_KEYWORDS["option"],
    )
    assert result["missed_keywords"] == ["아이스"]


def test_keyword_recall_counts_repeated_keyword_by_occurrence() -> None:
    # 동일 메뉴가 두 번 등장하고 한 번만 인식되면 recall이 1.0이 아니다.
    result = keyword_recall(
        "아메리카노 한 잔 아메리카노",
        "아메리카노 한 잔",
        ["아메리카노"],
    )
    assert result["total"] == 2
    assert result["matched"] == 1
    assert result["recall"] == 0.5


def test_keyword_recall_counts_all_repeated_occurrences() -> None:
    result = keyword_recall(
        "아메리카노 한 잔 아메리카노",
        "아메리카노 한 잔 아메리카노",
        ["아메리카노"],
    )
    assert result["total"] == 2
    assert result["matched"] == 2
    assert result["recall"] == 1.0


def test_keyword_recall_counts_repeated_quantity() -> None:
    result = keyword_recall(
        "카페라떼 한 잔, 바닐라라떼 한 잔",
        "카페라떼 한 잔",
        DEFAULT_KEYWORDS["quantity"],
    )
    assert result["total"] == 2
    assert result["matched"] == 1
    assert result["recall"] == 0.5


def test_keyword_recall_does_not_double_count_contained_keywords() -> None:
    # "5000원입니다"에서 "원"과 "원입니다"가 같은 span을 중복 집계하지 않는다.
    result = keyword_recall(
        "아이스 아메리카노 5000원입니다",
        "아이스 아메리카노 5000원입니다",
        DEFAULT_KEYWORDS["price"],
    )
    assert result["total"] == 1
    assert result["matched"] == 1
    assert result["recall"] == 1.0


def test_keyword_recall_partial_repeat_reports_both_lists() -> None:
    # 일부만 누락된 반복 키워드는 matched와 missed 양쪽에 모두 나타난다.
    result = keyword_recall(
        "아메리카노 한 잔 아메리카노",
        "아메리카노 한 잔",
        ["아메리카노"],
    )
    assert result["matched_keywords"] == ["아메리카노"]
    assert result["missed_keywords"] == ["아메리카노"]


def test_keyword_accuracy_flattens_numeric_fields() -> None:
    result = keyword_accuracy(
        "아이스 아메리카노",
        "따뜻한 아메리카노",
        DEFAULT_KEYWORDS["option"],
    )
    assert set(result) == {"total", "matched", "recall"}
    assert result["total"] == 1
    assert result["matched"] == 0
    assert result["recall"] == 0.0


def test_default_keywords_cover_order_categories() -> None:
    assert set(DEFAULT_KEYWORDS) == {
        "menu",
        "quantity",
        "option",
        "price",
    }
    assert len(DEFAULT_KEYWORDS["menu"]) == 10


def test_corpus_cer_equals_perfect_match_zero() -> None:
    refs = ["아이스 아메리카노 한 잔", "바닐라라떼 두 잔"]
    hyps = ["아이스 아메리카노 한 잔", "바닐라라떼 두 잔"]
    assert corpus_cer(refs, hyps) == 0.0


def test_corpus_cer_aggregates_across_sentences() -> None:
    refs = ["아메리카노", "바닐라라떼 두 잔"]
    hyps = ["아메리카노", "바닐라라떼 두 잔"]
    assert corpus_cer(refs, hyps) == 0.0


def test_corpus_cer_raises_on_length_mismatch() -> None:
    try:
        corpus_cer(["하나"], ["하나", "둘"])
    except ValueError:
        return
    raise AssertionError("corpus_cer가 길이 불일치를 감지하지 못함")


def test_corpus_wer_raises_on_length_mismatch() -> None:
    try:
        corpus_wer(["하나"], ["하나", "둘"])
    except ValueError:
        return
    raise AssertionError("corpus_wer가 길이 불일치를 감지하지 못함")


def test_corpus_wer_aggregates_across_sentences() -> None:
    refs = ["아이스 아메리카노", "바닐라라떼 두 잔"]
    hyps = ["아이스 아메리카노", "바닐라라떼 두 잔"]
    assert corpus_wer(refs, hyps) == 0.0


def test_corpus_wer_positive_when_one_sentence_wrong() -> None:
    refs = ["아메리카노", "바닐라라떼 두 잔"]
    hyps = ["따뜻한 차", "바닐라라떼 두 잔"]
    assert corpus_wer(refs, hyps) > 0.0


def test_aggregate_keyword_recall_uses_total_matched_over_total() -> None:
    # 문장별 recall 평균과 달리, 키워드가 없는 문장이 분모에 포함되지 않는다.
    sentences = [
        ("아이스 아메리카노 한 잔", "아이스 아메리카노 한 잔"),
        ("인사말입니다", "인사말입니다"),
    ]
    result = aggregate_keyword_recall(
        sentences,
        DEFAULT_KEYWORDS["menu"],
    )
    assert result["total"] == 1
    assert result["matched"] == 1
    assert result["recall"] == 1.0


def test_aggregate_keyword_recall_sums_total_and_matched() -> None:
    sentences = [
        ("아이스 아메리카노", "따뜻한 차"),
        ("바닐라라떼 한 잔", "바닐라라떼 한 잔"),
    ]
    result = aggregate_keyword_recall(
        sentences,
        DEFAULT_KEYWORDS["menu"],
    )
    assert result["total"] == 2
    assert result["matched"] == 1
    assert result["recall"] == 0.5


def test_aggregate_keyword_recall_accepts_dict_items() -> None:
    sentences = [
        {"reference": "아이스 아메리카노", "hypothesis": "아이스 아메리카노"},
    ]
    result = aggregate_keyword_recall(
        sentences,
        DEFAULT_KEYWORDS["menu"],
    )
    assert result["total"] == 1
    assert result["matched"] == 1
    assert result["recall"] == 1.0


def test_aggregate_keyword_recall_zero_total() -> None:
    sentences = [
        ("인사말입니다", "인사말입니다"),
        ("오늘 날씨가 좋네요", "오늘 날씨가 좋네요"),
    ]
    result = aggregate_keyword_recall(
        sentences,
        DEFAULT_KEYWORDS["menu"],
    )
    assert result["total"] == 0
    assert result["matched"] == 0
    assert result["recall"] == 0.0
