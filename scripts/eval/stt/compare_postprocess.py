"""
STT 메뉴명 보정 전/후 성능 비교 (S-15 ~ S-17)
============================================

1) 실제 데이터: compare_both_150_seed-42.csv 의 baseline/qlora 텍스트에
   CandidateMatcher.correct() 를 적용해 보정 발생 여부와 CER/WER 무영향을 확인한다.
   (평가셋에 메뉴명이 없음이 확인되면 이는 S-10 도메인 평가셋 필요의 근거가 된다.)

2) 합성 메뉴 발화(--synthetic): 정상/오인식/비메뉴 발화로 교정 성공률과
   환각 보정 비율을 Threshold별로 측정해 S-16 Threshold를 선정한다.

사용법 (src/adapters/stt 디렉토리에서 실행):
    python compare_postprocess.py
    python compare_postprocess.py --synthetic
    python compare_postprocess.py --synthetic --seed 42
"""

from __future__ import annotations

import argparse
import random
import sys

import pandas as pd

from scripts.eval.stt.metrics import (
    aggregate_keyword_recall,
    corpus_cer,
    corpus_wer,
    DEFAULT_MENU_KEYWORDS,
    _normalize as metric_normalize,
)
from adapters.stt.postprocess import CandidateMatcher, normalize, normalize_wer


DEFAULT_CSV = (
    "models/whisper-medium-qlora-speaker-split/lr-2e-05_ep-5/"
    "compare_both_150_seed-42.csv"
)

THRESHOLD_SWEEP = [0.65, 0.70, 0.75, 0.80, 0.85]

NON_MENU_UTTERANCES = [
    "안녕하세요",
    "아이스크림 주세요",
    "한 잔 주세요",
    "오늘은 날씨가 좋네요",
    "계산해 주세요",
    "커피 하나 주세요",
    "주문할게요",
]

PERTURB_CHARS = "가나다라마바사아자차카타파하구드"


def _perturb_menu_name(menu: str, rng: random.Random) -> str:
    """메뉴명 내부의 글자 하나만 무작위 대체한다.

    공백은 제외하고(복수 단어 메뉴) 메뉴명 글자만 변형해,
    메뉴명 자체가 오인식된 합성 발화를 만든다.
    대체 문자는 원래 글자와 반드시 다른 문자를 선택해
    "한 글자 오인식" 계약이 실제로 보장되게 한다.
    """
    chars = list(menu)
    char_indices = [
        index for index, char in enumerate(chars) if not char.isspace()
    ]
    index = rng.choice(char_indices)
    original = chars[index]
    candidates = [char for char in PERTURB_CHARS if char != original]
    chars[index] = rng.choice(candidates)
    return "".join(chars)


def build_synthetic_cases(
    seed: int,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """(ground_truth_menu, full_utterance, text) 목록과 비메뉴 발화 목록을 만든다.

    - ground_truth_menu: 메뉴명 recall 계산용 정답 메뉴명
    - full_utterance: 템플릿 전체(정답 발화) — CER/WER의 reference
    - text: STT 가설 텍스트 (메뉴명 변형 발화는 메뉴명만 오인식됨)
    """
    rng = random.Random(seed)
    menu_utterances: list[tuple[str, str, str]] = []

    for menu in DEFAULT_MENU_KEYWORDS:
        for template in (f"{menu} 한 잔 주세요", f"{menu} 두 잔이요"):
            menu_utterances.append((menu, template, template))
            for _ in range(15):
                perturbed = _perturb_menu_name(menu, rng)
                menu_utterances.append(
                    (menu, template, template.replace(menu, perturbed))
                )

    return menu_utterances, list(NON_MENU_UTTERANCES)


def evaluate_real_data(csv_path: str, matcher: CandidateMatcher) -> None:
    df = pd.read_csv(csv_path)
    print("=" * 70)
    print("1. 실제 데이터 (150샘플) — 보정 효과/무영향 확인")
    print("=" * 70)
    print()

    refs = df["reference"].astype(str)
    menu_rows = sum(
        1
        for ref in refs
        if any(
            metric_normalize(keyword) in metric_normalize(ref)
            for keyword in DEFAULT_MENU_KEYWORDS
        )
    )
    print(f"전체 행 수            : {len(df)}")
    print(f"정답에 메뉴명 있는 행  : {menu_rows}")
    print()

    header = (
        f"{'열':>6} | "
        f"{'보정 행':>6} | "
        f"{'CER 전':>7} | "
        f"{'CER 후':>7} | "
        f"{'WER 전':>7} | "
        f"{'WER 후':>7}"
    )
    print(header)
    print("-" * len(header))

    for column in ("baseline", "qlora"):
        texts = df[column].astype(str)
        changed = 0
        refs_norm: list[str] = []
        refs_wer: list[str] = []
        hyp_before: list[str] = []
        hyp_after: list[str] = []
        hyp_wer_before: list[str] = []
        hyp_wer_after: list[str] = []

        for ref, hyp in zip(refs, texts):
            result = matcher.correct(hyp)
            if result.changed:
                changed += 1
            refs_norm.append(normalize(ref))
            refs_wer.append(normalize_wer(ref))
            hyp_before.append(normalize(hyp))
            hyp_after.append(normalize(result.text))
            hyp_wer_before.append(normalize_wer(hyp))
            hyp_wer_after.append(normalize_wer(result.text))

        print(
            f"{column:>6} | "
            f"{changed:>6} | "
            f"{corpus_cer(refs_norm, hyp_before):>7.4f} | "
            f"{corpus_cer(refs_norm, hyp_after):>7.4f} | "
            f"{corpus_wer(refs_wer, hyp_wer_before):>7.4f} | "
            f"{corpus_wer(refs_wer, hyp_wer_after):>7.4f}"
        )
    print()


def _print_synthetic_metrics(
    ground_truth_menus: list[str],
    full_refs: list[str],
    texts_before: list[str],
    texts_after: list[str],
    non_menu: list[str],
    matcher: CandidateMatcher,
    label: str,
) -> None:
    """S-17 지표: CER/WER(corpus, 전체 발화 기준) · 메뉴명 recall · 환각 보정 비율.

    CER/WER은 메뉴명만이 아니라 전체 정답 발화(full_refs)를 reference로
    비교한다. 메뉴명 recall은 정답 메뉴명(ground_truth_menus)을 별도 reference로
    사용한다.

    정규화 정책을 CER과 WER로 분리한다.
    - CER: 공백을 제거해 글자 단위 오류율로 계산 (기존 정책 유지)
    - WER: 단어 경계를 보존해 단어 단위 오류율로 계산 (normalize_wer)
    """
    refs_norm = [normalize(ref) for ref in full_refs]
    refs_wer = [normalize_wer(ref) for ref in full_refs]
    before_norm = [normalize(t) for t in texts_before]
    after_norm = [normalize(t) for t in texts_after]
    before_wer = [normalize_wer(t) for t in texts_before]
    after_wer = [normalize_wer(t) for t in texts_after]

    cer_before = corpus_cer(refs_norm, before_norm)
    cer_after = corpus_cer(refs_norm, after_norm)
    wer_before = corpus_wer(refs_wer, before_wer)
    wer_after = corpus_wer(refs_wer, after_wer)

    recall = aggregate_keyword_recall(
        list(zip(ground_truth_menus, texts_after)),
        DEFAULT_MENU_KEYWORDS,
    )

    hallucination = sum(
        1 for text in non_menu if matcher.correct(text).changed
    )
    hallucination_rate = hallucination / len(non_menu) if non_menu else 0.0

    print(f"[{label}]")
    print(f"  교정 발생 행 수       : {sum(m.changed for m in map(matcher.correct, texts_before))}")
    print(
        f"  CER (보정 전/후)      : {cer_before:.4f} → {cer_after:.4f}"
    )
    print(
        f"  WER (보정 전/후)      : {wer_before:.4f} → {wer_after:.4f}"
    )
    print(
        f"  메뉴명 recall (후)    : {recall['recall']:.4f} "
        f"({recall['matched']}/{recall['total']})"
    )
    print(
        f"  환각 보정 비율        : {hallucination_rate:.4f} "
        f"({hallucination}/{len(non_menu)})"
    )
    print()


def evaluate_synthetic(seed: int) -> None:
    menu_cases, non_menu = build_synthetic_cases(seed)

    normal_cases = [
        (menu, full, text)
        for menu, full, text in menu_cases
        if normalize(menu) in normalize(text)
    ]
    perturbed_cases = [
        (menu, full, text)
        for menu, full, text in menu_cases
        if normalize(menu) not in normalize(text)
    ]

    print("=" * 70)
    print("2. 합성 메뉴 발화 — Threshold 스윕 (S-16) + S-17 지표")
    print("=" * 70)
    print()

    print(
        f"메뉴 발화       : {len(menu_cases)}건 "
        "(정상 + 메뉴명 내부 1자 오인식 변형)"
    )
    print(f"  - 정상 발화         : {len(normal_cases)}건")
    print(
        f"  - 메뉴명 변형 발화  : {len(perturbed_cases)}건"
    )
    print(f"비메뉴 발화     : {len(non_menu)}건")
    print()

    header = (
        f"{'threshold':>10} | "
        f"{'교정성공':>8} | "
        f"{'오교정':>6} | "
        f"{'무교정':>6} | "
        f"{'환각보정':>6} | "
        f"{'환각비율':>8}"
    )
    print(header)
    print("-" * len(header))

    for threshold in THRESHOLD_SWEEP:
        matcher = CandidateMatcher(threshold=threshold)

        corrected = wrong = unchanged = 0
        for ground_truth, _, text in perturbed_cases:
            result = matcher.correct(text)
            expected = normalize(ground_truth)
            if expected in normalize(result.text):
                corrected += 1
            elif result.changed:
                wrong += 1
            else:
                unchanged += 1

        hallucination = sum(
            1
            for text in non_menu
            if matcher.correct(text).changed
        )

        print(
            f"{threshold:>10.2f} | "
            f"{corrected:>8} | "
            f"{wrong:>6} | "
            f"{unchanged:>6} | "
            f"{hallucination:>6} | "
            f"{hallucination / len(non_menu):>8.4f}"
        )

    print()
    print("교정성공: 메뉴명 변형 발화가 정답 메뉴로 교정됨")
    print("오교정  : 변형 발화가 다른 메뉴로 교정됨")
    print("무교정  : 변형 발화가 교정되지 않음")
    print("환각보정: 비메뉴 발화가 메뉴로 오교정됨")
    print()

    default_matcher = CandidateMatcher()
    _print_synthetic_metrics(
        [menu for menu, _, _ in perturbed_cases],
        [full for _, full, _ in perturbed_cases],
        [text for _, _, text in perturbed_cases],
        [
            default_matcher.correct(text).text
            for _, _, text in perturbed_cases
        ],
        non_menu,
        default_matcher,
        "기본 Threshold 0.65 — 메뉴명 변형 발화",
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="STT 메뉴명 보정 전/후 성능 비교"
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=DEFAULT_CSV,
        help="실제 평가 CSV 경로",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="합성 메뉴 발화 Threshold 스윕 포함",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="오인식 변형 생성 시드",
    )
    args = parser.parse_args()

    matcher = CandidateMatcher()
    evaluate_real_data(args.csv, matcher)

    if args.synthetic:
        evaluate_synthetic(args.seed)


if __name__ == "__main__":
    main()
