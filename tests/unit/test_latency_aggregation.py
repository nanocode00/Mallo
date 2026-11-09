from __future__ import annotations

import pytest

from utils.latency_aggregation import (
    MOCK_E2E,
    REAL_E2E,
    COMPONENT_BENCHMARK,
    WARMUP_TURNS,
    classify_turn,
    nearest_rank_percentile,
    select_warm_population,
    summarize_warm_turns,
)


def test_nearest_rank_percentile_uses_ceil_rank() -> None:
    values = list(range(1, 11))

    assert nearest_rank_percentile(values, 95) == 10
    assert nearest_rank_percentile(values, 50) == 5


def test_nearest_rank_percentile_rejects_empty_and_bad_percentile() -> None:
    with pytest.raises(ValueError):
        nearest_rank_percentile([], 95)
    with pytest.raises(ValueError):
        nearest_rank_percentile([1.0], 0)
    with pytest.raises(ValueError):
        nearest_rank_percentile([1.0], 101)


def test_classify_turn_boundaries_ac02() -> None:
    assert classify_turn(1100) == "target_met"
    assert classify_turn(1300) == "requirement_only"
    assert classify_turn(1600) == "below_requirement"

    assert classify_turn(1200) == "target_met"
    assert classify_turn(1200.001) == "requirement_only"
    assert classify_turn(1500) == "requirement_only"
    assert classify_turn(1500.001) == "below_requirement"


def test_measurement_types_are_distinct() -> None:
    assert len({REAL_E2E, MOCK_E2E, COMPONENT_BENCHMARK}) == 3
    assert REAL_E2E == "REAL_E2E"


def test_select_warm_population_exactly_excludes_first_three_ac07() -> None:
    measured = [{"round": 0}] * WARMUP_TURNS + [{"round": r} for r in range(1, 51)]
    population = select_warm_population(measured)

    assert len(measured) == 53
    assert len(population) == 50
    assert population[0]["round"] == 1


def test_select_warm_population_rejects_too_few_turns() -> None:
    with pytest.raises(ValueError):
        select_warm_population([{}, {}])


def test_summarize_target_met_requires_all_gates() -> None:
    values = [900.0, 1000.0, 1100.0, 1200.0]
    summary = summarize_warm_turns(values, [True, True, True, True])

    assert summary["p95"] == 1200
    assert summary["target_met"] is True
    assert summary["requirement_met"] is True
    assert summary["over_requirement_count"] == 0
    assert summary["failure_count"] == 0


def test_summarize_requirement_only_when_p95_between_bounds() -> None:
    values = [1300.0] * 4 + [1400.0] * 16
    summary = summarize_warm_turns(values, [True] * 20)

    assert 1200 < summary["p95"] <= 1500
    assert summary["target_met"] is False
    assert summary["requirement_met"] is True


def test_summarize_fails_when_more_than_two_turns_over_requirement() -> None:
    values = [1600.0] * 3 + [800.0] * 17
    summary = summarize_warm_turns(values, [True] * 20)

    assert summary["over_requirement_count"] == 3
    assert summary["target_met"] is False
    assert summary["requirement_met"] is False


def test_summarize_tolerates_two_turns_over_requirement_if_p95_low() -> None:
    values = [1700.0] * 2 + [700.0] * 38
    summary = summarize_warm_turns(values, [True] * 40)

    assert summary["over_requirement_count"] == 2
    assert summary["p95"] <= 1500
    assert summary["requirement_met"] is True


def test_summarize_fails_on_any_processing_failure() -> None:
    successes = [True] * 19 + [False]
    values = [600.0] * 20
    summary = summarize_warm_turns(values, successes)

    assert summary["failure_count"] == 1
    assert summary["target_met"] is False
    assert summary["requirement_met"] is False


def test_summarize_rejects_mismatched_lengths_and_empty_population() -> None:
    with pytest.raises(ValueError):
        summarize_warm_turns([100.0], [])
    with pytest.raises(ValueError):
        summarize_warm_turns([], [])


def test_over_requirement_counts_only_strictly_above_1500() -> None:
    values = [1500.0, 1500.0, 1500.0001, 500.0]
    summary = summarize_warm_turns(values, [True] * 4)

    assert summary["over_requirement_count"] == 1
    assert summary["requirement_met"] is False
