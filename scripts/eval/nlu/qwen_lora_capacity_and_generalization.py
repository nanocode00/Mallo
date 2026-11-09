#!/usr/bin/env python3
"""
Qwen3-TTS 0.6B LoRA Capacity & Generalization Experiments:
1. All-Linear LoRA (q, k, v, o, gate, up, down) r=16 / r=32
2. Selective Unfreeze (text_projection, codec_head)
3. Step-by-step 1-Sample evaluation (0, 50, 100, 250, 500, 1000)
4. Small-Subset Generalization Test (16 samples) on Train & Held-out sentences
"""

import os
import sys
import json
import math
import shutil
from pathlib import Path
from collections import Counter

import torch
import torch.nn as nn
import torch.nn.functional as F
import soundfile as sf
import numpy as np
import librosa
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

def train_and_eval_1sample(model_name, lora_config, unfreeze_modules, lr, num_steps=1000, target_steps=[0, 50, 100, 250, 500, 1000]):
    print(f"\n--- Running 1-Sample Test: {model_name} (LR={lr}) ---")
    
    out_dir = Path(f"data/tts/runs/qwen_capacity/{model_name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    sample = json.loads(open(train_jsonl).readline())
    whisper = WhisperModel("tiny", device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
    
    # Load Model
    model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-0.6B-Base", dtype=torch.bfloat16, device_map=DEVICE)
    
    # Freeze / Unfreeze
    for p in model.model.speaker_encoder.parameters(): p.requires_grad = False
    for p in model.model.talker.code_predictor.parameters(): p.requires_grad = False
    
    if lora_config is not None:
        model.model.talker.model = get_peft_model(model.model.talker.model, lora_config)
    else:
        for p in model.model.talker.model.parameters(): p.requires_grad = True
        
    if unfreeze_modules:
        if "text_projection" in unfreeze_modules and hasattr(model.model.talker, "text_projection") and model.model.talker.text_projection is not None:
            for p in model.model.talker.text_projection.parameters(): p.requires_grad = True
        if "codec_head" in unfreeze_modules and hasattr(model.model.talker, "codec_head") and model.model.talker.codec_head is not None:
            for p in model.model.talker.codec_head.parameters(): p.requires_grad = True
            
    trainable_params = sum(p.numel() for p in model.model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.model.parameters())
    print(f"Trainable Parameters: {trainable_params:,} ({trainable_params/total_params*100:.2f}%)")
    
    # Dataset & Dataloader
    dataset = TTSDataset([sample], model.processor, model.model.config)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=dataset.collate_fn)
    batch = next(iter(dataloader))
    
    # Trainable param optimizer
    trainable_list = [p for p in model.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_list, lr=lr)
    
    results = []
    
    for step in range(num_steps + 1):
        if step in target_steps:
            model.model.eval()
            with torch.no_grad():
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
                
                if lora_config is not None:
                    text_emb_mod = model.model.talker.model.get_base_model().text_embedding
                    codec_emb_mod = model.model.talker.model.get_base_model().codec_embedding
                else:
                    text_emb_mod = model.model.talker.model.text_embedding
                    codec_emb_mod = model.model.talker.model.codec_embedding
                    
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
                logits = outputs.logits
                talker_loss = F.cross_entropy(
                    logits.reshape(-1, logits.shape[-1]).float(),
                    codec_0_labels[:, 1:].contiguous().reshape(-1),
                    ignore_index=-100
                ).item()
                
                valid_mask = (codec_0_labels[:, 1:] != -100)
                v_logits = logits[valid_mask]
                v_targets = codec_0_labels[:, 1:][valid_mask]
                
                exact_acc = (v_logits.argmax(dim=-1) == v_targets).float().mean().item() * 100.0
                top5_acc = (v_logits.topk(5, dim=-1).indices == v_targets.unsqueeze(-1)).any(dim=-1).float().mean().item() * 100.0
                
                # Check EOS accuracy
                eos_id = 2150
                eos_pos = (v_targets == eos_id).nonzero()
                if len(eos_pos) > 0:
                    eos_idx = eos_pos[-1].item()
                    eos_pred = v_logits.argmax(dim=-1)[eos_idx].item()
                    eos_acc = "100%" if eos_pred == eos_id else "0%"
                else:
                    eos_acc = "N/A"
                    
                # Synthesis & STT
                prompt = model.create_voice_clone_prompt(ref_audio=sample["audio"], ref_text=sample["text"], x_vector_only_mode=False)
                wavs, sr = model.generate_voice_clone(
                    text=sample["text"],
                    voice_clone_prompt=prompt,
                    language="Korean",
                    max_new_tokens=100
                )
                wav_file = out_dir / f"step_{step}.wav"
                sf.write(wav_file, wavs[0], sr)
                dur = len(wavs[0]) / sr
                
                segs, _ = whisper.transcribe(str(wav_file), language="ko")
                stt_text = "".join(s.text for s in segs).strip()
                
                res = {
                    "step": step,
                    "loss": talker_loss,
                    "exact_acc": exact_acc,
                    "top5_acc": top5_acc,
                    "eos_acc": eos_acc,
                    "dur": dur,
                    "stt": stt_text,
                    "trainable_params": trainable_params
                }
                results.append(res)
                print(f"  [Step {step:>4}] Loss: {talker_loss:.4f} | Exact: {exact_acc:>5.1f}% | Top-5: {top5_acc:>5.1f}% | EOS: {eos_acc:<4} | Dur: {dur:.2f}s | STT: '{stt_text[:40]}'")
                
        if step < num_steps:
            model.model.train()
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
            
            if lora_config is not None:
                text_emb_mod = model.model.talker.model.get_base_model().text_embedding
                codec_emb_mod = model.model.talker.model.get_base_model().codec_embedding
            else:
                text_emb_mod = model.model.talker.model.text_embedding
                codec_emb_mod = model.model.talker.model.codec_embedding
                
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
            
    return model, results


def run_16_sample_generalization(best_model_fn, lr=2e-6, num_steps=500):
    print_header("5. Small-Subset Generalization Test (16 Samples)")
    
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    all_data = [json.loads(line) for line in open(train_jsonl)]
    train_16 = all_data[:16]
    whisper = WhisperModel("tiny", device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
    
    out_dir = Path("data/tts/runs/qwen_generalization_16")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize best model config (All-Linear LoRA + text_projection)
    model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-0.6B-Base", dtype=torch.bfloat16, device_map=DEVICE)
    for p in model.model.speaker_encoder.parameters(): p.requires_grad = False
    for p in model.model.talker.code_predictor.parameters(): p.requires_grad = False
    
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none"
    )
    model.model.talker.model = get_peft_model(model.model.talker.model, lora_config)
    if hasattr(model.model.talker, "text_projection") and model.model.talker.text_projection is not None:
        for p in model.model.talker.text_projection.parameters(): p.requires_grad = True
        
    dataset = TTSDataset(train_16, model.processor, model.model.config)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=2, shuffle=True, collate_fn=dataset.collate_fn)
    
    trainable_list = [p for p in model.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_list, lr=lr)
    
    print(f"Training on 16 samples for {num_steps} steps (LR={lr})...")
    step = 0
    model.model.train()
    
    while step < num_steps:
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
            
            if step % 100 == 0:
                print(f"  [16-Sample Step {step:>4}/{num_steps}] Talker Loss: {loss.item():.4f}")
                
    # Evaluate on Train Sample
    print("\n--- Evaluating 16-Sample Model on Train Sample ---")
    model.model.eval()
    train_sample = train_16[0]
    prompt = model.create_voice_clone_prompt(ref_audio=train_sample["audio"], ref_text=train_sample["text"], x_vector_only_mode=False)
    with torch.no_grad():
        train_wavs, sr = model.generate_voice_clone(
            text=train_sample["text"],
            voice_clone_prompt=prompt,
            language="Korean",
            max_new_tokens=100
        )
    train_wav_path = out_dir / "eval_train_sample.wav"
    sf.write(train_wav_path, train_wavs[0], sr)
    segs, _ = whisper.transcribe(str(train_wav_path), language="ko")
    train_stt = "".join(s.text for s in segs).strip()
    print(f"  - Target Text: '{train_sample['text']}'")
    print(f"  - STT Output:  '{train_stt}'")
    print(f"  - Duration:    {len(train_wavs[0])/sr:.2f}s")
    
    # Evaluate on Held-out Unseen Sentences
    print("\n--- Evaluating 16-Sample Model on Held-out Unseen Sentence ---")
    heldout_text = "주문하신 따뜻한 카페라떼 나왔습니다. 영수증 필요하신가요?"
    with torch.no_grad():
        held_wavs, sr = model.generate_voice_clone(
            text=heldout_text,
            voice_clone_prompt=prompt,
            language="Korean",
            max_new_tokens=100
        )
    held_wav_path = out_dir / "eval_heldout_sample.wav"
    sf.write(held_wav_path, held_wavs[0], sr)
    segs, _ = whisper.transcribe(str(held_wav_path), language="ko")
    held_stt = "".join(s.text for s in segs).strip()
    print(f"  - Target Text: '{heldout_text}'")
    print(f"  - STT Output:  '{held_stt}'")
    print(f"  - Duration:    {len(held_wavs[0])/sr:.2f}s")
    
    return train_stt, held_stt


def main():
    print("="*80)
    print("Qwen3-TTS 0.6B LoRA Capacity Expansion & Generalization Evaluation")
    print("="*80)
    
    # 1. Config A: q/v LoRA (baseline)
    lora_qv = LoraConfig(r=8, lora_alpha=16, target_modules=["q_proj", "v_proj"], bias="none")
    _, res_qv = train_and_eval_1sample("lora_qv", lora_qv, [], lr=2e-6, num_steps=500, target_steps=[0, 100, 250, 500])
    
    # 2. Config B: All-Linear LoRA r=16
    lora_all_r16 = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none"
    )
    _, res_all_r16 = train_and_eval_1sample("lora_all_r16", lora_all_r16, [], lr=5e-6, num_steps=500, target_steps=[0, 100, 250, 500])
    
    # 3. Config C: All-Linear LoRA r=16 + Selective Unfreeze (text_projection)
    _, res_all_proj = train_and_eval_1sample("lora_all_plus_proj", lora_all_r16, ["text_projection"], lr=5e-6, num_steps=500, target_steps=[0, 100, 250, 500])
    
    # 4. Config D: Full FT (Control)
    _, res_full_ft = train_and_eval_1sample("full_ft_control", None, ["text_projection"], lr=5e-6, num_steps=500, target_steps=[0, 100, 250, 500])
    
    # 5. Small-subset Generalization (16 samples)
    train_stt, held_stt = run_16_sample_generalization(None, lr=2e-6, num_steps=400)
    
    print("\n" + "="*80)
    print("All Experiments Completed Successfully!")
    print("="*80)

if __name__ == "__main__":
    main()
