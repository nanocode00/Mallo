#!/usr/bin/env python3
"""
Mallo Real Pipeline End-to-End Latency 측정 스크립트
- 실제 STT(Faster-Whisper), NLU(MockNLU/Domain Resolver), Order Engine, Adaptive TTS(MeloTTS Finetuned) 연결
- Cold Start 분리 및 Warm E2E 다회차 벤치마크 수행
- SSOT (docs/specs/e2e-latency.md) 기준 Target(<=1.2s), Requirement(<=1.5s) 판정
"""

from __future__ import annotations

import argparse
import io
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from faster_whisper import WhisperModel

# 프로젝트 루트 경로 추가
sys.path.insert(0, "src")
sys.path.insert(0, "data/tts/repos/MeloTTS")

from adapters.nlu.mock_nlu import MockNLU
from adapters.stt.common import resample_to_16k_mono
from adapters.tts.melotts_adapter import MeloTTSAdapter
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.models import Cart
from domain.stt_result import STTResult
from interfaces.stt import STTFailure
from orchestrator.voice_pipeline import VoicePipeline


class FasterWhisperSTT:
    """Faster-Whisper 기반 STT 어댑터 (16kHz 자동 리샘플링 포함)."""

    def __init__(
        self,
        model_size: str = "tiny",
        device: str = "cuda",
        compute_type: str = "float16",
    ) -> None:
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: bytes, language: str = "ko") -> STTResult:
        try:
            audio_stream = io.BytesIO(audio)
            data, sr = sf.read(audio_stream)
            resampled, target_sr = resample_to_16k_mono(data, sr)
            dur_ms = (len(resampled) / target_sr) * 1000.0 if target_sr > 0 else 0.0

            segments, _ = self.model.transcribe(
                resampled, language=language, beam_size=1
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            return STTResult(text=text, duration_ms=dur_ms)
        except Exception as e:
            raise STTFailure(str(e)) from e


DEFAULT_TEST_PHRASES = [
    ("메뉴추가-1", "아이스 아메리카노 두 잔 주세요"),
    ("메뉴추가-2", "따뜻한 카페라떼 한 잔 주세요"),
    ("디저트추가", "바스크 치즈 케이크 한 개 주세요"),
    ("옵션지정", "아이스 아메리카노 한 잔 디카페인으로 주세요"),
    ("복합주문", "아이스 아메리카노 두 잔이랑 따뜻한 카페라떼 한 잔 주세요"),
    ("주문삭제", "아이스 아메리카노 삭제해 주세요"),
    ("옵션변경", "아메리카노를 따뜻하게 바꿔 주세요"),
    ("메뉴조회", "커피 메뉴 알려 주세요"),
    ("장바구니조회", "현재 주문 알려 주세요"),
    ("주문확정", "주문 확정할게요"),
]


def nearest_rank_percentile(values: list[float], percentile: float) -> float:
    """nearest-rank 방식으로 percentile을 계산한다."""
    if not values:
        raise ValueError("values must not be empty")
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")

    ordered = sorted(values)
    rank = math.ceil((percentile / 100.0) * len(ordered))
    return float(ordered[rank - 1])


def run_benchmark(
    rounds: int = 5,
    whisper_size: str = "tiny",
    device: str = "cuda:0" if torch.cuda.is_available() else "cpu",
    quiet: bool = False,
) -> dict[str, Any]:
    print("=" * 80)
    print("🚀 Mallo Real Pipeline End-to-End Latency Measurement")
    print("=" * 80)
    print(f"• 디바이스: {device}")
    print(f"• STT 모델: Faster-Whisper ({whisper_size}, float16)")
    print(f"• TTS 모델: MeloTTS Korean (models/tts/mallo-friendly/G_2800.pth)")
    print(f"• 반복 횟수: {rounds} 라운드 (시나리오 {len(DEFAULT_TEST_PHRASES)}개 x {rounds} = {len(DEFAULT_TEST_PHRASES) * rounds}회)")
    print("=" * 80)

    # 1. 컴포넌트 초기화
    stt = FasterWhisperSTT(
        model_size=whisper_size,
        device="cuda" if "cuda" in device else "cpu",
        compute_type="float16" if "cuda" in device else "float32",
    )

    ckpt_path = Path("models/tts/mallo-friendly/G_2800.pth")
    config_path = Path("models/tts/mallo-friendly/config.json")


    tts = MeloTTSAdapter(
        config_path=config_path,
        ckpt_path=ckpt_path,
        speaker="10",
        device=device,
    )
    nlu = MockNLU()
    agent = ConversationAgent(load_menu())
    pipeline = VoicePipeline(nlu=nlu, agent=agent, tts=tts, stt=stt)

    # 2. 테스트 음원 생성
    if not quiet:
        print(f"\n[1/3] {len(DEFAULT_TEST_PHRASES)}개 테스트 발화 오디오 생성 중...")
    user_audios = []
    for label, phrase in DEFAULT_TEST_PHRASES:
        res = tts.synthesize(phrase, level=0)
        user_audios.append((label, phrase, res.audio))

    # 3. Cold Start 측정
    if not quiet:
        print("\n[2/3] Cold Start 측정 (최초 1회 실행)...")
    t0 = time.perf_counter()
    cold_res = pipeline.handle_audio(user_audios[0][2], Cart())
    cold_total_ms = (time.perf_counter() - t0) * 1000.0
    if not quiet:
        print(f"  - Cold Start Total: {cold_total_ms:.1f}ms")
        print(
            f"  - STT: {cold_res.stt_latency_ms:.1f}ms | "
            f"NLU: {cold_res.nlu_latency_ms:.1f}ms | "
            f"Order: {cold_res.agent_latency_ms:.1f}ms | "
            f"TTS: {cold_res.tts_latency_ms:.1f}ms"
        )

    # 4. Warm E2E 반복 측정
    if not quiet:
        print(f"\n[3/3] Warm E2E 벤치마크 수행 ({rounds}회 반복)...")
    all_records = []
    for r in range(1, rounds + 1):
        for label, phrase, audio_bytes in user_audios:
            cart = Cart()
            res = pipeline.handle_audio(audio_bytes, cart)
            all_records.append(
                {
                    "round": r,
                    "label": label,
                    "phrase": phrase,
                    "stt_text": res.stt_result.text,
                    "response_text": res.order_result.response_text,
                    "stt_ms": res.stt_latency_ms,
                    "nlu_ms": res.nlu_latency_ms,
                    "order_ms": res.agent_latency_ms,
                    "tts_ms": res.tts_latency_ms,
                    "e2e_ms": res.total_e2e_latency_ms,
                    "success": res.order_result.success,
                }
            )

    # 5. 통계 집계
    def calc_stats(values: list[float]) -> dict[str, float]:
        return {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "p95": nearest_rank_percentile(values, 95),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "std": float(np.std(values)),
        }

    stt_stats = calc_stats([rec["stt_ms"] for rec in all_records])
    nlu_stats = calc_stats([rec["nlu_ms"] for rec in all_records])
    order_stats = calc_stats([rec["order_ms"] for rec in all_records])
    tts_stats = calc_stats([rec["tts_ms"] for rec in all_records])
    e2e_stats = calc_stats([rec["e2e_ms"] for rec in all_records])

    print("\n" + "=" * 80)
    print("📊 Mallo Real Warm E2E Latency 실측 통계 보고서")
    print("=" * 80)
    print(f"| 구간 (Stage)            | 평균 (Mean) | 중앙값 (Median) | p95       | 최소 (Min) | 최대 (Max) |")
    print(f"|------------------------|------------|----------------|-----------|-----------|-----------|")
    print(f"| 1. STT (Whisper {whisper_size:<5}) | {stt_stats['mean']:>8.1f}ms | {stt_stats['median']:>12.1f}ms | {stt_stats['p95']:>7.1f}ms | {stt_stats['min']:>7.1f}ms | {stt_stats['max']:>7.1f}ms |")
    print(f"| 2. NLU (Intent/Alias)  | {nlu_stats['mean']:>8.1f}ms | {nlu_stats['median']:>12.1f}ms | {nlu_stats['p95']:>7.1f}ms | {nlu_stats['min']:>7.1f}ms | {nlu_stats['max']:>7.1f}ms |")
    print(f"| 3. Order Engine        | {order_stats['mean']:>8.1f}ms | {order_stats['median']:>12.1f}ms | {order_stats['p95']:>7.1f}ms | {order_stats['min']:>7.1f}ms | {order_stats['max']:>7.1f}ms |")
    print(f"| 4. Adaptive TTS (Melo) | {tts_stats['mean']:>8.1f}ms | {tts_stats['median']:>12.1f}ms | {tts_stats['p95']:>7.1f}ms | {tts_stats['min']:>7.1f}ms | {tts_stats['max']:>7.1f}ms |")
    print(f"|------------------------|------------|----------------|-----------|-----------|-----------|")
    print(f"| 🚀 Total Warm E2E      | {e2e_stats['mean']:>8.1f}ms | {e2e_stats['median']:>12.1f}ms | {e2e_stats['p95']:>7.1f}ms | {e2e_stats['min']:>7.1f}ms | {e2e_stats['max']:>7.1f}ms |")
    print("=" * 80)

    target = 1200.0
    req = 1500.0
    over_requirement_count = sum(rec["e2e_ms"] > req for rec in all_records)
    failure_count = sum(not rec["success"] for rec in all_records)
    target_met = (
        e2e_stats["p95"] <= target
        and over_requirement_count <= 2
        and failure_count == 0
    )
    requirement_met = (
        e2e_stats["p95"] <= req
        and over_requirement_count <= 2
        and failure_count == 0
    )
    print(
        f"🎯 Target 목표 (<= 1,200ms):  "
        f"{'✅ 달성' if target_met else '⚠️ 미달'} "
        f"(p95 = {e2e_stats['p95']:.1f}ms, 평균 = {e2e_stats['mean']:.1f}ms)"
    )
    print(
        f"📋 Requirement 한계 (<= 1,500ms): "
        f"{'✅ 충족' if requirement_met else '❌ 실패'} "
        f"(p95 = {e2e_stats['p95']:.1f}ms, 1,500ms 초과 = {over_requirement_count}건, "
        f"처리 실패 = {failure_count}건)"
    )
    print("=" * 80)

    return {
        "cold_start_total_ms": cold_total_ms,
        "stt": stt_stats,
        "nlu": nlu_stats,
        "order": order_stats,
        "tts": tts_stats,
        "e2e": e2e_stats,
        "sample_count": len(all_records),
        "over_requirement_count": over_requirement_count,
        "failure_count": failure_count,
        "target_met": target_met,
        "requirement_met": requirement_met,
        "records": all_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Mallo Real E2E Latency 벤치마크")
    parser.add_argument(
        "--rounds",
        "-r",
        type=int,
        default=5,
        help="시나리오별 반복 횟수 (기본값: 5)",
    )
    parser.add_argument(
        "--whisper-size",
        "-w",
        type=str,
        default="tiny",
        help="Whisper 모델 크기 (기본값: tiny)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="상세 진행 로그 생략",
    )
    args = parser.parse_args()

    run_benchmark(
        rounds=args.rounds,
        whisper_size=args.whisper_size,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
