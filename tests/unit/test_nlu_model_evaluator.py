import json

import pytest

from scripts.eval.nlu.model_evaluator import EvaluationError, NLUEvaluator, summarize


def _gold(value, output_type="commands", label="ADD_ITEM"):
    return {
        "sample_id": "nlu_000001",
        "output": {"type": output_type, "value": value},
        "metadata": {"label_group": label},
    }


def _command(menu="americano", quantity=1):
    return {
        "intent": "ADD_ITEM",
        "target_item_id": menu,
        "category_id": None,
        "quantity": quantity,
        "temperature": "iced",
        "query_tags": None,
        "detail_fields": None,
        "options": None,
        "fulfillment_type": None,
    }


def test_exact_command_prediction_passes_all_contract_metrics():
    evaluator = NLUEvaluator()
    command = _command()

    result = evaluator.score(_gold([command]), json.dumps([command]))
    summary = summarize([result], [10.0])

    assert result["json_valid"] is True
    assert result["schema_valid"] is True
    assert summary["intent_accuracy"] == 1.0
    assert summary["slot_accuracy"] == 1.0
    assert summary["exact_match"] == 1.0
    assert summary["invalid_menu_output_rate"] == 0.0


def test_invalid_json_is_recorded_separately():
    result = NLUEvaluator().score(_gold([_command()]), "not-json")
    summary = summarize([result], [])

    assert result["predicted_label"] == "INVALID_JSON"
    assert summary["failure_counts"]["invalid_json"] == 1
    assert summary["failure_counts"]["schema_error"] == 0


def test_schema_and_unknown_menu_failures_can_overlap():
    prediction = _command(menu="hallucinated_menu")
    del prediction["quantity"]

    result = NLUEvaluator().score(_gold([_command()]), json.dumps([prediction]))
    summary = summarize([result], [])

    assert result["schema_valid"] is False
    assert result["invalid_menu"] is True
    assert summary["failure_counts"]["schema_error"] == 1
    assert summary["failure_counts"]["invalid_menu"] == 1


def test_error_code_accuracy_is_independent_of_message():
    expected = {
        "code": "MISSING_FIELD",
        "message": "온도를 말씀해 주세요.",
        "command_index": 0,
        "field": "temperature",
        "candidates": ["hot", "iced"],
        "retryable": True,
    }
    prediction = expected | {"message": "다른 안전한 안내"}

    result = NLUEvaluator().score(
        _gold(expected, output_type="error", label="MISSING_FIELD"), json.dumps(prediction)
    )

    assert result["error_code_correct"] is True
    assert result["exact_match"] is False


def test_multi_command_order_change_is_detected():
    first = _command("americano", 1)
    second = _command("cafe_latte", 2)

    result = NLUEvaluator().score(_gold([first, second]), json.dumps([second, first]))
    summary = summarize([result], [])

    assert result["command_order_correct"] is False
    assert summary["multi_command_order_accuracy"] == 0.0
    assert summary["failure_counts"]["command_order"] == 1


def test_latency_reports_median_and_nearest_rank_p95():
    result = NLUEvaluator().score(_gold([_command()]), json.dumps([_command()]))

    summary = summarize([result], [10.0, 20.0, 30.0, 40.0])

    assert summary["warm_latency_ms"] == {"median": 25.0, "p95": 40.0}


def test_empty_results_are_rejected():
    with pytest.raises(EvaluationError, match="비어"):
        summarize([], [])
