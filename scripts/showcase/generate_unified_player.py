#!/usr/bin/env python3
"""
Generate a Unified HTML Audio Player comparing:
1. MeloTTS Best Preset (P03_Smooth_LowNoise) - Ultra Low Latency (180ms)
2. Qwen3-TTS 299-Sample Full LoRA - High Fidelity Audio LLM (Prosody)
"""

import os
import json
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="말로 TTS 듀얼 엔진 비교 청음 플레이어 생성기")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("artifacts/showcase/legacy/tts/tts_unified_comparison_player.html"),
        help="생성할 HTML 파일 경로 (기본값: artifacts/showcase/legacy/tts/tts_unified_comparison_player.html)"
    )
    args = parser.parse_args()

    player_path = args.output
    player_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check audio files
    melo_dir = Path("data/tts/runs/melo_sweep/P03_Smooth_LowNoise")
    qwen_dir = Path("data/tts/runs/qwen3_full299/eval_wavs")
    
    sentences = [
        ("01_Greeting", "안녕하세요! 말로 카페입니다. 주문 도와드릴까요?", "S1_Greeting.wav", "BM_01_Greeting.wav"),
        ("02_SingleDrink", "따뜻한 아메리카노 한 잔 주문 접수되었습니다.", "S2_SingleDrink.wav", "BM_02_SingleDrink.wav"),
        ("03_CustomOption", "아이스 카페라떼 샷 추가하고 두유로 변경해 드렸습니다.", "S3_CustomOption.wav", "BM_03_CustomOption.wav"),
        ("04_DessertCombo", "아이스 아메리카노 두 잔과 바스크 치즈케이크 한 조각 맞으실까요?", "S4_DessertCombo.wav", "BM_04_DessertCombo.wav"),
        ("05_PaymentGuide", "총 결제 금액은 8,500원입니다. 신용카드를 투입구에 꽂아주세요.", "S5_PaymentGuide.wav", "BM_09_PaymentGuide.wav"),
    ]
    
    html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>말로(Mallo) TTS 듀얼 엔진 최종 비교 청음 플레이어</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 30px; line-height: 1.6; }
        h1 { color: #38bdf8; margin-bottom: 8px; }
        p.desc { color: #94a3b8; font-size: 1.1em; margin-bottom: 25px; }
        .grid-header { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 25px; }
        .card { background: #1e293b; padding: 20px; border-radius: 10px; border-left: 5px solid #38bdf8; }
        .card.melo { border-left-color: #10b981; }
        .card.qwen { border-left-color: #8b5cf6; }
        .card h3 { margin-top: 0; }
        .card.melo h3 { color: #34d399; }
        .card.qwen h3 { color: #a78bfa; }
        .table-container { background: #1e293b; border-radius: 10px; overflow: hidden; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 14px 18px; text-align: left; border-bottom: 1px solid #334155; }
        th { background: #0f172a; color: #94a3b8; font-weight: 600; font-size: 0.95em; }
        tr:hover { background: #334155; }
        audio { height: 36px; width: 260px; }
        .tag { background: #334155; color: #94a3b8; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }
    </style>
</head>
<body>
    <h1>☕ 말로(Mallo) TTS 듀얼 엔진 비교 청음 플레이어</h1>
    <p class="desc">초저지연 실시간 인터랙션 엔진(MeloTTS)과 고품질 감성 대화 엔진(Qwen3-TTS)의 음질 및 억양을 비교 청음하실 수 있습니다.</p>

    <div class="grid-header">
        <div class="card melo">
            <h3>⚡ MeloTTS (최적 프리셋 P03 + G_2800)</h3>
            <p><strong>응답 속도:</strong> 180ms ~ 190ms (RTF 0.036 / 28배속)<br>
            <strong>특징:</strong> 터치 즉시 피드백, 매끄러운 저노이즈 친절체 톤 (44.1kHz)</p>
        </div>
        <div class="card qwen">
            <h3>🎧 Qwen3-TTS 0.6B (299개 All-Linear LoRA)</h3>
            <p><strong>응답 속도:</strong> ~5-7초 (RTF 1.6)<br>
            <strong>특징:</strong> 실제 사람 같은 풍부한 운율, 자연스러운 숨소리 및 감성 친절체 (24kHz)</p>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 10%;">ID</th>
                    <th style="width: 35%;">안내 문장 (Text)</th>
                    <th style="width: 27%;">⚡ MeloTTS (180ms 초저지연)</th>
                    <th style="width: 28%;">🎧 Qwen3-TTS (고품질 감성체)</th>
                </tr>
            </thead>
            <tbody>
"""

    for tag, text, melo_file, qwen_file in sentences:
        melo_rel = f"melo_sweep/P03_Smooth_LowNoise/{melo_file}"
        qwen_rel = f"qwen3_full299/eval_wavs/{qwen_file}"
        
        html += f"""                <tr>
                    <td><span class="tag">{tag}</span></td>
                    <td><strong>{text}</strong></td>
                    <td><audio controls src="{melo_rel}"></audio></td>
                    <td><audio controls src="{qwen_rel}"></audio></td>
                </tr>
"""

    html += """            </tbody>
        </table>
    </div>
</body>
</html>
"""

    with open(player_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    print(f"Generated Unified Comparison Player at: {player_path}")

if __name__ == "__main__":
    main()
