import wave
from pathlib import Path
import pytest
from scripts.eval.tts.eval_synthesis import (
    load_evaluation_sentences,
    run_evaluation_synthesis,
    save_summary_report,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SENTENCES_PATH = REPOSITORY_ROOT / "data/tts/evaluation/sentences.json"


class MockTTSBackend:
    """테스트용 Mock TTS 백엔드."""

    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self.call_count = 0

    def synthesize(self, text: str, output_path: Path) -> tuple[int, int]:
        self.call_count += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        num_samples = len(text) * 1600  # 0.1초 * 글자수
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(b"\0\0" * num_samples)
        return self.sample_rate, num_samples


def test_load_evaluation_sentences():
    sentences = load_evaluation_sentences(SENTENCES_PATH)
    assert len(sentences) == 20
    assert sentences[0]["id"] == "tts_eval_01"
    assert "text" in sentences[0]


def test_run_evaluation_synthesis(tmp_path: Path):
    sentences = load_evaluation_sentences(SENTENCES_PATH)
    backend = MockTTSBackend()
    out_dir = tmp_path / "mock_eval"

    summary = run_evaluation_synthesis(
        backend=backend,
        sentences=sentences,
        output_dir=out_dir,
        model_name="MockTTS",
        device="cpu",
    )

    assert summary.model_name == "MockTTS"
    assert summary.total_sentences == 20
    assert len(summary.results) == 20
    assert summary.mean_latency_seconds >= 0
    assert summary.mean_rtf >= 0
    assert summary.sample_rate == 16000

    # 20개 WAV 파일 생성 검증
    for r in summary.results:
        wav = Path(r.wav_path)
        assert wav.is_file()
        assert wav.stat().st_size > 0

    # Report JSON 저장 검증
    report_path = out_dir / "summary.json"
    save_summary_report(summary, report_path)
    assert report_path.is_file()


def test_resolve_speaker_id_dict_mappings():
    from types import SimpleNamespace
    from scripts.eval.tts.eval_synthesis import _resolve_speaker_id

    # 1) dict with "10"
    assert _resolve_speaker_id({"10": 0, "KR": 1}, speaker="10") == 0
    assert _resolve_speaker_id({"10": 3, "KR": 0}) == 3

    # 2) dict with "KR" only
    assert _resolve_speaker_id({"KR": 2}, speaker="10") == 2
    assert _resolve_speaker_id({"KR": 1}, speaker="KR") == 1

    # 3) custom speaker
    assert _resolve_speaker_id({"custom_spk": 7, "10": 0}, speaker="custom_spk") == 7

    # 4) SimpleNamespace / object
    ns = SimpleNamespace()
    setattr(ns, "10", 4)
    assert _resolve_speaker_id(ns, speaker="10") == 4

    ns_kr = SimpleNamespace()
    setattr(ns_kr, "KR", 5)
    assert _resolve_speaker_id(ns_kr, speaker="10") == 5

    # 5) Empty / unknown fallback to 0
    assert _resolve_speaker_id({}, speaker="10") == 0
    assert _resolve_speaker_id(None, speaker="10") == 0
