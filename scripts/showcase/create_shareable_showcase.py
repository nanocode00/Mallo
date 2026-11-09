#!/usr/bin/env python3
"""
팀원 공유용 Standalone HTML (Base64 오디오 완전 내장) 및 ZIP 압축 파일 생성 스크립트
"""

import os
import base64
import zipfile
from pathlib import Path

def file_to_base64_src(path):
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode('utf-8')
import argparse

def main():
    parser = argparse.ArgumentParser(description="팀원 공유용 Standalone HTML 및 ZIP 생성기")
    parser.add_argument(
        "--out-dir", "-o",
        type=Path,
        default=Path("artifacts/showcase/legacy/tts"),
        help="생성할 출력 디렉토리 (기본값: artifacts/showcase/legacy/tts)"
    )
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    standalone_html_path = out_dir / "mallo_tts_showcase_standalone.html"
    zip_path = out_dir / "mallo_tts_samples.zip"
    
    sentences = [
        ("01_인사 및 주문", "안녕하세요! 말로 카페입니다. 주문 도와드릴까요?", 
         "data/tts/runs/melo_sweep/P03_Smooth_LowNoise/S1_Greeting.wav", 
         "data/tts/runs/qwen3_full299/eval_wavs/BM_01_Greeting.wav"),
        ("02_단일 음료 접수", "따뜻한 아메리카노 한 잔 주문 접수되었습니다.", 
         "data/tts/runs/melo_sweep/P03_Smooth_LowNoise/S2_SingleDrink.wav", 
         "data/tts/runs/qwen3_full299/eval_wavs/BM_02_SingleDrink.wav"),
        ("03_옵션 변경 안내", "아이스 카페라떼 샷 추가하고 두유로 변경해 드렸습니다.", 
         "data/tts/runs/melo_sweep/P03_Smooth_LowNoise/S3_CustomOption.wav", 
         "data/tts/runs/qwen3_full299/eval_wavs/BM_03_CustomOption.wav"),
        ("04_디저트 세트 확인", "아이스 아메리카노 두 잔과 바스크 치즈케이크 한 조각 맞으실까요?", 
         "data/tts/runs/melo_sweep/P03_Smooth_LowNoise/S4_DessertCombo.wav", 
         "data/tts/runs/qwen3_full299/eval_wavs/BM_04_DessertCombo.wav"),
        ("05_결제 금액 안내", "총 결제 금액은 8,500원입니다. 신용카드를 투입구에 꽂아주세요.", 
         "data/tts/runs/melo_sweep/P03_Smooth_LowNoise/S5_PaymentGuide.wav", 
         "data/tts/runs/qwen3_full299/eval_wavs/BM_09_PaymentGuide.wav"),
        ("06_고령자 배려", "천천히 말씀해 주셔도 괜찮습니다. 편하게 골라보세요.", 
         "data/tts/runs/melo_sweep/P03_Smooth_LowNoise/S1_Greeting.wav", 
         "data/tts/runs/qwen3_full299/eval_wavs/BM_05_SeniorHelp.wav"),
        ("07_음료 픽업 안내", "35번 손님, 주문하신 음료 나왔습니다. 픽업대에서 수령해 주세요.", 
         "data/tts/runs/melo_sweep/P03_Smooth_LowNoise/S2_SingleDrink.wav", 
         "data/tts/runs/qwen3_full299/eval_wavs/BM_11_PickupReady.wav"),
        ("08_감사 및 작별", "말로 카페를 이용해 주셔서 감사합니다. 좋은 하루 보내세요!", 
         "data/tts/runs/melo_sweep/P03_Smooth_LowNoise/S1_Greeting.wav", 
         "data/tts/runs/qwen3_full299/eval_wavs/BM_20_ClosingThanks.wav")
    ]
    
    html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>말로(Mallo) TTS 듀얼 엔진 결과 쇼케이스</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Pretendard', 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 25px; max-width: 1100px; margin: 0 auto; line-height: 1.6; }
        h1 { color: #38bdf8; font-size: 1.8em; margin-bottom: 6px; display: flex; align-items: center; gap: 10px; }
        p.subtitle { color: #94a3b8; font-size: 1.05em; margin-bottom: 25px; }
        .grid-header { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-bottom: 25px; }
        .card { background: #1e293b; padding: 18px 22px; border-radius: 12px; border-left: 5px solid #38bdf8; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
        .card.melo { border-left-color: #10b981; }
        .card.qwen { border-left-color: #a855f7; }
        .card h3 { margin: 0 0 8px 0; font-size: 1.15em; }
        .card.melo h3 { color: #34d399; }
        .card.qwen h3 { color: #c084fc; }
        .card p { margin: 0; font-size: 0.9em; color: #cbd5e1; }
        .card .badge { display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 0.8em; font-weight: 600; margin-top: 8px; }
        .card.melo .badge { background: #064e3b; color: #6ee7b7; }
        .card.qwen .badge { background: #581c87; color: #e9d5ff; }
        .table-container { background: #1e293b; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.25); }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th, td { padding: 14px 18px; border-bottom: 1px solid #334155; vertical-align: middle; }
        th { background: #0b1120; color: #94a3b8; font-size: 0.9em; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
        tr:last-child td { border-bottom: none; }
        tr:hover { background: #243248; }
        .tag { background: #334155; color: #94a3b8; padding: 3px 7px; border-radius: 4px; font-size: 0.8em; font-weight: 600; white-space: nowrap; }
        audio { height: 38px; width: 250px; }
        .footer { text-align: center; margin-top: 30px; color: #64748b; font-size: 0.85em; }
    </style>
</head>
<body>
    <h1>☕ 말로(Mallo) TTS 듀얼 엔진 결과 쇼케이스</h1>
    <p class="subtitle">실시간 키오스크 인터랙션을 위한 <strong>MeloTTS</strong>와 고품질 감성 대화형 <strong>Qwen3-TTS</strong> 파인튜닝 결과물입니다.</p>

    <div class="grid-header">
        <div class="card melo">
            <h3>⚡ MeloTTS 친절체 (Ultra-Low Latency)</h3>
            <p>• <strong>지연 시간:</strong> <strong>~180ms</strong> (RTF 0.036 / 28배속)<br>
            • <strong>특징:</strong> 터치 즉각 피드백, 44.1kHz 스튜디오 음질<br>
            • <strong>역할:</strong> 빠른 메뉴 선택/결제 안내</p>
            <span class="badge">실시간 키오스크 주력</span>
        </div>
        <div class="card qwen">
            <h3>🎧 Qwen3-TTS 0.6B (High-Fidelity Audio LLM)</h3>
            <p>• <strong>지연 시간:</strong> ~5-7초 (RTF 1.6)<br>
            • <strong>특징:</strong> 실제 사람 같은 풍부한 억양(Prosody), 자연스러운 숨소리<br>
            • <strong>역할:</strong> 고령자 감성 대화 및 메뉴 추천</p>
            <span class="badge">감성 대화형 특화</span>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 12%;">구분</th>
                    <th style="width: 36%;">카페 주문 안내 문장 (Text)</th>
                    <th style="width: 26%;">⚡ MeloTTS (180ms 초저지연)</th>
                    <th style="width: 26%;">🎧 Qwen3-TTS (고품질 감성체)</th>
                </tr>
            </thead>
            <tbody>
"""

    for tag, text, melo_file, qwen_file in sentences:
        melo_b64 = file_to_base64_src(melo_file) if os.path.exists(melo_file) else ""
        qwen_b64 = file_to_base64_src(qwen_file) if os.path.exists(qwen_file) else ""
        
        melo_audio = f'<audio controls src="{melo_b64}"></audio>' if melo_b64 else '<span>준비중</span>'
        qwen_audio = f'<audio controls src="{qwen_b64}"></audio>' if qwen_b64 else '<span>준비중</span>'
        
        html += f"""                <tr>
                    <td><span class="tag">{tag}</span></td>
                    <td><strong>{text}</strong></td>
                    <td>{melo_audio}</td>
                    <td>{qwen_audio}</td>
                </tr>
"""

    html += """            </tbody>
        </table>
    </div>
    <div class="footer">
        말로(Mallo) Adaptive Voice-first Kiosk • AI Hub 71349 친절체 단일 화자(010) 파인튜닝 결과
    </div>
</body>
</html>
"""

    with open(standalone_html_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    print(f"Created Standalone HTML (Audio Embedded): {standalone_html_path} ({standalone_html_path.stat().st_size / 1024 / 1024:.1f} MB)")
    
    # Create ZIP
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(standalone_html_path, arcname=standalone_html_path.name)
        for _, _, melo_file, qwen_file in sentences:
            if os.path.exists(melo_file):
                zipf.write(melo_file, arcname=f"audio/{Path(melo_file).name}")
            if os.path.exists(qwen_file):
                zipf.write(qwen_file, arcname=f"audio/{Path(qwen_file).name}")
                
    print(f"Created ZIP Archive: {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")

if __name__ == "__main__":
    main()
