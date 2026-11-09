import json
from pathlib import Path

import pytest

from adapters.nlu.qwen_training_data import (
    TrainingDataError,
    build_system_prompt,
    canonical_json,
    convert_file,
    render_chat,
    to_conversation,
)


def _record(*, output_type="commands", value=None):
    if value is None:
        value = [
            {
                "intent": "ADD_ITEM",
                "target_item_id": "americano",
                "category_id": None,
                "quantity": 1,
                "temperature": "iced",
                "query_tags": None,
                "detail_fields": None,
                "options": None,
            }
        ]
    return {
        "sample_id": "nlu_000001",
        "input": {"utterance": "아이스 아메리카노 한 잔 주세요", "cart_before": []},
        "output": {"type": output_type, "value": value},
        "metadata": {
            "label_group": "ADD_ITEM",
            "menu_version": "1.3",
            "source": "llm_synthetic",
        },
    }


class RecordingTokenizer:
    def __init__(self):
        self.conversation = None
        self.kwargs = None

    def apply_chat_template(self, conversation, **kwargs):
        self.conversation = conversation
        self.kwargs = kwargs
        return "rendered"


def test_system_prompt_is_built_from_current_contracts():
    prompt = build_system_prompt()

    assert "Qwen" not in prompt
    assert "/no_think" in prompt
    assert '"americano"' in prompt
    assert '"ADD_ITEM"' in prompt
    assert '"UNSUPPORTED_UTTERANCE"' in prompt
    assert "request_id는 출력 금지" in prompt


def test_conversation_contains_only_output_value_as_canonical_json():
    conversation = to_conversation(_record(), "system")

    assert [message["role"] for message in conversation["messages"]] == [
        "system",
        "user",
        "assistant",
    ]
    assistant = json.loads(conversation["messages"][2]["content"])
    assert isinstance(assistant, list)
    assert "type" not in conversation["messages"][2]["content"]
    assert "request_id" not in assistant[0]
    assert conversation == to_conversation(_record(), "system")


def test_error_value_is_serialized_as_top_level_object():
    error = {
        "code": "MISSING_FIELD",
        "message": "온도를 말씀해 주세요.",
        "command_index": 0,
        "field": "temperature",
        "candidates": ["hot", "iced"],
        "retryable": True,
    }

    conversation = to_conversation(_record(output_type="error", value=error), "system")

    assert json.loads(conversation["messages"][2]["content"]) == error


def test_render_chat_strictly_disables_thinking():
    tokenizer = RecordingTokenizer()

    rendered = render_chat(_record(), "system", tokenizer)

    assert rendered == "rendered"
    assert tokenizer.kwargs == {
        "tokenize": False,
        "add_generation_prompt": False,
        "enable_thinking": False,
    }
    assert tokenizer.conversation[-1]["role"] == "assistant"


def test_request_id_in_training_target_is_rejected():
    record = _record()
    record["output"]["value"][0]["request_id"] = "model-must-not-create-this"

    with pytest.raises(TrainingDataError, match="request_id"):
        to_conversation(record, "system")


def test_convert_file_is_byte_deterministic(tmp_path: Path):
    source = tmp_path / "train.jsonl"
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    source.write_text(canonical_json(_record()) + "\n", encoding="utf-8")

    assert convert_file(source, first, split="train") == 1
    assert convert_file(source, second, split="train") == 1

    assert first.read_bytes() == second.read_bytes()
    converted = json.loads(first.read_text(encoding="utf-8"))
    assert converted["sample_id"] == "nlu_000001"


def test_test_split_cannot_be_converted_for_training(tmp_path: Path):
    source = tmp_path / "test.jsonl"
    source.write_text(canonical_json(_record()) + "\n", encoding="utf-8")

    with pytest.raises(TrainingDataError, match="train과 validation"):
        convert_file(source, tmp_path / "output.jsonl", split="test")
