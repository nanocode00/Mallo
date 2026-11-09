from __future__ import annotations

import re

# 한자어 수사 (금액, 날짜, 일반 숫자용)
_SINO_DIGITS = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_SINO_SMALL_UNITS = ["", "십", "백", "천"]
_SINO_BIG_UNITS = ["", "만", "억", "조"]

# 고유어 수사 (수량 단위 명사 앞용)
_NATIVE_NUM_MAP = {
    1: "한",
    2: "두",
    3: "세",
    4: "네",
    5: "다섯",
    6: "여섯",
    7: "일곱",
    8: "여덟",
    9: "아홉",
    10: "열",
    11: "열한",
    12: "열두",
    13: "열세",
    14: "열네",
    15: "열다섯",
    16: "열여섯",
    17: "열일곱",
    18: "열여덟",
    19: "열아홉",
    20: "스무",
}


def sino_number_to_korean(num: int) -> str:
    """정수를 한자어 한국어 수사 문자열로 변환합니다.

    예:
        0 -> '영'
        5200 -> '오천이백'
        10400 -> '만 사백'
        15400 -> '만 오천사백'
        12000 -> '만 이천'
        10000 -> '만'
        100000 -> '십만'
    """
    if num == 0:
        return "영"
    if num < 0:
        return f"마이너스 {sino_number_to_korean(-num)}"

    result: list[str] = []
    big_idx = 0
    remaining = num

    while remaining > 0:
        chunk = remaining % 10000
        remaining //= 10000

        if chunk > 0:
            chunk_str: list[str] = []
            for s_idx in range(4):
                d = chunk % 10
                chunk //= 10
                if d > 0:
                    unit = _SINO_SMALL_UNITS[s_idx]
                    d_str = _SINO_DIGITS[d]
                    if d == 1 and unit != "":
                        chunk_str.append(unit)
                    else:
                        chunk_str.append(f"{d_str}{unit}")
            chunk_res = "".join(reversed(chunk_str))
            big_unit = _SINO_BIG_UNITS[big_idx]

            if big_unit == "만" and chunk_res == "일":
                result.append("만")
            else:
                result.append(f"{chunk_res}{big_unit}")
        big_idx += 1

    return " ".join(reversed(result))


def native_number_to_korean(num: int, is_counter: bool = True) -> str:
    """수량 단위 앞의 고유어 수사로 변환합니다."""
    if num in _NATIVE_NUM_MAP:
        return _NATIVE_NUM_MAP[num]
    # 20을 초과하거나 매핑에 없는 경우 한자어 수사 반환
    return sino_number_to_korean(num)


def _normalize_price_match(match: re.Match[str]) -> str:
    raw_num = match.group(1).replace(",", "").strip()
    try:
        num = int(raw_num)
        kor = sino_number_to_korean(num)
        return f"{kor}원"
    except ValueError:
        return match.group(0)


def _normalize_quantity_match(match: re.Match[str]) -> str:
    raw_num = match.group(1).strip()
    unit = match.group(2).strip()
    try:
        num = int(raw_num)
        kor = native_number_to_korean(num, is_counter=True)
        return f"{kor} {unit}"
    except ValueError:
        return match.group(0)


def normalize_korean_text_for_tts(text: str) -> str:
    """TTS 입력 텍스트를 고령자 및 음성 합성 엔진에 최적화된 표준 한글로 정규화합니다.

    1. 금액 숫자 정규화: '5,200원' -> '오천이백원', '15,400원' -> '만 오천사백원'
    2. 수량 단위 숫자 정규화: '3잔' -> '세 잔', '4개' -> '네 잔'
    3. 비표준 분절 기호 정제: ', ... ', '...', '…', '/', '|', '~' 등을 표준 쉼표 및 마침표로 정제
    4. 중복 공백 및 구두점 정리
    """
    if not text or not text.strip():
        return ""

    normalized = text.strip()

    # 1. 금액 정규화 (쉼표 포함 숫자 + 원)
    normalized = re.sub(r"([0-9,]+)\s*원", _normalize_price_match, normalized)

    # 2. 수량 단위 정규화 (숫자 + 잔/개/조각/명/번/세트/박스)
    normalized = re.sub(
        r"([0-9]+)\s*(잔|개|조각|명|번|세트|박스)",
        _normalize_quantity_match,
        normalized,
    )

    # 3. 비표준 분절 기호 정제
    # ', ... ' or ' ... ' -> ', '
    normalized = re.sub(r",\s*\.\.\.\s*", ", ", normalized)
    normalized = re.sub(r"\s+\.\.\.\s*", ", ", normalized)
    # 연속된 점(...) or 줄임표(…) -> '.'
    normalized = re.sub(r"\.{2,}", ".", normalized)
    normalized = normalized.replace("…", ".")
    # 슬래시(/)나 파이프(|) -> ', '
    normalized = re.sub(r"\s*[/|]\s*", ", ", normalized)
    # 물결(~) 및 대시(-) -> 공백 또는 쉼표
    normalized = re.sub(r"~+", " ", normalized)

    # 4. 중복 쉼표 및 마침표 정리
    normalized = re.sub(r",\s*,+", ", ", normalized)
    normalized = re.sub(r"\.\s*\.+", ". ", normalized)
    normalized = re.sub(r",\s*\.", ".", normalized)
    normalized = re.sub(r"\.\s*,", ".", normalized)

    # 5. 공백 정규화
    normalized = re.sub(r"\s*,\s*", ", ", normalized)
    normalized = re.sub(r"\s*\.\s*", ". ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized.strip()
