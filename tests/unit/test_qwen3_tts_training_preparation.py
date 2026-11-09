import json
from pathlib import Path

import pytest

from scripts.data.tts import prepare_qwen3_tts_training as preparation
from scripts.eval.tts.qwen_custom_voice_inference import synthesize


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    repository = (tmp_path / "Qwen3-TTS").resolve()
    for relative in preparation.REQUIRED_REPOSITORY_FILES:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n", encoding="utf-8")
    monkeypatch.setattr(preparation, "_git_revision", lambda _: "b" * 40)

    derived = (tmp_path / "derived").resolve()
    derived.mkdir()
    reference = derived / "reference.wav"
    reference.write_bytes(b"reference")
    qwen_rows = []
    melo_lines = []
    for index in range(3):
        audio = derived / f"audio-{index}.wav"
        audio.write_bytes(f"audio-{index}".encode())
        text = f"학습 문장 {index}입니다."
        qwen_rows.append({"audio": str(audio), "text": text, "ref_audio": str(reference)})
        melo_lines.append(f"{audio}|10|KR|{text}\n")
    (derived / "qwen_train.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in qwen_rows),
        encoding="utf-8",
    )
    (derived / "melotts_train.txt").write_text("".join(melo_lines), encoding="utf-8")
    return {
        "repository": repository,
        "derived": derived,
        "run": (tmp_path / "run").resolve(),
    }


def test_prepare_plan_creates_two_record_smoke_package(inputs: dict[str, Path]) -> None:
    plan = preparation.prepare_run_plan(inputs["repository"], inputs["derived"], inputs["run"])
    assert plan["status"] == "SMOKE_PREPARED_NOT_EXECUTED"
    assert plan["qwen3_tts_revision"] == "b" * 40
    assert plan["manifest"]["records"] == 3
    assert plan["manifest"]["paired_with_melotts"] is True
    assert plan["smoke_test"]["records"] == 2
    assert plan["smoke_test"]["inference_uses_reference_audio"] is False
    assert plan["full_training"]["status"].startswith("BLOCKED")
    assert plan["models"]["primary"]["required_local_path"] in plan["commands"]["train_smoke"]
    smoke_rows = (inputs["run"] / "smoke-raw.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(smoke_rows) == 2


def test_rejects_different_reference_audio(inputs: dict[str, Path]) -> None:
    manifest = inputs["derived"] / "qwen_train.jsonl"
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    other_reference = inputs["derived"] / "other-reference.wav"
    other_reference.write_bytes(b"other")
    rows[-1]["ref_audio"] = str(other_reference)
    manifest.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="동일한 ref_audio"):
        preparation.validate_qwen_manifest(manifest)


def test_rejects_reference_audio_as_training_audio(inputs: dict[str, Path]) -> None:
    manifest = inputs["derived"] / "qwen_train.jsonl"
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    rows[0]["ref_audio"] = rows[0]["audio"]
    manifest.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="일반 학습 audio"):
        preparation.validate_qwen_manifest(manifest)


def test_rejects_cross_model_pair_mismatch(inputs: dict[str, Path]) -> None:
    melo = inputs["derived"] / "melotts_train.txt"
    melo.write_text(melo.read_text(encoding="utf-8").replace("학습 문장 0", "다른 문장", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="일치하지 않음"):
        preparation.prepare_run_plan(inputs["repository"], inputs["derived"], inputs["run"])


def test_inference_validates_paths_before_optional_imports(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="model"):
        synthesize((tmp_path / "missing-model").resolve(), (tmp_path / "text.txt").resolve(), tmp_path / "out.wav", "speaker")
