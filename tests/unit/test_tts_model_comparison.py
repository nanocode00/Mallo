import csv
import json
import wave
from pathlib import Path

import pytest

from scripts.eval.tts.listening_evaluation import EVALUATION_COLUMNS, create_listening_package
from scripts.eval.tts.model_comparison import compare_models


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SENTENCES_PATH = REPOSITORY_ROOT / "data/tts/evaluation/sentences.json"
MENU_PATH = REPOSITORY_ROOT / "src/config/menu.json"
CANDIDATES = ("baseline", "finetuned-a", "finetuned-b")


def _write_wav(path: Path, marker: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(bytes([marker, 0]) * 800)


def _write_benchmark(path: Path, ttfb: float, rtf: float, ram: float, vram: float) -> None:
    def metric(value: float) -> dict[str, float]:
        return {"mean": value, "median": value, "p95_nearest_rank": value}

    payload = {
        "summary": {
            "cold": {"successful_runs": 20},
            "warm": {
                "successful_runs": 100,
                "metrics": {
                    "ttfb_seconds": metric(ttfb),
                    "rtf": metric(rtf),
                    "peak_ram_mb": metric(ram),
                    "peak_vram_mb": metric(vram),
                },
            },
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_sim(path: Path, value: float) -> None:
    path.write_text(
        json.dumps(
            {
                "encoder_id": "speechbrain/ecapa",
                "encoder_revision": "fixed-revision",
                "reference_count": 3,
                "sentence_scores": {
                    f"tts_eval_{index:02d}": value for index in range(1, 21)
                },
            }
        ),
        encoding="utf-8",
    )


def _complete_evaluation(package: Path, scores: dict[str, str]) -> None:
    with (package / "answer-key.tsv").open(encoding="utf-8", newline="") as source:
        answers = {row["sample_id"]: row for row in csv.DictReader(source, delimiter="\t")}
    with (package / "evaluation.tsv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    for row in rows:
        candidate_id = answers[row["sample_id"]]["candidate_id"]
        score = scores[candidate_id]
        for column in (
            "naturalness",
            "overall_clarity",
            "friendliness",
            "menu_name_clarity",
            "quantity_unit_clarity",
            "price_clarity",
            "store_guidance_suitability",
        ):
            if row[column] != "NA":
                row[column] = score
        row["critical_information_success"] = "yes"
        row["serious_misread_or_corruption"] = "no"
    with (package / "evaluation.tsv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target, fieldnames=EVALUATION_COLUMNS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def comparison_inputs(tmp_path: Path) -> dict[str, Path]:
    sentence_ids = [f"tts_eval_{index:02d}" for index in range(1, 21)]
    sample_candidates = []
    for candidate_index, candidate_id in enumerate(CANDIDATES, start=1):
        samples = []
        for sentence_index, sentence_id in enumerate(sentence_ids, start=1):
            audio = (tmp_path / "wav" / candidate_id / f"{sentence_id}.wav").resolve()
            _write_wav(audio, candidate_index + sentence_index)
            samples.append({"sentence_id": sentence_id, "audio_path": str(audio)})
        sample_candidates.append({"candidate_id": candidate_id, "samples": samples})
    samples_path = (tmp_path / "samples.json").resolve()
    samples_path.write_text(
        json.dumps({"experiment_id": "comparison-001", "candidates": sample_candidates}),
        encoding="utf-8",
    )

    evaluations = []
    for participant in ("p1", "p2", "p3"):
        package = (tmp_path / participant).resolve()
        create_listening_package(
            samples_path, SENTENCES_PATH, MENU_PATH, package, participant, seed=42
        )
        _complete_evaluation(
            package, {"baseline": "3", "finetuned-a": "5", "finetuned-b": "4"}
        )
        evaluations.append(
            {
                "evaluation_path": str(package / "evaluation.tsv"),
                "answer_key_path": str(package / "answer-key.tsv"),
            }
        )

    candidate_rows = []
    benchmark_values = {
        "baseline": (0.5, 0.5, 1000.0, 4000.0),
        "finetuned-a": (0.4, 0.4, 1200.0, 5000.0),
        "finetuned-b": (0.3, 0.3, 900.0, 3500.0),
    }
    for candidate_id in CANDIDATES:
        benchmark = (tmp_path / f"{candidate_id}-benchmark.json").resolve()
        sim = (tmp_path / f"{candidate_id}-sim.json").resolve()
        _write_benchmark(benchmark, *benchmark_values[candidate_id])
        _write_sim(sim, 0.7)
        role = "baseline" if candidate_id == "baseline" else "finetuned"
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_role": role,
                "baseline_candidate_id": None if role == "baseline" else "baseline",
                "benchmark_path": str(benchmark),
                "sim_path": str(sim),
                "evaluations": evaluations,
                "benchmark_rerun_success": True,
                "resource_limits_met": True,
                "operational_checklist": [True, True, True, True, True],
            }
        )
    manifest = (tmp_path / "comparison.json").resolve()
    manifest.write_text(
        json.dumps(
            {
                "experiment_id": "comparison-001",
                "author_participant_id": "author",
                "candidates": candidate_rows,
            }
        ),
        encoding="utf-8",
    )
    return {"manifest": manifest, "output": (tmp_path / "result.json").resolve()}


def test_selects_highest_scoring_candidate(comparison_inputs: dict[str, Path]) -> None:
    result = compare_models(
        comparison_inputs["manifest"], SENTENCES_PATH, MENU_PATH, comparison_inputs["output"]
    )
    assert result["status"] == "SELECTED"
    assert result["selected_candidate_id"] == "finetuned-a"
    candidates = {item["candidate_id"]: item for item in result["candidates"]}
    assert "scores" not in candidates["baseline"]
    assert candidates["finetuned-a"]["gate_passed"] is True
    assert candidates["finetuned-a"]["scores"]["total"] <= 100
    assert candidates["finetuned-a"]["sim"]["mean"] == pytest.approx(0.7)
    assert Path(candidates["finetuned-a"]["benchmark_path"]).is_file()
    assert Path(candidates["finetuned-a"]["sim_path"]).is_file()
    assert len(candidates["finetuned-a"]["evaluations"]) == 3


def test_withholds_when_all_candidates_fail_resource_gate(
    comparison_inputs: dict[str, Path]
) -> None:
    payload = json.loads(comparison_inputs["manifest"].read_text(encoding="utf-8"))
    for candidate in payload["candidates"]:
        if candidate["candidate_role"] == "finetuned":
            candidate["resource_limits_met"] = False
    comparison_inputs["manifest"].write_text(json.dumps(payload), encoding="utf-8")
    result = compare_models(
        comparison_inputs["manifest"], SENTENCES_PATH, MENU_PATH, comparison_inputs["output"]
    )
    assert result["status"] == "WITHHELD"
    assert result["selected_candidate_id"] is None


def test_rejects_author_as_final_evaluator(comparison_inputs: dict[str, Path]) -> None:
    payload = json.loads(comparison_inputs["manifest"].read_text(encoding="utf-8"))
    payload["author_participant_id"] = "p1"
    comparison_inputs["manifest"].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="작성자"):
        compare_models(
            comparison_inputs["manifest"], SENTENCES_PATH, MENU_PATH, comparison_inputs["output"]
        )


def test_withholds_when_scores_and_tie_breakers_are_equal(
    comparison_inputs: dict[str, Path]
) -> None:
    payload = json.loads(comparison_inputs["manifest"].read_text(encoding="utf-8"))
    candidates = {item["candidate_id"]: item for item in payload["candidates"]}
    candidates["finetuned-b"]["benchmark_path"] = candidates["finetuned-a"]["benchmark_path"]
    comparison_inputs["manifest"].write_text(json.dumps(payload), encoding="utf-8")
    for participant in ("p1", "p2", "p3"):
        package = comparison_inputs["manifest"].parent / participant
        _complete_evaluation(
            package, {"baseline": "3", "finetuned-a": "5", "finetuned-b": "5"}
        )
    result = compare_models(
        comparison_inputs["manifest"], SENTENCES_PATH, MENU_PATH, comparison_inputs["output"]
    )
    assert result["status"] == "WITHHELD_TIE"
    assert result["selected_candidate_id"] is None
