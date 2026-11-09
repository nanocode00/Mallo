"""T-21 고정 평가 문장과 학습 데이터 누수를 검증한다."""

from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter
from pathlib import Path


CATEGORIES = {
    "menu_temperature",
    "quantity_unit",
    "price_total",
    "modify_delete",
    "summary_payment",
}
SENTENCE_FIELDS = {"id", "category", "text", "critical_terms", "menu_ids"}


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    without_punctuation = "".join(
        " " if unicodedata.category(character)[0] in {"P", "S"} else character
        for character in normalized
    )
    return " ".join(without_punctuation.split())


def load_and_validate(sentences_path: Path, menu_path: Path) -> list[dict[str, object]]:
    payload = json.loads(sentences_path.read_text(encoding="utf-8"))
    if set(payload) != {"version", "language", "sentences"}:
        raise ValueError("평가 문장 최상위 필드 오류")
    if payload["version"] != "1.0" or payload["language"] != "KR":
        raise ValueError("평가 문장 version 또는 language 오류")
    sentences = payload["sentences"]
    if not isinstance(sentences, list) or len(sentences) != 20:
        raise ValueError("평가 문장은 정확히 20개여야 함")

    menu_payload = json.loads(menu_path.read_text(encoding="utf-8"))
    menus = {item["id"]: item["name"] for item in menu_payload["items"]}
    expected_ids = [f"tts_eval_{index:02d}" for index in range(1, 21)]
    normalized_texts: set[str] = set()
    category_counts: Counter[str] = Counter()

    for index, sentence in enumerate(sentences):
        if not isinstance(sentence, dict) or set(sentence) != SENTENCE_FIELDS:
            raise ValueError(f"평가 문장 {index + 1} 필드 오류")
        if sentence["id"] != expected_ids[index]:
            raise ValueError("평가 문장 ID는 01부터 20까지 연속이어야 함")
        if sentence["category"] not in CATEGORIES:
            raise ValueError(f"알 수 없는 category: {sentence['category']}")
        text = sentence["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"빈 평가 문장: {sentence['id']}")
        normalized = normalize_text(text)
        if normalized in normalized_texts:
            raise ValueError(f"평가 문장 text 중복: {sentence['id']}")
        normalized_texts.add(normalized)

        critical_terms = sentence["critical_terms"]
        if not isinstance(critical_terms, list) or not critical_terms:
            raise ValueError(f"critical_terms 누락: {sentence['id']}")
        if len(set(critical_terms)) != len(critical_terms) or any(
            not isinstance(term, str) or not term or term not in text for term in critical_terms
        ):
            raise ValueError(f"critical_terms 오류: {sentence['id']}")

        menu_ids = sentence["menu_ids"]
        if not isinstance(menu_ids, list) or len(set(menu_ids)) != len(menu_ids):
            raise ValueError(f"menu_ids 오류: {sentence['id']}")
        if any(menu_id not in menus for menu_id in menu_ids):
            raise ValueError(f"존재하지 않는 menu_id: {sentence['id']}")
        if any(menus[menu_id] not in text for menu_id in menu_ids):
            raise ValueError(f"공식 메뉴명이 text에 없음: {sentence['id']}")
        mentioned_ids = {menu_id for menu_id, name in menus.items() if name in text}
        if mentioned_ids != set(menu_ids):
            raise ValueError(f"text와 menu_ids가 일치하지 않음: {sentence['id']}")
        category_counts[sentence["category"]] += 1

    if category_counts != Counter({category: 4 for category in CATEGORIES}):
        raise ValueError(f"category별 문장 수 오류: {dict(category_counts)}")
    return sentences


def check_manifest_leakage(
    sentences: list[dict[str, object]], manifest_paths: list[Path]
) -> dict[str, object]:
    evaluation_texts = {normalize_text(str(sentence["text"])): sentence["id"] for sentence in sentences}
    overlaps: list[dict[str, str]] = []
    checked_records = 0
    checked_manifests: list[str] = []
    for manifest_path in manifest_paths:
        if not manifest_path.is_absolute() or not manifest_path.is_file():
            raise ValueError(f"manifest는 존재하는 절대 파일이어야 함: {manifest_path}")
        checked_manifests.append(str(manifest_path.resolve()))
        for line_number, line in enumerate(
            manifest_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            fields = line.split("|", 3)
            if len(fields) != 4:
                raise ValueError(f"manifest {line_number}행 형식 오류: {manifest_path}")
            checked_records += 1
            normalized = normalize_text(fields[3])
            if normalized in evaluation_texts:
                overlaps.append(
                    {
                        "evaluation_id": str(evaluation_texts[normalized]),
                        "manifest": str(manifest_path.resolve()),
                        "line": str(line_number),
                    }
                )
    return {
        "status": "PASS" if not overlaps else "FAIL",
        "checked_manifests": checked_manifests,
        "checked_records": checked_records,
        "overlaps": overlaps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TTS 평가 문장 검증")
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--menu", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    args = parser.parse_args()
    sentences = load_and_validate(args.sentences, args.menu)
    report = {
        "sentences": len(sentences),
        "categories": dict(sorted(Counter(str(item["category"]) for item in sentences).items())),
        "leakage": (
            check_manifest_leakage(sentences, args.manifest)
            if args.manifest
            else {"status": "NOT_RUN", "checked_manifests": [], "checked_records": 0, "overlaps": []}
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["leakage"]["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
