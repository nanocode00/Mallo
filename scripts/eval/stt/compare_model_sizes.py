"""
Whisper 모델 크기 비교 (base / small / medium)
============================================

동일 평가 데이터에서 Whisper Base·Small·Medium의 한국어 성능(CER/WER),
지연(latency), 자원(VRAM·파라미터 수)을 비교한다. S-08/09(후보 조사/로컬 실행)와
S-14(최종 STT 선정)의 근거 자료다.

- 모든 모델을 BF16으로 통일해 dtype 혼입 변수를 제거한다.
- **모델 선택은 validation split으로만 수행**한다. test split은 최종 모델 선정
  이후 1회 성능 보고 용도로 보존한다.
- CER/WER는 문장별 평균이 아니라 corpus-level(전체 목록 집계)로 계산하고,
  split(validation/test)별로 분리 보고한다.
- 메뉴 keyword recall은 평가셋에 메뉴명이 없어(S-10) 산출하지 않는다.

사용법 (GPU venv에서):
    # 1단계 — 모델 크기 선택: validation split에서 모든 모델 비교
    python compare_model_sizes.py --split validation --models base,small,medium

    # 2단계 — 최종 모델 test 1회 평가 (선정된 모델만)
    python compare_model_sizes.py --split test --models medium
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from pathlib import Path

# 최상위 디렉터리 및 src 디렉터리를 sys.path에 추가하여 어디서든 실행 가능하게 설정
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parents[2]
_SRC_DIR = _PROJECT_ROOT / "src"

for _p in (str(_PROJECT_ROOT), str(_SRC_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd
import soundfile as sf
import torch

from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
)

from adapters.stt.common import (
    setup_cuda_dll_paths,
    require_cuda,
    set_seed,
    resolve_audio_path,
    DEFAULT_SEED,
    VALIDATION_CSV,
    TEST_CSV,
    MODELS_DIR,
)
from scripts.eval.stt.metrics import corpus_cer, corpus_wer


setup_cuda_dll_paths()

MODEL_IDS = {
    "base": "openai/whisper-base",
    "small": "openai/whisper-small",
    "medium": "openai/whisper-medium",
}

DEVICE = "cuda"

EVAL_DTYPE = torch.bfloat16

MAX_NEW_TOKENS = 440


def load_audio(audio_path: str | Path):
    audio_path = resolve_audio_path(audio_path)
    audio_array, sampling_rate = sf.read(str(audio_path))

    if audio_array.ndim > 1:
        audio_array = audio_array.mean(axis=1)

    return audio_array, sampling_rate


@torch.inference_mode()
def transcribe(model, processor, audio_path: str) -> str:
    audio_array, sampling_rate = load_audio(audio_path)

    inputs = processor(
        audio_array,
        sampling_rate=sampling_rate,
        return_attention_mask=True,
        return_tensors="pt",
    )

    model_dtype = next(model.parameters()).dtype

    input_features = (
        inputs.input_features.to(device=DEVICE, dtype=model_dtype)
    )
    attention_mask = (
        inputs.attention_mask.to(device=DEVICE)
        if getattr(inputs, "attention_mask", None) is not None
        else None
    )

    gen_kwargs = {
        "input_features": input_features,
        "language": "ko",
        "task": "transcribe",
        "max_new_tokens": MAX_NEW_TOKENS,
    }
    if attention_mask is not None:
        gen_kwargs["attention_mask"] = attention_mask

    generated_ids = model.generate(**gen_kwargs)

    text = processor.batch_decode(
        generated_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]

    return text.strip()


def count_parameters(model) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def build_dataset(args) -> pd.DataFrame:
    val_csv = getattr(args, "val_csv", None) or VALIDATION_CSV
    test_csv = getattr(args, "test_csv", None) or TEST_CSV

    split_csvs = []
    if args.split in ("validation", "both"):
        split_csvs.append(("validation", val_csv))
    if args.split in ("test", "both"):
        split_csvs.append(("test", test_csv))

    frames = []
    for split_name, csv_path in split_csvs:
        if not csv_path.exists():
            raise FileNotFoundError(f"{split_name}.csv를 찾을 수 없습니다: {csv_path}")
        df = pd.read_csv(csv_path)
        df["split"] = split_name
        frames.append(df)

    df = pd.concat(frames, ignore_index=True)

    required_columns = {"audio_path", "reference"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"필요한 컬럼이 없습니다: {missing}")

    df["audio_path"] = df["audio_path"].apply(lambda p: str(resolve_audio_path(p)))

    if args.samples is not None and len(df) > args.samples:
        df = df.sample(n=args.samples, random_state=args.seed)

    return df.reset_index(drop=True)


def run_model(model_key: str, test_df: pd.DataFrame) -> dict:
    model_id = MODEL_IDS[model_key]

    print("=" * 70)
    print(f"모델 로딩: {model_key} ({model_id})")
    print("=" * 70)

    processor = WhisperProcessor.from_pretrained(
        model_id,
        language="ko",
        task="transcribe",
    )

    model = (
        WhisperForConditionalGeneration.from_pretrained(
            model_id,
            dtype=EVAL_DTYPE,
        )
        .to(DEVICE)
    )
    model.eval()

    params_m = count_parameters(model) / 1e6
    model_dtype = next(model.parameters()).dtype
    print(f"파라미터: {params_m:.1f}M | dtype: {model_dtype}")

    texts = []
    latencies = []

    torch.cuda.reset_peak_memory_stats()

    for index, row in test_df.iterrows():
        audio_path = str(row["audio_path"])
        resolved_path = resolve_audio_path(audio_path)

        if not resolved_path.is_file():
            print(f"⚠ 음성 파일을 찾을 수 없습니다: {audio_path}")
            texts.append("")
            latencies.append(float("nan"))
            continue

        start = time.perf_counter()
        text = transcribe(model, processor, str(resolved_path))
        latency = time.perf_counter() - start

        texts.append(text)
        latencies.append(latency)

        if (index + 1) % 25 == 0 or (index + 1) == len(test_df):
            print(f"  [{index + 1}/{len(test_df)}] {resolved_path.name}")

    vram_gb = torch.cuda.max_memory_allocated() / 1024**3

    del model, processor
    gc.collect()
    torch.cuda.empty_cache()

    return {
        "model_key": model_key,
        "texts": texts,
        "latencies": latencies,
        "params_m": params_m,
        "vram_gb": vram_gb,
    }


def summarize_corpus(
    results: dict,
    model_keys: list[str],
    references: list[str],
    rows: pd.DataFrame,
) -> list[dict]:
    """split별 corpus-level CER/WER 요약 행을 만든다."""
    summary_rows = []
    for split_name in sorted(rows["split"].unique()):
        mask = rows["split"] == split_name
        split_indices = list(rows.index[mask])
        split_refs = [references[i] for i in split_indices]
        for model_key in model_keys:
            run = results[model_key]
            split_hyps = [
                run["texts"][i] if not pd.isna(run["latencies"][i]) else ""
                for i in split_indices
            ]
            summary_rows.append(
                {
                    "split": split_name,
                    "model": model_key,
                    "n": len(split_indices),
                    "cer": corpus_cer(split_refs, split_hyps),
                    "wer": corpus_wer(split_refs, split_hyps),
                    "latency": pd.Series(
                        [run["latencies"][i] for i in split_indices]
                    ).mean(skipna=True),
                    "params_m": results[model_key]["params_m"],
                    "vram_gb": results[model_key]["vram_gb"],
                }
            )
    return summary_rows


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    require_cuda()

    parser = argparse.ArgumentParser(
        description="Whisper 모델 크기 비교 (base/small/medium)"
    )
    parser.add_argument(
        "--split",
        type=str,
        choices=["validation", "test", "both"],
        default="validation",
        help="평가할 분할 (기본: validation — 모델 선택은 validation에서만 수행)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=150,
        help="랜덤 샘플 수 (기본: 150)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="샘플링 시드",
    )
    parser.add_argument(
        "--models",
        type=str,
        default="base,small,medium",
        help="비교할 모델 (콤마 구분, 기본: base,small,medium)",
    )
    parser.add_argument(
        "--val-csv",
        type=Path,
        default=None,
        help="커스텀 검증 CSV 경로 (미지정 시 기본 splits/validation.csv 사용)",
    )
    parser.add_argument(
        "--test-csv",
        type=Path,
        default=None,
        help="커스텀 테스트 CSV 경로 (미지정 시 기본 splits/test.csv 사용)",
    )
    args = parser.parse_args()

    model_keys = [key.strip() for key in args.models.split(",")]
    for key in model_keys:
        if key not in MODEL_IDS:
            raise ValueError(f"알 수 없는 모델: {key} (허용: {list(MODEL_IDS)})")

    set_seed(args.seed)

    test_df = build_dataset(args)

    print("=" * 70)
    print("Whisper 모델 크기 비교")
    print("=" * 70)
    print(f"분할      : {args.split}")
    print(f"평가 샘플 : {len(test_df)}개")
    print(f"모델      : {', '.join(model_keys)}")
    print(f"dtype     : {EVAL_DTYPE}")
    print()

    results = {}
    for model_key in model_keys:
        results[model_key] = run_model(model_key, test_df)

    references = test_df["reference"].astype(str).tolist()

    records = []
    for index in range(len(test_df)):
        record = {
            "split": test_df.iloc[index]["split"],
            "file": Path(str(test_df.iloc[index]["audio_path"])).name,
            "reference": references[index],
        }
        for model_key in model_keys:
            run = results[model_key]
            text = run["texts"][index]
            record[f"{model_key}_text"] = text
            record[f"{model_key}_latency"] = run["latencies"][index]
        records.append(record)

    results_df = pd.DataFrame(records)

    for model_key in model_keys:
        results_df[f"{model_key}_params_m"] = results[model_key]["params_m"]
        results_df[f"{model_key}_vram_gb"] = results[model_key]["vram_gb"]

    results_df["model_dtype"] = str(EVAL_DTYPE)
    results_df["seed"] = args.seed

    print("=" * 70)
    print("요약 (corpus-level, split별)")
    print("=" * 70)

    summary = summarize_corpus(
        results, model_keys, references, results_df
    )

    header = (
        f"{'split':>10} | "
        f"{'model':>8} | "
        f"{'n':>4} | "
        f"{'CER':>8} | "
        f"{'WER':>8} | "
        f"{'latency(s)':>11} | "
        f"{'params(M)':>9} | "
        f"{'vram(GB)':>8}"
    )
    print(header)
    print("-" * len(header))

    for row in summary:
        print(
            f"{row['split']:>10} | "
            f"{row['model']:>8} | "
            f"{row['n']:>4} | "
            f"{row['cer']:>8.4f} | "
            f"{row['wer']:>8.4f} | "
            f"{row['latency']:>11.3f} | "
            f"{row['params_m']:>9.1f} | "
            f"{row['vram_gb']:>8.2f}"
        )

    print()
    print("CER/WER는 corpus-level(전체 목록 집계) 지표입니다.")
    print("모델 선택은 validation 결과로, test는 최종 모델 1회 보고에만 사용합니다.")

    output_dir = MODELS_DIR / "model-size-compare"
    output_csv = output_dir / (
        f"compare_{args.split}_{len(results_df)}_seed-{args.seed}.csv"
    )
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print()
    print(f"결과 저장: {output_csv}")
    print("=" * 70)


if __name__ == "__main__":
    main()
