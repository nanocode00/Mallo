"""후보별 TTS WAV를 익명화하고 T-23 평가 TSV를 생성·검증한다."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import wave
from pathlib import Path

from scripts.eval.tts.evaluation_sentences import load_and_validate



IDENTITY_COLUMNS = [
    "participant_id",
    "presentation_order",
    "sample_id",
    "sentence_id",
    "text",
    "critical_terms",
]
RATING_COLUMNS = [
    "naturalness",
    "overall_clarity",
    "friendliness",
    "menu_name_clarity",
    "quantity_unit_clarity",
    "price_clarity",
    "store_guidance_suitability",
]
BINARY_COLUMNS = ["critical_information_success", "serious_misread_or_corruption"]
TEXT_COLUMNS = ["calm_friendly_notes", "comments"]
EVALUATION_COLUMNS = IDENTITY_COLUMNS + RATING_COLUMNS + BINARY_COLUMNS + TEXT_COLUMNS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_wav(path: Path) -> None:
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"WAV는 존재하는 절대 파일이어야 함: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getframerate() <= 0 or wav.getnframes() <= 0:
                raise ValueError(f"0초 WAV: {path}")
    except (EOFError, wave.Error) as error:
        raise ValueError(f"WAV decode 실패: {path}") from error


def _applicability(sentence: dict[str, object]) -> dict[str, bool]:
    terms = [str(term) for term in sentence["critical_terms"]]
    return {
        "menu_name_clarity": bool(sentence["menu_ids"]),
        "quantity_unit_clarity": any("잔" in term or "개" in term for term in terms),
        "price_clarity": any("원" in term for term in terms),
    }


def _validate_form(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != "1.0" or payload.get("rating_scale") != {
        "1": "매우 나쁨",
        "2": "나쁨",
        "3": "보통",
        "4": "좋음",
        "5": "매우 좋음",
    }:
        raise ValueError("청취 평가 척도 계약 오류")
    ratings = payload.get("always_required_ratings", []) + payload.get("conditional_ratings", [])
    if len(ratings) != len(RATING_COLUMNS) or set(ratings) != set(RATING_COLUMNS):
        raise ValueError("청취 평가 점수 열 계약 오류")
    if payload.get("binary_fields") != BINARY_COLUMNS or payload.get("text_fields") != TEXT_COLUMNS:
        raise ValueError("청취 평가 응답 열 계약 오류")


def _load_samples(samples_path: Path, sentence_ids: set[str]) -> tuple[str, list[dict[str, str]]]:
    payload = json.loads(samples_path.read_text(encoding="utf-8"))
    if set(payload) != {"experiment_id", "candidates"}:
        raise ValueError("샘플 manifest 최상위 필드 오류")
    experiment_id = payload["experiment_id"]
    candidates = payload["candidates"]
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("experiment_id가 필요함")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("청취 평가 후보는 최소 2개여야 함")

    entries: list[dict[str, str]] = []
    candidate_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {"candidate_id", "samples"}:
            raise ValueError("candidate 필드 오류")
        candidate_id = candidate["candidate_id"]
        if not isinstance(candidate_id, str) or not candidate_id.strip() or candidate_id in candidate_ids:
            raise ValueError("candidate_id 누락 또는 중복")
        candidate_ids.add(candidate_id)
        samples = candidate["samples"]
        if not isinstance(samples, list):
            raise ValueError(f"samples 형식 오류: {candidate_id}")
        seen_ids: set[str] = set()
        for sample in samples:
            if not isinstance(sample, dict) or set(sample) != {"sentence_id", "audio_path"}:
                raise ValueError(f"sample 필드 오류: {candidate_id}")
            sentence_id = sample["sentence_id"]
            if sentence_id in seen_ids:
                raise ValueError(f"문장 ID 중복: {candidate_id}:{sentence_id}")
            seen_ids.add(sentence_id)
            audio_path = Path(sample["audio_path"])
            _validate_wav(audio_path)
            entries.append(
                {
                    "candidate_id": candidate_id,
                    "sentence_id": sentence_id,
                    "audio_path": str(audio_path.resolve()),
                }
            )
        if seen_ids != sentence_ids:
            missing = sorted(sentence_ids - seen_ids)
            extra = sorted(seen_ids - sentence_ids)
            raise ValueError(f"후보별 문장 세트 오류: {candidate_id}, missing={missing}, extra={extra}")
    return experiment_id, entries


def create_listening_package(
    samples_path: Path,
    sentences_path: Path,
    menu_path: Path,
    output_root: Path,
    participant_id: str,
    seed: int = 42,
) -> dict[str, object]:
    if not participant_id.strip():
        raise ValueError("participant_id가 필요함")
    if output_root.exists():
        raise FileExistsError(f"기존 출력 경로를 덮어쓸 수 없음: {output_root}")
    sentences = load_and_validate(sentences_path, menu_path)
    form_path = sentences_path.with_name("listening-form.json")
    _validate_form(form_path)
    sentence_map = {str(sentence["id"]): sentence for sentence in sentences}
    experiment_id, entries = _load_samples(samples_path, set(sentence_map))
    if any(entry["candidate_id"] in str(sentence_map[entry["sentence_id"]]["text"]) for entry in entries):
        raise ValueError("candidate_id가 공개 평가 text에 포함됨")

    random.Random(f"{seed}:{participant_id}").shuffle(entries)
    audio_root = output_root / "audio"
    audio_root.mkdir(parents=True)
    evaluation_rows: list[dict[str, object]] = []
    answer_rows: list[dict[str, object]] = []
    for order, entry in enumerate(entries, start=1):
        sample_id = f"sample_{order:03d}"
        source = Path(entry["audio_path"])
        destination = audio_root / f"{sample_id}.wav"
        shutil.copyfile(source, destination)
        source_hash = _sha256(source)
        destination_hash = _sha256(destination)
        if source_hash != destination_hash:
            raise RuntimeError(f"익명화 WAV hash 불일치: {sample_id}")
        sentence = sentence_map[entry["sentence_id"]]
        applicability = _applicability(sentence)
        row: dict[str, object] = {
            "participant_id": participant_id,
            "presentation_order": order,
            "sample_id": sample_id,
            "sentence_id": entry["sentence_id"],
            "text": sentence["text"],
            "critical_terms": json.dumps(sentence["critical_terms"], ensure_ascii=False),
            **{column: "" for column in RATING_COLUMNS + BINARY_COLUMNS + TEXT_COLUMNS},
        }
        for column, applies in applicability.items():
            if not applies:
                row[column] = "NA"
        evaluation_rows.append(row)
        answer_rows.append(
            {
                "sample_id": sample_id,
                "candidate_id": entry["candidate_id"],
                "sentence_id": entry["sentence_id"],
                "original_audio_path": str(source),
                "sha256": source_hash,
            }
        )

    _write_tsv(output_root / "evaluation.tsv", EVALUATION_COLUMNS, evaluation_rows)
    answer_columns = ["sample_id", "candidate_id", "sentence_id", "original_audio_path", "sha256"]
    _write_tsv(output_root / "answer-key.tsv", answer_columns, answer_rows)
    shutil.copyfile(form_path, output_root / "listening-form.json")
    readme = (
        f"experiment_id: {experiment_id}\nparticipant_id: {participant_id}\nseed: {seed}\n"
        "evaluation.tsv와 audio/만 평가자에게 제공하세요. answer-key.tsv는 비공개입니다.\n"
    )
    (output_root / "README.txt").write_text(readme, encoding="utf-8")
    return {
        "experiment_id": experiment_id,
        "participant_id": participant_id,
        "seed": seed,
        "samples": len(entries),
        "output_root": str(output_root.resolve()),
    }


def _write_tsv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_completed_evaluation(path: Path, sentences_path: Path, menu_path: Path) -> dict[str, object]:
    sentences = load_and_validate(sentences_path, menu_path)
    sentence_map = {str(sentence["id"]): sentence for sentence in sentences}
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        if reader.fieldnames != EVALUATION_COLUMNS:
            raise ValueError("evaluation.tsv 열 계약 오류")
        rows = list(reader)
    if not rows:
        raise ValueError("평가 응답이 비어 있음")
    participant_ids = {row["participant_id"] for row in rows}
    if len(participant_ids) != 1 or not next(iter(participant_ids)).strip():
        raise ValueError("participant_id는 하나의 비어 있지 않은 값이어야 함")
    sample_ids: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        if row["sample_id"] in sample_ids:
            raise ValueError(f"sample_id 중복: {line_number}행")
        sample_ids.add(row["sample_id"])
        sentence = sentence_map.get(row["sentence_id"])
        if sentence is None or row["text"] != sentence["text"]:
            raise ValueError(f"문장 계약 오류: {line_number}행")
        applicability = _applicability(sentence)
        for column in RATING_COLUMNS:
            value = row[column]
            if column in applicability and not applicability[column]:
                if value != "NA":
                    raise ValueError(f"{column}은 NA여야 함: {line_number}행")
            elif value not in {"1", "2", "3", "4", "5"}:
                raise ValueError(f"{column} 점수 오류: {line_number}행")
        if any(row[column] not in {"yes", "no"} for column in BINARY_COLUMNS):
            raise ValueError(f"yes/no 판정 오류: {line_number}행")
    return {"status": "PASS", "participant_id": participant_ids.pop(), "rows": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="TTS 블라인드 청취 평가 패키지")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--samples", type=Path, required=True)
    create.add_argument("--sentences", type=Path, required=True)
    create.add_argument("--menu", type=Path, required=True)
    create.add_argument("--output-root", type=Path, required=True)
    create.add_argument("--participant-id", required=True)
    create.add_argument("--seed", type=int, default=42)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evaluation", type=Path, required=True)
    validate.add_argument("--sentences", type=Path, required=True)
    validate.add_argument("--menu", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        result = create_listening_package(
            args.samples.resolve(),
            args.sentences.resolve(),
            args.menu.resolve(),
            args.output_root.resolve(),
            args.participant_id,
            args.seed,
        )
    else:
        result = validate_completed_evaluation(
            args.evaluation.resolve(), args.sentences.resolve(), args.menu.resolve()
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
