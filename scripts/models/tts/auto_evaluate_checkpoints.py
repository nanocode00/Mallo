#!/usr/bin/env python3
"""MeloTTS 새 체크포인트가 나올 때마다 자동으로 대표 문장 3개를 합성하고 HTML 플레이어를 갱신한다."""

import time
import os
from pathlib import Path
import soundfile as sf
import base64
import torch

log_dir = Path("logs/mallo-friendly")
out_dir = Path("data/tts/runs/live_checkpoints")
out_dir.mkdir(parents=True, exist_ok=True)

test_sentences = [
    ("s1", "아이스 아메리카노 두 잔 주문을 확인했습니다."),
    ("s2", "따뜻한 카페라떼 한 잔은 5,200원입니다."),
    ("s3", "바스크 치즈 케이크와 크로플을 추가했습니다."),
]

def update_html():
    from melo.api import TTS
    
    ckpts = sorted(log_dir.glob("G_*.pth"), key=lambda p: int(p.stem.split("_")[1]) if p.stem.split("_")[1].isdigit() else 0)
    
    ckpt_data = []
    for ckpt in ckpts:
        step = ckpt.stem.split("_")[1]
        if ckpt.stat().st_size < 100 * 1024 * 1024:
            continue
            
        # Check if synthesized
        audio_items = []
        for sid, text in test_sentences:
            wav_file = out_dir / f"{ckpt.stem}_{sid}.wav"
            if not wav_file.exists():
                print(f"[AutoEval] Synthesizing {ckpt.name} for {sid}...")
                tts = TTS(
                    language="KR",
                    device="cuda:0",
                    use_hf=False,
                    config_path="data/tts/runs/melotts/config.json",
                    ckpt_path=str(ckpt),
                )
                tts.tts_to_file(text, 0, str(wav_file), speed=1.0)
                
            data, sr = sf.read(wav_file)
            dur = len(data) / sr
            b64 = base64.b64encode(wav_file.read_bytes()).decode("utf-8")
            audio_items.append((sid, text, dur, b64))
            
        ckpt_data.append((ckpt.stem, step, audio_items))
        
    html = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>MeloTTS 체크포인트별 실시간 음질·어조 변화 대시보드</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 32px 16px; max-width: 960px; margin: 0 auto; line-height: 1.5; }
  h1 { color: #38bdf8; text-align: center; margin-bottom: 6px; font-size: 24px; }
  .subtitle { text-align: center; color: #94a3b8; font-size: 14px; margin-bottom: 28px; }
  .ckpt-card { background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 20px; margin-bottom: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); }
  .ckpt-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 16px; }
  .ckpt-title { font-size: 18px; font-weight: 700; color: #38bdf8; }
  .ckpt-badge { background: #0284c7; color: white; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
  .item-box { background: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; }
  .item-meta { font-size: 11px; color: #94a3b8; margin-bottom: 6px; }
  .item-text { font-size: 15px; font-weight: 600; color: #f1f5f9; margin-bottom: 12px; }
  audio { width: 100%; height: 38px; }
</style>
</head>
<body>
<h1>🎙️ MeloTTS 체크포인트 실시간 비교 대시보드</h1>
<p class="subtitle">체크포인트(Step 0, 200, 400, 600...)별 문장 명료도 및 친절체 어조 전이 실시간 모니터링</p>
"""
    for ckpt_stem, step, items in ckpt_data:
        html += f"""
<div class="ckpt-card">
  <div class="ckpt-header">
    <span class="ckpt-title">체크포인트: {ckpt_stem}.pth</span>
    <span class="ckpt-badge">Step {step}</span>
  </div>
  <div class="grid">
"""
        for sid, text, dur, b64 in items:
            html += f"""
    <div class="item-box">
      <div class="item-meta">[{sid}] 길이: {dur:.2f}초 | 44.1kHz</div>
      <div class="item-text">"{text}"</div>
      <audio controls preload="none" src="data:audio/wav;base64,{b64}"></audio>
    </div>
"""
        html += """  </div>
</div>
"""
    html += """
</body>
</html>
"""
    (out_dir / "dashboard.html").write_text(html, encoding="utf-8")
    print(f"[AutoEval] Updated {out_dir / 'dashboard.html'} with {len(ckpt_data)} checkpoints!")

if __name__ == "__main__":
    update_html()
