import wave
from pathlib import Path

import pytest

from scripts.eval.tts import benchmark

from scripts.eval.tts.benchmark import BackendMeasurement, BenchmarkIdentity, run_benchmark



REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SENTENCES_PATH = REPOSITORY_ROOT / "data/tts/evaluation/sentences.json"
MENU_PATH = REPOSITORY_ROOT / "src/config/menu.json"


class CountingBackend:
    def __init__(self, instances: list["CountingBackend"]) -> None:
        self.calls = 0
        instances.append(self)

    def synthesize_to_file(self, text: str, output_path: Path) -> BackendMeasurement:
        assert text
        self.calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16_000)
            wav.writeframes(b"\0\0" * 1_600)
        return BackendMeasurement(peak_vram_mb=None, vram_reason="unsupported")


def test_benchmark_runs_cold_once_and_warm_five_times_per_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmark, "_git_revision", lambda _: "c" * 40)
    instances: list[CountingBackend] = []
    result = run_benchmark(
        SENTENCES_PATH,
        MENU_PATH,
        tmp_path / "wav",
        tmp_path / "result.json",
        BenchmarkIdentity("test-model", "revision", "cpu", False),
        lambda: CountingBackend(instances),
        REPOSITORY_ROOT,
    )

    assert len(instances) == 20
    assert all(instance.calls == 6 for instance in instances)
    assert len(result["runs"]) == 120
    assert result["summary"]["cold"]["total_runs"] == 20
    assert result["summary"]["warm"]["total_runs"] == 100
    assert result["summary"]["warm"]["successful_runs"] == 100
    assert (tmp_path / "result.json").is_file()
    for run in result["runs"]:
        assert run["generation_latency_seconds"] > 0
        assert run["ttfb_seconds"] == run["generation_latency_seconds"]
        assert run["audio_duration_seconds"] == pytest.approx(0.1)
        assert run["rtf"] > 0
        assert run["peak_ram_mb"] is None or run["peak_ram_mb"] > 0


def test_backend_initialization_failure_is_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmark, "_git_revision", lambda _: "d" * 40)

    def fail() -> CountingBackend:
        raise RuntimeError("model load failed\ninternal detail")

    result = run_benchmark(
        SENTENCES_PATH,
        MENU_PATH,
        tmp_path / "wav",
        tmp_path / "result.json",
        BenchmarkIdentity("broken", "revision", "cuda:0", False),
        fail,
        REPOSITORY_ROOT,
    )
    assert len(result["runs"]) == 120
    assert result["summary"]["cold"]["failed_runs"] == 20
    assert result["summary"]["warm"]["failed_runs"] == 100
    assert all("\n" not in run["error"] for run in result["runs"])


def test_invalid_streaming_first_audio_time_fails_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmark, "_git_revision", lambda _: "e" * 40)

    class InvalidStreamingBackend(CountingBackend):
        def synthesize_to_file(self, text: str, output_path: Path) -> BackendMeasurement:
            super().synthesize_to_file(text, output_path)
            return BackendMeasurement(first_audio_seconds=999.0)

    result = run_benchmark(
        SENTENCES_PATH,
        MENU_PATH,
        tmp_path / "wav",
        tmp_path / "result.json",
        BenchmarkIdentity("streaming", "revision", "cuda:0", True),
        lambda: InvalidStreamingBackend([]),
        REPOSITORY_ROOT,
    )
    assert result["summary"]["cold"]["successful_runs"] == 0
    assert "first_audio_seconds" in result["runs"][0]["error"]


def test_streaming_backend_requires_first_audio_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(benchmark, "_git_revision", lambda _: "f" * 40)
    result = run_benchmark(
        SENTENCES_PATH,
        MENU_PATH,
        tmp_path / "wav",
        tmp_path / "result.json",
        BenchmarkIdentity("streaming", "revision", "cuda:0", True),
        lambda: CountingBackend([]),
        REPOSITORY_ROOT,
    )
    assert result["summary"]["warm"]["successful_runs"] == 0
    assert "제공해야 함" in result["runs"][0]["error"]


def test_nearest_rank_p95() -> None:
    assert benchmark._metric_summary([float(value) for value in range(1, 21)]) == {
        "mean": 10.5,
        "median": 10.5,
        "p95_nearest_rank": 19.0,
    }


def test_peak_ram_mb_and_total_ram_mb_return_none_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(benchmark, "resource", None)
    assert benchmark._peak_ram_mb() is None

    monkeypatch.delattr(benchmark.os, "sysconf", raising=False)
    assert benchmark._total_ram_mb() is None

