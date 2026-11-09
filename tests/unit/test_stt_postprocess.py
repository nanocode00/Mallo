from adapters.stt.postprocess import CandidateMatcher, normalize


def make_matcher(threshold: float = 0.8) -> CandidateMatcher:
    return CandidateMatcher(threshold=threshold)


# ------------------------------------------------------------
# AC-01 · AC-09 — 정확 일치 / changed 플래그
# ------------------------------------------------------------

def test_exact_match_is_recognized_without_change() -> None:
    result = make_matcher().correct("카페라떼 한 잔 주세요")

    assert result.changes
    assert result.changes[0].score == 1.0
    assert result.changes[0].canonical == "카페라떼"
    assert result.changed is False


def test_changed_flag_is_false_when_no_substitution() -> None:
    result = make_matcher().correct("카페라떼 한 잔 주세요")
    assert result.changed is False


# ------------------------------------------------------------
# AC-02 — 한 글자 대체 오인식 교정
# ------------------------------------------------------------

def test_single_char_substitution_is_corrected() -> None:
    result = make_matcher().correct("자몽에이들 한 잔 주세요")

    assert result.changed is True
    assert "자몽에이드" in result.text
    assert result.changes[0].score >= 0.8


# ------------------------------------------------------------
# AC-03 — 무관 문장 무교정
# ------------------------------------------------------------

def test_unrelated_text_is_untouched() -> None:
    text = "안녕하세요 메뉴 추천해 주세요"
    result = make_matcher().correct(text)

    assert result.changes == []
    assert result.changed is False
    assert result.text == text


# ------------------------------------------------------------
# AC-04 — Threshold 게이팅
# ------------------------------------------------------------

def test_threshold_gating_blocks_low_similarity() -> None:
    strict = make_matcher(threshold=0.85)
    relaxed = make_matcher(threshold=0.75)

    strict_result = strict.correct("자몽에이들 한 잔")
    relaxed_result = relaxed.correct("자몽에이들 한 잔")

    assert strict_result.changes == []
    assert relaxed_result.changed is True


# ------------------------------------------------------------
# AC-05 — 조사 보존
# ------------------------------------------------------------

def test_josa_is_preserved() -> None:
    result = make_matcher().correct("카페라떼를 한 잔 주세요")

    assert result.changes[0].original == "카페라떼"
    assert "카페라떼를" in result.text


# ------------------------------------------------------------
# AC-06 — 유사 메뉴 구분
# ------------------------------------------------------------

def test_similar_menus_are_not_cross_corrected() -> None:
    matcher = make_matcher()

    vanilla = matcher.correct("바닐라라떼 한 잔 주세요")
    cafe = matcher.correct("카페라떼 한 잔 주세요")
    matcha = matcher.correct("말차라떼 한 잔 주세요")

    assert vanilla.changes[0].canonical == "바닐라라떼"
    assert cafe.changes[0].canonical == "카페라떼"
    assert matcha.changes[0].canonical == "말차라떼"
    assert vanilla.changed is False
    assert cafe.changed is False
    assert matcha.changed is False


# ------------------------------------------------------------
# AC-07 — 띄어쓰기 무시
# ------------------------------------------------------------

def test_spacing_is_ignored() -> None:
    result = make_matcher().correct("카페 라떼 한 잔")

    assert result.changes
    assert result.changes[0].canonical == "카페라떼"
    assert result.changed is False


# ------------------------------------------------------------
# AC-08 — 복수 메뉴 교정
# ------------------------------------------------------------

def test_multiple_menus_in_one_utterance() -> None:
    result = make_matcher().correct(
        "자몽에이들 한 잔 그리고 바스크치즈케이크 하나요"
    )

    assert len(result.changes) == 2
    assert "자몽에이드" in result.text
    assert "바스크치즈케이크" in result.text
    assert result.changed is True


def test_no_hallucination_correction_for_partial_overlap() -> None:
    result = make_matcher().correct("아이스크림 주세요")

    assert result.changes == []
    assert result.changed is False


def test_multi_word_menu_is_corrected() -> None:
    result = make_matcher().correct("크로플 아이스마림 한 잔 주세요")

    assert result.changed is True
    assert "크로플 아이스크림" in result.text
    assert result.changes[0].item_id == "croffle_icecream"


def test_near_miss_words_are_not_corrected() -> None:
    matcher = make_matcher()
    for text in (
        "크로와상 주세요",
        "치즈케이크 주세요",
        "초코라떼 주세요",
        "그린티 하나 주세요",
    ):
        result = matcher.correct(text)
        assert result.changed is False, text


# ------------------------------------------------------------
# 추가 — 메뉴 로딩 / 빈 텍스트 / 정규화
# ------------------------------------------------------------

def test_matcher_loads_ten_menu_items_by_default() -> None:
    matcher = make_matcher()

    assert len(matcher.candidates) == 10
    assert matcher.menu_path.name == "menu.json"


def test_empty_text_returns_unchanged() -> None:
    result = make_matcher().correct("")

    assert result.text == ""
    assert result.changes == []
    assert result.changed is False


def test_normalize_strips_whitespace_and_case() -> None:
    assert normalize("  카페 라떼  ") == "카페라떼"


# ------------------------------------------------------------
# 리뷰 반영 — 원문 공백·비메뉴 텍스트 보존
# ------------------------------------------------------------

def test_original_spacing_and_non_menu_text_are_preserved() -> None:
    result = make_matcher().correct("자몽에이들 한 잔 주세요")

    assert result.text == "자몽에이드 한 잔 주세요"


def test_non_menu_text_preserved_without_normalization() -> None:
    result = make_matcher().correct("자몽에이들 한 잔 주세요 감사합니다")

    assert result.text == "자몽에이드 한 잔 주세요 감사합니다"


def test_unchanged_spacing_is_not_collapsed() -> None:
    result = make_matcher().correct("카페 라떼 한 잔 주세요")

    assert result.changed is False
    assert result.text == "카페 라떼 한 잔 주세요"


def test_default_threshold_is_0_65() -> None:
    from adapters.stt.postprocess import CandidateMatcher

    assert CandidateMatcher.DEFAULT_THRESHOLD == 0.65
