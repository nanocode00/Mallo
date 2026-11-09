from pathlib import Path

from scripts.showcase.build_stt_offline_showcase import _build_html, _comparison, _input_wavs
import io
import json

import numpy as np
import soundfile as sf

from domain.tts_result import TTSResult
from scripts.showcase.build_tts_offline_showcase import SAMPLES, _render_page, build_adaptive_showcase
from src.domain.korean_normalizer import normalize_korean_text_for_tts


def test_stt_html_uses_only_relative_audio_paths(tmp_path: Path) -> None:
    wav = tmp_path / "sample.wav"
    wav.write_bytes(b"RIFF")
    assert _input_wavs([wav]) == [wav.resolve()]
    page = _build_html(
        [{"filename": "sample.wav", "audio_file": "audio/01-sample.wav", "reference": "주문", "transcript": "주문", "comparison": "일치"}],
        "models/stt/final-train65-merged-bf16",
    )
    assert 'src="audio/01-sample.wav"' in page
    assert "localhost" not in page
    assert "http://" not in page
    assert "https://" not in page
    assert "실제 발화" in page
    assert _comparison("바닐라라떼 세 잔", "바닐라 라떼 3잔") == "일치"
    assert _comparison("아이스 카페라떼", "아이스틸 카페 라떼") == "오류"


def test_tts_representative_samples_have_quantity_and_price_normalization() -> None:
    normalized = [normalize_korean_text_for_tts(item["original"]) for item in SAMPLES]
    assert "두 잔" in normalized[0]
    assert "만 오천백원" in normalized[0]
    assert "오천이백원" in normalized[2]
    page = _render_page("test", "desc", ["<article>ok</article>"])
    assert "localhost" not in page
    assert "http://" not in page
    assert "https://" not in page


class _FakeAdapter:
    def synthesize(self, text: str, level: int = 0) -> TTSResult:
        buffer = io.BytesIO()
        # A deterministic, valid mono WAV makes inserted silence measurable.
        sf.write(buffer, np.ones(800, dtype="float32") * (level + 1) / 10, 8000, format="WAV")
        return TTSResult(text=text, level=level, sample_rate=8000, audio=buffer.getvalue())


def test_adaptive_showcase_uses_production_chunks_and_preserves_model_metadata(tmp_path: Path) -> None:
    output = tmp_path / "tts"
    audio = output / "audio"
    audio.mkdir(parents=True)
    model_comparison = [{"id": "unchanged", "voices": [{"audio_file": "audio/model.wav"}]}]
    (output / "results.json").write_text(json.dumps({"model_comparison": model_comparison}), encoding="utf-8")
    model_page = output / "model-comparison.html"
    model_page.write_text("do not change", encoding="utf-8")

    rows = build_adaptive_showcase(
        output, adapter=_FakeAdapter(), write_speed_levels_html=True,
    )

    metadata = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert metadata["model_comparison"] == model_comparison
    assert model_page.read_text(encoding="utf-8") == "do not change"
    assert metadata["adaptive_policy"]["levels"]["1"]["gap_ms"] == 280
    assert metadata["adaptive_policy"]["levels"]["2"]["speed"] == 0.75
    assert len(rows) == 3
    assert all(level["chunks"] for row in rows for level in row["levels"])
    assert all((audio / Path(level["audio_file"]).name).is_file() for row in rows for level in row["levels"])

    level_1 = rows[0]["levels"][1]
    wav, rate = sf.read(audio / "speed-quantity-price-level-1.wav")
    expected_gap_frames = round(rate * level_1["gap_ms"] / 1000)
    assert level_1["silence_duration_s"] == 0.28 * (len(level_1["chunks"]) - 1)
    assert expected_gap_frames > 0
    assert (wav == 0).sum() >= expected_gap_frames

    page = (output / "speed-levels.html").read_text(encoding="utf-8")
    assert "1.00x" in page
    assert "0.75x" in page
    assert "0.70x" not in page
    assert "audio/speed-quantity-price-level-1.wav" in page


def test_adaptive_generation_does_not_replace_curated_speed_levels_html_by_default(tmp_path: Path) -> None:
    output = tmp_path / "tts"
    (output / "audio").mkdir(parents=True)
    (output / "results.json").write_text(json.dumps({"model_comparison": []}), encoding="utf-8")
    curated_page = output / "speed-levels.html"
    curated_page.write_text("<html>curated UI</html>", encoding="utf-8")

    build_adaptive_showcase(output, adapter=_FakeAdapter())

    assert curated_page.read_text(encoding="utf-8") == "<html>curated UI</html>"
