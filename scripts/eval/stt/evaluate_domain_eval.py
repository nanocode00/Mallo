"""
도메인 평가 음성 STT 평가 (S-12, S-13)
======================================

TTS 합성된 도메인 평가셋으로 메뉴명/수량/옵션 인식률을 측정한다.

측정 지표:
    - 메뉴명 recall (S-12)
    - 수량 recall (S-13)
    - 옵션 recall
    - CER, WER

사용법:
    python evaluate_domain_eval.py --variant baseline
    python evaluate_domain_eval.py --variant train65
    python evaluate_domain_eval.py --variant baseline --eval-dir ./domain_eval

주의:
    - GPU 환경 필요 (CUDA)
    - S-10으로 생성된 domain_eval.csv 필요
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import torch

from adapters.stt.whisper_medium import WhisperMediumSTT
from adapters.stt.common import (
    setup_cuda_dll_paths,
    require_cuda,
    set_seed,
    resample_to_16k_mono,
    DEFAULT_SEED,
)
from scripts.eval.stt.metrics import (
    compute_cer,
    compute_wer,
    corpus_cer,
    corpus_wer,
    keyword_recall,
    aggregate_keyword_recall,
    DEFAULT_KEYWORDS,
    _normalize_quantity,
)

# ============================================================
# CUDA 설정
# ============================================================

setup_cuda_dll_paths()


# ============================================================
# 상수
# ============================================================

STT_DIR = Path(__file__).resolve().parent
DEFAULT_EVAL_DIR = STT_DIR / "stt_data" / "domain_eval"
DEFAULT_OUTPUT_DIR = STT_DIR / "stt_data" / "domain_eval_results"


# ============================================================
# 평가 데이터 로드
# ============================================================

def load_eval_data(eval_dir: Path) -> pd.DataFrame:
    """domain_eval.csv에서 평가 데이터를 로드한다."""
    csv_path = eval_dir / "domain_eval.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"평가 데이터를 찾을 수 없습니다:\n{csv_path}\n"
            f"먼저 synthesize_domain_eval.py를 실행하세요."
        )
    df = pd.read_csv(csv_path)
    # 성공한 합성만 사용
    df = df[df["status"] == "success"].reset_index(drop=True)
    return df


# ============================================================
# 평가
# ============================================================

def evaluate_domain(
    stt: WhisperMediumSTT,
    eval_df: pd.DataFrame,
) -> pd.DataFrame:
    """도메인 평가셋에 대해 STT 추론 및 지표를 측정한다."""
    results = []

    for idx, row in eval_df.iterrows():
        audio_path = Path(row["audio_path"])
        reference_text = row["text"]
        menu = row["menu"]
        quantity = row["quantity"]
        option = row["option"]

        # 오디오 로드 및 전처리
        import soundfile as sf
        import io

        audio_array, sr = sf.read(str(audio_path))
        audio_array, sr = resample_to_16k_mono(audio_array, sr)

        # WAV 바이트로 변환
        buffer = io.BytesIO()
        sf.write(buffer, audio_array, sr, format="WAV")
        audio_bytes = buffer.getvalue()

        # STT 추론
        result = stt.transcribe(audio_bytes)
        hypothesis = result.text

        # 지표 계산
        cer_score = compute_cer(reference_text, hypothesis)
        wer_score = compute_wer(reference_text, hypothesis)

        # 키워드 recall (메뉴)
        menu_result = keyword_recall(
            reference_text,
            hypothesis,
            DEFAULT_KEYWORDS["menu"],
        )

        # 키워드 recall (수량)
        quantity_result = keyword_recall(
            reference_text,
            hypothesis,
            DEFAULT_KEYWORDS["quantity"],
            normalize_fn=_normalize_quantity,
        )

        # 키워드 recall (옵션)
        option_result = keyword_recall(
            reference_text,
            hypothesis,
            DEFAULT_KEYWORDS["option"],
        )

        results.append({
            "id": row["id"],
            "reference": reference_text,
            "hypothesis": hypothesis,
            "menu_gt": menu,
            "quantity_gt": quantity,
            "option_gt": option,
            "cer": cer_score,
            "wer": wer_score,
            "menu_recall": menu_result["recall"],
            "menu_matched": menu_result["matched"],
            "menu_total": menu_result["total"],
            "quantity_recall": quantity_result["recall"],
            "quantity_matched": quantity_result["matched"],
            "quantity_total": quantity_result["total"],
            "option_recall": option_result["recall"],
            "option_matched": option_result["matched"],
            "option_total": option_result["total"],
            "latency": result.duration_ms,
        })

        # 진행률
        if (idx + 1) % 50 == 0 or idx == len(eval_df) - 1:
            print(f"진행: {idx + 1}/{len(eval_df)}")

    return pd.DataFrame(results)


def print_summary(results_df: pd.DataFrame) -> None:
    """요약 통계를 출력한다."""
    print("\n" + "=" * 60)
    print("도메인 평가 결과 요약")
    print("=" * 60)

    n = len(results_df)
    print(f"평가 샘플 수: {n}")

    # CER / WER
    avg_cer = results_df["cer"].mean()
    avg_wer = results_df["wer"].mean()
    print(f"\n[CER] 평균: {avg_cer:.4f}")
    print(f"[WER] 평균: {avg_wer:.4f}")

    # 메뉴 recall
    menu_total = results_df["menu_total"].sum()
    menu_matched = results_df["menu_matched"].sum()
    menu_recall = menu_matched / menu_total if menu_total > 0 else 0.0
    print(f"\n[메뉴 recall] {menu_matched}/{menu_total} = {menu_recall:.4f}")

    # 수량 recall
    qty_total = results_df["quantity_total"].sum()
    qty_matched = results_df["quantity_matched"].sum()
    qty_recall = qty_matched / qty_total if qty_total > 0 else 0.0
    print(f"[수량 recall] {qty_matched}/{qty_total} = {qty_recall:.4f}")

    # 옵션 recall
    opt_total = results_df["option_total"].sum()
    opt_matched = results_df["option_matched"].sum()
    opt_recall = opt_matched / opt_total if opt_total > 0 else 0.0
    print(f"[옵션 recall] {opt_matched}/{opt_total} = {opt_recall:.4f}")

    # Latency
    avg_latency = results_df["latency"].mean()
    print(f"\n[Latency] 평균: {avg_latency:.3f}s")

    print("=" * 60)


# ============================================================
# 메인
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="도메인 평가 음성 STT 평가 (S-12, S-13)"
    )
    parser.add_argument(
        "--variant",
        type=str,
        choices=["baseline", "qlora", "train65", "peft"],
        default="train65",
        help="STT 모델 variant",
    )
    parser.add_argument(
        "--eval-dir",
        type=str,
        default=str(DEFAULT_EVAL_DIR),
        help="평가 데이터 디렉토리",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="결과 출력 디렉토리",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="랜덤 시드",
    )
    parser.add_argument(
        "--qlora-path",
        type=str,
        default=None,
        help="커스텀 train65/QLoRA merged 모델 경로 (legacy option name)",
    )
    args = parser.parse_args()

    set_seed(args.seed)
    eval_dir = Path(args.eval_dir)
    output_dir = Path(args.output_dir)

    print("=" * 60)
    print("도메인 평가 음성 STT 평가 (S-12, S-13)")
    print("=" * 60)
    print(f"모델 variant: {args.variant}")
    print(f"평가 데이터: {eval_dir}")
    print()

    # 평가 데이터 로드
    eval_df = load_eval_data(eval_dir)
    print(f"평가 샘플 수: {len(eval_df)}")

    # STT 모델 로드
    print(f"\nSTT 모델 로딩 ({args.variant})...")
    stt = WhisperMediumSTT(variant=args.variant, qlora_path=args.qlora_path)
    print("모델 로딩 완료")

    # 평가 실행
    print("\n평가 시작...")
    results_df = evaluate_domain(stt, eval_df)

    # 요약 출력
    print_summary(results_df)

    # 결과 저장
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.qlora_path:
        output_csv = output_dir / f"domain_eval_{args.variant}_domain.csv"
    else:
        output_csv = output_dir / f"domain_eval_{args.variant}.csv"
    results_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\n결과 저장: {output_csv}")


if __name__ == "__main__":
    main()
