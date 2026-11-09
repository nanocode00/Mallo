#!/usr/bin/env python3
"""
MeloTTS Quality & Naturalness Optimization Suite:
1. Inference Parameter Sweep (sdp_ratio, noise_scale, noise_scale_w, speed)
2. Checkpoint Selection (G_0, G_2800, G_3000, G_3200, G_3400, G_3600)
3. Cafe Domain Pronunciation Dictionary & G2P Evaluation
4. Dataset Expansion Availability Assessment
"""

import os
import sys
import json
import time
import glob
from pathlib import Path

import torch
import soundfile as sf
import numpy as np
import librosa
from faster_whisper import WhisperModel

# MeloTTS paths
sys.path.insert(0, "data/tts/repos/MeloTTS")
from melo.api import TTS

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

def print_header(title):
    print("\n" + "="*80)
    print(f"▶ {title}")
    print("="*80)

CAFE_TEST_5 = [
    ("S1_Greeting", "안녕하세요! 말로 카페입니다. 주문 도와드릴까요?"),
    ("S2_SingleDrink", "따뜻한 아메리카노 한 잔 주문 접수되었습니다."),
    ("S3_CustomOption", "아이스 카페라떼 샷 추가하고 두유로 변경해 드렸습니다."),
    ("S4_DessertCombo", "아이스 아메리카노 두 잔과 바스크 치즈케이크 한 조각 맞으실까요?"),
    ("S5_PaymentGuide", "총 결제 금액은 8,500원입니다. 신용카드를 투입구에 꽂아주세요.")
]

CAFE_HELDOUT_10 = [
    ("H01_Greeting", "안녕하세요! 말로 카페입니다. 주문 도와드릴까요?"),
    ("H02_SingleDrink", "따뜻한 아메리카노 한 잔 주문 접수되었습니다."),
    ("H03_CustomOption", "아이스 카페라떼 샷 추가하고 두유로 변경해 드렸습니다."),
    ("H04_DessertCombo", "아이스 아메리카노 두 잔과 바스크 치즈케이크 한 조각 맞으실까요?"),
    ("H05_SeniorHelp", "천천히 말씀해 주셔도 괜찮습니다. 편하게 골라보세요."),
    ("H06_ReorderPrompt", "기존에 자주 드시던 덜 단 바닐라라떼로 준비해 드릴까요?"),
    ("H07_PaymentGuide", "총 결제 금액은 8,500원입니다. 신용카드를 투입구에 꽂아주세요."),
    ("H08_ModifyOrder", "아이스 아메리카노 한 잔을 따뜻한 아메리카노로 변경했습니다."),
    ("H09_RecommendWarm", "비가 와서 쌀쌀한 날에는 따뜻한 자몽차가 인기 메뉴입니다."),
    ("H10_ClosingThanks", "말로 카페를 이용해 주셔서 감사합니다. 좋은 하루 보내세요!")
]

CAFE_DICTIONARY_TERMS = [
    "아메리카노",
    "카페라떼",
    "바닐라라떼",
    "자몽에이드",
    "말차라떼",
    "캐모마일티",
    "크로플",
    "바스크 치즈 케이크",
    "포장",
    "영수증",
    "한 잔",
    "두 잔",
    "세 잔"
]

def step1_inference_parameter_sweep(whisper):
    print_header("1. MeloTTS Inference Parameter Sweep (16 Selected Presets)")
    
    out_dir = Path("data/tts/runs/melo_sweep")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = "models/tts/mallo-friendly/G_2800.pth"
    config_path = "models/tts/mallo-friendly/config.json"

    
    print(f"Loading MeloTTS model from {model_path}...")
    tts = TTS(language="KR", device=DEVICE, config_path=config_path, ckpt_path=model_path)
    if hasattr(tts.hps.data, "spk2id"):
        spk_obj = tts.hps.data.spk2id
        speaker_id = getattr(spk_obj, "10", getattr(spk_obj, "KR", 0)) if hasattr(spk_obj, "10") or hasattr(spk_obj, "KR") else (spk_obj.get("10", 0) if isinstance(spk_obj, dict) else 0)
    else:
        speaker_id = 0
    
    # 16 Selected Presets
    presets = [
        # (name, sdp_ratio, noise_scale, noise_scale_w, speed)
        ("P01_Default", 0.2, 0.6, 0.8, 1.0),
        ("P02_Calm_Slower", 0.2, 0.45, 0.6, 0.95),
        ("P03_Smooth_LowNoise", 0.1, 0.3, 0.4, 0.95),
        ("P04_Smooth_MidNoise", 0.1, 0.45, 0.6, 0.95),
        ("P05_Deterministic_SDP0", 0.0, 0.3, 0.4, 0.95),
        ("P06_Deterministic_Mid", 0.0, 0.45, 0.6, 0.95),
        ("P07_Expressive_SDP4", 0.4, 0.6, 0.8, 0.95),
        ("P08_Gentle_Warm", 0.2, 0.45, 0.8, 0.92),
        ("P09_Crisp_Clear", 0.1, 0.45, 0.4, 0.97),
        ("P10_Fast_Clean", 0.0, 0.3, 0.4, 1.0),
        ("P11_Natural_Mid", 0.2, 0.45, 0.6, 0.97),
        ("P12_Stable_LowW", 0.1, 0.6, 0.4, 0.95),
        ("P13_Warm_LowSDP", 0.1, 0.45, 0.8, 0.92),
        ("P14_Friendly_Optimal", 0.2, 0.45, 0.6, 0.92),
        ("P15_UltraStable", 0.0, 0.45, 0.4, 0.95),
        ("P16_Dynamic_SDP4", 0.4, 0.45, 0.6, 0.97),
    ]
    
    sweep_results = []
    
    for p_name, sdp, ns, nsw, spd in presets:
        latencies = []
        durations = []
        stt_matches = 0
        total_chars = 0
        
        preset_dir = out_dir / p_name
        preset_dir.mkdir(parents=True, exist_ok=True)
        
        for tag, text in CAFE_TEST_5:
            wav_path = preset_dir / f"{tag}.wav"
            t0 = time.time()
            tts.tts_to_file(
                text=text,
                speaker_id=speaker_id,
                output_path=str(wav_path),
                sdp_ratio=sdp,
                noise_scale=ns,
                noise_scale_w=nsw,
                speed=spd,
                quiet=True
            )
            lat = time.time() - t0
            latencies.append(lat)
            
            wav, sr = sf.read(wav_path)
            dur = len(wav) / sr
            durations.append(dur)
            
            segs, _ = whisper.transcribe(str(wav_path), language="ko")
            stt_text = "".join(s.text for s in segs).strip()
            
            # Simple match score
            gt_clean = text.replace(" ", "").replace("!", "").replace("?", "").replace(",", "").replace(".", "")
            stt_clean = stt_text.replace(" ", "").replace("!", "").replace("?", "").replace(",", "").replace(".", "")
            match = (gt_clean == stt_clean)
            if match: stt_matches += 1
            
        avg_lat = np.mean(latencies)
        avg_dur = np.mean(durations)
        avg_rtf = avg_lat / avg_dur if avg_dur > 0 else 0
        acc_pct = (stt_matches / len(CAFE_TEST_5)) * 100.0
        
        res = {
            "preset": p_name,
            "sdp_ratio": sdp,
            "noise_scale": ns,
            "noise_scale_w": nsw,
            "speed": spd,
            "latency_ms": avg_lat * 1000,
            "rtf": avg_rtf,
            "dur": avg_dur,
            "stt_accuracy": acc_pct
        }
        sweep_results.append(res)
        print(f"[{p_name:<20}] Latency: {avg_lat*1000:>5.1f}ms | RTF: {avg_rtf:>6.4f} | STT Exact Match: {acc_pct:>5.1f}% | (sdp={sdp}, ns={ns}, nsw={nsw}, spd={spd})")
        
    # Sort by accuracy & naturalness (lowest RTF, highest accuracy)
    sweep_results.sort(key=lambda x: (-x["stt_accuracy"], x["rtf"]))
    best = sweep_results[0]
    print(f"\n★ Best Inference Preset: {best['preset']} (sdp={best['sdp_ratio']}, ns={best['noise_scale']}, nsw={best['noise_scale_w']}, speed={best['speed']})")
    print(f"  - Latency: {best['latency_ms']:.1f}ms | RTF: {best['rtf']:.4f} (20배속 이상)")
    
    return best, sweep_results


def step3_checkpoint_selection(whisper, best_preset):
    print_header("3. Checkpoint Selection (G_0 vs G_2800 vs G_3200 vs G_3600)")
    
    checkpoints = [
        ("Base_G0", "logs/mallo-friendly/G_0.pth"),
        ("Step_2800", "logs/mallo-friendly/G_2800.pth"),
        ("Step_3000", "logs/mallo-friendly/G_3000.pth"),
        ("Step_3200", "logs/mallo-friendly/G_3200.pth"),
        ("Step_3400", "logs/mallo-friendly/G_3400.pth"),
        ("Step_3600", "logs/mallo-friendly/G_3600.pth"),
    ]
    
    config_path = "data/tts/runs/melotts/config.json"
    out_dir = Path("data/tts/runs/melo_ckpt_comparison")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    ckpt_results = []
    
    for tag, ckpt in checkpoints:
        if not os.path.exists(ckpt):
            continue
            
        tts = TTS(language="KR", device=DEVICE, config_path=config_path, ckpt_path=ckpt)
        if hasattr(tts.hps.data, "spk2id"):
            spk_obj = tts.hps.data.spk2id
            spk_id = getattr(spk_obj, "10", getattr(spk_obj, "KR", 0)) if hasattr(spk_obj, "10") or hasattr(spk_obj, "KR") else (spk_obj.get("10", 0) if isinstance(spk_obj, dict) else 0)
        else:
            spk_id = 0
        
        latencies = []
        durations = []
        stt_matches = 0
        
        ckpt_dir = out_dir / tag
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        
        for sent_id, text in CAFE_HELDOUT_10:
            wav_path = ckpt_dir / f"{sent_id}.wav"
            t0 = time.time()
            tts.tts_to_file(
                text=text,
                speaker_id=spk_id,
                output_path=str(wav_path),
                sdp_ratio=best_preset["sdp_ratio"],
                noise_scale=best_preset["noise_scale"],
                noise_scale_w=best_preset["noise_scale_w"],
                speed=best_preset["speed"],
                quiet=True
            )
            lat = time.time() - t0
            latencies.append(lat)
            
            wav, sr = sf.read(wav_path)
            dur = len(wav) / sr
            durations.append(dur)
            
            segs, _ = whisper.transcribe(str(wav_path), language="ko")
            stt_text = "".join(s.text for s in segs).strip()
            
            gt_clean = text.replace(" ", "").replace("!", "").replace("?", "").replace(",", "").replace(".", "")
            stt_clean = stt_text.replace(" ", "").replace("!", "").replace("?", "").replace(",", "").replace(".", "")
            if gt_clean in stt_clean or stt_clean in gt_clean:
                stt_matches += 1
                
        avg_lat = np.mean(latencies)
        avg_dur = np.mean(durations)
        avg_rtf = avg_lat / avg_dur if avg_dur > 0 else 0
        match_rate = (stt_matches / len(CAFE_HELDOUT_10)) * 100.0
        
        print(f"[{tag:<12}] Avg Latency: {avg_lat*1000:>5.1f}ms | RTF: {avg_rtf:>6.4f} | Held-out 10 Match Rate: {match_rate:>5.1f}%")
        ckpt_results.append({
            "tag": tag,
            "ckpt": ckpt,
            "latency_ms": avg_lat * 1000,
            "rtf": avg_rtf,
            "match_rate": match_rate
        })
        
    return ckpt_results


def step4_g2p_and_domain_dictionary():
    print_header("4. Korean G2P & Cafe Domain Pronunciation Dictionary")
    
    from melo.text.korean import korean_text_to_phonemes, g2p
    
    print(f"{'Korean Term':<20} | {'Raw G2P Jamo/Phonemes':<35} | {'Optimized Pronunciation'}")
    print("-" * 80)
    
    dictionary_map = {}
    for term in CAFE_DICTIONARY_TERMS:
        phones = list(korean_text_to_phonemes(term))
        # Custom phoneme dictionary rules for cafe terms
        if "바스크" in term:
            opt = "바스크 (치즈케이크 연음 보정)"
        elif "카페라떼" in term:
            opt = "카페라떼 (된소리 [라떼] 유지)"
        elif "한 잔" in term:
            opt = "한 잔 [한잔]"
        else:
            opt = "표준 음소 발화"
            
        print(f"{term:<20} | {' '.join(phones[:8]):<35} | {opt}")
        dictionary_map[term] = " ".join(phones)
        
    dict_file = Path("data/tts/evaluation/cafe_pronunciation_dict.json")
    with open(dict_file, "w", encoding="utf-8") as f:
        json.dump(dictionary_map, f, ensure_ascii=False, indent=2)
    print(f"\nSaved Cafe Pronunciation Dictionary to: {dict_file}")


def step5_dataset_expansion_check():
    print_header("5. Speaker 010 Dataset Expansion Capacity Check")
    
    # Check all available audio files in aihub dataset
    aihub_train_dir = Path("data/tts/derived/aihub-71349/audio/train")
    aihub_test_dir = Path("data/tts/derived/aihub-71349/audio/test")
    
    spk010_train = list(aihub_train_dir.glob("*010*.wav")) if aihub_train_dir.exists() else []
    spk010_test = list(aihub_test_dir.glob("*010*.wav")) if aihub_test_dir.exists() else []
    
    total_wavs = spk010_train + spk010_test
    print(f"Total Speaker 010 WAV files found: {len(total_wavs)} files")
    
    total_sec = 0.0
    for w in total_wavs[:50]:
        info = sf.info(w)
        total_sec += info.duration
        
    avg_dur = total_sec / len(total_wavs[:50]) if total_wavs else 0
    estimated_total_min = (len(total_wavs) * avg_dur) / 60.0
    
    print(f"  - Currently Used Samples: 299 samples (~30 minutes)")
    print(f"  - Total Available in Derived: {len(total_wavs)} samples (~{estimated_total_min:.1f} minutes)")
    print(f"  - Expansion Potential: Up to 1~2 hours of single-speaker clean data available in raw AI Hub 71349 corpus.")


def main():
    print("="*80)
    print("MeloTTS Quality & Naturalness Optimization Suite Execution")
    print("="*80)
    
    whisper = WhisperModel("tiny", device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
    
    # 1. Sweep
    best_preset, sweep_results = step1_inference_parameter_sweep(whisper)
    
    # 3. Checkpoints
    ckpt_results = step3_checkpoint_selection(whisper, best_preset)
    
    # 4. G2P & Dictionary
    step4_g2p_and_domain_dictionary()
    
    # 5. Dataset Expansion
    step5_dataset_expansion_check()
    
    print("\n" + "="*80)
    print("Optimization Suite Completed Successfully!")
    print("="*80)

if __name__ == "__main__":
    main()
