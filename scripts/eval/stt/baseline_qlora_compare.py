"""
Whisper Medium Baseline vs QLoRA 비교 테스트
=============================================

비교:
    1. Whisper Medium Baseline
    2. Whisper Medium + QLoRA

테스트:
    validation.csv / test.csv 전체 (또는 --samples만큼 랜덤 샘플)

출력:
    - 파일명
    - 정답
    - Baseline 결과
    - QLoRA 결과
    - Baseline CER / WER
    - QLoRA CER / WER
    - CER / WER 개선량
    - 전체 평균

사용법:
    python baseline_qlora_compare.py --split test
    python baseline_qlora_compare.py --split validation --samples 10 --seed 42
    python baseline_qlora_compare.py --split both
    python baseline_qlora_compare.py --split both --merged --checkpoint <merged-bf16 경로>

주의:
    Baseline과 QLoRA 모두 BF16으로 평가해 dtype 혼입 변수를 제거한다.
    기본 QLoRA 로딩은 4-bit 어댑터, --merged는 BF16 머지 모델.
"""

from __future__ import annotations

import argparse
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

from peft import PeftModel

from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
    BitsAndBytesConfig,
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
    MODEL_ID,
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
# 1. CUDA DLL PATH
# ============================================================

setup_cuda_dll_paths()


# ============================================================
# 2. CONFIG
# ============================================================

# 기본 체크포인트 경로
FINAL_MERGED_PATH = MODELS_DIR / "final-train65-merged-bf16"
DEFAULT_QLORA_PATH = (
    MODELS_DIR
    / "archive"
    / "whisper-medium-qlora-speaker-split"
    / "lr-2e-05_ep-5"
    / "checkpoint-220"
)

DEVICE = "cuda"

# Baseline과 QLoRA를 같은 dtype(BF16)으로 평가해 dtype 혼입 변수를 제거한다.
EVAL_DTYPE = torch.bfloat16

# Whisper Medium의 decoder 최대 길이 448 고려
MAX_NEW_TOKENS = 440


# ============================================================
# 3. Audio loading
# ============================================================

def load_audio(
    audio_path: str | Path,
):
    audio_path = resolve_audio_path(audio_path)
    audio_array, sampling_rate = (
        sf.read(str(audio_path))
    )

    # Stereo → Mono
    if audio_array.ndim > 1:
        audio_array = (
            audio_array.mean(axis=1)
        )

    return (
        audio_array,
        sampling_rate,
    )


# ============================================================
# 5. Model dtype 확인
# ============================================================

def get_model_dtype(model):

    """
    모델의 실제 파라미터 dtype을 가져온다.

    Baseline:
        torch.float16

    QLoRA:
        torch.bfloat16
    """

    return next(
        model.parameters()
    ).dtype


def load_processor(qlora_path, merged: bool):
    """
    전사용 processor를 로드한다.

    merged=True: 머지 모델 번들(merge_qlora_adapter.py가 저장한 디렉터리)에
                 저장된 processor를 우선 로드하고, 없으면 MODEL_ID 폴백한다.
                 (번들은 모델 + processor를 함께 저장한다는 계약)
    merged=False: MODEL_ID의 processor를 로드한다.
    """
    if merged:
        bundle_processor = qlora_path / "preprocessor_config.json"
        if bundle_processor.exists():
            return (
                WhisperProcessor
                .from_pretrained(
                    str(qlora_path),
                    language="ko",
                    task="transcribe",
                )
            )

    return (
        WhisperProcessor
        .from_pretrained(
            MODEL_ID,
            language="ko",
            task="transcribe",
        )
    )


def load_qlora_model(
    qlora_path,
    merged: bool,
    device: str = "cuda",
    eval_dtype=None,
):
    if merged:
        model = (
            WhisperForConditionalGeneration
            .from_pretrained(
                qlora_path,
                dtype=(
                    eval_dtype if eval_dtype is not None else EVAL_DTYPE
                ),
            )
            .to(device)
        )
        model.eval()
        return model

    adapter_config = qlora_path / "adapter_config.json"
    adapter_model = qlora_path / "adapter_model.safetensors"

    if not adapter_config.exists():
        raise FileNotFoundError(
            "adapter_config.json이 없습니다:\n"
            f"{adapter_config.resolve()}"
        )

    if not adapter_model.exists():
        raise FileNotFoundError(
            "adapter_model.safetensors가 없습니다:\n"
            f"{adapter_model.resolve()}"
        )

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    qlora_base_model = (
        WhisperForConditionalGeneration
        .from_pretrained(
            MODEL_ID,
            quantization_config=bnb_config,
            device_map={"": 0},
            dtype=torch.bfloat16,
        )
    )

    qlora_model = (
        PeftModel
        .from_pretrained(
            qlora_base_model,
            str(qlora_path),
        )
    )
    qlora_model.eval()
    return qlora_model


# ============================================================
# 6. Transcription
# ============================================================

@torch.inference_mode()
def transcribe(
    model,
    processor,
    audio_path: str | Path,
):
    """
    Whisper 모델을 사용해서 음성을 전사한다.

    입력 dtype은 모델의 실제 dtype에 맞춘다.
    """

    # --------------------------------------------------------
    # Audio
    # --------------------------------------------------------

    audio_array, sampling_rate = (
        load_audio(audio_path)
    )

    # --------------------------------------------------------
    # Processor
    # --------------------------------------------------------

    inputs = processor(
        audio_array,
        sampling_rate=sampling_rate,
        return_attention_mask=True,
        return_tensors="pt",
    )

    # --------------------------------------------------------
    # Model dtype 확인
    # --------------------------------------------------------

    model_dtype = get_model_dtype(
        model
    )

    # --------------------------------------------------------
    # Input features
    # --------------------------------------------------------

    input_features = (
        inputs.input_features
        .to(
            device=DEVICE,
            dtype=model_dtype,
        )
    )
    attention_mask = (
        inputs.attention_mask.to(device=DEVICE)
        if getattr(inputs, "attention_mask", None) is not None
        else None
    )

    # --------------------------------------------------------
    # Generate
    # --------------------------------------------------------

    gen_kwargs = {
        "input_features": input_features,
        "language": "ko",
        "task": "transcribe",
        "max_new_tokens": MAX_NEW_TOKENS,
    }
    if attention_mask is not None:
        gen_kwargs["attention_mask"] = attention_mask

    generated_ids = model.generate(**gen_kwargs)

    # --------------------------------------------------------
    # Decode
    # --------------------------------------------------------

    text = (
        processor
        .batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
    )

    return text.strip()


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
            raise FileNotFoundError(
                f"{split_name}.csv를 찾을 수 없습니다:\n"
                f"{csv_path.resolve()}"
            )
        df = pd.read_csv(csv_path)
        df["split"] = split_name
        frames.append(df)

    df = pd.concat(frames, ignore_index=True)

    required_columns = {
        "audio_path",
        "reference",
    }

    missing = (
        required_columns
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"필요한 컬럼이 없습니다:\n"
            f"{missing}"
        )

    df["audio_path"] = df["audio_path"].apply(lambda p: str(resolve_audio_path(p)))

    if args.samples is not None and len(df) > args.samples:
        df = df.sample(
            n=args.samples,
            random_state=args.seed,
        )

    return df.reset_index(drop=True)


# ============================================================
# 7. Main
# ============================================================

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    require_cuda()

    # ========================================================
    # Arguments
    # ========================================================

    parser = argparse.ArgumentParser(
        description="Whisper Baseline vs QLoRA 비교"
    )

    parser.add_argument(
        "--split",
        type=str,
        choices=["validation", "test", "both"],
        default="validation",
        help="평가할 분할 (기본: validation)",
    )

    parser.add_argument(
        "--samples",
        type=int,
        default=None,
        help="랜덤 샘플 수 (기본: 전체)",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="샘플링 시드",
    )

    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="비교할 QLoRA checkpoint 경로 (미지정 시 --merged 여부에 따라 기본 경로 자동 선택)",
    )

    parser.add_argument(
        "--merged",
        action="store_true",
        help=(
            "체크포인트를 4-bit 어댑터가 아닌 "
            "BF16 머지 모델(merge_qlora_adapter.py 결과)로 로드"
        ),
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

    set_seed(args.seed)

    if args.checkpoint is not None:
        qlora_path = Path(args.checkpoint)
    elif args.merged:
        qlora_path = FINAL_MERGED_PATH
    else:
        qlora_path = DEFAULT_QLORA_PATH

    if not qlora_path.exists():
        raise FileNotFoundError(
            "QLoRA checkpoint를 찾을 수 없습니다:\n"
            f"{qlora_path.resolve()}"
        )

    # ========================================================
    # Dataset
    # ========================================================

    test_df = build_dataset(args)

    print("=" * 70)
    print(
        "Whisper Baseline vs QLoRA 비교 테스트"
    )
    print("=" * 70)
    print()

    print(
        f"분할      : {args.split}"
    )

    print(
        f"평가 샘플 : {len(test_df)}개"
    )

    print(
        f"QLoRA     : "
        f"{'BF16 머지' if args.merged else '4-bit 어댑터'}"
    )

    print()

    # ========================================================
    # Processor
    # ========================================================

    print(
        "Processor 로딩..."
    )

    processor = load_processor(
        qlora_path,
        merged=args.merged,
    )

    print(
        "Processor 완료"
    )

    print()

    # ========================================================
    # Baseline Model
    # ========================================================

    print(
        "Baseline Whisper Medium 로딩..."
    )

    baseline_model = (
        WhisperForConditionalGeneration
        .from_pretrained(
            MODEL_ID,
            dtype=EVAL_DTYPE,
        )
        .to(DEVICE)
    )

    baseline_model.eval()

    print(
        "Baseline 완료"
    )

    print(
        f"Baseline dtype: "
        f"{get_model_dtype(baseline_model)}"
    )

    print()

    # ========================================================
    # QLoRA Model
    # ========================================================

    print(
        "QLoRA 모델 로딩..."
    )

    print(
        f"Checkpoint: "
        f"{qlora_path}"
    )

    if args.merged:
        # ----------------------------------------------------
        # BF16 머지 모델 (merge_qlora_adapter.py 결과)
        # ----------------------------------------------------
        # 4-bit 역양자화 없이 native BF16 계산으로 추론해
        # latency 병목이 해소되는지 확인한다.

        qlora_model = load_qlora_model(
            qlora_path,
            merged=True,
            device=DEVICE,
            eval_dtype=EVAL_DTYPE,
        )

        print(
            "BF16 머지 모델 로딩 완료"
        )

        print(
            f"QLoRA dtype: "
            f"{get_model_dtype(qlora_model)}"
        )

    else:
        qlora_model = load_qlora_model(
            qlora_path,
            merged=False,
            device=DEVICE,
        )

        print(
            "QLoRA 완료"
        )

        print(
            f"QLoRA dtype: "
            f"{get_model_dtype(qlora_model)}"
        )

    print()

    # ========================================================
    # Metrics
    # ========================================================

    # jiwer 기반 오프라인 지표를 사용한다 (evaluate는 HF hub 다운로드 필요).
    print(
        "Metrics: jiwer (offline) + 주문 도메인 키워드"
    )

    print()

    # ========================================================
    # Results
    # ========================================================

    results = []

    # ========================================================
    # Test Loop
    # ========================================================

    for index, row in test_df.iterrows():

        audio_path = str(
            row["audio_path"]
        )
        resolved_path = resolve_audio_path(
            audio_path
        )

        reference = str(
            row["reference"]
        )

        file_name = (
            resolved_path.name
        )

        test_number = (
            len(results) + 1
        )

        print("=" * 70)

        print(
            f"[{test_number:02d}/{len(test_df):02d}] "
            f"{file_name}"
        )

        print("=" * 70)

        # ----------------------------------------------------
        # File check
        # ----------------------------------------------------

        if not resolved_path.is_file():

            print(
                "⚠ 음성 파일을 찾을 수 없습니다."
            )

            print(
                f"경로: {audio_path}"
            )

            print()

            continue

        # ----------------------------------------------------
        # Baseline
        # ----------------------------------------------------

        print(
            "Baseline 추론 중..."
        )

        t_baseline_start = (
            time.perf_counter()
        )

        baseline_text = transcribe(
            baseline_model,
            processor,
            str(resolved_path),
        )

        baseline_latency = (
            time.perf_counter()
            - t_baseline_start
        )

        # ----------------------------------------------------
        # QLoRA
        # ----------------------------------------------------

        print(
            "QLoRA 추론 중..."
        )

        t_qlora_start = (
            time.perf_counter()
        )

        qlora_text = transcribe(
            qlora_model,
            processor,
            str(resolved_path),
        )

        qlora_latency = (
            time.perf_counter()
            - t_qlora_start
        )

        # ----------------------------------------------------
        # VRAM (추론 직후 사용량, GB)
        # ----------------------------------------------------

        allocated_gb = (
            torch.cuda.memory_allocated()
            / 1024**3
        )

        # ----------------------------------------------------
        # Baseline metrics
        # ----------------------------------------------------

        baseline_wer = compute_wer(
            reference,
            baseline_text,
        )

        baseline_cer = compute_cer(
            reference,
            baseline_text,
        )

        # ----------------------------------------------------
        # QLoRA metrics
        # ----------------------------------------------------

        qlora_wer = compute_wer(
            reference,
            qlora_text,
        )

        qlora_cer = compute_cer(
            reference,
            qlora_text,
        )

        # ----------------------------------------------------
        # 주문 도메인 키워드 (메뉴/수량/옵션/금액)
        # ----------------------------------------------------

        baseline_keywords = {
            category: keyword_recall(
                reference,
                baseline_text,
                keywords,
                normalize_fn=_normalize_quantity if category == "quantity" else None,
            )
            for category, keywords in DEFAULT_KEYWORDS.items()
        }

        qlora_keywords = {
            category: keyword_recall(
                reference,
                qlora_text,
                keywords,
                normalize_fn=_normalize_quantity if category == "quantity" else None,
            )
            for category, keywords in DEFAULT_KEYWORDS.items()
        }

        # ----------------------------------------------------
        # Improvement
        # ----------------------------------------------------

        cer_improvement = (
            baseline_cer
            - qlora_cer
        )

        wer_improvement = (
            baseline_wer
            - qlora_wer
        )

        # ----------------------------------------------------
        # Output
        # ----------------------------------------------------

        print()

        print(
            "정답:"
        )

        print(
            reference
        )

        print()

        print(
            "Baseline:"
        )

        print(
            baseline_text
        )

        print(
            f"CER: {baseline_cer:.4f}"
        )

        print(
            f"WER: {baseline_wer:.4f}"
        )

        print()

        print(
            "QLoRA:"
        )

        print(
            qlora_text
        )

        print(
            f"CER: {qlora_cer:.4f}"
        )

        print(
            f"WER: {qlora_wer:.4f}"
        )

        print()

        print(
            "개선:"
        )

        print(
            f"CER 변화: "
            f"{cer_improvement:+.4f}"
        )

        print(
            f"WER 변화: "
            f"{wer_improvement:+.4f}"
        )

        print()

        # ----------------------------------------------------
        # Save
        # ----------------------------------------------------

        record = {

            "split":
                row.get("split", ""),

            "file":
                file_name,

            "reference":
                reference,

            "baseline":
                baseline_text,

            "qlora":
                qlora_text,

            "baseline_cer":
                baseline_cer,

            "baseline_wer":
                baseline_wer,

            "qlora_cer":
                qlora_cer,

            "qlora_wer":
                qlora_wer,

            "cer_improvement":
                cer_improvement,

            "wer_improvement":
                wer_improvement,

            "baseline_latency":
                baseline_latency,

            "qlora_latency":
                qlora_latency,

            "vram_gb":
                allocated_gb,
        }

        for category in DEFAULT_KEYWORDS:

            record[
                f"baseline_{category}_recall"
            ] = baseline_keywords[
                category
            ]["recall"]

            record[
                f"qlora_{category}_recall"
            ] = qlora_keywords[
                category
            ]["recall"]

        results.append(record)

    # ========================================================
    # Summary
    # ========================================================

    print()
    print("=" * 70)
    print("전체 결과")
    print("=" * 70)
    print()

    if not results:

        print(
            "테스트 결과가 없습니다."
        )

        return

    results_df = pd.DataFrame(
        results
    )

    # --------------------------------------------------------
    # Corpus-level 집계 (문장별 평균이 아님)
    # --------------------------------------------------------
    #
    # 문장별 CER/WER의 단순 평균은 짧은 문장과 긴 문장을 같은 비중으로
    # 반영해 전체 성능을 왜곡한다. 여기서는 전체 reference/hypothesis를
    # 한 번에 묶어 corpus-level CER/WER을 계산한다.
    # 키워드 recall도 문장별 평균이 아니라 "전체 matched / 전체 total"로 집계한다.

    corpus_baseline_cer = corpus_cer(
        results_df["reference"].tolist(),
        results_df["baseline"].tolist(),
    )

    corpus_baseline_wer = corpus_wer(
        results_df["reference"].tolist(),
        results_df["baseline"].tolist(),
    )

    corpus_qlora_cer = corpus_cer(
        results_df["reference"].tolist(),
        results_df["qlora"].tolist(),
    )

    corpus_qlora_wer = corpus_wer(
        results_df["reference"].tolist(),
        results_df["qlora"].tolist(),
    )

    sentences = [
        (reference, baseline)
        for reference, baseline in zip(
            results_df["reference"].tolist(),
            results_df["baseline"].tolist(),
        )
    ]

    qlora_sentences = [
        (reference, qlora)
        for reference, qlora in zip(
            results_df["reference"].tolist(),
            results_df["qlora"].tolist(),
        )
    ]

    baseline_keyword_summary = {
        category: aggregate_keyword_recall(
            sentences,
            keywords,
            normalize_fn=_normalize_quantity if category == "quantity" else None,
        )
        for category, keywords in DEFAULT_KEYWORDS.items()
    }

    qlora_keyword_summary = {
        category: aggregate_keyword_recall(
            qlora_sentences,
            keywords,
            normalize_fn=_normalize_quantity if category == "quantity" else None,
        )
        for category, keywords in DEFAULT_KEYWORDS.items()
    }

    # --------------------------------------------------------
    # Split별 집계 (corpus-level)
    # --------------------------------------------------------

    print()
    print("corpus-level CER / WER (전체)")
    print()

    print(
        f"테스트 수: "
        f"{len(results_df)}"
    )

    print()

    print(
        "Baseline"
    )

    print(
        f"CER: "
        f"{corpus_baseline_cer:.4f}"
    )

    print(
        f"WER: "
        f"{corpus_baseline_wer:.4f}"
    )

    print()

    print(
        "QLoRA"
    )

    print(
        f"CER: "
        f"{corpus_qlora_cer:.4f}"
    )

    print(
        f"WER: "
        f"{corpus_qlora_wer:.4f}"
    )

    print()

    print(
        f"CER 개선: "
        f"{corpus_baseline_cer - corpus_qlora_cer:+.4f}"
    )

    print(
        f"WER 개선: "
        f"{corpus_baseline_wer - corpus_qlora_wer:+.4f}"
    )

    # --------------------------------------------------------
    # Split별 corpus-level CER/WER
    # --------------------------------------------------------

    if "split" in results_df.columns:
        split_names = [
            name
            for name in results_df["split"].unique()
        ]
    else:
        split_names = []

    for split_name in split_names:

        split_df = results_df[
            results_df["split"]
            == split_name
        ]

        print()
        print(
            f"corpus-level CER / WER "
            f"(split: {split_name})"
        )

        print(
            f"  Baseline CER: "
            f"{corpus_cer(split_df['reference'].tolist(), split_df['baseline'].tolist()):.4f}"
        )

        print(
            f"  Baseline WER: "
            f"{corpus_wer(split_df['reference'].tolist(), split_df['baseline'].tolist()):.4f}"
        )

        print(
            f"  QLoRA   CER: "
            f"{corpus_cer(split_df['reference'].tolist(), split_df['qlora'].tolist()):.4f}"
        )

        print(
            f"  QLoRA   WER: "
            f"{corpus_wer(split_df['reference'].tolist(), split_df['qlora'].tolist()):.4f}"
        )

    # --------------------------------------------------------
    # 추론 Latency 평균 (초)
    # --------------------------------------------------------

    print()

    print(
        "평균 Latency (초)"
    )

    print(
        f"Baseline: "
        f"{results_df['baseline_latency'].mean():.3f}"
    )

    print(
        f"QLoRA   : "
        f"{results_df['qlora_latency'].mean():.3f}"
    )

    # --------------------------------------------------------
    # 주문 도메인 키워드 recall (전체 matched / total)
    # --------------------------------------------------------

    print()

    print(
        "주문 도메인 키워드 recall (전체 matched / total)"
    )

    for category in DEFAULT_KEYWORDS:

        baseline_total = (
            baseline_keyword_summary[category]["total"]
        )

        baseline_matched = (
            baseline_keyword_summary[category]["matched"]
        )

        qlora_total = (
            qlora_keyword_summary[category]["total"]
        )

        qlora_matched = (
            qlora_keyword_summary[category]["matched"]
        )

        print(
            f"  {category:8s} "
            f"Baseline: {baseline_matched}/{baseline_total} "
            f"({baseline_keyword_summary[category]['recall']:.3f}) / "
            f"QLoRA: {qlora_matched}/{qlora_total} "
            f"({qlora_keyword_summary[category]['recall']:.3f})"
        )

    # --------------------------------------------------------
    # 메타데이터 컬럼 추가 (재현성)
    # --------------------------------------------------------

    results_df["model"] = MODEL_ID

    results_df["baseline_dtype"] = (
        str(get_model_dtype(baseline_model))
    )

    results_df["qlora_dtype"] = (
        str(get_model_dtype(qlora_model))
    )

    results_df["seed"] = args.seed

    results_df["checkpoint"] = (
        str(qlora_path)
    )

    # --------------------------------------------------------
    # corpus-level 지표 컬럼 추가 (재현성)
    # --------------------------------------------------------

    corpus_metrics = {
        "corpus_baseline_cer":
            corpus_baseline_cer,
        "corpus_baseline_wer":
            corpus_baseline_wer,
        "corpus_qlora_cer":
            corpus_qlora_cer,
        "corpus_qlora_wer":
            corpus_qlora_wer,
        "corpus_cer_improvement":
            corpus_baseline_cer
            - corpus_qlora_cer,
        "corpus_wer_improvement":
            corpus_baseline_wer
            - corpus_qlora_wer,
    }

    for category in DEFAULT_KEYWORDS:
        corpus_metrics[
            f"corpus_baseline_{category}_recall"
        ] = (
            baseline_keyword_summary[
                category
            ]["recall"]
        )
        corpus_metrics[
            f"corpus_qlora_{category}_recall"
        ] = (
            qlora_keyword_summary[
                category
            ]["recall"]
        )

    for key, value in corpus_metrics.items():
        results_df[key] = value

    results_df["merged"] = args.merged

    # ========================================================
    # CSV
    # ========================================================

    output_dir = (
        qlora_path
        if args.merged
        else qlora_path.parent
    )

    output_csv = (
        output_dir
        / (
            f"compare_{args.split}"
            f"_{len(results_df)}"
            f"_seed-{args.seed}.csv"
        )
    )

    output_csv.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    results_df.to_csv(
        output_csv,
        index=False,
        encoding="utf-8-sig",
    )

    print()

    print(
        f"결과 저장:"
        f" {output_csv}"
    )

    print()

    print("=" * 70)
    print("테스트 종료")
    print("=" * 70)


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":

    main()