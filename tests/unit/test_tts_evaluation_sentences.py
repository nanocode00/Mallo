import json
from collections import Counter
from pathlib import Path

import pytest

from scripts.eval.tts.evaluation_sentences import (
    check_manifest_leakage,
    load_and_validate,
    normalize_text,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SENTENCES_PATH = REPOSITORY_ROOT / "data/tts/evaluation/sentences.json"
MENU_PATH = REPOSITORY_ROOT / "src/config/menu.json"


def test_fixed_sentence_set_is_balanced_and_valid() -> None:
    sentences = load_and_validate(SENTENCES_PATH, MENU_PATH)
    assert len(sentences) == 20
    assert Counter(sentence["category"] for sentence in sentences) == {
        "menu_temperature": 4,
        "quantity_unit": 4,
        "price_total": 4,
        "modify_delete": 4,
        "summary_payment": 4,
    }


def test_normalization_removes_symbol_and_whitespace_differences() -> None:
    assert normalize_text("Ａ메리카노,  한 잔!") == normalize_text("A메리카노 한 잔")


def test_rejects_critical_term_missing_from_text(tmp_path: Path) -> None:
    payload = json.loads(SENTENCES_PATH.read_text(encoding="utf-8"))
    payload["sentences"][0]["critical_terms"] = ["없는 표현"]
    invalid = tmp_path / "sentences.json"
    invalid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="critical_terms"):
        load_and_validate(invalid, MENU_PATH)


def test_rejects_menu_id_that_does_not_match_text(tmp_path: Path) -> None:
    payload = json.loads(SENTENCES_PATH.read_text(encoding="utf-8"))
    payload["sentences"][0]["menu_ids"] = ["cafe_latte"]
    invalid = tmp_path / "sentences.json"
    invalid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="공식 메뉴명"):
        load_and_validate(invalid, MENU_PATH)


def test_detects_normalized_manifest_overlap(tmp_path: Path) -> None:
    sentences = load_and_validate(SENTENCES_PATH, MENU_PATH)
    manifest = (tmp_path / "train.list").resolve()
    manifest.write_text(
        "/tmp/audio.wav|10|KR|아이스 아메리카노 한 잔을 주문에 담았습니다!\n",
        encoding="utf-8",
    )
    report = check_manifest_leakage(sentences, [manifest])
    assert report["status"] == "FAIL"
    assert report["checked_records"] == 1
    assert report["overlaps"][0]["evaluation_id"] == "tts_eval_01"


def test_passes_when_manifest_has_no_overlap(tmp_path: Path) -> None:
    sentences = load_and_validate(SENTENCES_PATH, MENU_PATH)
    manifest = (tmp_path / "train.list").resolve()
    manifest.write_text("/tmp/audio.wav|10|KR|전혀 다른 문장입니다.\n", encoding="utf-8")
    assert check_manifest_leakage(sentences, [manifest])["status"] == "PASS"
