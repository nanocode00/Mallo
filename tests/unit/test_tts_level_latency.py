from pathlib import Path

import pytest

from scripts.eval.tts import level_latency
from scripts.eval.tts.level_latency import run_level_latency_comparison
from domain.tts_result import TTSResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class RecordingTTS:
    def __init__(self, fail_level: int | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail_level = fail_level

    def synthesize(self, text: str, level: int = 0) -> TTSResult:
        self.calls.append((text, level))
        if self.fail_level == level and len(self.calls) > 2:
            raise RuntimeError("synthesis failed")
        latency_ms = 10.0 if level == 0 else 12.0
        return TTSResult(
            text=text,
            level=level,
            sample_rate=16_000,
            duration_ms=100.0,
            latency_ms=latency_ms,
            audio=b"RIFF-valid-fixture",
        )


def _run(tmp_path: Path, tts: RecordingTTS, repeats: int = 5) -> dict[str, object]:
    return run_level_latency_comparison(
        tts,
        REPOSITORY_ROOT / "data/tts/evaluation/sentences.json",
        REPOSITORY_ROOT / "src/config/menu.json",
        tmp_path / "result.json",
        REPOSITORY_ROOT,
        "fixture",
        "1",
        "cpu",
        repeats,
    )


def test_level_latency_uses_same_20_sentences_five_times_per_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(level_latency, "_git_revision", lambda _: "a" * 40)
    tts = RecordingTTS()
    result = _run(tmp_path, tts)

    assert len(result["runs"]) == 200
    assert result["summary"]["level_0"]["successful_runs"] == 100
    assert result["summary"]["level_1"]["successful_runs"] == 100
    assert len(tts.calls) == 202  # Level별 warm-up 1회 포함
    assert (tmp_path / "result.json").is_file()


def test_level_latency_transforms_text_and_alternates_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(level_latency, "_git_revision", lambda _: "b" * 40)
    tts = RecordingTTS()
    result = _run(tmp_path, tts, repeats=2)
    runs = result["runs"]

    assert [run["level"] for run in runs[:4]] == [1, 0, 0, 1]
    assert all(text == run["transformed_text"] and level == run["level"] for (text, level), run in zip(tts.calls[2:], runs))


def test_level_latency_calculates_delta_ratio_and_nearest_rank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(level_latency, "_git_revision", lambda _: "c" * 40)
    result = _run(tmp_path, RecordingTTS(), repeats=1)
    comparison = result["summary"]["level_1_vs_level_0"]

    assert comparison["latency_ms_mean_delta"] == pytest.approx(2.0)
    assert comparison["latency_ms_mean_ratio"] == pytest.approx(1.2)
    assert result["summary"]["level_0"]["latency_ms"]["p95_nearest_rank"] == 10.0


def test_level_latency_preserves_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(level_latency, "_git_revision", lambda _: "d" * 40)
    result = _run(tmp_path, RecordingTTS(fail_level=1), repeats=1)

    assert result["summary"]["level_1"]["failed_runs"] == 20
    assert result["summary"]["completed"] is False
    assert result["summary"]["level_1_vs_level_0"] is None
    assert all("RuntimeError" in run["error"] for run in result["runs"] if run["level"] == 1)
