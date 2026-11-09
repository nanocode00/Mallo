import json

from scripts.eval.nlu.challenge_evaluator import ChallengeEvaluator, summarize


def command(menu_id, quantity, temperature=None):
    return {"intent": "ADD_ITEM", "target_item_id": menu_id, "category_id": None, "quantity": quantity, "temperature": temperature, "query_tags": None, "detail_fields": None, "options": None}


def case(sample_id, category, expected, *, behavioral=None, scored=True):
    return {"sample_id": sample_id, "input": {"utterance": "x", "cart_before": []}, "output": {"type": "commands", "value": expected}, "metadata": {"category": category, "scored": scored, "behavioral": behavioral}}


def test_multi_command_order_and_quantity_are_strict():
    record = case("c1", "multi_item", [command("americano", 2, "iced"), command("cafe_latte", 1, "hot")])
    evaluator = ChallengeEvaluator()
    good = evaluator.score(record, json.dumps(record["output"]["value"]))
    wrong_order = evaluator.score(record, json.dumps(list(reversed(record["output"]["value"]))))
    assert good["semantic_pass"] and good["quantity_pass"]
    assert not wrong_order["semantic_pass"]


def test_existing_cart_and_behavioral_temperature_are_scored_separately():
    add = case("c1", "existing_cart_add", [command("cafe_latte", 2, "iced")])
    temp = case("c2", "temperature_no_question", [], behavioral="temperature_no_question")
    predictions = {
        "c1": {"prediction": json.dumps(add["output"]["value"]), "latency_ms": 3},
        "c2": {"prediction": json.dumps({"code": "MISSING_FIELD", "message": "온도를 선택해 주세요.", "command_index": None, "field": "temperature", "candidates": None, "retryable": True}), "latency_ms": 4},
    }
    _, report = summarize([add, temp], predictions)
    assert report["existing_cart_add_pass_rate"] == 1.0
    assert report["temperature_no_question_behavioral_pass_rate"] == 0.0


def test_unsupported_contract_case_is_excluded():
    record = case("p1", "payment_method_stt_confusion", None, scored=False)
    results, report = summarize([record], {"p1": {"prediction": "[]", "latency_ms": 1}})
    assert report["scored_case_count"] == 0
    assert results[0]["semantic_pass"] is None


def test_iced_only_null_and_catalog_temperature_are_semantically_equivalent():
    record = case("c1", "existing_cart_add", [command("iced_tea", 1, None)])
    predicted = [command("iced_tea", 1, "iced")]

    score = ChallengeEvaluator().score(record, json.dumps(predicted))

    assert score["exact_match"] is True
    assert score["semantic_pass"] is True


def test_existing_cart_add_ignores_production_only_null_fulfillment_type():
    record = case("c1", "existing_cart_add", [command("cafe_latte", 2, None)])
    final = [dict(command("cafe_latte", 2, None), fulfillment_type=None)]

    score = ChallengeEvaluator().score(record, json.dumps(final))

    assert score["exact_match"] is True
    assert score["semantic_pass"] is True


def test_confirm_order_ignores_production_only_null_fulfillment_type():
    expected = [{"intent": "CONFIRM_ORDER", "target_item_id": None, "category_id": None,
                 "quantity": None, "temperature": None, "query_tags": None,
                 "detail_fields": None, "options": None}]
    record = case("c1", "confirm_order", expected)
    final = [dict(expected[0], fulfillment_type=None)]

    score = ChallengeEvaluator().score(record, json.dumps(final))

    assert score["exact_match"] is True
    assert score["semantic_pass"] is True
