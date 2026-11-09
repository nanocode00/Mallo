"""E2E Latency 측정 집계 계약 (docs/specs/e2e-latency.md).

측정 유형 구분, Turn 분류, Warm-up 제외, nearest-rank p95 집계와
Target/Requirement 판정 규칙의 단일 구현이다. Real 측정 스크립트와
단위 테스트가 이 모듈만을 기준으로 동작한다.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Sequence

TARGET_P95_MS = 1200.0
REQUIREMENT_P95_MS = 1500.0
MAX_TURNS_OVER_REQUIREMENT = 2
WARMUP_TURNS = 3

REAL_E2E = "REAL_E2E"
MOCK_E2E = "MOCK_E2E"
COMPONENT_BENCHMARK = "COMPONENT_BENCHMARK"


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    """nearest-rank 방식으로 백분위를 계산한다."""
    if not values:
        raise ValueError("values must not be empty")
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")

    ordered = sorted(values)
    rank = math.ceil((percentile / 100.0) * len(ordered))
    return float(ordered[rank - 1])


def classify_turn(e2e_ms: float) -> str:
    """AC-02: Turn 단위 성능 구간을 분류한다.

    <=1.2초 target_met, <=1.5초 requirement_only, 초과 below_requirement.
    """
    if e2e_ms <= TARGET_P95_MS:
        return "target_met"
    if e2e_ms <= REQUIREMENT_P95_MS:
        return "requirement_only"
    return "below_requirement"


def select_warm_population(turns: list[Any], warmup_turns: int = WARMUP_TURNS) -> list[Any]:
    """AC-07: 최초 warmup_turns개 Turn을 Warm-up으로 제외한 판정 모집단을 반환한다."""
    if warmup_turns < 0:
        raise ValueError("warmup_turns must not be negative")
    if warmup_turns > len(turns):
        raise ValueError("warmup_turns exceeds number of turns")
    return turns[warmup_turns:]


def summarize_warm_turns(
    e2e_values_ms: Sequence[float], successes: Sequence[bool]
) -> dict[str, Any]:
    """AC-08: Warm 판정 모집단의 통계와 Target/Requirement 판정을 계산한다.

    Requirement는 p95<=1.5초, 1.5초 초과 최대 2 Turn, 처리 실패 0건을
    모두 충족할 때만 통과한다. Target은 같은 게이트를 p95<=1.2초로 적용한다.
    """
    if not e2e_values_ms:
        raise ValueError("e2e_values_ms must not be empty")
    if len(e2e_values_ms) != len(successes):
        raise ValueError("e2e_values_ms and successes must have the same length")

    values = [float(v) for v in e2e_values_ms]
    p95 = nearest_rank_percentile(values, 95)
    over_requirement_count = sum(v > REQUIREMENT_P95_MS for v in values)
    failure_count = sum(1 for success in successes if not success)

    gates_met = (
        over_requirement_count <= MAX_TURNS_OVER_REQUIREMENT and failure_count == 0
    )

    return {
        "mean": float(statistics.fmean(values)),
        "median": float(statistics.median(values)),
        "p95": p95,
        "max": max(values),
        "turn_count": len(values),
        "over_requirement_count": over_requirement_count,
        "failure_count": failure_count,
        "target_met": p95 <= TARGET_P95_MS and gates_met,
        "requirement_met": p95 <= REQUIREMENT_P95_MS and gates_met,
    }
