"""
STT 평가 지표 유틸리티
=====================

jiwer 기반 오프라인 지표와 주문 도메인 Token Accuracy를 제공한다.

- WER은 공백 단위라 한국어에서 과대 평가되므로 CER을 기본 지표로 사용한다.
- 메뉴명 / 수량 / 옵션 / 금액 키워드는 주문 도메인 평가(TRD 25.1)에 사용한다.

설치 필요 패키지:
    jiwer>=4.0.0

사용 예:
    from metrics import compute_cer, keyword_accuracy, DEFAULT_KEYWORDS
"""

from __future__ import annotations

from typing import Sequence

from jiwer import cer, wer

# ------------------------------------------------------------
# 기본 지표 (jiwer)
# ------------------------------------------------------------

def compute_cer(reference: str, hypothesis: str) -> float:
    """CER (Character Error Rate) — 한국어 STT 기본 지표."""
    return float(cer(reference, hypothesis))


def compute_wer(reference: str, hypothesis: str) -> float:
    """WER (Word Error Rate) — 공백 단위, 한국어에선 참고용으로만 사용."""
    return float(wer(reference, hypothesis))


def corpus_cer(
    references: Sequence[str],
    hypotheses: Sequence[str],
) -> float:
    """
    Corpus-level CER.

    문장별 CER의 평균이 아니라, 전체 reference/hypothesis 목록을
    한 번에 묶어 jiwer가 집계한 오류를 전체 글자 수로 나눈 값이다.
    짧은 문장이 긴 문장과 같은 비중으로 반영되는 편향을 제거한다.

    references와 hypotheses의 길이는 같아야 한다.
    """
    if len(references) != len(hypotheses):
        raise ValueError(
            "references와 hypotheses의 길이가 다릅니다: "
            f"{len(references)} != {len(hypotheses)}"
        )
    if not references:
        return 0.0
    return float(cer(references, hypotheses))


def corpus_wer(
    references: Sequence[str],
    hypotheses: Sequence[str],
) -> float:
    """Corpus-level WER. 문장별 평균이 아니라 전체 집계로 계산한다."""
    if len(references) != len(hypotheses):
        raise ValueError(
            "references와 hypotheses의 길이가 다릅니다: "
            f"{len(references)} != {len(hypotheses)}"
        )
    if not references:
        return 0.0
    return float(wer(references, hypotheses))


# ------------------------------------------------------------
# 주문 도메인 키워드 (TRD 25.1: 메뉴·수량·옵션·금액 Token Accuracy)
# ------------------------------------------------------------

DEFAULT_MENU_KEYWORDS = [
    "아메리카노",
    "카페라떼",
    "바닐라라떼",
    "자몽에이드",
    "말차라떼",
    "밀크티",
    "캐모마일티",
    "아이스티",
    "크로플 아이스크림",
    "바스크 치즈 케이크",
]

DEFAULT_QUANTITY_KEYWORDS = [
    "한 잔",
    "두 잔",
    "세 잔",
    "네 잔",
    "다섯 잔",
    "한 개",
    "두 개",
    "세 개",
    "하나",
]

DEFAULT_OPTION_KEYWORDS = [
    "아이스",
    "따뜻한",
    "핫",
    "ice",
    "hot",
]

DEFAULT_PRICE_KEYWORDS = [
    "원",
    "원입니다",
    "원이에요",
]

DEFAULT_KEYWORDS = {
    "menu": DEFAULT_MENU_KEYWORDS,
    "quantity": DEFAULT_QUANTITY_KEYWORDS,
    "option": DEFAULT_OPTION_KEYWORDS,
    "price": DEFAULT_PRICE_KEYWORDS,
}


def _normalize(text: str) -> str:
    """
    대소문자·공백 변동으로 인한 오탐을 줄이기 위한 정규화.

    모든 공백을 제거하므로 "카페 라떼"와 "카페라떼"를 동일하게 취급한다.
    """
    return "".join(text.strip().lower().split())


_KOREAN_NUM_MAP = {
    "하나": "1", "한": "1",
    "두": "2", "둘": "2",
    "세": "3", "셋": "3",
    "네": "4", "넷": "4",
    "다섯": "5",
}


def _normalize_quantity(text: str) -> str:
    """
    한글 숫자를 아라비아 숫자로 변환한 뒤 공백을 제거한다.

    "세 잔" → "3잔", "다섯 개" → "5개" 등.
    STT가 숫자를 아라비아 숫자로 전사할 때 recall이 떨어지는 문제를 방지한다.
    """
    norm = _normalize(text)
    for ko, digit in sorted(_KOREAN_NUM_MAP.items(), key=lambda x: -len(x[0])):
        norm = norm.replace(ko, digit)
    return norm


def _find_keyword_counts(
    text: str,
    keywords: Sequence[str],
    normalize_fn=None,
) -> dict[str, int]:
    """
    keywords로 text를 스캔해 키워드별 비중복 매치 횟수를 센다.

    - 긴 키워드 우선으로 매치하므로 "원"이 "원입니다"와 동일 span에서
      중복 집계되지 않는다.
    - 이미 소비된 span과 겹치는 매치는 건너뛴다.
    - 키워드는 정규화된 형태로 집계하며, span 겹침 판정은 정규화된 text에
      적용한다.

    반환:
        {정규화된 키워드: 등장(비중복 매치) 횟수}
    """
    if normalize_fn is None:
        normalize_fn = _normalize

    norm_keywords = sorted(
        {normalize_fn(k) for k in keywords if normalize_fn(k)},
        key=lambda k: (len(k), k),
        reverse=True,
    )
    spans: list[tuple[int, int]] = []
    counts: dict[str, int] = {k: 0 for k in norm_keywords}

    for keyword in norm_keywords:
        start = 0
        while True:
            idx = text.find(keyword, start)
            if idx == -1:
                break
            end = idx + len(keyword)
            if all(end <= s or idx >= e for s, e in spans):
                spans.append((idx, end))
                counts[keyword] += 1
                start = end
            else:
                start = idx + 1

    return counts


def keyword_recall(
    reference: str,
    hypothesis: str,
    keywords: Sequence[str],
    normalize_fn=None,
) -> dict[str, float | list[str]]:
    """
    reference에 등장한 키워드가 hypothesis에서 인식된 비율(recall)을
    '발생 횟수' 기준으로 계산한다.

    - reference와 hypothesis 각각에서 키워드의 비중복 매치 수를 세고,
      키워드별로 matched = min(reference 횟수, hypothesis 횟수)를 합산한다.
      "아메리카노"가 reference에 두 번, hypothesis에 한 번만 등장하면
      matched는 1이 되어 recall이 1.0이 되지 않는다.
    - 긴 키워드 우선 매치로 "원"이 "5000원입니다"의 span을 "원입니다"와
      중복 집계하지 않는다.
    - reference에 등장하지 않는 키워드는 분모에서 제외한다.
    - 부분 문자열 포함을 검사하므로 "카페라떼"가 "카페 라떼"로 띄어 써도
      공백만 정규화하면 매칭된다. 어미 변화 등 형태 변이는 별도 후처리 대상이다.

    반환:
        {
            "total": int,          # reference의 비중복 키워드 매치 수
            "matched": int,        # hypothesis에서도 인식된 매치 수
            "recall": float,       # matched / total (total==0 이면 0.0)
            "matched_keywords": list[str],
            "missed_keywords": list[str],
        }
    """
    if normalize_fn is None:
        normalize_fn = _normalize

    ref_counts = _find_keyword_counts(normalize_fn(reference), keywords, normalize_fn)
    hyp_counts = _find_keyword_counts(normalize_fn(hypothesis), keywords, normalize_fn)

    total = 0
    matched = 0
    matched_keywords: list[str] = []
    missed_keywords: list[str] = []

    for keyword in keywords:
        norm_keyword = normalize_fn(keyword)
        if not norm_keyword:
            continue
        ref_count = ref_counts.get(norm_keyword, 0)
        if ref_count == 0:
            continue
        total += ref_count
        matched_count = min(ref_count, hyp_counts.get(norm_keyword, 0))
        matched += matched_count
        if matched_count > 0:
            matched_keywords.append(keyword)
        if matched_count < ref_count:
            missed_keywords.append(keyword)

    recall = matched / total if total > 0 else 0.0

    return {
        "total": total,
        "matched": matched,
        "matched_keywords": matched_keywords,
        "missed_keywords": missed_keywords,
        "recall": recall,
    }


def keyword_accuracy(
    reference: str,
    hypothesis: str,
    keywords: Sequence[str],
) -> dict[str, float | int]:
    """keyword_recall의 결과에서 수치 필드만 평탄하게 반환한다."""
    result = keyword_recall(reference, hypothesis, keywords)
    return {
        "total": result["total"],
        "matched": result["matched"],
        "recall": result["recall"],
    }


def aggregate_keyword_recall(
    sentences: Sequence[
        tuple[str, str] | dict[str, str]
    ],
    keywords: Sequence[str],
    normalize_fn=None,
) -> dict[str, float | int]:
    """
    문장 전체에 걸친 키워드 recall을 "전체 matched / 전체 total"로 집계한다.

    문장별 recall의 단순 평균은 해당 키워드가 아예 없는 문장이 분모에
    포함되지 않아 recall 0 문장으로 평균을 낮추는 편향이 있다.
    여기서는 모든 문장의 total과 matched를 각각 합산한 뒤 한 번에 나눈다.

    sentences:
        각 항목은 ("reference", "hypothesis") 순서의 튜플 또는
        {"reference": ..., "hypothesis": ...} dict.

    반환:
        {
            "total": int,      # 전체 문장에서 reference에 등장한 키워드 수
            "matched": int,    # 전체 문장에서 hypothesis에도 인식된 키워드 수
            "recall": float,   # matched / total (total==0 이면 0.0)
        }
    """
    total = 0
    matched = 0

    for item in sentences:
        if isinstance(item, dict):
            reference = item["reference"]
            hypothesis = item["hypothesis"]
        else:
            reference, hypothesis = item

        result = keyword_recall(
            reference,
            hypothesis,
            keywords,
            normalize_fn=normalize_fn,
        )
        total += int(result["total"])
        matched += int(result["matched"])

    recall = matched / total if total > 0 else 0.0

    return {
        "total": total,
        "matched": matched,
        "recall": recall,
    }
