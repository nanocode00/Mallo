#!/usr/bin/env python3
"""
Qwen3-TTS 0.6B Full 299-Sample Production Fine-Tuning & 20 Benchmark Sentences Evaluation
- Model: Qwen/Qwen3-TTS-12Hz-0.6B-Base
- LoRA: All-Linear (q, k, v, o, gate, up, down, r=16, alpha=32) + text_projection unfreeze
- Optimizer: AdamW, LR: 2e-6
- Epochs: 10 (~750 optimizer steps with Grad Accum 2)
- Evaluation: 20 Standard Cafe Ordering Benchmark Sentences with Whisper STT & HTML Player
"""

import os
import sys
import json
import time
import math
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
import soundfile as sf
import numpy as np
from faster_whisper import WhisperModel
from peft import LoraConfig, get_peft_model

sys.path.insert(0, "data/tts/repos/Qwen3-TTS")
sys.path.insert(0, "data/tts/repos/Qwen3-TTS/finetuning")

from dataset import TTSDataset
from qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel
from qwen_tts.core.models.configuration_qwen3_tts import Qwen3TTSConfig

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

def print_header(title):
    print("\n" + "="*80)
    print(f"▶ {title}")
    print("="*80)

BENCHMARK_20_SENTENCES = [
    ("BM_01_Greeting", "안녕하세요! 말로 카페입니다. 주문 도와드릴까요?"),
    ("BM_02_SingleDrink", "따뜻한 아메리카노 한 잔 주문 접수되었습니다."),
    ("BM_03_CustomOption", "아이스 카페라떼 샷 추가하고 두유로 변경해 드렸습니다."),
    ("BM_04_DessertCombo", "아이스 아메리카노 두 잔과 바스크 치즈케이크 한 조각 맞으실까요?"),
    ("BM_05_SeniorHelp", "천천히 말씀해 주셔도 괜찮습니다. 편하게 골라보세요."),
    ("BM_06_ReorderPrompt", "기존에 자주 드시던 덜 단 바닐라라떼로 준비해 드릴까요?"),
    ("BM_07_TakeoutAsk", "매장에서 드시고 가시나요, 아니면 포장이신가요?"),
    ("BM_08_PointAsk", "적립하실 전화번호 열한 자리를 말씀해 주세요."),
    ("BM_09_PaymentGuide", "총 결제 금액은 8,500원입니다. 신용카드를 투입구에 꽂아주세요."),
    ("BM_10_OrderComplete", "결제가 정상적으로 완료되었습니다. 영수증과 주문번호 35번을 확인해 주세요."),
    ("BM_11_PickupReady", "35번 손님, 주문하신 음료 나왔습니다. 픽업대에서 수령해 주세요."),
    ("BM_12_ModifyOrder", "아이스 아메리카노 한 잔을 따뜻한 아메리카노로 변경했습니다."),
    ("BM_13_DeleteOrder", "장바구니에서 카페라떼를 삭제했습니다. 다른 메뉴를 추가하시겠어요?"),
    ("BM_14_AllCancel", "주문이 모두 취소되었습니다. 처음부터 다시 시작할까요?"),
    ("BM_15_SoldOutAlert", "죄송합니다. 요청하신 딸기 수플레는 현재 재료가 소진되었습니다."),
    ("BM_16_RecommendCold", "날씨가 많이 더우시죠? 시원한 청포도 에이드는 어떠세요?"),
    ("BM_17_RecommendWarm", "비가 와서 쌀쌀한 날에는 따뜻한 자몽차가 인기 메뉴입니다."),
    ("BM_18_DecafGuide", "저희 매장의 모든 에스프레소 음료는 디카페인 원두로 변경 가능합니다."),
    ("BM_19_TumblerDiscount", "개인 텀블러를 이용해 주셔서 300원 할인 혜택이 적용되었습니다."),
    ("BM_20_ClosingThanks", "말로 카페를 이용해 주셔서 감사합니다. 향긋하고 행복한 하루 보내세요!")
]

def main():
    print_header("Qwen3-TTS 0.6B Full 299-Sample Fine-Tuning Pipeline")
    
    out_dir = Path("data/tts/runs/qwen3_full299")
    eval_dir = out_dir / "eval_wavs"
    ckpt_dir = out_dir / "checkpoints"
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    
    # Load 299 samples
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    train_data = [json.loads(line) for line in open(train_jsonl)]
    print(f"Loaded all {len(train_data)} training samples (Speaker: 010 Calm Friendly).")
    
    # Load Base Model
    model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    print(f"Loading Base model: {model_id}...")
    model = Qwen3TTSModel.from_pretrained(model_id, dtype=torch.bfloat16, device_map=DEVICE)
    
    # Freeze Speaker Encoder & Sub-Talker (Code Predictor)
    for p in model.model.speaker_encoder.parameters(): p.requires_grad = False
    for p in model.model.talker.code_predictor.parameters(): p.requires_grad = False
    
    # Attach All-Linear LoRA
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none"
    )
    model.model.talker.model = get_peft_model(model.model.talker.model, lora_config)
    
    # Unfreeze text_projection
    if hasattr(model.model.talker, "text_projection") and model.model.talker.text_projection is not None:
        for p in model.model.talker.text_projection.parameters(): p.requires_grad = True
        
    trainable_params = sum(p.numel() for p in model.model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.model.parameters())
    print(f"Trainable Parameters: {trainable_params:,} / {total_params:,} ({trainable_params/total_params*100:.2f}%)")
    
    # DataLoader
    dataset = TTSDataset(train_data, model.processor, model.model.config)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=2, shuffle=True, collate_fn=dataset.collate_fn)
    
    # Optimizer
    trainable_list = [p for p in model.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_list, lr=2e-6, weight_decay=0.01)
    
    num_epochs = 10
    grad_accum_steps = 2
    total_batches = len(dataloader) * num_epochs
    print(f"Training Plan: {num_epochs} Epochs, {len(dataloader)} Batches/Epoch, Total Batches: {total_batches}")
    
    model.model.train()
    optimizer.zero_grad()
    
    step = 0
    start_time = time.time()
    
    for epoch in range(1, num_epochs + 1):
        epoch_loss = 0.0
        for b_idx, batch in enumerate(dataloader, 1):
            input_ids = batch["input_ids"].to(DEVICE)
            codec_ids = batch["codec_ids"].to(DEVICE)
            ref_mels = batch["ref_mels"].to(DEVICE)
            text_embedding_mask = batch["text_embedding_mask"].to(DEVICE)
            codec_embedding_mask = batch["codec_embedding_mask"].to(DEVICE)
            attention_mask = batch["attention_mask"].to(DEVICE)
            codec_0_labels = batch["codec_0_labels"].to(DEVICE)
            
            speaker_embedding = model.model.speaker_encoder(ref_mels.to(DEVICE).to(model.model.dtype)).detach()
            input_text_ids = input_ids[:, :, 0]
            input_codec_ids = input_ids[:, :, 1]
            
            text_emb_mod = model.model.talker.model.get_base_model().text_embedding
            codec_emb_mod = model.model.talker.model.get_base_model().codec_embedding
            
            input_text_embedding = text_emb_mod(input_text_ids)
            if hasattr(model.model.talker, 'text_projection') and model.model.talker.text_projection is not None:
                input_text_embedding = model.model.talker.text_projection(input_text_embedding)
            input_text_embedding = input_text_embedding * text_embedding_mask
            input_codec_embedding = codec_emb_mod(input_codec_ids) * codec_embedding_mask
            input_codec_embedding[:, 6, :] = speaker_embedding
            input_embeddings = input_text_embedding + input_codec_embedding
            
            outputs = model.model.talker(
                inputs_embeds=input_embeddings[:, :-1, :],
                attention_mask=attention_mask[:, :-1],
                labels=None,
            )
            talker_logits = outputs.logits
            loss = F.cross_entropy(
                talker_logits.reshape(-1, talker_logits.shape[-1]).float(),
                codec_0_labels[:, 1:].contiguous().reshape(-1),
                ignore_index=-100
            ) / grad_accum_steps
            
            loss.backward()
            epoch_loss += loss.item() * grad_accum_steps
            
            if b_idx % grad_accum_steps == 0 or b_idx == len(dataloader):
                optimizer.step()
                optimizer.zero_grad()
                step += 1
                
                if step % 50 == 0:
                    elapsed = time.time() - start_time
                    avg_loss = epoch_loss / b_idx
                    print(f"  [Epoch {epoch:02d}/{num_epochs:02d} | Step {step:>4}] Talker Loss: {avg_loss:.4f} (Elapsed: {elapsed/60:.1f}m)")
                    
        print(f"▶ Epoch {epoch:02d} Complete! Average Epoch Loss: {epoch_loss/len(dataloader):.4f}")
        
    print_header("Saving Final Trained Model Checkpoint")
    adapter_save_dir = ckpt_dir / "adapter_model"
    model.model.talker.model.save_pretrained(str(adapter_save_dir))
    print(f"Final LoRA Adapter saved to {adapter_save_dir}")
    
    # -------------------------------------------------------------
    # 20 Benchmark Sentences Synthesis & Faster-Whisper Evaluation
    # -------------------------------------------------------------
    print_header("20 Standard Cafe Ordering Benchmark Sentences Evaluation")
    model.model.eval()
    
    ref_audio = train_data[0]["audio"]
    ref_text = train_data[0]["text"]
    prompt = model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text, x_vector_only_mode=False)
    
    whisper = WhisperModel("tiny", device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
    results = []
    
    print(f"{'ID':<20} | {'Latency':<8} | {'Dur (s)':<8} | {'RTF':<6} | {'Whisper STT Transcription':<40}")
    print("-" * 95)
    
    for tag, text in BENCHMARK_20_SENTENCES:
        t0 = time.time()
        with torch.no_grad():
            wavs, sr = model.generate_voice_clone(
                text=text,
                voice_clone_prompt=prompt,
                language="Korean",
                max_new_tokens=120
            )
        infer_latency = time.time() - t0
        
        wav_path = eval_dir / f"{tag}.wav"
        sf.write(wav_path, wavs[0], sr)
        
        dur = len(wavs[0]) / sr
        rtf = infer_latency / dur if dur > 0 else 0
        rms = float((wavs[0]**2).mean()**0.5)
        
        segs, _ = whisper.transcribe(str(wav_path), language="ko")
        stt_text = "".join(s.text for s in segs).strip()
        
        print(f"{tag:<20} | {infer_latency:>6.2f}s | {dur:>6.2f}s | {rtf:>5.2f} | {stt_text:<40}")
        
        results.append({
            "tag": tag,
            "target": text,
            "stt": stt_text,
            "latency": infer_latency,
            "duration": dur,
            "rtf": rtf,
            "rms": rms,
            "rel_path": f"eval_wavs/{tag}.wav"
        })
        
    eval_json = out_dir / "benchmark_results.json"
    with open(eval_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    # Generate HTML Audio Player
    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>Qwen3-TTS (0.6B) All-Linear LoRA 299-Sample 최종 벤치마크 플레이어</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 30px; }}
        h1 {{ color: #38bdf8; }}
        .meta {{ background: #1e293b; padding: 15px; border-radius: 8px; margin-bottom: 25px; border-left: 4px solid #38bdf8; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-weight: 600; }}
        tr:hover {{ background: #334155; }}
        audio {{ height: 36px; width: 280px; }}
        .badge {{ background: #059669; color: #ecfdf5; padding: 3px 8px; border-radius: 4px; font-size: 0.85em; }}
    </style>
</head>
<body>
    <h1>☕ Qwen3-TTS (0.6B) 친절체 최종 벤치마크 (299개 전체 파인튜닝)</h1>
    <div class="meta">
        <strong>모델:</strong> Qwen3-TTS 12Hz 0.6B Base + All-Linear LoRA (r=16, alpha=32) + text_projection<br>
        <strong>화자:</strong> Speaker 010 (AI Hub 친절체 단일 여성 화자)<br>
        <strong>학습 데이터:</strong> 299개 전체 완주 (10 Epochs, LR=2e-6)<br>
        <strong>평가 항목:</strong> 대표 카페 주문 시나리오 20종 전수 합성
    </div>
    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>목표 문장 (Target Text)</th>
                <th>Whisper STT 전사</th>
                <th>음원 길이</th>
                <th>음성 재생</th>
            </tr>
        </thead>
        <tbody>
"""
    for r in results:
        html_content += f"""            <tr>
                <td><strong>{r['tag']}</strong></td>
                <td>{r['target']}</td>
                <td style="color: #67e8f9;">{r['stt']}</td>
                <td>{r['duration']:.2f}s</td>
                <td><audio controls src="{r['rel_path']}"></audio></td>
            </tr>
"""
    html_content += """        </tbody>
    </table>
</body>
</html>
"""
    player_path = out_dir / "eval_player.html"
    with open(player_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"\nHTML Audio Player created at: {player_path}")
    print_header("Full 299-Sample Training & 20-Sentence Benchmark Complete!")

if __name__ == "__main__":
    main()
