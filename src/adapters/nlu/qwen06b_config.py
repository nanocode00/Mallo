"""Pinned constants for the Qwen3-0.6B NLU baseline experiment."""

from __future__ import annotations

from pathlib import Path

from adapters.nlu.qwen_training_data import REPOSITORY_ROOT


MODEL_ID = "Qwen/Qwen3-0.6B"
MODEL_REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"
# Exact parameter count for the pinned Qwen3-0.6B architecture:
# 151,936 vocab, hidden_size=1,024, 28 layers, GQA 16Q/8KV, tied embeddings.
# Hugging Face reports this family as 0.6B total / 0.44B non-embedding params.
MODEL_PARAMETER_COUNT = 596_049_920
MODEL_WEIGHT_BYTES = 1_500_000_000
DEFAULT_EXPERIMENT_ID = "honorbear-20260825-qwen3-0p6b-bf16-lora-v1"
DEFAULT_RUN_ROOT = REPOSITORY_ROOT / "models/nlu/qwen3-0.6b-lora"
DEFAULT_RUN_DIR = DEFAULT_RUN_ROOT / DEFAULT_EXPERIMENT_ID
DEFAULT_SCRATCH_DIR = REPOSITORY_ROOT / "scratch/nlu-qwen06b"
DEFAULT_LOG_DIR = REPOSITORY_ROOT / "logs"


def reject_test_path(path: Path, *, label: str) -> None:
    """Fail closed if an experiment input path appears to target the frozen test split."""

    lowered = "/".join(part.lower() for part in path.parts)
    if "test" in lowered:
        raise ValueError(f"{label} 경로에 test가 포함되어 있습니다: {path}")
