#!/usr/bin/env python3
"""
4대 TTS 모델 (Melo Baseline vs Melo Friendly vs Qwen Baseline vs Qwen Friendly 299)
20개 전체 도메인 문장 전수 비교 Standalone HTML (Base64 완전 내장) 플레이어 생성기
"""

import os
import sys
import json
import base64
import time
from pathlib import Path

import torch
import soundfile as sf
from peft import PeftModel

sys.path.insert(0, "data/tts/repos/Qwen3-TTS")
from qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

def file_to_base64_src(path):
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode('utf-8')
    return f"data:audio/wav;base64,{b64}"

def synthesize_qwen3_friendly(sentences, raw_base_dir: Path):
    out_dir = raw_base_dir / "qwen3_friendly_299"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    adapter_path = "data/tts/runs/qwen3_full299/checkpoints/adapter_model"
    model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    
    missing_items = [item for item in sentences if not (out_dir / f"{item['id']}.wav").exists()]
    if not missing_items:
        return out_dir

    print(f"Loading Qwen3-TTS Base + LoRA adapter from {adapter_path}...")
    model = Qwen3TTSModel.from_pretrained(model_id, dtype=torch.bfloat16, device_map=DEVICE)
    model.model.talker.model = PeftModel.from_pretrained(model.model.talker.model, adapter_path)
    model.model.eval()
    
    ref_audio = "data/tts/derived/aihub-71349/audio/train/K-H3-D-010-0051.wav"
    ref_text = "전화 주셔서 감사합니다, 여름과 가을 사이 방문 상담 받고 푸짐한 혜택도 챙겨가세요!"
    prompt = model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text, x_vector_only_mode=False)
    
    print("Synthesizing 20 sentences with Qwen3-TTS Friendly (299 Samples)...")
    for item in missing_items:
        s_id = item["id"]
        text = item["text"]
        wav_path = out_dir / f"{s_id}.wav"
        
        with torch.no_grad():
            wavs, sr = model.generate_voice_clone(
                text=text,
                voice_clone_prompt=prompt,
                language="Korean",
                max_new_tokens=100
            )
        sf.write(wav_path, wavs[0], sr)
        print(f"  [{s_id}] Generated: '{text}' ({len(wavs[0])/sr:.2f}s)")
            
    return out_dir

import argparse

def main():
    parser = argparse.ArgumentParser(description="Mallo TTS 4대 모델 비교 HTML 플레이어 생성기")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("artifacts/showcase/legacy/tts/mallo_tts_all_models_standalone.html"),
        help="생성할 HTML 파일 경로 (기본값: artifacts/showcase/legacy/tts/mallo_tts_all_models_standalone.html)"
    )
    parser.add_argument(
        "--raw-dir", "-r",
        type=Path,
        default=Path("artifacts/showcase/legacy/tts/raw/benchmarks_gpu"),
        help="WAV 오디오 베이스 디렉토리 (기본값: artifacts/showcase/legacy/tts/raw/benchmarks_gpu)"
    )
    args = parser.parse_args()

    standalone_path = args.output
    standalone_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir = args.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("Loading 20 sentences from data/tts/evaluation/sentences.json...")
    with open("data/tts/evaluation/sentences.json", "r", encoding="utf-8") as f:
        sentences_data = json.load(f)["sentences"]
        
    # Ensure Qwen3 Friendly 20 sentences are synthesized in raw_dir
    qwen_friendly_dir = synthesize_qwen3_friendly(sentences_data, raw_dir)
    
    melo_base_dir = raw_dir / "melotts_baseline"
    melo_friend_dir = raw_dir / "melotts_friendly"
    qwen_base_dir = raw_dir / "qwen3_baseline"
    
    # Fallback to old runs if raw_dir has not copied them yet
    if not melo_base_dir.exists():
        melo_base_dir = Path("data/tts/runs/benchmarks_gpu/melotts_baseline")
    if not melo_friend_dir.exists():
        melo_friend_dir = Path("data/tts/runs/benchmarks_gpu/melotts_friendly")
    if not qwen_base_dir.exists():
        qwen_base_dir = Path("data/tts/runs/benchmarks_gpu/qwen3_baseline")
    
    print(f"Building Standalone HTML with Base64 audio embedded to: {standalone_path}...")
    
    html = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>말로(Mallo) TTS 4대 모델(Baseline vs Fine-tuned) 종합 비교 쇼케이스</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Pretendard', 'Segoe UI', Roboto, sans-serif; background: #0b1120; color: #f8fafc; padding: 25px; max-width: 1450px; margin: 0 auto; line-height: 1.6; }
        h1 { color: #38bdf8; font-size: 1.9em; margin-bottom: 6px; }
        p.subtitle { color: #94a3b8; font-size: 1.05em; margin-bottom: 25px; }
        .grid-header { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 25px; }
        .card { background: #1e293b; padding: 16px 20px; border-radius: 12px; border-left: 5px solid #38bdf8; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
        .card.mb { border-left-color: #64748b; }
        .card.mf { border-left-color: #10b981; }
        .card.qb { border-left-color: #6366f1; }
        .card.qf { border-left-color: #ec4899; }
        .card h3 { margin: 0 0 6px 0; font-size: 1.1em; }
        .card.mb h3 { color: #94a3b8; }
        .card.mf h3 { color: #34d399; }
        .card.qb h3 { color: #818cf8; }
        .card.qf h3 { color: #f472b6; }
        .card p { margin: 0; font-size: 0.85em; color: #cbd5e1; }
        .badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.75em; font-weight: 600; margin-top: 6px; }
        .badge.mb { background: #334155; color: #cbd5e1; }
        .badge.mf { background: #064e3b; color: #6ee7b7; }
        .badge.qb { background: #312e81; color: #c7d2fe; }
        .badge.qf { background: #831843; color: #fbcfe8; }
        .table-container { background: #1e293b; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th, td { padding: 12px 14px; border-bottom: 1px solid #334155; vertical-align: middle; }
        th { background: #020617; color: #94a3b8; font-size: 0.85em; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
        tr:last-child td { border-bottom: none; }
        tr:hover { background: #27354a; }
        .tag { background: #334155; color: #94a3b8; padding: 2px 6px; border-radius: 4px; font-size: 0.75em; font-weight: 600; white-space: nowrap; }
        .cat { color: #38bdf8; font-size: 0.75em; display: block; margin-top: 2px; }
        audio { height: 34px; width: 220px; }
        .footer { text-align: center; margin-top: 30px; color: #64748b; font-size: 0.85em; }
    </style>
</head>
<body>
    <h1>☕ 말로(Mallo) TTS 4대 모델 (Baseline vs Fine-tuned) 종합 비교</h1>
    <p class="subtitle">사전학습 원본(Baseline)과 AI Hub 71349 친절체 파인튜닝 모델의 20개 대표 주문 시나리오 전수 비교 청음 쇼케이스입니다.</p>

    <div class="grid-header">
        <div class="card mb">
            <h3>1. MeloTTS Baseline</h3>
            <p>• <strong>지연:</strong> ~198ms (44.1kHz)<br>
            • <strong>특징:</strong> 기본 사전학습 (무감정 톤)</p>
            <span class="badge mb">VITS 기준군</span>
        </div>
        <div class="card mf">
            <h3>2. MeloTTS 친절체 (G_2800)</h3>
            <p>• <strong>지연:</strong> <strong>~180ms</strong> (44.1kHz)<br>
            • <strong>특징:</strong> 차분한 어미 하강 친절체</p>
            <span class="badge mf">실시간 키오스크 주력</span>
        </div>
        <div class="card qb">
            <h3>3. Qwen3-TTS Baseline</h3>
            <p>• <strong>지연:</strong> ~6.9s (24.0kHz)<br>
            • <strong>특징:</strong> 0.6B Zero-shot ICL 기본</p>
            <span class="badge qb">LLM 기준군</span>
        </div>
        <div class="card qf">
            <h3>4. Qwen3-TTS 친절체 (299 LoRA)</h3>
            <p>• <strong>지연:</strong> ~5-7s (24.0kHz)<br>
            • <strong>특징:</strong> 실제 사람 같은 풍부한 감성 운율</p>
            <span class="badge qf">고품질 감성 특화</span>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 7%;">ID</th>
                    <th style="width: 25%;">카페 주문 안내 문장 (Text)</th>
                    <th style="width: 17%;">MeloTTS Baseline</th>
                    <th style="width: 17%;">⚡ MeloTTS 친절체</th>
                    <th style="width: 17%;">Qwen3 Baseline</th>
                    <th style="width: 17%;">🎧 Qwen3 친절체 (299개)</th>
                </tr>
            </thead>
            <tbody>
"""

    for item in sentences_data:
        s_id = item["id"]
        cat = item["category"]
        text = item["text"]
        
        mb_path = melo_base_dir / f"{s_id}.wav"
        mf_path = melo_friend_dir / f"{s_id}.wav"
        qb_path = qwen_base_dir / f"{s_id}.wav"
        qf_path = qwen_friendly_dir / f"{s_id}.wav"
        
        mb_src = file_to_base64_src(mb_path)
        mf_src = file_to_base64_src(mf_path)
        qb_src = file_to_base64_src(qb_path)
        qf_src = file_to_base64_src(qf_path)
        
        mb_audio = f'<audio controls src="{mb_src}"></audio>' if mb_src else '<span style="color:#64748b;">-</span>'
        mf_audio = f'<audio controls src="{mf_src}"></audio>' if mf_src else '<span style="color:#64748b;">-</span>'
        qb_audio = f'<audio controls src="{qb_src}"></audio>' if qb_src else '<span style="color:#64748b;">-</span>'
        qf_audio = f'<audio controls src="{qf_src}"></audio>' if qf_src else '<span style="color:#64748b;">-</span>'
        
        html += f"""                <tr>
                    <td><span class="tag">{s_id}</span><span class="cat">{cat}</span></td>
                    <td><strong>{text}</strong></td>
                    <td>{mb_audio}</td>
                    <td>{mf_audio}</td>
                    <td>{qb_audio}</td>
                    <td>{qf_audio}</td>
                </tr>
"""

    html += """            </tbody>
        </table>
    </div>
    <div class="footer">
        말로(Mallo) Adaptive Voice-first Kiosk • TTS Baseline vs Fine-tuned 20-Sentence Evaluation
    </div>
</body>
</html>
"""

    with open(standalone_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    print(f"Successfully Created Standalone 4-Model HTML Player: {standalone_path} ({standalone_path.stat().st_size / 1024 / 1024:.1f} MB)")

if __name__ == "__main__":
    main()
