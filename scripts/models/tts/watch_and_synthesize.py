#!/usr/bin/env python3
"""새로운 MeloTTS 체크포인트가 생성될 때마다 즉시 테스트 발화 음성을 합성하여 검증한다."""

import time
import os
from pathlib import Path
import soundfile as sf
import torch

def main():
    log_dir = Path("logs/mallo-friendly")
    out_dir = Path("data/tts/runs/live_checkpoints")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    test_text = "아이스 아메리카노 두 잔 주문을 확인했습니다."
    processed = set()
    
    print("Watching for checkpoints in logs/mallo-friendly...")
    
    from melo.api import TTS
    
    while True:
        ckpts = sorted(log_dir.glob("G_*.pth"))
        for ckpt in ckpts:
            if ckpt.name not in processed and ckpt.stat().st_size > 100 * 1024 * 1024:
                time.sleep(2)
                print(f"[Watcher] Found new checkpoint: {ckpt.name}")
                try:
                    tts = TTS(
                        language="KR",
                        device="cuda:0",
                        use_hf=False,
                        config_path="data/tts/runs/melotts/config.json",
                        ckpt_path=str(ckpt),
                    )
                    out_wav = out_dir / f"{ckpt.stem}.wav"
                    tts.tts_to_file(
                        test_text,
                        0,
                        str(out_wav),
                        speed=1.0,
                        sdp_ratio=0.0,
                        noise_scale=0.33,
                        noise_scale_w=0.4,
                    )
                    data, sr = sf.read(out_wav)
                    dur = len(data) / sr
                    rms = float((data**2).mean()**0.5)
                    print(f"[Watcher] Synthesized {out_wav.name} | Duration: {dur:.2f}s | RMS: {rms:.4f}")
                    processed.add(ckpt.name)
                except Exception as e:
                    print(f"[Watcher] Error synthesizing {ckpt.name}: {e}")
                    
        time.sleep(5)

if __name__ == "__main__":
    main()
