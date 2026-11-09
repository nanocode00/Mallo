from __future__ import annotations

import pytest

from domain.korean_normalizer import (
    native_number_to_korean,
    normalize_korean_text_for_tts,
    sino_number_to_korean,
)


def test_sino_number_to_korean() -> None:
    assert sino_number_to_korean(0) == "영"
    assert sino_number_to_korean(1) == "일"
    assert sino_number_to_korean(10) == "십"
    assert sino_number_to_korean(15) == "십오"
    assert sino_number_to_korean(100) == "백"
    assert sino_number_to_korean(1000) == "천"
    assert sino_number_to_korean(4700) == "사천칠백"
    assert sino_number_to_korean(5200) == "오천이백"
    assert sino_number_to_korean(9400) == "구천사백"
    assert sino_number_to_korean(10000) == "만"
    assert sino_number_to_korean(10400) == "만 사백"
    assert sino_number_to_korean(12000) == "만 이천"
    assert sino_number_to_korean(15400) == "만 오천사백"
    assert sino_number_to_korean(100000) == "십만"
    assert sino_number_to_korean(1000000) == "백만"


def test_native_number_to_korean() -> None:
    assert native_number_to_korean(1) == "한"
    assert native_number_to_korean(2) == "두"
    assert native_number_to_korean(3) == "세"
    assert native_number_to_korean(4) == "네"
    assert native_number_to_korean(5) == "다섯"
    assert native_number_to_korean(10) == "열"


def test_normalize_korean_text_price() -> None:
    # 5,200원 -> 오천이백원 (오, 이백원 방지)
    text = "아이스 아메리카노 한 잔은 5,200원입니다."
    assert normalize_korean_text_for_tts(text) == "아이스 아메리카노 한 잔은 오천이백원입니다."

    # 15,400원 -> 만 오천사백원
    text = "총 결제 금액은 15,400원입니다."
    assert normalize_korean_text_for_tts(text) == "총 결제 금액은 만 오천사백원입니다."


def test_normalize_korean_text_quantity() -> None:
    # 3잔 -> 세 잔, 2개 -> 두 개
    text = "캐모마일티 3잔과 크로플 2개를 주문하셨습니다."
    assert (
        normalize_korean_text_for_tts(text)
        == "캐모마일티 세 잔과 크로플 두 개를 주문하셨습니다."
    )


def test_normalize_korean_text_symbols() -> None:
    # 분절 기호 및 비표준 기호 정제
    text = "아이스 아메리카노, ... 담았습니다."
    assert normalize_korean_text_for_tts(text) == "아이스 아메리카노, 담았습니다."

    text = "아메리카노 / 두 잔 | 라떼 한 잔"
    assert normalize_korean_text_for_tts(text) == "아메리카노, 두 잔, 라떼 한 잔"

    text = "주문 완료... 감사합니다."
    assert normalize_korean_text_for_tts(text) == "주문 완료. 감사합니다."
