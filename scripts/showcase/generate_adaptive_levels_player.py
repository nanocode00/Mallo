#!/usr/bin/env python3
"""
Mallo Adaptive TTS Level 0 vs Level 1 vs Level 2 종합 비교 Standalone HTML 플레이어 생성기
"""

import os
import sys
import json
import time
import base64
import argparse
from pathlib import Path

import torch
import soundfile as sf

# Add src and MeloTTS to path
sys.path.insert(0, "src")
sys.path.insert(0, "data/tts/repos/MeloTTS")

from adapters.tts.melotts_adapter import MeloTTSAdapter
from domain.text_transformer import AdaptiveTextTransformer

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

def file_to_base64_src(path: Path | str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode('utf-8')
    return f"data:audio/wav;base64,{b64}"

def main() -> None:
    parser = argparse.ArgumentParser(description="Mallo Adaptive TTS Level 0/1/2 HTML 쇼케이스 생성기")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("artifacts/showcase/legacy/tts/mallo_adaptive_levels_showcase.html"),
        help="생성할 HTML 파일 경로 (기본값: artifacts/showcase/legacy/tts/mallo_adaptive_levels_showcase.html)"
    )
    parser.add_argument(
        "--raw-dir", "-r",
        type=Path,
        default=Path("artifacts/showcase/legacy/tts/raw/adaptive_levels"),
        help="WAV 오디오 생성/저장 디렉토리 (기본값: artifacts/showcase/legacy/tts/raw/adaptive_levels)"
    )
    args = parser.parse_args()

    html_path = args.output
    html_path.parent.mkdir(parents=True, exist_ok=True)
    out_dir = args.raw_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("Mallo Adaptive TTS Level 0 vs Level 1 vs Level 2 비교 플레이어 생성")
    print(f"실행 장치: {DEVICE}")
    print(f"출력 HTML: {html_path}")
    print(f"RAW 오디오 디렉토리: {out_dir}")
    print("=" * 80)

    # Checkpoint & Config setup
    ckpt_path = "models/tts/mallo-friendly/G_2800.pth"
    config_path = "models/tts/mallo-friendly/config.json"


    print(f"MeloTTS Checkpoint: {ckpt_path}")
    print(f"MeloTTS Config: {config_path}")

    # Load Adapter
    adapter = MeloTTSAdapter(
        config_path=config_path,
        ckpt_path=ckpt_path,
        speaker="10",
        device=DEVICE
    )

    # Load sentences
    sentences_file = Path("data/tts/evaluation/sentences.json")
    with open(sentences_file, "r", encoding="utf-8") as f:
        sentences_data = json.load(f)["sentences"]

    print(f"총 {len(sentences_data)}개 주문 도메인 문장 대상 Level 0/1/2 처리 시작...")

    results = []

    for item in sentences_data:
        s_id = item["id"]
        cat = item["category"]
        raw_text = item["text"]

        row = {
            "id": s_id,
            "category": cat,
            "raw_text": raw_text,
            "levels": {}
        }

        print(f"\n[{s_id}] ({cat}) 원문: {raw_text}")

        for level in (0, 1, 2):
            transformed = AdaptiveTextTransformer.transform(raw_text, level=level)
            wav_path = out_dir / f"{s_id}_level_{level}.wav"

            if wav_path.exists():
                data, sr = sf.read(wav_path)
                dur_s = len(data) / sr
                lat_ms = 0.0
            else:
                t0 = time.perf_counter()
                tts_res = adapter.synthesize(transformed, level=level)
                lat_ms = (time.perf_counter() - t0) * 1000.0

                with open(wav_path, "wb") as f:
                    f.write(tts_res.audio)

                dur_s = tts_res.duration_ms / 1000.0
            
            print(f"  - Level {level} ({'기본 1.0x' if level == 0 else '느림 0.85x'}): '{transformed}' ({dur_s:.2f}초, {lat_ms:.1f}ms)")

            row["levels"][level] = {
                "text": transformed,
                "duration_s": dur_s,
                "latency_ms": lat_ms,
                "wav_path": str(wav_path)
            }

        results.append(row)

    print("\nStandalone HTML 생성 중...")

    html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>말로(Mallo) Adaptive TTS 빠르기 및 레벨(Level 0 vs 1 vs 2) 비교 쇼케이스</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Pretendard', 'Segoe UI', Roboto, sans-serif;
            background: #0b1120;
            color: #f8fafc;
            padding: 25px;
            max-width: 1480px;
            margin: 0 auto;
            line-height: 1.6;
        }
        h1 {
            color: #38bdf8;
            font-size: 1.9em;
            margin-bottom: 6px;
        }
        p.subtitle {
            color: #94a3b8;
            font-size: 1.05em;
            margin-bottom: 25px;
        }
        .grid-header {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 25px;
        }
        .card {
            background: #1e293b;
            padding: 18px 20px;
            border-radius: 12px;
            border-left: 5px solid #38bdf8;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }
        .card.l0 { border-left-color: #10b981; }
        .card.l1 { border-left-color: #f59e0b; }
        .card.l2 { border-left-color: #3b82f6; }
        .card h3 {
            margin: 0 0 6px 0;
            font-size: 1.15em;
        }
        .card.l0 h3 { color: #34d399; }
        .card.l1 h3 { color: #fbbf24; }
        .card.l2 h3 { color: #60a5fa; }
        .card p {
            margin: 0;
            font-size: 0.88em;
            color: #cbd5e1;
        }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: 600;
            margin-top: 8px;
        }
        .badge.l0 { background: #064e3b; color: #6ee7b7; }
        .badge.l1 { background: #78350f; color: #fde68a; }
        .badge.l2 { background: #1e3a8a; color: #93c5fd; }
        .table-container {
            background: #1e293b;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }
        th, td {
            padding: 14px 16px;
            border-bottom: 1px solid #334155;
            vertical-align: top;
        }
        th {
            background: #020617;
            color: #94a3b8;
            font-size: 0.85em;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        tr:last-child td { border-bottom: none; }
        tr:hover { background: #27354a; }
        .tag {
            background: #334155;
            color: #94a3b8;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: 600;
            white-space: nowrap;
        }
        .cat {
            color: #38bdf8;
            font-size: 0.75em;
            display: block;
            margin-top: 4px;
        }
        .text-box {
            font-size: 0.93em;
            color: #f1f5f9;
            margin-bottom: 8px;
            min-height: 42px;
        }
        .meta-info {
            font-size: 0.78em;
            color: #94a3b8;
            margin-bottom: 6px;
        }
        audio {
            height: 32px;
            width: 100%;
            max-width: 280px;
        }
        .highlight {
            color: #38bdf8;
            font-weight: 600;
        }
        .pause-marker {
            color: #fbbf24;
            font-weight: 700;
            background: rgba(251, 191, 36, 0.15);
            padding: 1px 4px;
            border-radius: 3px;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            color: #64748b;
            font-size: 0.85em;
        }
    </style>
</head>
<body>
    <h1>☕ 말로(Mallo) Adaptive TTS 빠르기 및 레벨(Level 0 vs 1 vs 2) 비교 쇼케이스</h1>
    <p class="subtitle">고령 사용자의 인지·청각 부담을 줄이기 위한 세션별 적응형 TTS의 발화 속도(Speed) 및 문장 구조(Pause/분절) 변환 비교 청음 플레이어입니다.</p>

    <div class="grid-header">
        <div class="card l0">
            <h3>🟢 Level 0: 기본 안내</h3>
            <p>• <strong>발화 속도:</strong> <strong>1.0x</strong> (기본 속도)<br>
            • <strong>문장 구조:</strong> 자연어 원본 문장 유지<br>
            • <strong>적용 대상:</strong> 일반 주문자 및 첫 대화</p>
            <span class="badge l0">기본 상태</span>
        </div>
        <div class="card l1">
            <h3>🟡 Level 1: 느린 안내 + Pause</h3>
            <p>• <strong>발화 속도:</strong> <strong>0.85x</strong> (15% 감속)<br>
            • <strong>문장 구조:</strong> 항목 및 서술어 사이에 Pause(쉼표) 삽입<br>
            • <strong>적용 대상:</strong> "천천히 말해줘", "다시 말해줘" 1회 요청 시</p>
            <span class="badge l1">1단계 완화</span>
        </div>
        <div class="card l2">
            <h3>🔵 Level 2: 단문 분절 + 정보 강조</h3>
            <p>• <strong>발화 속도:</strong> <strong>0.85x</strong> (15% 감속)<br>
            • <strong>문장 구조:</strong> 메뉴명·수량·가격을 독립 단문으로 분절 안내<br>
            • <strong>적용 대상:</strong> "더 천천히", "다시 말해줘" 연속 요청 시</p>
            <span class="badge l2">최대 인지 배려</span>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 8%;">ID</th>
                    <th style="width: 30%;">🟢 Level 0 (1.0x / 원본 문장)</th>
                    <th style="width: 31%;">🟡 Level 1 (0.85x / Pause 삽입)</th>
                    <th style="width: 31%;">🔵 Level 2 (0.85x / 단문 분절·강조)</th>
                </tr>
            </thead>
            <tbody>
"""

    for r in results:
        s_id = r["id"]
        cat = r["category"]

        l0 = r["levels"][0]
        l1 = r["levels"][1]
        l2 = r["levels"][2]

        l0_src = file_to_base64_src(l0["wav_path"])
        l1_src = file_to_base64_src(l1["wav_path"])
        l2_src = file_to_base64_src(l2["wav_path"])

        l1_highlighted = l1["text"].replace(", ... ", ' <span class="pause-marker">, ... </span>')

        html += f"""                <tr>
                    <td>
                        <span class="tag">{s_id}</span>
                        <span class="cat">{cat}</span>
                    </td>
                    <td>
                        <div class="text-box"><strong>{l0["text"]}</strong></div>
                        <div class="meta-info">⏱ 길이: {l0["duration_s"]:.2f}s | 지연: {l0["latency_ms"]:.0f}ms</div>
                        <audio controls src="{l0_src}"></audio>
                    </td>
                    <td>
                        <div class="text-box">{l1_highlighted}</div>
                        <div class="meta-info">⏱ 길이: {l1["duration_s"]:.2f}s | 지연: {l1["latency_ms"]:.0f}ms</div>
                        <audio controls src="{l1_src}"></audio>
                    </td>
                    <td>
                        <div class="text-box"><span class="highlight">{l2["text"]}</span></div>
                        <div class="meta-info">⏱ 길이: {l2["duration_s"]:.2f}s | 지연: {l2["latency_ms"]:.0f}ms</div>
                        <audio controls src="{l2_src}"></audio>
                    </td>
                </tr>
"""

    html += """            </tbody>
        </table>
    </div>
    <div class="footer">
        말로(Mallo) Adaptive Voice-first Kiosk • TTS Level 0/1/2 Speed & Segmentation Evaluation
    </div>
</body>
</html>
"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_mb = html_path.stat().st_size / 1024 / 1024
    print(f"\n★ Standalone HTML 플레이어 생성 완료: {html_path} ({size_mb:.1f} MB)")

if __name__ == "__main__":
    main()
