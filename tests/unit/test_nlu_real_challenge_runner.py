from __future__ import annotations

import importlib.util
from pathlib import Path

from domain.intents import Intent
from domain.models import OrderCommand, Temperature


def _runner_module():
    path = Path(__file__).parents[2] / "scripts" / "eval" / "nlu" / "run_nlu_real_challenge.py"
    spec = importlib.util.spec_from_file_location("nlu_real_challenge_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_runner_keeps_runtime_diagnostics_and_final_semantics():
    runner = _runner_module()

    class FakeNLU:
        last_original_text = "카페라테 한 잔 주세요"
        last_normalized_text = "카페라떼 1잔 주세요"
        last_normalization_replacements = (("카페라테", "카페라떼"), ("한", "1"))
        last_raw_prediction = '{"code":"MISSING_FIELD"}'
        last_repaired_payload = [{"intent": "ADD_ITEM"}]
        last_latency_ms = 12.5

        def parse(self, text, cart):
            return [OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="cafe_latte",
                quantity=1,
                temperature=Temperature.HOT,
            )]

    rows = [{
        "sample_id": "case-1",
        "input": {"utterance": "카페라테 한 잔 주세요", "cart_before": []},
    }]

    prediction = runner.run_production_nlu(FakeNLU(), rows)[0]

    assert prediction["original_utterance"] == "카페라테 한 잔 주세요"
    assert prediction["normalized_utterance"] == "카페라떼 1잔 주세요"
    assert prediction["normalization_replacements"] == [["카페라테", "카페라떼"], ["한", "1"]]
    assert prediction["raw_prediction"] == '{"code":"MISSING_FIELD"}'
    assert prediction["repaired_payload"] == [{"intent": "ADD_ITEM"}]
    assert prediction["final_semantic_result"][0]["intent"] == "ADD_ITEM"
    assert prediction["latency_ms"] == 12.5
