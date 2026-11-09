"""
전처리 전/후 STT 성능 비교 평가 스크립트

- 전처리 전 (baseline_results.csv): 기존 평가 결과
- 전처리 후 (preprocessed/): 전처리된 오디오로 재평가
- WER/CER 차이를 비교하여 전처리 효과를 정량적으로 확인

사용법:
    python preprocessed.py --model small --samples 100
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd
from faster_whisper import WhisperModel

from adapters.stt.common import (
    setup_cuda_dll_paths,
    set_seed,
    DEFAULT_SEED,
    DATA_ROOT,
    PREPROCESSED_DIR,
    BASELINE_RESULTS_CSV,
    PREPROCESSED_RESULTS_CSV,
)
from scripts.eval.stt.metrics import compute_cer, compute_wer

setup_cuda_dll_paths()


def load_sample_jsons(samples: int, seed: int = DEFAULT_SEED) -> list[Path]:
    """전처리된 파일 기준으로 평가할 JSON을 선택."""
    # 전처리된 파일명 목록
    preprocessed_stems = {
        wav.stem
        for wav in PREPROCESSED_DIR.rglob("*.wav")
    }

    # 전처리된 파일에 해당하는 JSON 찾기
    training_json = [
        f for f in DATA_ROOT.rglob("*.json")
        if "Training" in f.parts and f.stem in preprocessed_stems
    ]

    if len(training_json) <= samples:
        return training_json

    set_seed(seed)
    return sorted(random.sample(training_json, samples))


def transcribe(model: WhisperModel, audio_path: Path) -> str:
    segments, _ = model.transcribe(str(audio_path), language="ko")
    return " ".join(seg.text.strip() for seg in segments).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="전처리 전/후 STT 성능 비교")
    parser.add_argument("--model", type=str, default="small", help="Whisper 모델 크기")
    parser.add_argument("--samples", type=int, default=100, help="평가 샘플 수")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="랜덤 시드")
    args = parser.parse_args()

    # 모델 로드
    print(f"모델 로딩: {args.model} (cuda, float16)")
    model = WhisperModel(args.model, device="cuda", compute_type="float16")

    # 샘플 선택
    sample_jsons = load_sample_jsons(args.samples, args.seed)
    print(f"평가 샘플: {len(sample_jsons)}개")

    # 전처리 파일 존재 확인
    preprocessed_files = list(PREPROCESSED_DIR.rglob("*.wav"))
    print(f"전처리된 파일: {len(preprocessed_files):,}개")

    results = []

    for i, json_path in enumerate(sample_jsons, start=1):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # preprocess.py는 파일명(stem) 기준으로 저장하므로 stem으로 일치시킨다.
        file_name = json_path.stem
        reference = data["transcription"]["dialect"]

        # 전처리된 오디오 찾기
        processed_path = PREPROCESSED_DIR / f"{file_name}.wav"
        if not processed_path.exists():
            print(f"[{i}/{len(sample_jsons)}] ⚠️ 전처리 파일 없음: {file_name}")
            continue

        # 전처리 후 STT
        try:
            hypothesis = transcribe(model, processed_path)
        except Exception as exc:
            print(f"[{i}/{len(sample_jsons)}] ❌ STT 실패: {file_name} - {exc}")
            continue

        sample_wer = compute_wer(reference, hypothesis)
        sample_cer = compute_cer(reference, hypothesis)

        results.append(
            {
                "file": file_name,
                "reference": reference,
                "hypothesis_preprocessed": hypothesis,
                "cer_preprocessed": sample_cer,
                "wer_preprocessed": sample_wer,
            }
        )

        if i % 10 == 0 or i == len(sample_jsons):
            print(f"[{i}/{len(sample_jsons)}] 진행 중...")

    # 결과 DataFrame
    df_new = pd.DataFrame(results)

    # 전체 결과 저장 (500개)
    output_csv = PREPROCESSED_RESULTS_CSV
    df_new.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"전체 결과 저장: {output_csv} ({len(df_new)}개)")

    # 기존 baseline 결과 로드
    baseline_path = BASELINE_RESULTS_CSV
    if baseline_path.exists():
        df_base = pd.read_csv(baseline_path)
        df_base = df_base[df_base["status"] == "success"]
        df_base = df_base.rename(
            columns={
                "cer": "cer_baseline",
                "wer": "wer_baseline",
                "hypothesis": "hypothesis_baseline",
            }
        )
        df_base = df_base[["file", "cer_baseline", "wer_baseline", "hypothesis_baseline"]]

        # 병합 (baseline과 비교 가능한 샘플만)
        df_merged = df_new.merge(df_base, on="file", how="inner")
        print(f"\nbaseline 비교 가능한 샘플: {len(df_merged)}개")
    else:
        print("⚠️ baseline_results.csv를 찾을 수 없어 전처리 후 결과만 출력합니다.")
        df_merged = df_new

    # 요약 통계
    print("\n" + "=" * 60)
    print("=== 전처리 전/후 비교 ===")
    print("=" * 60)

    if "cer_baseline" in df_merged.columns and "cer_preprocessed" in df_merged.columns:
        print("\n[CER]")
        print(
            f"  전처리 전: {df_merged['cer_baseline'].mean():.4f} ± {df_merged['cer_baseline'].std():.4f}"
        )
        print(
            f"  전처리 후: {df_merged['cer_preprocessed'].mean():.4f} ± {df_merged['cer_preprocessed'].std():.4f}"
        )
        delta_cer = df_merged["cer_preprocessed"].mean() - df_merged["cer_baseline"].mean()
        print(f"  변화율  : {delta_cer:+.4f} ({delta_cer / df_merged['cer_baseline'].mean() * 100:+.1f}%)")

        print("\n[WER]")
        print(
            f"  전처리 전: {df_merged['wer_baseline'].mean():.4f} ± {df_merged['wer_baseline'].std():.4f}"
        )
        print(
            f"  전처리 후: {df_merged['wer_preprocessed'].mean():.4f} ± {df_merged['wer_preprocessed'].std():.4f}"
        )
        delta_wer = df_merged["wer_preprocessed"].mean() - df_merged["wer_baseline"].mean()
        print(f"  변화율  : {delta_wer:+.4f} ({delta_wer / df_merged['wer_baseline'].mean() * 100:+.1f}%)")

        # 개선/악화 샘플 수
        improved = (df_merged["cer_preprocessed"] < df_merged["cer_baseline"]).sum()
        worsened = (df_merged["cer_preprocessed"] > df_merged["cer_baseline"]).sum()
        same = len(df_merged) - improved - worsened
        print(f"\n[CER 기준] 개선: {improved}개 / 악화: {worsened}개 / 동일: {same}개")

        # 상위 10개 오류 샘플 (전처리 후)
        top10 = (
            df_merged.sort_values("wer_preprocessed", ascending=False)
            .head(10)
            .reset_index(drop=True)
        )
        print("\n=== 전처리 후 WER 상위 10개 ===")
        for i, row in top10.iterrows():
            print(f"[{i+1}] WER={row['wer_preprocessed']:.4f} | CER={row['cer_preprocessed']:.4f}")
            print(f"    파일: {row['file']}")
            print(f"    정답: {row['reference']}")
            print(f"    출력: {row['hypothesis_preprocessed']}")
            if "hypothesis_baseline" in row:
                print(f"    (전처리 전: {row['hypothesis_baseline']})")
            print()


if __name__ == "__main__":
    main()