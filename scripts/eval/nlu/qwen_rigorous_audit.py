#!/usr/bin/env python3
"""
Qwen3-TTS 0.6B Rigorous Contract & Capacity Audit:
1. BOS / EOS / PAD ID 전수 확인 (4개 시점)
2. Zero-Update Train/Inference Equivalence Test (Greedy next-token causal contract)
3. Learning Rate 후보 분석
4. 1-Sample Step-based Tracker (0, 50, 100, 250, 500, 1000 steps)
5. Main Talker Full FT vs LoRA Control Test
6. LoRA Capacity Comparison
7. End-of-WAV Silence Distribution & Padding Test
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

def step1_token_id_audit():
    print_header("1. BOS / EOS / PAD ID 전수 확인 (4개 시점)")
    
    # 1. Base Config from Hub/Snapshot
    base_model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    from huggingface_hub import snapshot_download
    base_local_dir = snapshot_download(repo_id=base_model_id)
    with open(Path(base_local_dir) / "config.json") as f:
        base_cfg = json.load(f)
    t_cfg_base = base_cfg.get("talker_config", {})
    
    # 2. Checkpoint Config
    ckpt_cfg_path = Path("data/tts/runs/qwen3_lora_5ep/checkpoint_final/config.json")
    if ckpt_cfg_path.exists():
        with open(ckpt_cfg_path) as f:
            ckpt_cfg = json.load(f)
        t_cfg_ckpt = ckpt_cfg.get("talker_config", {})
    else:
        t_cfg_ckpt = {}
        
    # 3. Model Loaded
    model = Qwen3TTSModel.from_pretrained(base_model_id, dtype=torch.bfloat16, device_map=DEVICE)
    t_cfg_loaded = model.model.config.talker_config
    
    print(f"{'Config Source':<30} | {'codec_pad_id':<14} | {'codec_bos_id':<14} | {'codec_eos_id':<14}")
    print("-" * 80)
    print(f"{'1. Original Base config.json':<30} | {str(t_cfg_base.get('codec_pad_id')):<14} | {str(t_cfg_base.get('codec_bos_id')):<14} | {str(t_cfg_base.get('codec_eos_id', t_cfg_base.get('codec_eos_token_id'))):<14}")
    print(f"{'2. Checkpoint config.json':<30} | {str(t_cfg_ckpt.get('codec_pad_id')):<14} | {str(t_cfg_ckpt.get('codec_bos_id')):<14} | {str(t_cfg_ckpt.get('codec_eos_id', t_cfg_ckpt.get('codec_eos_token_id'))):<14}")
    print(f"{'3. Loaded model.config':<30} | {str(getattr(t_cfg_loaded, 'codec_pad_id', None)):<14} | {str(getattr(t_cfg_loaded, 'codec_bos_id', None)):<14} | {str(getattr(t_cfg_loaded, 'codec_eos_id', getattr(t_cfg_loaded, 'codec_eos_token_id', None))):<14}")
    
    # Also check special tokens
    print(f"\nAdditional Special Tokens in Base:")
    for k in ["codec_think_id", "codec_think_bos_id", "codec_think_eos_id", "codec_nothink_id"]:
        print(f"  - {k}: {t_cfg_base.get(k)}")
        
    pad_val = t_cfg_base.get("codec_pad_id")
    bos_val = t_cfg_base.get("codec_bos_id")
    eos_val = t_cfg_base.get("codec_eos_id", t_cfg_base.get("codec_eos_token_id"))
    
    is_valid = (pad_val == 0 or pad_val == 2148) and (bos_val in [2149, 2150])
    print(f"\nResult: {'PASS (ID 정의 확인)' if is_valid else 'FAIL'}")
    return model


def step2_zero_update_equivalence_test(model):
    print_header("2. Zero-Update Train / Inference Causal Equivalence Test")
    
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    sample = json.loads(open(train_jsonl).readline())
    
    model.model.to(DEVICE)
    model.model.eval()
    
    # 1. Run greedy generation (do_sample=False)
    prompt = model.create_voice_clone_prompt(ref_audio=sample["audio"], ref_text=sample["text"], x_vector_only_mode=False)
    
    # Trace generation greedy
    with torch.no_grad():
        wavs, sr = model.generate_voice_clone(
            text="안녕하세요",
            voice_clone_prompt=prompt,
            language="Korean",
            do_sample=False, # Pure greedy
            max_new_tokens=15
        )
    print(f"Greedy Generation completed (Duration: {len(wavs[0])/sr:.2f}s).")
    
    # Compare step-by-step prefill vs forward pass
    dataset = TTSDataset([sample], model.processor, model.model.config)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=dataset.collate_fn)
    batch = next(iter(dataloader))
    
    input_ids = batch["input_ids"].to(DEVICE)
    codec_ids = batch["codec_ids"].to(DEVICE)
    ref_mels = batch["ref_mels"].to(DEVICE)
    text_embedding_mask = batch["text_embedding_mask"].to(DEVICE)
    codec_embedding_mask = batch["codec_embedding_mask"].to(DEVICE)
    attention_mask = batch["attention_mask"].to(DEVICE)
    codec_0_labels = batch["codec_0_labels"].to(DEVICE)
    codec_mask = batch["codec_mask"].to(DEVICE)
    
    speaker_embedding = model.model.speaker_encoder(ref_mels.to(DEVICE).to(model.model.dtype)).detach()
    input_text_ids = input_ids[:, :, 0]
    input_codec_ids = input_ids[:, :, 1]
    
    input_text_embedding = model.model.talker.model.text_embedding(input_text_ids)
    if hasattr(model.model.talker, 'text_projection') and model.model.talker.text_projection is not None:
        input_text_embedding = model.model.talker.text_projection(input_text_embedding)
    input_text_embedding = input_text_embedding * text_embedding_mask
    input_codec_embedding = model.model.talker.model.codec_embedding(input_codec_ids) * codec_embedding_mask
    input_codec_embedding[:, 6, :] = speaker_embedding
    input_embeddings = input_text_embedding + input_codec_embedding
    
    with torch.no_grad():
        outputs = model.model.talker(
            inputs_embeds=input_embeddings[:, :-1, :],
            attention_mask=attention_mask[:, :-1],
            labels=None,
        )
        forward_logits = outputs.logits # [1, SeqLen, Vocab]
        forward_argmax = forward_logits.argmax(dim=-1) # [1, SeqLen]
        target_tokens = codec_0_labels[:, 1:]
        
    print(f"\nStep-by-Step Training Forward vs GT Comparison (First 10 Audio Frames):")
    print(f"{'Frame':<8} | {'Forward Argmax':<18} | {'GT Target Token':<18} | {'Match?'}")
    print("-" * 65)
    
    valid_positions = (target_tokens != -100).nonzero(as_tuple=True)[1]
    matches = 0
    for idx, pos in enumerate(valid_positions[:10]):
        pred_tok = forward_argmax[0, pos].item()
        gt_tok = target_tokens[0, pos].item()
        is_m = (pred_tok == gt_tok)
        if is_m: matches += 1
        print(f"{idx:<8} | {pred_tok:<18} | {gt_tok:<18} | {'YES' if is_m else 'no'}")
        
    print(f"\nBase Model Zero-Update Top-1 Match Rate on GT: {matches}/10 ({matches*10}%)")


def step7_eos_silence_distribution():
    print_header("7. EOS Silence Data Distribution (299 Samples)")
    
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    train_data = [json.loads(line) for line in open(train_jsonl)]
    
    silence_brackets = {
        "0~100ms": 0,
        "100~300ms": 0,
        "300~500ms": 0,
        "500ms 이상": 0,
    }
    
    silence_durations = []
    
    for item in train_data:
        wav_path = item["audio"]
        audio, sr = sf.read(wav_path)
        if audio.ndim > 1:
            audio = np.mean(audio, axis=-1)
            
        # Detect non-silent intervals with librosa
        non_silent = librosa.effects.split(audio, top_db=30)
        if len(non_silent) > 0:
            last_speech_end = non_silent[-1][1]
            silence_samples = len(audio) - last_speech_end
            silence_sec = silence_samples / sr
        else:
            silence_sec = 0.0
            
        silence_durations.append(silence_sec)
        
        if silence_sec < 0.1:
            silence_brackets["0~100ms"] += 1
        elif silence_sec < 0.3:
            silence_brackets["100~300ms"] += 1
        elif silence_sec < 0.5:
            silence_brackets["300~500ms"] += 1
        else:
            silence_brackets["500ms 이상"] += 1
            
    print("End-of-WAV Silence Duration Distribution across 299 Samples:")
    for b, count in silence_brackets.items():
        pct = (count / len(train_data)) * 100.0
        print(f"  - {b:<12}: {count:>3} samples ({pct:>5.1f}%)")
        
    mean_sil = np.mean(silence_durations) * 1000
    median_sil = np.median(silence_durations) * 1000
    print(f"\nMean Tail Silence:   {mean_sil:.1f} ms")
    print(f"Median Tail Silence: {median_sil:.1f} ms")


def step4_and_5_step_based_tracking_and_full_ft_control():
    print_header("4 & 5. 1-Sample Step-Based Tracking: LoRA vs Main Talker Full FT")
    
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    sample = json.loads(open(train_jsonl).readline())
    whisper = WhisperModel("tiny", device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
    
    out_dir = Path("data/tts/runs/qwen_step_tracking")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    target_steps = [0, 50, 100, 250, 500, 1000]
    
    # -------------------------------------------------------------
    # Experiment A: Main Talker Full Fine-Tuning (Control)
    # -------------------------------------------------------------
    print("\n" + "-"*70)
    print("▶ Running Control Experiment A: Main Talker Full Fine-Tuning (LR=1e-5)")
    print("-" * 70)
    
    model_ft = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-0.6B-Base", dtype=torch.bfloat16, device_map=DEVICE)
    # Freeze Code Predictor & Speaker Encoder, only train Talker LLM
    for p in model_ft.model.speaker_encoder.parameters(): p.requires_grad = False
    for p in model_ft.model.talker.code_predictor.parameters(): p.requires_grad = False
    for p in model_ft.model.talker.model.parameters(): p.requires_grad = True
    
    dataset = TTSDataset([sample], model_ft.processor, model_ft.model.config)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=dataset.collate_fn)
    batch = next(iter(dataloader))
    
    optimizer = torch.optim.AdamW(model_ft.model.talker.model.parameters(), lr=1e-5)
    
    results_ft = []
    
    for step in range(1001):
        if step in target_steps:
            model_ft.model.eval()
            with torch.no_grad():
                input_ids = batch["input_ids"].to(DEVICE)
                codec_ids = batch["codec_ids"].to(DEVICE)
                ref_mels = batch["ref_mels"].to(DEVICE)
                text_embedding_mask = batch["text_embedding_mask"].to(DEVICE)
                codec_embedding_mask = batch["codec_embedding_mask"].to(DEVICE)
                attention_mask = batch["attention_mask"].to(DEVICE)
                codec_0_labels = batch["codec_0_labels"].to(DEVICE)
                
                speaker_embedding = model_ft.model.speaker_encoder(ref_mels.to(DEVICE).to(model_ft.model.dtype)).detach()
                input_text_ids = input_ids[:, :, 0]
                input_codec_ids = input_ids[:, :, 1]
                
                input_text_embedding = model_ft.model.talker.model.text_embedding(input_text_ids)
                if hasattr(model_ft.model.talker, 'text_projection') and model_ft.model.talker.text_projection is not None:
                    input_text_embedding = model_ft.model.talker.text_projection(input_text_embedding)
                input_text_embedding = input_text_embedding * text_embedding_mask
                input_codec_embedding = model_ft.model.talker.model.codec_embedding(input_codec_ids) * codec_embedding_mask
                input_codec_embedding[:, 6, :] = speaker_embedding
                input_embeddings = input_text_embedding + input_codec_embedding
                
                outputs = model_ft.model.talker(
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
                
                # Synthesis & STT
                prompt = model_ft.create_voice_clone_prompt(ref_audio=sample["audio"], ref_text=sample["text"], x_vector_only_mode=False)
                wavs, sr = model_ft.generate_voice_clone(
                    text=sample["text"],
                    voice_clone_prompt=prompt,
                    language="Korean",
                    max_new_tokens=100
                )
                wav_file = out_dir / f"full_ft_step_{step}.wav"
                sf.write(wav_file, wavs[0], sr)
                dur = len(wavs[0]) / sr
                
                segs, _ = whisper.transcribe(str(wav_file), language="ko")
                stt_text = "".join(s.text for s in segs).strip()
                
                results_ft.append({
                    "step": step,
                    "loss": talker_loss,
                    "exact_acc": exact_acc,
                    "top5_acc": top5_acc,
                    "dur": dur,
                    "stt": stt_text
                })
                print(f"[Full FT Step {step:>4}] Loss: {talker_loss:.4f} | Exact Acc: {exact_acc:>5.1f}% | Top-5: {top5_acc:>5.1f}% | Dur: {dur:.2f}s | STT: '{stt_text[:40]}'")
                
        if step < 1000:
            model_ft.model.train()
            optimizer.zero_grad()
            
            input_ids = batch["input_ids"].to(DEVICE)
            codec_ids = batch["codec_ids"].to(DEVICE)
            ref_mels = batch["ref_mels"].to(DEVICE)
            text_embedding_mask = batch["text_embedding_mask"].to(DEVICE)
            codec_embedding_mask = batch["codec_embedding_mask"].to(DEVICE)
            attention_mask = batch["attention_mask"].to(DEVICE)
            codec_0_labels = batch["codec_0_labels"].to(DEVICE)
            
            speaker_embedding = model_ft.model.speaker_encoder(ref_mels.to(DEVICE).to(model_ft.model.dtype)).detach()
            input_text_ids = input_ids[:, :, 0]
            input_codec_ids = input_ids[:, :, 1]
            
            input_text_embedding = model_ft.model.talker.model.text_embedding(input_text_ids)
            if hasattr(model_ft.model.talker, 'text_projection') and model_ft.model.talker.text_projection is not None:
                input_text_embedding = model_ft.model.talker.text_projection(input_text_embedding)
            input_text_embedding = input_text_embedding * text_embedding_mask
            input_codec_embedding = model_ft.model.talker.model.codec_embedding(input_codec_ids) * codec_embedding_mask
            input_codec_embedding[:, 6, :] = speaker_embedding
            input_embeddings = input_text_embedding + input_codec_embedding
            
            outputs = model_ft.model.talker(
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
            
    # -------------------------------------------------------------
    # Experiment B: LoRA (q_proj, v_proj) with LR=2e-6
    # -------------------------------------------------------------
    print("\n" + "-"*70)
    print("▶ Running Experiment B: LoRA (q, v) with Conservative LR=2e-6")
    print("-" * 70)
    
    model_lora = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-0.6B-Base", dtype=torch.bfloat16, device_map=DEVICE)
    lora_config = LoraConfig(r=8, lora_alpha=16, target_modules=["q_proj", "v_proj"], bias="none")
    model_lora.model.talker.model = get_peft_model(model_lora.model.talker.model, lora_config)
    
    optimizer_lora = torch.optim.AdamW(model_lora.model.talker.model.parameters(), lr=2e-6)
    results_lora = []
    
    for step in range(1001):
        if step in target_steps:
            model_lora.model.eval()
            with torch.no_grad():
                input_ids = batch["input_ids"].to(DEVICE)
                codec_ids = batch["codec_ids"].to(DEVICE)
                ref_mels = batch["ref_mels"].to(DEVICE)
                text_embedding_mask = batch["text_embedding_mask"].to(DEVICE)
                codec_embedding_mask = batch["codec_embedding_mask"].to(DEVICE)
                attention_mask = batch["attention_mask"].to(DEVICE)
                codec_0_labels = batch["codec_0_labels"].to(DEVICE)
                
                speaker_embedding = model_lora.model.speaker_encoder(ref_mels.to(DEVICE).to(model_lora.model.dtype)).detach()
                input_text_ids = input_ids[:, :, 0]
                input_codec_ids = input_ids[:, :, 1]
                
                input_text_embedding = model_lora.model.talker.model.get_base_model().text_embedding(input_text_ids)
                if hasattr(model_lora.model.talker, 'text_projection') and model_lora.model.talker.text_projection is not None:
                    input_text_embedding = model_lora.model.talker.text_projection(input_text_embedding)
                input_text_embedding = input_text_embedding * text_embedding_mask
                input_codec_embedding = model_lora.model.talker.model.get_base_model().codec_embedding(input_codec_ids) * codec_embedding_mask
                input_codec_embedding[:, 6, :] = speaker_embedding
                input_embeddings = input_text_embedding + input_codec_embedding
                
                outputs = model_lora.model.talker(
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
                
                prompt = model_lora.create_voice_clone_prompt(ref_audio=sample["audio"], ref_text=sample["text"], x_vector_only_mode=False)
                wavs, sr = model_lora.generate_voice_clone(
                    text=sample["text"],
                    voice_clone_prompt=prompt,
                    language="Korean",
                    max_new_tokens=100
                )
                wav_file = out_dir / f"lora_step_{step}.wav"
                sf.write(wav_file, wavs[0], sr)
                dur = len(wavs[0]) / sr
                
                segs, _ = whisper.transcribe(str(wav_file), language="ko")
                stt_text = "".join(s.text for s in segs).strip()
                
                results_lora.append({
                    "step": step,
                    "loss": talker_loss,
                    "exact_acc": exact_acc,
                    "top5_acc": top5_acc,
                    "dur": dur,
                    "stt": stt_text
                })
                print(f"[LoRA Step {step:>4}] Loss: {talker_loss:.4f} | Exact Acc: {exact_acc:>5.1f}% | Top-5: {top5_acc:>5.1f}% | Dur: {dur:.2f}s | STT: '{stt_text[:40]}'")
                
        if step < 1000:
            model_lora.model.train()
            optimizer_lora.zero_grad()
            
            input_ids = batch["input_ids"].to(DEVICE)
            codec_ids = batch["codec_ids"].to(DEVICE)
            ref_mels = batch["ref_mels"].to(DEVICE)
            text_embedding_mask = batch["text_embedding_mask"].to(DEVICE)
            codec_embedding_mask = batch["codec_embedding_mask"].to(DEVICE)
            attention_mask = batch["attention_mask"].to(DEVICE)
            codec_0_labels = batch["codec_0_labels"].to(DEVICE)
            
            speaker_embedding = model_lora.model.speaker_encoder(ref_mels.to(DEVICE).to(model_lora.model.dtype)).detach()
            input_text_ids = input_ids[:, :, 0]
            input_codec_ids = input_ids[:, :, 1]
            
            input_text_embedding = model_lora.model.talker.model.get_base_model().text_embedding(input_text_ids)
            if hasattr(model_lora.model.talker, 'text_projection') and model_lora.model.talker.text_projection is not None:
                input_text_embedding = model_lora.model.talker.text_projection(input_text_embedding)
            input_text_embedding = input_text_embedding * text_embedding_mask
            input_codec_embedding = model_lora.model.talker.model.get_base_model().codec_embedding(input_codec_ids) * codec_embedding_mask
            input_codec_embedding[:, 6, :] = speaker_embedding
            input_embeddings = input_text_embedding + input_codec_embedding
            
            outputs = model_lora.model.talker(
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
            optimizer_lora.step()
            
    return results_ft, results_lora


def main():
    print("="*80)
    print("Qwen3-TTS 0.6B Contract, Capacity, and Alignment Audit Suite")
    print("="*80)
    
    # 1. Token ID Audit
    model = step1_token_id_audit()
    
    # 2. Zero-Update Equivalence Test
    step2_zero_update_equivalence_test(model)
    
    # 7. EOS Silence Distribution
    step7_eos_silence_distribution()
    
    # 4 & 5. Step-based Tracking & Full FT Control
    results_ft, results_lora = step4_and_5_step_based_tracking_and_full_ft_control()
    
    print("\n" + "="*80)
    print("Audit Suite Execution Finished Successfully!")
    print("="*80)

if __name__ == "__main__":
    main()
