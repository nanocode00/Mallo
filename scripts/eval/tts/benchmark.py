"""T-21 문장으로 TTS backend의 latency, TTFB, RTF와 메모리를 측정한다."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

try:
    import resource
except ImportError:  # Windows 등 미지원 플랫폼
    resource = None  # type: ignore[assignment]

from scripts.eval.tts.evaluation_sentences import load_and_validate



@dataclass(frozen=True)
class BenchmarkIdentity:
    model_id: str
    model_revision: str
    device: str
    streaming: bool


@dataclass(frozen=True)
class BackendMeasurement:
    first_audio_seconds: float | None = None
    peak_vram_mb: float | None = None
    vram_reason: str | None = "unsupported"


class BenchmarkBackend(Protocol):
    def synthesize_to_file(self, text: str, output_path: Path) -> BackendMeasurement: ...


BackendFactory = Callable[[], BenchmarkBackend]


def _peak_ram_mb() -> float | None:
    if resource is not None:
        try:
            value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            return value / (1024 * 1024 if sys.platform == "darwin" else 1024)
        except (AttributeError, OSError, ValueError):
            pass
    return None


def _total_ram_mb() -> float | None:
    try:
        if hasattr(os, "sysconf"):
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 * 1024)
    except (AttributeError, OSError, ValueError):
        pass
    return None


def _git_revision(repository_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _wav_duration_seconds(path: Path) -> float:
    if not path.is_file():
        raise ValueError("합성 WAV가 생성되지 않음")
    try:
        with wave.open(str(path), "rb") as wav:
            sample_rate = wav.getframerate()
            if sample_rate <= 0 or wav.getnframes() <= 0:
                raise ValueError("합성 WAV 길이가 0초임")
            return wav.getnframes() / sample_rate
    except (EOFError, wave.Error) as error:
        raise ValueError("합성 WAV decode 실패") from error


def _error_message(error: Exception) -> str:
    message = " ".join(str(error).split())
    return f"{type(error).__name__}: {message}"[:500]


def _measure_run(
    backend: BenchmarkBackend,
    text: str,
    output_path: Path,
    phase: str,
    repeat: int,
    sentence_id: str,
    streaming: bool,
    started_at: float,
    setup_seconds: float,
    clock: Callable[[], float],
) -> dict[str, object]:
    try:
        measurement = backend.synthesize_to_file(text, output_path)
        finished_at = clock()
        latency = finished_at - started_at
        synthesis_seconds = latency - setup_seconds
        duration = _wav_duration_seconds(output_path)
        if streaming and measurement.first_audio_seconds is None:
            raise ValueError("streaming backend는 first_audio_seconds를 제공해야 함")
        if measurement.first_audio_seconds is not None and not (
            0 <= measurement.first_audio_seconds <= synthesis_seconds
        ):
            raise ValueError("first_audio_seconds가 합성 시간 범위를 벗어남")
        ttfb = (
            setup_seconds + measurement.first_audio_seconds
            if streaming and measurement.first_audio_seconds is not None
            else latency
        )
        if measurement.peak_vram_mb is not None and measurement.peak_vram_mb < 0:
            raise ValueError("peak_vram_mb는 음수일 수 없음")
        return {
            "sentence_id": sentence_id,
            "text": text,
            "phase": phase,
            "repeat": repeat,
            "status": "success",
            "output_path": str(output_path.resolve()),
            "generation_latency_seconds": latency,
            "ttfb_seconds": ttfb,
            "audio_duration_seconds": duration,
            "rtf": latency / duration,
            "peak_ram_mb": _peak_ram_mb(),
            "peak_vram_mb": measurement.peak_vram_mb,
            "vram_reason": None if measurement.peak_vram_mb is not None else measurement.vram_reason,
            "error": None,
        }
    except Exception as error:
        return {
            "sentence_id": sentence_id,
            "text": text,
            "phase": phase,
            "repeat": repeat,
            "status": "failure",
            "output_path": str(output_path.resolve()),
            "generation_latency_seconds": None,
            "ttfb_seconds": None,
            "audio_duration_seconds": None,
            "rtf": None,
            "peak_ram_mb": _peak_ram_mb(),
            "peak_vram_mb": None,
            "vram_reason": "measurement_failed",
            "error": _error_message(error),
        }


def _skipped_run(
    sentence_id: str, text: str, repeat: int, output_path: Path, error: Exception
) -> dict[str, object]:
    return {
        "sentence_id": sentence_id,
        "text": text,
        "phase": "warm",
        "repeat": repeat,
        "status": "failure",
        "output_path": str(output_path.resolve()),
        "generation_latency_seconds": None,
        "ttfb_seconds": None,
        "audio_duration_seconds": None,
        "rtf": None,
        "peak_ram_mb": _peak_ram_mb(),
        "peak_vram_mb": None,
        "vram_reason": "backend_initialization_failed",
        "error": _error_message(error),
    }


def _metric_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return {
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "p95_nearest_rank": ordered[rank - 1],
    }


def _summarize(runs: list[dict[str, object]], phase: str) -> dict[str, object]:
    selected = [run for run in runs if run["phase"] == phase]
    successful = [run for run in selected if run["status"] == "success"]
    metrics = {}
    for name in (
        "generation_latency_seconds",
        "ttfb_seconds",
        "audio_duration_seconds",
        "rtf",
        "peak_ram_mb",
        "peak_vram_mb",
    ):
        metrics[name] = _metric_summary(
            [float(run[name]) for run in successful if run[name] is not None]
        )
    return {
        "total_runs": len(selected),
        "successful_runs": len(successful),
        "failed_runs": len(selected) - len(successful),
        "success_rate": len(successful) / len(selected) if selected else 0.0,
        "metrics": metrics,
    }


def run_benchmark(
    sentences_path: Path,
    menu_path: Path,
    output_root: Path,
    result_path: Path,
    identity: BenchmarkIdentity,
    backend_factory: BackendFactory,
    repository_root: Path,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, object]:
    sentences = load_and_validate(sentences_path, menu_path)
    output_root.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, object]] = []
    for sentence in sentences:
        sentence_id = str(sentence["id"])
        text = str(sentence["text"])
        sentence_dir = output_root / sentence_id
        sentence_dir.mkdir(parents=True, exist_ok=True)
        cold_started = clock()
        try:
            backend = backend_factory()
            setup_seconds = clock() - cold_started
        except Exception as error:
            cold_path = sentence_dir / "cold_1.wav"
            runs.append(
                {
                    **_skipped_run(sentence_id, text, 1, cold_path, error),
                    "phase": "cold",
                }
            )
            for repeat in range(1, 6):
                runs.append(
                    _skipped_run(
                        sentence_id, text, repeat, sentence_dir / f"warm_{repeat}.wav", error
                    )
                )
            continue
        runs.append(
            _measure_run(
                backend,
                text,
                sentence_dir / "cold_1.wav",
                "cold",
                1,
                sentence_id,
                identity.streaming,
                cold_started,
                setup_seconds,
                clock,
            )
        )
        for repeat in range(1, 6):
            started = clock()
            runs.append(
                _measure_run(
                    backend,
                    text,
                    sentence_dir / f"warm_{repeat}.wav",
                    "warm",
                    repeat,
                    sentence_id,
                    identity.streaming,
                    started,
                    0.0,
                    clock,
                )
            )

    result = {
        "schema_version": "1.0",
        "experiment": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_revision": _git_revision(repository_root),
            "sentences_path": str(sentences_path.resolve()),
            "sentence_count": len(sentences),
            "cold_repeats_per_sentence": 1,
            "warm_repeats_per_sentence": 5,
            "p95_method": "nearest_rank",
        },
        "environment": {
            "os": platform.platform(),
            "cpu": platform.processor() or platform.machine(),
            "total_ram_mb": _total_ram_mb(),
            "python": platform.python_version(),
        },
        "model": asdict(identity),
        "runs": runs,
        "summary": {
            "cold": _summarize(runs, "cold"),
            "warm": _summarize(runs, "warm"),
        },
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


class FixtureWavBackend:
    """측정 파이프라인 smoke test용 결정론적 non-streaming backend."""

    def synthesize_to_file(self, text: str, output_path: Path) -> BackendMeasurement:
        del text
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16_000)
            wav.writeframes(b"\0\0" * 1_600)
        return BackendMeasurement()


def main() -> None:
    parser = argparse.ArgumentParser(description="TTS Benchmark fixture smoke test")
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--menu", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[3]
    result = run_benchmark(
        args.sentences.resolve(),
        args.menu.resolve(),
        args.output_root.resolve(),
        args.result.resolve(),
        BenchmarkIdentity("fixture-wav", "1", "cpu", False),
        FixtureWavBackend,
        repository_root,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
