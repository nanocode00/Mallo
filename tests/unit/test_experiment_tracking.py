import hashlib
from pathlib import Path

from scripts.eval.stt.experiment_tracking import (
    compute_split_hash,
    resolve_resume_checkpoint,
)


def test_relative_checkpoint_resolves_against_output_dir(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint-100"
    checkpoint.mkdir()

    result = resolve_resume_checkpoint("checkpoint-100", tmp_path)

    assert result == str(checkpoint)


def test_absolute_checkpoint_is_used_as_is(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    checkpoint = tmp_path / "elsewhere" / "checkpoint-200"
    checkpoint.mkdir(parents=True)

    result = resolve_resume_checkpoint(str(checkpoint), output_dir)

    assert result == str(checkpoint)


def test_missing_relative_checkpoint_returns_none(tmp_path: Path) -> None:
    assert resolve_resume_checkpoint("checkpoint-999", tmp_path) is None


def test_missing_absolute_checkpoint_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    assert resolve_resume_checkpoint(str(missing), tmp_path) is None


def test_empty_argument_returns_none(tmp_path: Path) -> None:
    assert resolve_resume_checkpoint(None, tmp_path) is None
    assert resolve_resume_checkpoint("", tmp_path) is None


def test_split_hash_matches_content_md5(tmp_path: Path) -> None:
    csv_file = tmp_path / "train.csv"
    payload = b"file,reference\na.wav,annyeong\n"
    csv_file.write_bytes(payload)

    assert compute_split_hash(csv_file) == hashlib.md5(payload).hexdigest()


def test_split_hash_changes_when_content_changes(tmp_path: Path) -> None:
    csv_file = tmp_path / "train.csv"
    csv_file.write_bytes(b"v1")
    first = compute_split_hash(csv_file)
    csv_file.write_bytes(b"v2")

    assert compute_split_hash(csv_file) != first
