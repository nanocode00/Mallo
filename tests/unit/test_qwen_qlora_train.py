import json
from pathlib import Path

import pytest

from scripts.train.nlu.qwen_qlora_train import (
    MODEL_DOWNLOAD_BYTES,
    MODEL_ID,
    MODEL_REVISION,
    HardwareReport,
    TrainingConfig,
    TrainingEnvironmentError,
    dry_run_report,
    finalize_adapter,
    optimizer_step_count,
    require_training_hardware,
    sft_arguments,
)


def _row(sample_id: str, split: str) -> dict:
    return {"sample_id": sample_id, "metadata": {"split": split}}


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _files(tmp_path: Path, *, train_rows: int = 2) -> tuple[Path, Path]:
    train = _write_jsonl(
        tmp_path / "train.jsonl",
        [_row(f"nlu_{index:06d}", "train") for index in range(1, train_rows + 1)],
    )
    validation = _write_jsonl(
        tmp_path / "validation.jsonl", [_row("nlu_validation_000001", "validation")]
    )
    return train, validation


def _hardware(*, cuda=False, capability=None, bf16=False):
    return HardwareReport(
        cuda_available=cuda,
        device_count=1 if cuda else 0,
        device_name="test-gpu" if cuda else None,
        compute_capability=capability,
        total_vram_bytes=8 * 1024**3 if cuda else None,
        bf16_supported=bf16,
        package_versions={},
    )


def test_model_and_revision_are_pinned():
    assert MODEL_ID == "Qwen/Qwen3-1.7B"
    assert MODEL_REVISION == "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
    assert MODEL_DOWNLOAD_BYTES == 4_077_751_381


def test_dry_run_on_cpu_never_allows_implicit_download(tmp_path: Path):
    train, validation = _files(tmp_path)
    config = TrainingConfig(train_path=train, validation_path=validation, output_dir=tmp_path / "run")

    report = dry_run_report(config, _hardware())

    assert report["hardware"]["training_ready"] is False
    assert report["model_download"]["allowed"] is False
    assert report["model_download"]["local_files_only"] is True


def test_training_requires_cuda():
    with pytest.raises(TrainingEnvironmentError, match="CUDA GPU"):
        require_training_hardware(_hardware())


def test_nf4_requires_compute_capability_six_or_newer():
    with pytest.raises(TrainingEnvironmentError, match="6.0"):
        require_training_hardware(_hardware(cuda=True, capability=(5, 2)))

    require_training_hardware(_hardware(cuda=True, capability=(8, 6)))


def test_sft_arguments_match_spec(tmp_path: Path):
    train, validation = _files(tmp_path, train_rows=2400)
    config = TrainingConfig(train_path=train, validation_path=validation, output_dir=tmp_path / "run")

    arguments = sft_arguments(config, bf16=True)

    assert arguments["assistant_only_loss"] is True
    assert arguments["max_length"] == 2048
    assert arguments["learning_rate"] == 2e-4
    assert arguments["gradient_accumulation_steps"] == 8
    assert arguments["warmup_steps"] == 14
    assert "warmup_ratio" not in arguments
    assert arguments["bf16"] is True
    assert arguments["fp16"] is False
    # checkpoint 선택은 semantic 지표로 별도 평가한다. eval_loss 자동 선택 금지.
    assert arguments["load_best_model_at_end"] is False
    assert "metric_for_best_model" not in arguments
    assert "greater_is_better" not in arguments
    assert arguments["save_total_limit"] is None


@pytest.mark.parametrize(
    (
        "epochs",
        "micro_batch_size",
        "gradient_accumulation_steps",
        "total_steps",
        "warmup_steps",
    ),
    [
        (3.0, 2, 8, 450, 14),
        (2.0, 2, 8, 300, 9),
        (3.0, 1, 16, 450, 14),
    ],
)
def test_warmup_steps_follow_training_configuration(
    tmp_path: Path,
    epochs: float,
    micro_batch_size: int,
    gradient_accumulation_steps: int,
    total_steps: int,
    warmup_steps: int,
):
    train, validation = _files(tmp_path, train_rows=2400)
    config = TrainingConfig(
        train_path=train,
        validation_path=validation,
        output_dir=tmp_path / "run",
        epochs=epochs,
        micro_batch_size=micro_batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
    )

    assert optimizer_step_count(config) == total_steps
    assert sft_arguments(config, bf16=False)["warmup_steps"] == warmup_steps


def test_empty_training_input_cannot_calculate_warmup(tmp_path: Path):
    train, _ = _files(tmp_path, train_rows=0)
    config = TrainingConfig(train_path=train)

    with pytest.raises(TrainingEnvironmentError, match="비어"):
        optimizer_step_count(config)


def test_test_split_content_is_rejected_regardless_of_filename(tmp_path: Path):
    # Test JSONL을 다른 이름으로 복사해 --train으로 넘겨도 내용 기반 검증으로 차단된다.
    copied = _write_jsonl(
        tmp_path / "my_train.jsonl", [_row("nlu_000009", "test")]
    )
    _, validation = _files(tmp_path)

    with pytest.raises(TrainingEnvironmentError, match="Test Split"):
        TrainingConfig(train_path=copied, validation_path=validation).validate()


def test_missing_split_metadata_is_rejected(tmp_path: Path):
    _, validation = _files(tmp_path)
    broken = _write_jsonl(
        tmp_path / "broken-train.jsonl", [{"sample_id": "nlu_000001", "metadata": {}}]
    )

    with pytest.raises(TrainingEnvironmentError, match="metadata.split 필드가 없습니다"):
        TrainingConfig(train_path=broken, validation_path=validation).validate()


def test_validation_role_requires_validation_split(tmp_path: Path):
    train, _ = _files(tmp_path)
    wrong = _write_jsonl(
        tmp_path / "validation.jsonl", [_row("nlu_000002", "train")]
    )

    with pytest.raises(TrainingEnvironmentError, match="'validation'"):
        TrainingConfig(train_path=train, validation_path=wrong).validate()


def test_duplicate_sample_id_across_files_is_rejected(tmp_path: Path):
    train = _write_jsonl(tmp_path / "train.jsonl", [_row("nlu_000001", "train")])
    validation = _write_jsonl(
        tmp_path / "validation.jsonl", [_row("nlu_000001", "validation")]
    )

    with pytest.raises(TrainingEnvironmentError, match="동시에 있습니다"):
        TrainingConfig(train_path=train, validation_path=validation).validate()


def test_empty_input_file_is_rejected(tmp_path: Path):
    _, validation = _files(tmp_path)
    empty = _write_jsonl(tmp_path / "empty-train.jsonl", [])

    with pytest.raises(TrainingEnvironmentError, match="행이 없습니다"):
        TrainingConfig(train_path=empty, validation_path=validation).validate()


def test_finalize_adapter_copies_selected_checkpoint(tmp_path: Path):
    checkpoint = tmp_path / "checkpoints" / "checkpoint-150"
    checkpoint.mkdir(parents=True)
    (checkpoint / "adapter_config.json").write_text("{}\n", encoding="utf-8")
    (checkpoint / "adapter_model.safetensors").write_text("weights", encoding="utf-8")
    run_dir = tmp_path / "run"

    target = finalize_adapter(run_dir, checkpoint)

    assert target == run_dir / "final-adapter"
    assert (target / "adapter_config.json").is_file()
    assert (target / "adapter_model.safetensors").read_text(encoding="utf-8") == "weights"


def test_finalize_adapter_replaces_previous_final_adapter(tmp_path: Path):
    first = tmp_path / "checkpoints" / "checkpoint-150"
    second = tmp_path / "checkpoints" / "checkpoint-300"
    for index, checkpoint in enumerate((first, second), start=1):
        checkpoint.mkdir(parents=True)
        (checkpoint / "adapter_config.json").write_text(f"run{index}\n", encoding="utf-8")
    run_dir = tmp_path / "run"

    finalize_adapter(run_dir, first)
    target = finalize_adapter(run_dir, second)

    assert (target / "adapter_config.json").read_text(encoding="utf-8") == "run2\n"


def test_finalize_adapter_rejects_non_checkpoint_directory(tmp_path: Path):
    not_checkpoint = tmp_path / "checkpoints" / "misc"
    not_checkpoint.mkdir(parents=True)

    with pytest.raises(TrainingEnvironmentError, match="checkpoint가 아닙니다"):
        finalize_adapter(tmp_path / "run", not_checkpoint)
