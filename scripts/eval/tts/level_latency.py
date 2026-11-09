"""T-12 Adaptive TTS Level 0/1 합성 지연 비교 실행기."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from scripts.eval.tts.evaluation_sentences import load_and_validate
from adapters.tts.melotts_adapter import MeloTTSAdapter
from domain.text_transformer import AdaptiveTextTransformer
from domain.tts_result import TTSResult


class LevelTTS(Protocol):
    def synthesize(self, text: str, level: int = 0) -> TTSResult: ...


def _metric(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return {
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "p95_nearest_rank": ordered[rank - 1],
    }


def _summary(runs: list[dict[str, object]], level: int) -> dict[str, object]:
    selected = [run for run in runs if run["level"] == level]
    successful = [run for run in selected if run["status"] == "success"]
    return {
        "total_runs": len(selected),
        "successful_runs": len(successful),
        "failed_runs": len(selected) - len(successful),
        "latency_ms": _metric([float(run["latency_ms"]) for run in successful]),
        "rtf": _metric([float(run["rtf"]) for run in successful]),
    }


def _comparison(level_0: dict[str, object], level_1: dict[str, object]) -> dict[str, float]:
    result: dict[str, float] = {}
    for metric in ("latency_ms", "rtf"):
        for statistic in ("mean", "median", "p95_nearest_rank"):
            baseline_metrics = level_0[metric]
            adaptive_metrics = level_1[metric]
            if not isinstance(baseline_metrics, dict) or not isinstance(adaptive_metrics, dict):
                raise ValueError("Level별 성공 측정값이 있어야 비교할 수 있음")
            baseline = float(baseline_metrics[statistic])
            adaptive = float(adaptive_metrics[statistic])
            if baseline <= 0:
                raise ValueError(f"Level 0 {metric}.{statistic}은 0보다 커야 함")
            key = f"{metric}_{statistic}"
            result[f"{key}_delta"] = adaptive - baseline
            result[f"{key}_ratio"] = adaptive / baseline
    return result


def _git_revision(repository_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def run_level_latency_comparison(
    tts: LevelTTS,
    sentences_path: Path,
    menu_path: Path,
    result_path: Path,
    repository_root: Path,
    model_id: str,
    model_revision: str,
    device: str,
    repeats: int = 5,
) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats는 1 이상이어야 함")
    sentences = load_and_validate(sentences_path, menu_path)

    for level in (0, 1):
        warmup_text = AdaptiveTextTransformer.transform("워밍업 안내입니다.", level)
        warmup = tts.synthesize(warmup_text, level)
        if not warmup.audio or warmup.duration_ms <= 0:
            raise ValueError(f"Level {level} warm-up 합성 실패")

    runs: list[dict[str, object]] = []
    for sentence_index, sentence in enumerate(sentences):
        original_text = str(sentence["text"])
        for repeat in range(1, repeats + 1):
            first_level = (sentence_index + repeat) % 2
            for level in (first_level, 1 - first_level):
                transformed = AdaptiveTextTransformer.transform(original_text, level)
                try:
                    synthesized = tts.synthesize(transformed, level)
                    if not synthesized.audio or synthesized.duration_ms <= 0:
                        raise ValueError("빈 오디오 또는 0ms 음성 길이")
                    runs.append(
                        {
                            "sentence_id": str(sentence["id"]),
                            "repeat": repeat,
                            "level": level,
                            "status": "success",
                            "transformed_text": transformed,
                            "latency_ms": synthesized.latency_ms,
                            "duration_ms": synthesized.duration_ms,
                            "rtf": synthesized.latency_ms / synthesized.duration_ms,
                            "error": None,
                        }
                    )
                except Exception as error:
                    runs.append(
                        {
                            "sentence_id": str(sentence["id"]),
                            "repeat": repeat,
                            "level": level,
                            "status": "failure",
                            "transformed_text": transformed,
                            "latency_ms": None,
                            "duration_ms": None,
                            "rtf": None,
                            "error": f"{type(error).__name__}: {' '.join(str(error).split())}"[:500],
                        }
                    )

    level_0 = _summary(runs, 0)
    level_1 = _summary(runs, 1)
    expected_successes = len(sentences) * repeats
    completed = (
        level_0["successful_runs"] == expected_successes
        and level_1["successful_runs"] == expected_successes
    )
    result = {
        "schema_version": "1.0",
        "experiment": {
            "ticket": "T-12",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_revision": _git_revision(repository_root),
            "sentence_count": len(sentences),
            "levels": [0, 1],
            "warmup_runs_per_level": 1,
            "repeats_per_sentence_level": repeats,
            "order_policy": "alternating_by_sentence_and_repeat",
            "p95_method": "nearest_rank",
        },
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "model_id": model_id,
            "model_revision": model_revision,
            "device": device,
        },
        "runs": runs,
        "summary": {
            "completed": completed,
            "level_0": level_0,
            "level_1": level_1,
            "level_1_vs_level_0": _comparison(level_0, level_1) if completed else None,
        },
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="T-12 Level 0/1 latency 비교")
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--menu", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--speaker", default="10")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[3]
    result = run_level_latency_comparison(
        MeloTTSAdapter(
            device=args.device,
            config_path=args.config.resolve(),
            ckpt_path=args.checkpoint.resolve(),
            speaker=args.speaker,
        ),
        args.sentences.resolve(),
        args.menu.resolve(),
        args.result.resolve(),
        repository_root,
        "MeloTTS Friendly",
        str(args.checkpoint.resolve()),
        args.device,
        args.repeats,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
