import json

import pytest

from adapters.nlu.qwen_prediction_runner import (
    PredictionConfig,
    PredictionError,
    _metric_summary,
    assert_test_run_available,
    generation_options,
    longest_common_token_prefix,
    mark_test_run_complete,
    restore_compact_prediction,
)
from adapters.nlu.qwen_training_data import build_compact_system_prompt, build_system_prompt


def test_generation_options_are_deterministic() -> None:
    assert generation_options(max_new_tokens=128, eos_token_id=2, pad_token_id=2) == {
        "do_sample": False,
        "max_new_tokens": 128,
        "eos_token_id": 2,
        "pad_token_id": 2,
    }


def test_metric_summary_uses_nearest_rank_p95() -> None:
    summary = _metric_summary(list(range(1, 21)))

    assert summary == {"min": 1, "median": 10.5, "p95": 19, "max": 20}


def test_longest_common_token_prefix_uses_token_ids() -> None:
    assert longest_common_token_prefix([[1, 2, 3], [1, 2, 4], [1, 2]]) == [1, 2]


def test_prefix_cache_requires_batch_one_dynamic_non_compile(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    config = PredictionConfig(
        split="validation",
        variant="baseline",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        prefix_cache=True,
        batch_size=8,
    )

    with pytest.raises(PredictionError, match="batch=1 Dynamic cache"):
        config.validate()


def test_prompt_lookup_requires_batch_one(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    config = PredictionConfig(
        split="validation",
        variant="baseline",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        prompt_lookup_num_tokens=5,
        batch_size=8,
    )

    with pytest.raises(PredictionError, match="prompt lookup"):
        config.validate()


def test_matching_ngram_requires_prompt_lookup(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    config = PredictionConfig(
        split="validation",
        variant="baseline",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        max_matching_ngram_size=4,
    )

    with pytest.raises(PredictionError, match="matching ngram"):
        config.validate()


def test_compact_prompt_preserves_contract_and_is_shorter() -> None:
    compact = build_compact_system_prompt()

    assert len(compact) < len(build_system_prompt())
    for required in ("ADD_ITEM", "MISSING_FIELD", "request_id", "americano"):
        assert required in compact


def test_invalid_generation_profile_is_rejected(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    config = PredictionConfig(
        split="validation",
        variant="baseline",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        generation_profile="sampling",
    )

    with pytest.raises(PredictionError, match="generation profile"):
        config.validate()


def test_non_positive_batch_size_is_rejected(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    config = PredictionConfig(
        split="validation",
        variant="baseline",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        batch_size=0,
    )

    with pytest.raises(PredictionError, match="batch size"):
        config.validate()


def test_invalid_precision_is_rejected(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    config = PredictionConfig(
        split="validation",
        variant="baseline",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        precision="fp32",
    )

    with pytest.raises(PredictionError, match="precision"):
        config.validate()


def test_merged_model_requires_bf16_and_artifact(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    merged = tmp_path / "merged"
    merged.mkdir()
    config = PredictionConfig(
        split="validation",
        variant="fine-tuned",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        model_format="merged",
        merged_model_path=merged,
        precision="4bit",
    )

    with pytest.raises(PredictionError, match="bf16"):
        config.validate()


def test_compile_requires_static_cache(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    config = PredictionConfig(
        split="validation",
        variant="baseline",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        cache_implementation="dynamic",
        compile_mode="reduce-overhead",
    )

    with pytest.raises(PredictionError, match="static cache"):
        config.validate()


def test_restore_compact_command_array_adds_nullable_fields() -> None:
    restored = json.loads(restore_compact_prediction('[{"intent":"QUERY_CART"}]'))

    assert restored[0] == {
        "intent": "QUERY_CART",
        "target_item_id": None,
        "category_id": None,
        "quantity": None,
        "temperature": None,
        "query_tags": None,
        "detail_fields": None,
        "options": None,
    }


def test_restore_compact_error_adds_nullable_fields() -> None:
    restored = json.loads(
        restore_compact_prediction(
            '{"code":"MIXED_INTENT","message":"한 번에 하나씩 말씀해 주세요."}'
        )
    )

    assert restored["command_index"] is None
    assert restored["field"] is None
    assert restored["candidates"] is None
    assert restored["retryable"] is True


def test_flash_only_kernel_rejects_flash_attention_2_dispatch(tmp_path) -> None:
    input_path = tmp_path / "validation.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    config = PredictionConfig(
        split="validation",
        variant="baseline",
        input_path=input_path,
        output_path=tmp_path / "output.jsonl",
        attention_backend="flash_attention_2",
        sdpa_kernel_backend="flash-only",
    )

    with pytest.raises(PredictionError, match="sdpa attention"):
        config.validate()


def test_completed_test_run_is_rejected(tmp_path) -> None:
    input_path = tmp_path / "test.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    ledger_path = tmp_path / "test-runs.json"
    config = PredictionConfig(
        split="test",
        variant="fine-tuned",
        input_path=input_path,
        output_path=tmp_path / "predictions.jsonl",
        adapter_path=adapter_path,
        experiment_id="experiment-v1",
        final_test=True,
        ledger_path=ledger_path,
    )

    mark_test_run_complete(config, sample_count=300)

    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["completed"]["experiment-v1:fine-tuned"]["sample_count"] == 300
    with pytest.raises(PredictionError, match="이미 완료"):
        assert_test_run_available(config)
