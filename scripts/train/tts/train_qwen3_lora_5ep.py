#!/usr/bin/env python3
"""Qwen3-TTS 0.6B LoRA 5 Epoch 파인튜닝 및 20개 문장 평가 생성 스크립트"""

import os
import json
import shutil
import torch
from pathlib import Path
from torch.utils.data import DataLoader
from torch.optim import AdamW
from transformers import AutoConfig
from accelerate import Accelerator
from peft import LoraConfig, get_peft_model
from safetensors.torch import save_file
import soundfile as sf
import base64

import sys
sys.path.insert(0, "data/tts/repos/Qwen3-TTS")
sys.path.insert(0, "data/tts/repos/Qwen3-TTS/finetuning")

from dataset import TTSDataset
from qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel
from huggingface_hub import snapshot_download

def main():
    model_id = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    train_jsonl = "data/tts/runs/qwen3/train_with_codes.jsonl"
    out_dir = Path("data/tts/runs/qwen3_lora_5ep")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    accelerator = Accelerator(gradient_accumulation_steps=4, mixed_precision="bf16")
    
    local_path = snapshot_download(repo_id=model_id)
    
    print("1. Loading Qwen3TTSModel...")
    qwen3tts = Qwen3TTSModel.from_pretrained(
        model_id,
        dtype=torch.bfloat16,
    )
    config = AutoConfig.from_pretrained(model_id)
    
    # Apply LoRA on Talker self-attention layers
    print("2. Applying LoRA (r=8, alpha=16) on Talker LLM...")
    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.05,
        bias="none",
    )
    
    # Wrap talker.model with LoRA
    qwen3tts.model.talker.model = get_peft_model(qwen3tts.model.talker.model, lora_config)
    qwen3tts.model.talker.model.print_trainable_parameters()
    
    # Load dataset
    train_data = [json.loads(line) for line in open(train_jsonl)]
    dataset = TTSDataset(train_data, qwen3tts.processor, config)
    train_loader = DataLoader(dataset, batch_size=2, shuffle=True, collate_fn=dataset.collate_fn)
    
    optimizer = AdamW(qwen3tts.model.parameters(), lr=5e-5, weight_decay=0.01)
    
    model, optimizer, train_loader = accelerator.prepare(
        qwen3tts.model, optimizer, train_loader
    )
    
    target_speaker_embedding = None
    
    print("3. Starting 5-Epoch LoRA Training...")
    model.train()
    for epoch in range(5):
        epoch_loss = 0.0
        steps = 0
        for step, batch in enumerate(train_loader):
            with accelerator.accumulate(model):
                input_ids = batch["input_ids"]
                codec_ids = batch["codec_ids"]
                ref_mels = batch["ref_mels"]
                text_embedding_mask = batch["text_embedding_mask"]
                codec_embedding_mask = batch["codec_embedding_mask"]
                attention_mask = batch["attention_mask"]
                codec_0_labels = batch["codec_0_labels"]
                codec_mask = batch["codec_mask"]
                
                speaker_embedding = model.speaker_encoder(ref_mels.to(model.device).to(model.dtype)).detach()
                if target_speaker_embedding is None:
                    target_speaker_embedding = speaker_embedding
                    
                input_text_ids = input_ids[:, :, 0]
                input_codec_ids = input_ids[:, :, 1]
                
                input_text_embedding = model.talker.model.get_base_model().text_embedding(input_text_ids) * text_embedding_mask
                if hasattr(model.talker, "text_projection") and model.talker.text_projection is not None:
                    input_text_embedding = model.talker.text_projection(input_text_embedding)
                    
                input_codec_embedding = model.talker.model.get_base_model().codec_embedding(input_codec_ids) * codec_embedding_mask
                input_codec_embedding[:, 6, :] = speaker_embedding
                
                input_embeddings = input_text_embedding + input_codec_embedding
                
                for i in range(1, 16):
                    codec_i_embedding = model.talker.code_predictor.get_input_embeddings()[i - 1](codec_ids[:, :, i])
                    codec_i_embedding = codec_i_embedding * codec_mask.unsqueeze(-1)
                    input_embeddings = input_embeddings + codec_i_embedding
                    
                outputs = model.talker(
                    inputs_embeds=input_embeddings[:, :-1, :],
                    attention_mask=attention_mask[:, :-1],
                    labels=None,
                    output_hidden_states=True
                )
                
                # Direct single-shift cross-entropy (prevents Double Shift bug)
                talker_logits = outputs.logits
                talker_loss = torch.nn.functional.cross_entropy(
                    talker_logits.reshape(-1, talker_logits.shape[-1]).float(),
                    codec_0_labels[:, 1:].contiguous().reshape(-1),
                    ignore_index=-100
                )
                
                hidden_states = outputs.hidden_states[0][-1]
                talker_hidden_states = hidden_states[codec_mask[:, :-1]]
                talker_codec_ids = codec_ids[codec_mask]
                
                sub_talker_logits, sub_talker_loss = model.talker.forward_sub_talker_finetune(talker_codec_ids, talker_hidden_states)
                loss = talker_loss + 0.3 * sub_talker_loss
                
                accelerator.backward(loss)
                if accelerator.sync_gradients:
                    accelerator.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                optimizer.zero_grad()
                
                epoch_loss += loss.item()
                steps += 1
                
        print(f"  [Epoch {epoch+1}/5] Mean Loss: {epoch_loss/steps:.4f}")
        
    print("4. Merging LoRA weights and saving checkpoint...")
    final_model_dir = out_dir / "checkpoint_final"
    shutil.copytree(local_path, final_model_dir, dirs_exist_ok=True)
    
    # Save config with custom speaker
    cfg_file = final_model_dir / "config.json"
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg_dict = json.load(f)
    cfg_dict["tts_model_type"] = "custom_voice"
    talker_cfg = cfg_dict.get("talker_config", {})
    talker_cfg["spk_id"] = {"calm_friendly": 3000}
    talker_cfg["spk_is_dialect"] = {"calm_friendly": False}
    cfg_dict["talker_config"] = talker_cfg
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg_dict, f, indent=2, ensure_ascii=False)
        
    unwrapped = accelerator.unwrap_model(model)
    # Merge LoRA back into base talker model
    unwrapped.talker.model = unwrapped.talker.model.merge_and_unload()
    
    state_dict = {k: v.detach().to("cpu") for k, v in unwrapped.state_dict().items()}
    # Drop speaker encoder
    for k in list(state_dict.keys()):
        if k.startswith("speaker_encoder"):
            del state_dict[k]
            
    # Inject speaker embedding at index 3000
    w = state_dict["talker.model.codec_embedding.weight"]
    state_dict["talker.model.codec_embedding.weight"][3000] = target_speaker_embedding[0].detach().to(w.device).to(w.dtype)
    
    save_path = final_model_dir / "model.safetensors"
    save_file(state_dict, str(save_path))
    print(f"Saved final merged model to {final_model_dir}!")
    
    # 5. Synthesize 20 evaluation sentences
    print("5. Synthesizing 20 evaluation sentences with LoRA 5-Epoch model...")
    eval_payload = json.loads(Path("data/tts/evaluation/sentences.json").read_text(encoding="utf-8"))
    sentences = eval_payload["sentences"]
    
    eval_model = Qwen3TTSModel.from_pretrained(
        str(final_model_dir),
        dtype=torch.bfloat16,
        device_map="cuda:0"
    )
    
    eval_wav_dir = out_dir / "eval_wavs"
    eval_wav_dir.mkdir(parents=True, exist_ok=True)
    
    eval_results = []
    for s in sentences:
        sid = s["id"]
        text = s["text"]
        cat = s.get("category", "")
        # Dynamic tokens based on text length to prevent timeout
        max_tokens = min(max(int(len(text) * 3), 50), 120)
        wavs, sr = eval_model.generate_custom_voice(
            text=text,
            speaker="calm_friendly",
            language="Korean",
            max_new_tokens=max_tokens
        )
        wav_path = eval_wav_dir / f"{sid}.wav"
        sf.write(wav_path, wavs[0], sr)
        dur = len(wavs[0]) / sr
        b64 = base64.b64encode(wav_path.read_bytes()).decode("utf-8")
        eval_results.append((sid, cat, text, dur, b64))
        print(f"  [{sid}] {dur:.2f}s | {text}")
        
    # Generate standalone player HTML
    html = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>Qwen3-TTS LoRA (5 Epoch) 20개 문장 평가 청음기</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #0f172a; color: #f8fafc; padding: 32px 16px; max-width: 900px; margin: 0 auto; line-height: 1.5; }
  h1 { color: #fbbf24; text-align: center; margin-bottom: 8px; }
  .desc { text-align: center; color: #94a3b8; font-size: 14px; margin-bottom: 24px; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 18px; margin-bottom: 16px; }
  .tag { background: #d97706; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-right: 8px; }
  .text { font-size: 16px; font-weight: 600; color: #f1f5f9; margin-bottom: 12px; margin-top: 8px; }
  audio { width: 100%; height: 38px; }
</style>
</head>
<body>
<h1>🎙️ Qwen3-TTS LoRA (5 Epoch) 20개 문장 청음기</h1>
<p class="desc">Cross-Attention LoRA (r=8, alpha=16) + 화자 임베딩 주입 • 24초 타임아웃 방지</p>
"""
    for sid, cat, text, dur, b64 in eval_results:
        html += f"""
<div class="card">
  <div><span class="tag">{cat}</span> <span style="color:#94a3b8; font-size:12px;">[{sid}] 길이: {dur:.2f}초</span></div>
  <div class="text">"{text}"</div>
  <audio controls src="data:audio/wav;base64,{b64}"></audio>
</div>
"""
    html += """
</body>
</html>
"""
    player_path = out_dir / "player_qwen_lora_5ep.html"
    player_path.write_text(html, encoding="utf-8")
    print(f"Successfully generated player: {player_path.resolve()}!")

if __name__ == "__main__":
    main()
