from pathlib import Path

import pytest

from adapters.nlu.qwen06b_config import (
    MODEL_ID,
    MODEL_PARAMETER_COUNT,
    MODEL_REVISION,
    reject_test_path,
)


def test_qwen06b_model_is_pinned() -> None:
    assert MODEL_ID == "Qwen/Qwen3-0.6B"
    assert MODEL_REVISION == "c1899de289a04d12100db370d81485cdf75e47ca"
    assert MODEL_PARAMETER_COUNT == 596_049_920


def test_reject_test_path_allows_train_and_validation() -> None:
    reject_test_path(Path("data/nlu/processed/qwen3/train.jsonl"), label="train")
    reject_test_path(Path("data/nlu/processed/validation.jsonl"), label="validation")


@pytest.mark.parametrize(
    "path",
    [
        Path("data/nlu/processed/test.jsonl"),
        Path("models/nlu/test-run/output.jsonl"),
        Path("scratch/final-test/predictions.jsonl"),
    ],
)
def test_reject_test_path_fails_closed(path: Path) -> None:
    with pytest.raises(ValueError, match="test"):
        reject_test_path(path, label="guard")
