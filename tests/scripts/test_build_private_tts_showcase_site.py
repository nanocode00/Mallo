from pathlib import Path

import pytest

from scripts.showcase.build_private_tts_showcase_site import Showcase, extract_showcase


WAV_DATA_URI = "data:audio/wav;base64,UklGRg=="


def test_extract_showcase_separates_audio_and_uses_relative_path(tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    source.write_text(
        f'<html><body><audio controls src="{WAV_DATA_URI}"></audio></body></html>',
        encoding="utf-8",
    )
    output = tmp_path / "site"

    count = extract_showcase(Showcase("demo", "Demo", source), output)

    converted = (output / "demo.html").read_text(encoding="utf-8")
    assert count == 1
    assert "data:audio" not in converted
    assert 'src="assets/audio/demo/audio-001.wav"' in converted
    assert 'href="./"' in converted
    assert 'aria-label="쇼케이스 홈으로 돌아가기"' in converted
    assert "← 쇼케이스 홈" in converted
    assert (output / "assets/audio/demo/audio-001.wav").read_bytes() == b"RIFF"


def test_extract_showcase_rejects_html_without_embedded_audio(tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    source.write_text("<p>오디오 없음</p>", encoding="utf-8")

    with pytest.raises(ValueError, match="Base64 WAV가 없습니다"):
        extract_showcase(Showcase("demo", "Demo", source), tmp_path / "site")


def test_extract_showcase_rejects_html_without_body(tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    source.write_text(f'<audio src="{WAV_DATA_URI}"></audio>', encoding="utf-8")

    with pytest.raises(ValueError, match="<body> 태그가 없습니다"):
        extract_showcase(Showcase("demo", "Demo", source), tmp_path / "site")
