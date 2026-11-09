import sys
from pathlib import Path

# compare_postprocess — 메뉴명 변형 생성·분리·정규화 비교

def test_perturb_only_changes_menu_name_inside() -> None:
    import random

    from scripts.eval.stt.compare_postprocess import _perturb_menu_name
    from scripts.eval.stt.metrics import _normalize as mnorm

    rng = random.Random(42)
    menu = "카페라떼"
    perturbed = _perturb_menu_name(menu, rng)

    assert len(perturbed) == len(menu)
    diff_count = sum(
        1 for c, o in zip(perturbed, menu) if c != o
    )
    assert diff_count == 1
    assert mnorm(perturbed) != mnorm(menu)
    assert perturbed[0] != "카"  # 시드 42 기준 첫 글자가 변형됨


def test_perturb_keeps_spaces_in_multi_word_menu() -> None:
    import random

    from scripts.eval.stt.compare_postprocess import _perturb_menu_name

    rng = random.Random(7)
    menu = "크로플 아이스크림"
    perturbed = _perturb_menu_name(menu, rng)

    assert perturbed.count(" ") == menu.count(" ")
    assert len(perturbed) == len(menu)


def test_perturb_always_changes_a_single_character() -> None:
    # 원래 글자와 같은 문자를 다시 선택하지 않아 "한 글자 오인식"이 보장된다.
    import random

    from scripts.eval.stt.compare_postprocess import _perturb_menu_name

    rng = random.Random(0)
    menus = [
        "카페라떼",
        "자몽에이드",
        "밀크티",
        "크로플 아이스크림",
        "바스크 치즈 케이크",
    ]

    for menu in menus:
        for _ in range(50):
            perturbed = _perturb_menu_name(menu, rng)
            assert len(perturbed) == len(menu)
            diff_count = sum(
                1 for c, o in zip(perturbed, menu) if c != o
            )
            assert diff_count == 1


def test_synthetic_split_counts_normal_vs_perturbed() -> None:
    from scripts.eval.stt.compare_postprocess import build_synthetic_cases
    from scripts.eval.stt.metrics import _normalize as mnorm

    menu_cases, non_menu = build_synthetic_cases(42)

    normal = sum(1 for gt, _full, t in menu_cases if mnorm(gt) in mnorm(t))
    perturbed = len(menu_cases) - normal

    assert len(menu_cases) == 320
    assert normal == 20
    assert perturbed == 300
    assert len(non_menu) == 7


def test_correction_success_uses_normalized_comparison() -> None:
    from scripts.eval.stt.compare_postprocess import CandidateMatcher, normalize

    matcher = CandidateMatcher(threshold=0.65)
    result = matcher.correct("크로플 아이스마림 한 잔 주세요")

    assert normalize("크로플 아이스크림") in normalize(result.text)
    assert result.changed is True


def test_correction_improves_corpus_cer_wer_on_full_utterance() -> None:
    # 합성 CER/WER reference는 메뉴명이 아니라 전체 정답 발화여야 한다.
    # 메뉴명만 교정되어도 전체 발화 기준 CER/WER이 실제로 개선돼야 한다.
    # CER은 공백 제거 정규화, WER은 단어 경계 보존 정규화를 각각 사용한다.
    from scripts.eval.stt.compare_postprocess import (
        CandidateMatcher,
        build_synthetic_cases,
        normalize,
        normalize_wer,
    )
    from scripts.eval.stt.metrics import corpus_cer, corpus_wer

    menu_cases, _non_menu = build_synthetic_cases(42)
    perturbed = [
        (menu, full, text)
        for menu, full, text in menu_cases
        if normalize(menu) not in normalize(text)
    ]
    matcher = CandidateMatcher(threshold=0.65)

    refs = [normalize(full) for _menu, full, _text in perturbed]
    before = [normalize(text) for _menu, _full, text in perturbed]
    after = [
        normalize(matcher.correct(text).text)
        for _menu, _full, text in perturbed
    ]
    refs_wer = [normalize_wer(full) for _menu, full, _text in perturbed]
    before_wer = [normalize_wer(text) for _menu, _full, text in perturbed]
    after_wer = [
        normalize_wer(matcher.correct(text).text)
        for _menu, _full, text in perturbed
    ]

    assert corpus_cer(refs, after) < corpus_cer(refs, before)
    assert corpus_wer(refs_wer, after_wer) < corpus_wer(
        refs_wer, before_wer
    )


def test_wer_preserves_word_boundaries() -> None:
    # WER 계산 전 정규화는 단어 경계를 보존해야 한다. 공백을 지우면
    # 문장 전체가 단어 하나가 되어 한 단어 오류도 WER 1.0이 된다.
    from scripts.eval.stt.compare_postprocess import normalize_wer
    from scripts.eval.stt.metrics import corpus_wer

    reference = normalize_wer("카페라떼 한 잔 주세요")
    hypothesis = normalize_wer("카페랕떼 한 잔 주세요")

    assert reference == "카페라떼 한 잔 주세요"
    assert hypothesis == "카페랕떼 한 잔 주세요"
    assert reference.count(" ") == 3  # 단어 경계(공백)가 그대로 유지된다

    wer = corpus_wer([reference], [hypothesis])
    assert 0.0 < wer < 1.0  # 4단어 중 1단어 오류 → WER 0.25 (전체 불일치 1.0이 아님)


def test_synthetic_case_keeps_full_utterance_reference() -> None:
    # build_synthetic_cases가 전체 정답 발화를 reference로 보관한다.
    from scripts.eval.stt.compare_postprocess import build_synthetic_cases

    menu_cases, _non_menu = build_synthetic_cases(42)
    menu, full, text = menu_cases[2]

    assert menu in full
    assert "한 잔" in full or "두 잔이요" in full
    assert text != full
