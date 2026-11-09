from __future__ import annotations

import pytest

from domain.korean_normalizer import normalize_korean_text_for_tts
from domain.models import AdaptiveTextTransformer, transform_text_by_level


def _assert_canonical_chunks(text: str, level: int) -> None:
    """가격 수사 정규화 외에는 chunk 결합 결과가 canonical text여야 한다."""
    assert " ".join(AdaptiveTextTransformer.transform_to_chunks(text, level=level)) == normalize_korean_text_for_tts(text)


def test_level_0_preserves_original_text() -> None:
    """Level 0 변환 시 수사 정규화와 함께 원본 문장이 유지되어야 한다 (AC-01)."""
    text = "아이스 아메리카노 두 잔을 담았습니다."
    assert AdaptiveTextTransformer.transform(text, level=0) == text
    assert AdaptiveTextTransformer.transform_to_chunks(text, level=0) == [text]
    assert AdaptiveTextTransformer.get_gap_ms(0) == 0
    assert transform_text_by_level(text, level=0) == text


def test_level_1_semantic_chunks() -> None:
    """Level 1 변환 시 가짜 문장부호 삽입 없이 자연스러운 의미 단위로 분절되어야 한다."""
    text = "아이스 아메리카노 두 잔과 따뜻한 카페라떼 한 잔을 담았습니다."
    chunks = AdaptiveTextTransformer.transform_to_chunks(text, level=1)
    assert chunks == [text]
    _assert_canonical_chunks(text, 1)
    assert AdaptiveTextTransformer.get_gap_ms(1) == 280


def test_level_2_uses_original_conjunction_boundary_without_rewriting() -> None:
    text = "아이스 아메리카노 두 잔과 따뜻한 카페라떼 한 잔을 담았습니다."
    chunks = AdaptiveTextTransformer.transform_to_chunks(text, level=2)
    assert chunks == ["아이스 아메리카노 두 잔과", "따뜻한 카페라떼 한 잔을 담았습니다."]
    _assert_canonical_chunks(text, 2)
    assert AdaptiveTextTransformer.get_gap_ms(2) == 480


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("아이스 아메리카노 두 잔과 따뜻한 카페라떼 한 잔을 담았습니다.", "장바구니에 담았습니다."),
        ("아이스 아메리카노 두 잔과 따뜻한 카페라떼 한 잔을 추가했습니다.", "추가했습니다."),
        ("아이스 아메리카노 두 잔과 따뜻한 카페라떼 한 잔을 변경했습니다.", "변경했습니다."),
    ],
)
def test_level_2_action_sentences_preserve_canonical_text(text: str, action: str) -> None:
    chunks = AdaptiveTextTransformer.transform_to_chunks(text, level=2)

    assert "장바구니에입니다." not in chunks
    assert action not in chunks
    _assert_canonical_chunks(text, 2)


def test_level_2_menu_list_uses_only_canonical_substrings() -> None:
    chunks = AdaptiveTextTransformer.transform_to_chunks(
        "커피 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, 바닐라라떼 3,400원입니다.",
        level=2,
    )

    assert chunks == [
        "커피 메뉴는 아메리카노 사천칠백원,",
        "카페라떼 오천이백원,",
        "바닐라라떼 삼천사백원입니다.",
    ]
    _assert_canonical_chunks("커피 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, 바닐라라떼 3,400원입니다.", 2)


def test_price_announcement_transformation() -> None:
    """결제 금액 안내 문장의 Level 0/1/2 변환 및 한글 수사 정규화가 올바르게 수행되어야 한다."""
    text = "총 결제 금액은 9,400원입니다."

    assert (
        AdaptiveTextTransformer.transform(text, level=0)
        == "총 결제 금액은 구천사백원입니다."
    )
    assert (
        AdaptiveTextTransformer.transform_to_chunks(text, level=1)
        == ["총 결제 금액은 구천사백원입니다."]
    )
    assert (
        AdaptiveTextTransformer.transform_to_chunks(text, level=2)
        == ["총 결제 금액은 구천사백원입니다."]
    )


def test_empty_or_whitespace_input() -> None:
    """빈 문자열이나 공백만 있는 입력은 빈 문자열을 반환해야 한다 (EC-01)."""
    assert AdaptiveTextTransformer.transform("", level=0) == ""
    assert AdaptiveTextTransformer.transform("   ", level=1) == ""
    assert AdaptiveTextTransformer.transform(None, level=2) == ""  # type: ignore[arg-type]


def test_general_short_sentence_preservation() -> None:
    """일반 단문은 형태를 온전히 보존하여 분절되어야 한다 (EC-02)."""
    text = "주문을 말씀해 주세요."
    assert AdaptiveTextTransformer.transform(text, level=0) == text
    assert AdaptiveTextTransformer.transform_to_chunks(text, level=1) == [text]
    assert AdaptiveTextTransformer.transform_to_chunks(text, level=2) == [text]


def test_invalid_level_raises_value_error() -> None:
    """유효하지 않은 Level 입력 시 ValueError가 발생해야 한다 (AC-05, EC-03)."""
    with pytest.raises(ValueError, match="Invalid TTS level"):
        AdaptiveTextTransformer.transform("아메리카노 한 잔", level=3)

    with pytest.raises(ValueError, match="Invalid TTS level"):
        AdaptiveTextTransformer.transform("아메리카노 한 잔", level=-1)
