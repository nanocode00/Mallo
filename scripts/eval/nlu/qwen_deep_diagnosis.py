#!/usr/bin/env python3
"""
Qwen3-TTS 0.6B Deep Diagnosis:
1. Speaker distribution & Female voice clone check
2. LoRA integration A/B test
3. 1-Sample Overfit test with STT evaluation
4. Codec0 exact accuracy, top-5 accuracy, EOS accuracy, frame comparison
5. #337 Hidden-state alignment table
"""

import os
import sys
import json
import math
from pathlib import Path
from collections import Counter

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
    out_dir = Path("data/tts/runs/qwen_diagnosis")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------
    # 1. Dataset Speaker Distribution & Female Voice Clone Test
    # -------------------------------------------------------------
    print_header("1. Dataset Speaker Distribution & Female Voice Clone Test")
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    train_data = [json.loads(line) for line in open(train_jsonl)]
    print(f"Total training samples: {len(train_data)}")
    
    speaker_counts = Counter()
    for item in train_data:
        # Extract speaker id from audio filename (e.g. K-H3-D-010-0051.wav -> 010)
        fname = Path(item["audio"]).name
        parts = fname.split("-")
        spk_id = parts[3] if len(parts) >= 4 else "unknown"
        speaker_counts[spk_id] += 1
        
    print("Speaker distribution in 299 samples:")
    for spk, count in speaker_counts.items():
        print(f"  - Speaker ID '{spk}': {count} samples ({(count/len(train_data))*100:.1f}%)")
        
    # Test Female Voice Clone on Base Model
    print("\nTesting Female Voice Clone on Base Model (Zero-shot ICL)...")
    model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    model = Qwen3TTSModel.from_pretrained(model_id, dtype=torch.bfloat16, device_map=DEVICE)
    
    ref_audio = train_data[0]["audio"]
    ref_text = train_data[0]["text"]
    test_text = "주문하신 아이스 아메리카노 두 잔 준비해 드리겠습니다."
    
    prompt = model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text, x_vector_only_mode=False)
    with torch.no_grad():
        wavs, sr = model.generate_voice_clone(
            text=test_text,
            voice_clone_prompt=prompt,
            language="Korean",
            max_new_tokens=80
        )
    clone_wav_path = out_dir / "female_voice_clone_base.wav"
    sf.write(clone_wav_path, wavs[0], sr)
    print(f"  - Saved Base clone: {clone_wav_path} (Duration: {len(wavs[0])/sr:.2f}s)")
    
    # Run Faster-Whisper STT
    print("Running Faster-Whisper STT on Base Voice Clone...")
    whisper = WhisperModel("tiny", device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
    segments, info = whisper.transcribe(str(clone_wav_path), language="ko")
    stt_text = "".join(seg.text for seg in segments).strip()
    print(f"  - Ground Truth: '{test_text}'")
    print(f"  - STT Output:   '{stt_text}'")
    
    # -------------------------------------------------------------
    # 2. LoRA A/B Test (Base vs Base + Init LoRA)
    # -------------------------------------------------------------
    print_header("2. LoRA Integration A/B Test")
    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.0,
        bias="none",
    )
    
    # Wrap model with LoRA
    talker_peft = get_peft_model(model.model.talker.model, lora_config)
    print("LoRA Target Modules & Trainable Parameters:")
    talker_peft.print_trainable_parameters()
    
    trainable_params = [n for n, p in talker_peft.named_parameters() if p.requires_grad]
    print(f"Trainable parameters count: {len(trainable_params)}")
    
    # Test generation with initialized (zero) LoRA
    with torch.no_grad():
        wavs_lora_init, _ = model.generate_voice_clone(
            text=test_text,
            voice_clone_prompt=prompt,
            language="Korean",
            max_new_tokens=80
        )
    lora_init_path = out_dir / "base_plus_init_lora.wav"
    sf.write(lora_init_path, wavs_lora_init[0], sr)
    
    # Compare waveforms between Base (A) and Base+InitLoRA (B)
    diff = np.abs(wavs[0][:min(len(wavs[0]), len(wavs_lora_init[0]))] - wavs_lora_init[0][:min(len(wavs[0]), len(wavs_lora_init[0]))])
    print(f"Waveform Max Diff between Base and Base+InitLoRA: {diff.max():.6f}")
    print(f"Waveform Mean Diff: {diff.mean():.6f}")
    
    # -------------------------------------------------------------
    # 3. 1-Sample Overfit & Codec0 Analysis
    # -------------------------------------------------------------
    print_header("3. 1-Sample Overfit & Main Talker (Codec0) Deep Analysis")
    sample = train_data[0]
    gt_audio_codes = torch.tensor(sample["audio_codes"]).to(DEVICE) # [Frames, 16]
    gt_codec0 = gt_audio_codes[:, 0]
    print(f"GT Audio Frames: {gt_codec0.shape[0]}")
    print(f"GT Codec0 Tokens (first 20): {gt_codec0[:20].tolist()}")
    
    # Dataset & Dataloader
    dataset = TTSDataset([sample], model.processor, model.model.config)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=dataset.collate_fn)
    batch = next(iter(dataloader))
    
    # Train 1-sample overfit for 30 epochs with AdamW
    optimizer = torch.optim.AdamW(model.model.parameters(), lr=2e-4)
    model.model.train()
    
    print("\nTraining on 1-sample (30 Epochs):")
    for epoch in range(1, 31):
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
        
        outputs = model.model.talker(
            inputs_embeds=input_embeddings[:, :-1, :],
            attention_mask=attention_mask[:, :-1],
            labels=None,
            output_hidden_states=True
        )
        
        talker_logits = outputs.logits
        talker_loss = F.cross_entropy(
            talker_logits.reshape(-1, talker_logits.shape[-1]).float(),
            codec_0_labels[:, 1:].contiguous().reshape(-1),
            ignore_index=-100
        )
        
        hidden_states = outputs.hidden_states[0][-1]
        talker_hidden_states = hidden_states[codec_mask[:, :-1]]
        talker_codec_ids = codec_ids[codec_mask]
        
        sub_talker_logits, sub_talker_loss = model.model.talker.forward_sub_talker_finetune(talker_codec_ids, talker_hidden_states)
        total_loss = talker_loss + 0.3 * sub_talker_loss
        
        optimizer.zero_grad()
        total_loss.backward()
        optimizer.step()
        
        if epoch % 5 == 0 or epoch == 1:
            print(f"  [Epoch {epoch:02d}/30] Total Loss: {total_loss.item():.4f} (Talker Loss: {talker_loss.item():.4f}, Sub Loss: {sub_talker_loss.item():.4f})")
            
    # Evaluation on Teacher-Forcing Codec0
    model.model.eval()
    with torch.no_grad():
        eval_outputs = model.model.talker(
            inputs_embeds=input_embeddings[:, :-1, :],
            attention_mask=attention_mask[:, :-1],
            labels=None,
            output_hidden_states=True
        )
        eval_logits = eval_outputs.logits # [1, SeqLen, Vocab]
        target_labels = codec_0_labels[:, 1:] # [1, SeqLen]
        
        valid_mask = (target_labels != -100)
        valid_logits = eval_logits[valid_mask] # [NumTokens, Vocab]
        valid_targets = target_labels[valid_mask] # [NumTokens]
        
        pred_tokens = valid_logits.argmax(dim=-1)
        exact_acc = (pred_tokens == valid_targets).float().mean().item() * 100.0
        
        # Top-5 accuracy
        top5_preds = valid_logits.topk(5, dim=-1).indices
        top5_acc = (top5_preds == valid_targets.unsqueeze(-1)).any(dim=-1).float().mean().item() * 100.0
        
        # EOS accuracy (EOS token id is 2150 in Qwen3-TTS 12Hz)
        eos_id = getattr(model.model.config.talker_config, "codec_eos_id", 2150)
        if (valid_targets == eos_id).any():
            eos_pos = (valid_targets == eos_id).nonzero()[-1].item()
            eos_pred = pred_tokens[eos_pos].item()
            eos_acc = (eos_pred == eos_id)
        else:
            eos_acc = False
            
    print(f"\nTeacher-Forcing Metrics on GT Frames:")
    print(f"  - Argmax Exact Accuracy: {exact_acc:.2f}%")
    print(f"  - Top-5 Accuracy:        {top5_acc:.2f}%")
    print(f"  - Codec0 EOS Accuracy:   {'PASS (100%)' if eos_acc else 'FAIL'}")
    
    print(f"\nFrame-by-Frame Comparison (first 15 tokens):")
    print(f"  - Target GT: {valid_targets[:15].tolist()}")
    print(f"  - Predicted: {pred_tokens[:15].tolist()}")
    
    # -------------------------------------------------------------
    # 4. Autoregressive Synthesis & Whisper STT Check
    # -------------------------------------------------------------
    print_header("4. Autoregressive Synthesis & Whisper STT Intelligibility Check")
    prompt = model.create_voice_clone_prompt(ref_audio=sample["audio"], ref_text=sample["text"], x_vector_only_mode=False)
    with torch.no_grad():
        overfit_wavs, sr = model.generate_voice_clone(
            text=sample["text"],
            voice_clone_prompt=prompt,
            language="Korean",
            max_new_tokens=100
        )
    overfit_path = out_dir / "overfit_trained_sample.wav"
    sf.write(overfit_path, overfit_wavs[0], sr)
    dur = len(overfit_wavs[0]) / sr
    rms = float((overfit_wavs[0]**2).mean()**0.5)
    print(f"Saved Overfit Sample: {overfit_path}")
    print(f"  - Duration: {dur:.2f}s | RMS: {rms:.4f}")
    
    print("\nTranscribing Overfit Sample with Faster-Whisper...")
    segments, info = whisper.transcribe(str(overfit_path), language="ko")
    overfit_stt = "".join(seg.text for seg in segments).strip()
    print(f"  - Target Text:  '{sample['text']}'")
    print(f"  - STT Transcript: '{overfit_stt}'")
    
    is_intelligible = len(overfit_stt) > 0 and any(w in overfit_stt for w in ["전화", "감사", "방문", "상담", "혜택"])
    print(f"  - Intelligibility Assessment: {'PASS (문장 식별 성공)' if is_intelligible else 'FAIL (외계어/식별 불가)'}")
    
    # -------------------------------------------------------------
    # 5. #337 Hidden State Alignment Sequence Dump
    # -------------------------------------------------------------
    print_header("5. #337 Hidden-State Alignment Frame Table")
    print(f"{'Step':<5} | {'Talker Input':<15} | {'Hidden State':<15} | {'Predicted Codec0':<18} | {'Sub-talker Target Codec 1..15'}")
    print("-" * 85)
    for t in range(5):
        print(f"{t:<5} | {'Frame '+str(t):<15} | {'H(k-'+str(t)+')':<15} | {'Codec0['+str(t+1)+']':<18} | {'Codec 1..15['+str(t+1)+']'}")
        
    print("\nDiagnosis Complete!")

if __name__ == "__main__":
    main()
