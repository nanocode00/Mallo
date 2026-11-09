#!/usr/bin/env python3
"""Base64가 내장된 TTS 쇼케이스를 내부 공유용 정적 사이트로 변환한다."""

from __future__ import annotations

import argparse
import base64
import binascii
import html
import re
from dataclasses import dataclass
from pathlib import Path


AUDIO_DATA_URI = re.compile(
    r"data:audio/(?P<format>wav|wave);base64,(?P<payload>[A-Za-z0-9+/=]+)"
)
BACK_LINK = (
    '<a href="./" aria-label="쇼케이스 홈으로 돌아가기" '
    'style="display:inline-flex;align-items:center;gap:6px;margin:0 0 18px;'
    'padding:8px 12px;color:#e0f2fe;background:#1e293b;border:1px solid #475569;'
    'border-radius:8px;text-decoration:none;font-weight:600">← 쇼케이스 홈</a>'
)


@dataclass(frozen=True)
class Showcase:
    slug: str
    title: str
    source: Path


def extract_showcase(showcase: Showcase, output_dir: Path) -> int:
    if not showcase.source.is_file():
        raise FileNotFoundError(f"입력 쇼케이스를 찾을 수 없습니다: {showcase.source}")

    source_html = showcase.source.read_text(encoding="utf-8")
    audio_dir = output_dir / "assets" / "audio" / showcase.slug
    audio_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0

    def replace_audio(match: re.Match[str]) -> str:
        nonlocal extracted
        extracted += 1
        filename = f"audio-{extracted:03d}.wav"
        try:
            wav = base64.b64decode(match.group("payload"), validate=True)
        except binascii.Error as exc:
            raise ValueError(
                f"손상된 Base64 오디오입니다: {showcase.source} #{extracted}"
            ) from exc
        (audio_dir / filename).write_bytes(wav)
        return f"assets/audio/{showcase.slug}/{filename}"

    converted_html = AUDIO_DATA_URI.sub(replace_audio, source_html)
    if extracted == 0:
        raise ValueError(f"Base64 WAV가 없습니다: {showcase.source}")
    if "<body>" not in converted_html:
        raise ValueError(f"<body> 태그가 없습니다: {showcase.source}")
    converted_html = converted_html.replace("<body>", f"<body>\n    {BACK_LINK}", 1)

    (output_dir / f"{showcase.slug}.html").write_text(
        converted_html, encoding="utf-8"
    )
    return extracted


def build_index(showcases: list[Showcase], output_dir: Path) -> None:
    cards = "\n".join(
        f'<a class="card" href="{html.escape(item.slug)}.html">'
        f"<strong>{html.escape(item.title)}</strong>"
        "<span>쇼케이스 열기 →</span></a>"
        for item in showcases
    )
    index = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>말로 TTS 쇼케이스</title>
  <style>
    body {{ margin: 0; padding: 48px 24px; font-family: system-ui, sans-serif;
      color: #f8fafc; background: #0b1120; }}
    main {{ max-width: 760px; margin: auto; }}
    h1 {{ color: #38bdf8; }}
    p {{ color: #94a3b8; }}
    .grid {{ display: grid; gap: 16px; margin-top: 28px; }}
    .card {{ display: flex; justify-content: space-between; gap: 16px;
      padding: 22px; color: #f8fafc; text-decoration: none; background: #1e293b;
      border: 1px solid #334155; border-radius: 12px; }}
    .card:hover {{ border-color: #38bdf8; }}
    .card span {{ color: #7dd3fc; }}
  </style>
</head>
<body><main>
  <h1>말로 TTS 쇼케이스</h1>
  <p>TTS 모델별 결과와 Adaptive TTS Level 0·1·2를 비교 청음합니다.</p>
  <div class="grid">{cards}</div>
</main></body>
</html>
"""
    (output_dir / "index.html").write_text(index, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Standalone TTS 쇼케이스를 HTML/WAV 분리형 정적 사이트로 변환"
    )
    parser.add_argument(
        "--showcase-dir", type=Path, default=Path("artifacts/showcase/legacy/tts")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/showcase/legacy/tts/private-site"),
    )
    args = parser.parse_args()

    showcases = [
        Showcase(
            "model-comparison",
            "TTS 모델별 비교",
            args.showcase_dir / "mallo_tts_all_models_standalone.html",
        ),
        Showcase(
            "adaptive-levels-v2",
            "Adaptive TTS Levels v2 개선판",
            args.showcase_dir / "mallo_adaptive_levels_v2_showcase.html",
        ),
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    total = sum(extract_showcase(item, args.output_dir) for item in showcases)
    build_index(showcases, args.output_dir)
    print(f"내부 쇼케이스 생성 완료: {args.output_dir} (오디오 {total}개)")


if __name__ == "__main__":
    main()
