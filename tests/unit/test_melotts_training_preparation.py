import json
from pathlib import Path

import pytest

from scripts.data.tts import prepare_melotts_training as preparation



def write_manifest(path: Path, audio: Path, text: str = "안내 문장입니다.") -> None:
    path.write_text(f"{audio.resolve()}|10|KR|{text}\n", encoding="utf-8")


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    repository = (tmp_path / "MeloTTS").resolve()
    for relative in preparation.REQUIRED_REPOSITORY_FILES:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "# fixture\n", encoding="utf-8")
    base_config = repository / "melo/configs/config.json"
    base_config.write_text(
        json.dumps({"train": {}, "data": {}, "model": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(preparation, "_git_revision", lambda _: "a" * 40)

    derived = (tmp_path / "derived").resolve()
    derived.mkdir()
    train_audio = derived / "train.wav"
    validation_audio = derived / "validation.wav"
    train_audio.write_bytes(b"train")
    validation_audio.write_bytes(b"validation")
    write_manifest(derived / "melotts_train.txt", train_audio)
    write_manifest(derived / "melotts_validation.txt", validation_audio)

    pretrain = (tmp_path / "pretrain").resolve()
    pretrain.mkdir()
    for filename in preparation.PRETRAIN_FILES:
        (pretrain / filename).write_bytes(filename.encode())
    baseline = (tmp_path / "checkpoint.pth").resolve()
    baseline.write_bytes(b"baseline")
    return {
        "repository": repository,
        "derived": derived,
        "pretrain": pretrain,
        "baseline": baseline,
        "run": (tmp_path / "run").resolve(),
    }


def test_prepare_run_plan_records_inputs_and_commands(inputs: dict[str, Path]) -> None:
    plan = preparation.prepare_run_plan(
        inputs["repository"],
        inputs["derived"],
        inputs["pretrain"],
        inputs["baseline"],
        inputs["run"],
    )
    assert plan["status"] == "PREPARED_NOT_EXECUTED"
    assert plan["melotts_revision"] == "a" * 40
    assert plan["manifests"]["train"]["records"] == 1
    assert set(plan["pretrained_weights"]) == {"G.pth", "D.pth", "DUR.pth"}
    assert "--val-per-spk 0" in plan["commands"]["preprocess_train"]
    assert "--pretrain_dur" in plan["commands"]["train"]
    assert json.loads((inputs["run"] / "run-plan.json").read_text(encoding="utf-8"))["status"] == "PREPARED_NOT_EXECUTED"


def test_rejects_train_validation_audio_overlap(inputs: dict[str, Path]) -> None:
    train_line = (inputs["derived"] / "melotts_train.txt").read_text(encoding="utf-8")
    (inputs["derived"] / "melotts_validation.txt").write_text(train_line, encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        preparation.prepare_run_plan(
            inputs["repository"],
            inputs["derived"],
            inputs["pretrain"],
            inputs["baseline"],
            inputs["run"],
        )


def test_rejects_missing_pretrained_weight(inputs: dict[str, Path]) -> None:
    (inputs["pretrain"] / "DUR.pth").unlink()
    with pytest.raises(ValueError, match="DUR.pth"):
        preparation.prepare_run_plan(
            inputs["repository"],
            inputs["derived"],
            inputs["pretrain"],
            inputs["baseline"],
            inputs["run"],
        )


def test_finalize_config_preserves_model_and_applies_contract(inputs: dict[str, Path]) -> None:
    base = inputs["repository"] / "melo/configs/config.json"
    base.write_text(
        json.dumps({"train": {"epochs": 10000}, "data": {}, "model": {"hidden_channels": 192}}),
        encoding="utf-8",
    )
    train = (inputs["run"] / "train.list").resolve()
    validation = (inputs["run"] / "validation.list").resolve()
    inputs["run"].mkdir()
    train.write_text("cleaned train\n", encoding="utf-8")
    validation.write_text("cleaned validation\n", encoding="utf-8")
    output = inputs["run"] / "config.json"

    preparation.finalize_config(base, train, validation, output)

    config = json.loads(output.read_text(encoding="utf-8"))
    assert config["train"] | {"epochs": 10000} == {
        "epochs": 10000,
        "seed": 42,
        "learning_rate": 0.0001,
        "batch_size": 4,
        "eval_interval": 500,
        "skip_optimizer": True,
    }
    assert config["data"]["spk2id"] == {"10": 0}
    assert config["data"]["training_files"] == str(train)
    assert config["model"] == {"hidden_channels": 192}


def test_manifest_requires_absolute_existing_audio(tmp_path: Path) -> None:
    manifest = (tmp_path / "metadata.list").resolve()
    manifest.write_text("relative.wav|10|KR|안내\n", encoding="utf-8")
    with pytest.raises(ValueError, match="WAV 경로"):
        preparation.validate_manifest(manifest)
