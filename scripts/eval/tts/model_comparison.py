"""T-22·T-23·SIM 결과를 검증하고 T-28 모델 선택 점수를 계산한다."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.eval.tts.listening_evaluation import validate_completed_evaluation



RATING_COLUMNS = (
    "naturalness",
    "overall_clarity",
    "friendliness",
    "menu_name_clarity",
    "quantity_unit_clarity",
    "price_clarity",
    "store_guidance_suitability",
)
SELECTION_WEIGHTS = {
    "menu_name_clarity": 10.0,
    "quantity_unit_clarity": 15.0,
    "price_clarity": 15.0,
    "naturalness": 10.0,
    "friendliness": 10.0,
    "store_guidance_suitability": 10.0,
}


def _absolute_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{label}는 존재하는 절대 파일이어야 함: {path}")
    return path.resolve()


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def _load_listening(
    candidate_id: str,
    evaluations: list[dict[str, str]],
    author_id: str,
    sentences_path: Path,
    menu_path: Path,
) -> dict[str, object]:
    participant_rows: dict[str, list[dict[str, str]]] = {}
    for item in evaluations:
        if set(item) != {"evaluation_path", "answer_key_path"}:
            raise ValueError(f"평가 입력 필드 오류: {candidate_id}")
        evaluation_path = _absolute_file(item["evaluation_path"], "evaluation_path")
        answer_path = _absolute_file(item["answer_key_path"], "answer_key_path")
        validation = validate_completed_evaluation(evaluation_path, sentences_path, menu_path)
        participant_id = str(validation["participant_id"])
        if participant_id == author_id:
            raise ValueError(f"작성자는 최종 평가자가 될 수 없음: {participant_id}")
        if participant_id in participant_rows:
            raise ValueError(f"평가자 중복: {participant_id}")
        evaluation_by_sample = {row["sample_id"]: row for row in _read_tsv(evaluation_path)}
        selected = []
        for answer in _read_tsv(answer_path):
            if answer["candidate_id"] == candidate_id:
                row = evaluation_by_sample.get(answer["sample_id"])
                if row is None or row["sentence_id"] != answer["sentence_id"]:
                    raise ValueError(f"평가표와 정답표 불일치: {candidate_id}")
                selected.append(row)
        expected_ids = {f"tts_eval_{index:02d}" for index in range(1, 21)}
        actual_ids = {row["sentence_id"] for row in selected}
        if len(selected) != 20 or actual_ids != expected_ids:
            raise ValueError(f"후보별 평가 문장 세트 오류: {candidate_id}:{participant_id}")
        participant_rows[participant_id] = selected
    if len(participant_rows) < 3:
        raise ValueError(f"최종 평가자는 최소 3명이어야 함: {candidate_id}")

    ratings: dict[str, list[float]] = defaultdict(list)
    by_sentence: dict[str, list[dict[str, str]]] = defaultdict(list)
    for rows in participant_rows.values():
        for row in rows:
            by_sentence[row["sentence_id"]].append(row)
            for column in RATING_COLUMNS:
                if row[column] != "NA":
                    ratings[column].append(float(row[column]))
    averages = {column: statistics.fmean(ratings[column]) for column in RATING_COLUMNS}
    serious_count = 0
    critical_success_count = 0
    for rows in by_sentence.values():
        majority = len(rows) // 2 + 1
        serious_count += sum(row["serious_misread_or_corruption"] == "yes" for row in rows) >= majority
        critical_success_count += sum(row["critical_information_success"] == "yes" for row in rows) >= majority
    return {
        "participants": sorted(participant_rows),
        "participant_count": len(participant_rows),
        "rating_averages": averages,
        "mos": averages["naturalness"],
        "serious_misread_or_corruption_sentences": serious_count,
        "critical_information_success_sentences": critical_success_count,
    }


def _load_benchmark(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cold = payload["summary"]["cold"]
    warm = payload["summary"]["warm"]
    metrics = warm["metrics"]
    values = {
        "warm_ttfb_p95": metrics["ttfb_seconds"]["p95_nearest_rank"],
        "warm_rtf_p95": metrics["rtf"]["p95_nearest_rank"],
        "peak_ram_p95_mb": metrics["peak_ram_mb"]["p95_nearest_rank"],
        "peak_vram_p95_mb": metrics["peak_vram_mb"]["p95_nearest_rank"],
    }
    valid = all(isinstance(value, (int, float)) and value > 0 for value in values.values())
    return {
        **values,
        "cold_successful_runs": cold["successful_runs"],
        "warm_successful_runs": warm["successful_runs"],
        "complete": cold["successful_runs"] == 20 and warm["successful_runs"] == 100 and valid,
    }


def _load_sim(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"encoder_id", "encoder_revision", "reference_count", "sentence_scores"}
    if set(payload) != required or not payload["encoder_id"] or not payload["encoder_revision"]:
        raise ValueError("SIM 결과 필드 오류")
    scores = payload["sentence_scores"]
    expected_ids = {f"tts_eval_{index:02d}" for index in range(1, 21)}
    if set(scores) != expected_ids or payload["reference_count"] != 3:
        raise ValueError("SIM 문장 또는 참조 수 오류")
    if not all(isinstance(value, (int, float)) and -1 <= value <= 1 for value in scores.values()):
        raise ValueError("SIM 점수 범위 오류")
    return {
        "encoder_id": payload["encoder_id"],
        "encoder_revision": payload["encoder_revision"],
        "reference_count": 3,
        "mean": statistics.fmean(scores.values()),
    }


def _gate_candidate(
    candidate: dict[str, object], baseline: dict[str, object]
) -> list[str]:
    failures = []
    listening = candidate["listening"]
    averages = listening["rating_averages"]
    if listening["serious_misread_or_corruption_sentences"] != 0:
        failures.append("serious_misread_or_corruption")
    if listening["critical_information_success_sentences"] < 18:
        failures.append("critical_information_success_below_18")
    for name in ("friendliness", "overall_clarity", "store_guidance_suitability"):
        if averages[name] < 4.0:
            failures.append(f"{name}_below_4")
    improvement = averages["friendliness"] - baseline["listening"]["rating_averages"]["friendliness"]
    if improvement < 0.5:
        failures.append("friendliness_improvement_below_0.5")
    if not candidate["benchmark"]["complete"] or not candidate["benchmark_rerun_success"]:
        failures.append("benchmark_incomplete")
    if not candidate["resource_limits_met"]:
        failures.append("resource_limits_not_met")
    return failures


def _score_candidates(candidates: list[dict[str, object]]) -> None:
    minima = {
        name: min(candidate["benchmark"][name] for candidate in candidates)
        for name in ("warm_ttfb_p95", "warm_rtf_p95", "peak_ram_p95_mb", "peak_vram_p95_mb")
    }
    for candidate in candidates:
        averages = candidate["listening"]["rating_averages"]
        clarity = sum(averages[name] / 5 * weight for name, weight in SELECTION_WEIGHTS.items() if name.endswith("clarity"))
        friendly = sum(
            averages[name] / 5 * SELECTION_WEIGHTS[name]
            for name in ("naturalness", "friendliness", "store_guidance_suitability")
        )
        performance = (
            minima["warm_ttfb_p95"] / candidate["benchmark"]["warm_ttfb_p95"] * 10
            + minima["warm_rtf_p95"] / candidate["benchmark"]["warm_rtf_p95"] * 10
        )
        resources = (
            minima["peak_ram_p95_mb"] / candidate["benchmark"]["peak_ram_p95_mb"] * 2.5
            + minima["peak_vram_p95_mb"] / candidate["benchmark"]["peak_vram_p95_mb"] * 2.5
        )
        reproducibility = float(sum(candidate["operational_checklist"]))
        candidate["scores"] = {
            "order_information_clarity": clarity,
            "calm_friendly_quality": friendly,
            "response_performance": performance,
            "resource_efficiency": resources,
            "reproducibility_integration": reproducibility,
            "total": clarity + friendly + performance + resources + reproducibility,
        }


def compare_models(
    manifest_path: Path, sentences_path: Path, menu_path: Path, output_path: Path
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(manifest) != {"experiment_id", "author_participant_id", "candidates"}:
        raise ValueError("비교 manifest 최상위 필드 오류")
    candidates = []
    by_id = {}
    for source in manifest["candidates"]:
        required = {
            "candidate_id", "candidate_role", "baseline_candidate_id", "benchmark_path",
            "sim_path", "evaluations", "benchmark_rerun_success", "resource_limits_met",
            "operational_checklist",
        }
        if set(source) != required or source["candidate_role"] not in {"baseline", "finetuned"}:
            raise ValueError("후보 필드 또는 역할 오류")
        if source["candidate_id"] in by_id:
            raise ValueError("candidate_id 중복")
        checklist = source["operational_checklist"]
        if not isinstance(checklist, list) or len(checklist) != 5 or not all(type(x) is bool for x in checklist):
            raise ValueError("운영 체크리스트는 bool 5개여야 함")
        candidate = {
            **source,
            "benchmark_path": str(_absolute_file(source["benchmark_path"], "benchmark_path")),
            "sim_path": str(_absolute_file(source["sim_path"], "sim_path")),
            "evaluations": [
                {
                    "evaluation_path": str(_absolute_file(item["evaluation_path"], "evaluation_path")),
                    "answer_key_path": str(_absolute_file(item["answer_key_path"], "answer_key_path")),
                }
                for item in source["evaluations"]
            ],
            "benchmark": _load_benchmark(_absolute_file(source["benchmark_path"], "benchmark_path")),
            "sim": _load_sim(_absolute_file(source["sim_path"], "sim_path")),
            "listening": _load_listening(
                source["candidate_id"], source["evaluations"], manifest["author_participant_id"],
                sentences_path, menu_path,
            ),
        }
        candidates.append(candidate)
        by_id[source["candidate_id"]] = candidate
    baselines = [candidate for candidate in candidates if candidate["candidate_role"] == "baseline"]
    eligible = [candidate for candidate in candidates if candidate["candidate_role"] == "finetuned"]
    if not baselines or not eligible:
        raise ValueError("baseline과 finetuned 후보가 모두 필요함")
    for candidate in baselines:
        if candidate["baseline_candidate_id"] is not None:
            raise ValueError("baseline의 baseline_candidate_id는 null이어야 함")
    passed = []
    for candidate in eligible:
        baseline = by_id.get(candidate["baseline_candidate_id"])
        if baseline is None or baseline["candidate_role"] != "baseline":
            raise ValueError("finetuned 후보의 baseline 연결 오류")
        candidate["friendliness_improvement"] = (
            candidate["listening"]["rating_averages"]["friendliness"]
            - baseline["listening"]["rating_averages"]["friendliness"]
        )
        candidate["gate_failures"] = _gate_candidate(candidate, baseline)
        candidate["gate_passed"] = not candidate["gate_failures"]
        if candidate["gate_passed"]:
            passed.append(candidate)
    if passed:
        _score_candidates(passed)
        ordered = sorted(passed, key=lambda item: item["scores"]["total"], reverse=True)
        selected = ordered[0]
        status = "SELECTED"
        reason = "highest_total_score"
        if len(ordered) > 1 and ordered[0]["scores"]["total"] - ordered[1]["scores"]["total"] <= 2:
            tied = ordered[:2]
            tie_order = sorted(
                tied,
                key=lambda item: (
                    item["benchmark"]["warm_ttfb_p95"],
                    item["benchmark"]["peak_vram_p95_mb"],
                    -sum(item["operational_checklist"]),
                ),
            )
            first_key = (
                tie_order[0]["benchmark"]["warm_ttfb_p95"],
                tie_order[0]["benchmark"]["peak_vram_p95_mb"],
                sum(tie_order[0]["operational_checklist"]),
            )
            second_key = (
                tie_order[1]["benchmark"]["warm_ttfb_p95"],
                tie_order[1]["benchmark"]["peak_vram_p95_mb"],
                sum(tie_order[1]["operational_checklist"]),
            )
            if first_key == second_key:
                selected, status, reason = None, "WITHHELD_TIE", "tie_breakers_equal"
            else:
                selected, reason = tie_order[0], "tie_breakers"
    else:
        selected, status, reason = None, "WITHHELD", "all_candidates_failed_gates"

    def public(candidate: dict[str, object]) -> dict[str, object]:
        return {
            key: candidate[key]
            for key in (
                "candidate_id", "candidate_role", "baseline_candidate_id",
                "benchmark_path", "sim_path", "evaluations",
                "benchmark", "sim", "listening",
                "benchmark_rerun_success", "resource_limits_met",
                "operational_checklist", "friendliness_improvement", "gate_failures", "gate_passed",
                "scores",
            )
            if key in candidate
        }

    result = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": manifest["experiment_id"],
        "status": status,
        "selected_candidate_id": selected["candidate_id"] if selected else None,
        "selection_reason": reason,
        "candidates": [public(candidate) for candidate in candidates],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="TTS 다중 모델 비교")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--menu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare_models(
        args.manifest.resolve(), args.sentences.resolve(), args.menu.resolve(), args.output.resolve()
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
