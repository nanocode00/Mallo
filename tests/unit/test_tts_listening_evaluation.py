import csv
import json
import wave
from pathlib import Path

import pytest

from scripts.eval.tts.listening_evaluation import (
    EVALUATION_COLUMNS,
    create_listening_package,
    validate_completed_evaluation,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SENTENCES_PATH = REPOSITORY_ROOT / "data/tts/evaluation/sentences.json"
MENU_PATH = REPOSITORY_ROOT / "src/config/menu.json"


def write_wav(path: Path, marker: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(bytes([marker, 0]) * 1_600)


@pytest.fixture
def samples_manifest(tmp_path: Path) -> Path:
    sentence_ids = [f"tts_eval_{index:02d}" for index in range(1, 21)]
    candidates = []
    for candidate_index, candidate_id in enumerate(("baseline-internal", "finetuned-internal"), start=1):
        samples = []
        for sentence_index, sentence_id in enumerate(sentence_ids, start=1):
            audio = (tmp_path / "source" / candidate_id / f"{sentence_id}.wav").resolve()
            write_wav(audio, candidate_index + sentence_index)
            samples.append({"sentence_id": sentence_id, "audio_path": str(audio)})
        candidates.append({"candidate_id": candidate_id, "samples": samples})
    manifest = (tmp_path / "samples.json").resolve()
    manifest.write_text(
        json.dumps({"experiment_id": "test-001", "candidates": candidates}, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def test_creates_anonymous_complete_package(samples_manifest: Path, tmp_path: Path) -> None:
    output = (tmp_path / "listening").resolve()
    result = create_listening_package(
        samples_manifest, SENTENCES_PATH, MENU_PATH, output, "participant-01", 42
    )
    evaluation = read_tsv(output / "evaluation.tsv")
    answers = read_tsv(output / "answer-key.tsv")
    assert result["samples"] == 40
    assert (output / "listening-form.json").is_file()
    assert len(evaluation) == len(answers) == 40
    assert list(evaluation[0]) == EVALUATION_COLUMNS
    assert all(row["sample_id"].startswith("sample_") for row in evaluation)
    public_text = (output / "evaluation.tsv").read_text(encoding="utf-8")
    assert "baseline-internal" not in public_text
    assert "finetuned-internal" not in public_text
    assert {row["candidate_id"] for row in answers} == {
        "baseline-internal",
        "finetuned-internal",
    }
    for answer in answers:
        anonymous = output / "audio" / f"{answer['sample_id']}.wav"
        assert anonymous.read_bytes() == Path(answer["original_audio_path"]).read_bytes()


def test_randomization_is_reproducible_per_participant(samples_manifest: Path, tmp_path: Path) -> None:
    outputs = [(tmp_path / name).resolve() for name in ("a", "b", "c")]
    create_listening_package(samples_manifest, SENTENCES_PATH, MENU_PATH, outputs[0], "p1", 42)
    create_listening_package(samples_manifest, SENTENCES_PATH, MENU_PATH, outputs[1], "p1", 42)
    create_listening_package(samples_manifest, SENTENCES_PATH, MENU_PATH, outputs[2], "p2", 42)
    answers = [
        [(row["candidate_id"], row["sentence_id"]) for row in read_tsv(path / "answer-key.tsv")]
        for path in outputs
    ]
    assert answers[0] == answers[1]
    assert answers[0] != answers[2]


def test_rejects_incomplete_candidate(samples_manifest: Path, tmp_path: Path) -> None:
    payload = json.loads(samples_manifest.read_text(encoding="utf-8"))
    payload["candidates"][0]["samples"].pop()
    samples_manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="문장 세트"):
        create_listening_package(
            samples_manifest, SENTENCES_PATH, MENU_PATH, (tmp_path / "out").resolve(), "p1"
        )


def test_does_not_overwrite_existing_output(samples_manifest: Path, tmp_path: Path) -> None:
    output = (tmp_path / "existing").resolve()
    output.mkdir()
    with pytest.raises(FileExistsError, match="덮어쓸"):
        create_listening_package(samples_manifest, SENTENCES_PATH, MENU_PATH, output, "p1")


def test_validates_completed_evaluation(samples_manifest: Path, tmp_path: Path) -> None:
    output = (tmp_path / "completed").resolve()
    create_listening_package(samples_manifest, SENTENCES_PATH, MENU_PATH, output, "p1")
    rows = read_tsv(output / "evaluation.tsv")
    for row in rows:
        for column in EVALUATION_COLUMNS:
            if column.endswith("clarity") or column in {
                "naturalness",
                "friendliness",
                "store_guidance_suitability",
            }:
                if row[column] != "NA":
                    row[column] = "4"
        row["critical_information_success"] = "yes"
        row["serious_misread_or_corruption"] = "no"
    with (output / "evaluation.tsv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target, fieldnames=EVALUATION_COLUMNS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    assert validate_completed_evaluation(
        output / "evaluation.tsv", SENTENCES_PATH, MENU_PATH
    ) == {"status": "PASS", "participant_id": "p1", "rows": 40}


def test_rejects_invalid_completed_score(samples_manifest: Path, tmp_path: Path) -> None:
    output = (tmp_path / "invalid").resolve()
    create_listening_package(samples_manifest, SENTENCES_PATH, MENU_PATH, output, "p1")
    rows = read_tsv(output / "evaluation.tsv")
    rows[0]["naturalness"] = "6"
    with (output / "evaluation.tsv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target, fieldnames=EVALUATION_COLUMNS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="점수 오류"):
        validate_completed_evaluation(output / "evaluation.tsv", SENTENCES_PATH, MENU_PATH)
