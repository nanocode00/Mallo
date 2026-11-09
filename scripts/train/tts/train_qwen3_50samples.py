#!/usr/bin/env python3
"""
Qwen3-TTS 0.6B 50-Sample Training & Evaluation Script
- Model: Qwen/Qwen3-TTS-12Hz-0.6B-Base
- LoRA: All-Linear (q, k, v, o, gate, up, down, r=16, alpha=32) + text_projection
- LR: 2e-6
- Steps: 600 steps (~24 epochs on 50 samples)
- Evaluation: 1 Train Sample + 5 Held-out Cafe Ordering Sentences with Faster-Whisper STT
"""

import os
import sys
import json
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

def main():
    print_header("Qwen3-TTS 0.6B 50-Sample Fine-Tuning")
    
    out_dir = Path("data/tts/runs/qwen3_50samples")
    eval_dir = out_dir / "eval_wavs"
    ckpt_dir = out_dir / "checkpoints"
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    
    # Load 50 samples
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    all_data = [json.loads(line) for line in open(train_jsonl)]
    train_50 = all_data[:50]
    print(f"Loaded {len(train_50)} training samples (Speaker: 010 Calm Friendly).")
    
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
    dataset = TTSDataset(train_50, model.processor, model.model.config)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=2, shuffle=True, collate_fn=dataset.collate_fn)
    
    # Optimizer & Scheduler
    trainable_list = [p for p in model.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_list, lr=2e-6, weight_decay=0.01)
    
    num_steps = 600
    print(f"Starting Training: {num_steps} steps, Batch Size: 2, LR: 2e-6...")
    
    step = 0
    epoch = 0
    model.model.train()
    
    while step < num_steps:
        epoch += 1
        epoch_loss = 0.0
        batch_count = 0
        
        for batch in dataloader:
            if step >= num_steps: break
            
            optimizer.zero_grad()
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
            )
            loss.backward()
            optimizer.step()
            
            step += 1
            epoch_loss += loss.item()
            batch_count += 1
            
            if step % 50 == 0:
                print(f"  [Step {step:>4}/{num_steps}] (Epoch {epoch:>2}) Talker Loss: {loss.item():.4f}")
                
    print(f"\nTraining Complete at Step {step}! Saving adapter checkpoint...")
    adapter_save_dir = ckpt_dir / "adapter_model"
    model.model.talker.model.save_pretrained(str(adapter_save_dir))
    print(f"Adapter saved to {adapter_save_dir}")
    
    # -------------------------------------------------------------
    # Evaluation on Train Sample & 5 Held-out Cafe Sentences
    # -------------------------------------------------------------
    print_header("Evaluation & Whisper STT Verification")
    model.model.eval()
    
    ref_audio = train_50[0]["audio"]
    ref_text = train_50[0]["text"]
    prompt = model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text, x_vector_only_mode=False)
    
    eval_sentences = [
        ("Train_01", train_50[0]["text"]),
        ("Heldout_01", "안녕하세요! 말로 카페입니다. 주문 도와드릴까요?"),
        ("Heldout_02", "주문하신 따뜻한 카페라떼 한 잔 나왔습니다."),
        ("Heldout_03", "아이스 아메리카노 두 잔과 치즈케이크 주문 확인되었습니다."),
        ("Heldout_04", "총 결제 금액은 9,000원입니다. 카드를 꽂아주세요."),
        ("Heldout_05", "이용해 주셔서 감사합니다. 좋은 하루 보내세요!")
    ]
    
    whisper = WhisperModel("tiny", device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
    results = []
    
    print(f"{'ID':<12} | {'Dur (s)':<8} | {'RMS':<7} | {'STT Transcription':<40}")
    print("-" * 75)
    
    for tag, text in eval_sentences:
        with torch.no_grad():
            wavs, sr = model.generate_voice_clone(
                text=text,
                voice_clone_prompt=prompt,
                language="Korean",
                max_new_tokens=100
            )
        wav_path = eval_dir / f"{tag}.wav"
        sf.write(wav_path, wavs[0], sr)
        
        dur = len(wavs[0]) / sr
        rms = float((wavs[0]**2).mean()**0.5)
        
        segs, _ = whisper.transcribe(str(wav_path), language="ko")
        stt_text = "".join(s.text for s in segs).strip()
        
        print(f"{tag:<12} | {dur:>6.2f}s | {rms:>6.4f} | {stt_text:<40}")
        results.append({
            "tag": tag,
            "target": text,
            "stt": stt_text,
            "duration": dur,
            "rms": rms,
            "wav_path": str(wav_path)
        })
        
    eval_summary_json = out_dir / "eval_summary.json"
    with open(eval_summary_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nEvaluation summary saved to {eval_summary_json}")
    
    print("\n" + "="*80)
    print("50-Sample Fine-Tuning and Evaluation Completed Successfully!")
    print("="*80)

if __name__ == "__main__":
    main()
