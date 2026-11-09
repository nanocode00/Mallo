"""
Whisper Medium QLoRA Fine-tuning
================================

Model:
    openai/whisper-medium

Method:
    QLoRA
    - 4-bit NF4 quantization
    - LoRA adapter

Dataset:
    train.csv      : 350
    validation.csv : 75

Language:
    Korean

Task:
    Speech-to-Text / Transcription

First experiment:
    LR      = 1e-5
    Epochs  = 5
    Batch   = 1
    Grad Accum = 8

Metrics:
    WER
    CER

Example:
    python finetune_whisper_qlora.py ^
        --lr 1e-5 ^
        --epochs 5 ^
        --batch-size 1 ^
        --grad-accum 8 ^
        --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd
import soundfile as sf
import torch

# 이 스크립트는 파일 경로로 직접 실행하는 것을 공식 진입점으로 한다.
# (문서 상단 예시, finetune_kiosk.py의 subprocess 호출 모두 직접 실행)
# 따라서 같은 디렉터리 모듈은 common/metrics와 동일하게 bare import를 사용한다.
try:
    from scripts.eval.stt.experiment_tracking import (
        compute_split_hash,
        resolve_resume_checkpoint,
    )
except ImportError:
    from experiment_tracking import (
        compute_split_hash,
        resolve_resume_checkpoint,
    )


from datasets import Dataset

from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
    BitsAndBytesConfig,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
)

from peft import (
    LoraConfig,
    prepare_model_for_kbit_training,
)

from adapters.stt.common import (
    setup_cuda_dll_paths,
    set_seed,
    require_cuda,
    resample_to_16k_mono,
    TRAIN_CSV,
    VALIDATION_CSV,
    MODELS_DIR,
    MODEL_ID,
)
from scripts.eval.stt.metrics import corpus_cer, corpus_wer


# ============================================================
# 1. CUDA DLL PATH
# ============================================================

setup_cuda_dll_paths()


# ============================================================
# 2. CONFIG
# ============================================================

DEFAULT_OUTPUT_DIR = (
    MODELS_DIR
    / "whisper-medium-qlora"
)


# ============================================================
# 3. Data Collator
# ============================================================

@dataclass
class DataCollatorSpeechSeq2SeqWithPadding:

    processor: WhisperProcessor

    def __call__(self, features):

        # ----------------------------------------------------
        # Audio features
        # ----------------------------------------------------

        input_features = [
            {
                "input_features":
                    feature["input_features"]
            }
            for feature in features
        ]

        batch = (
            self.processor
            .feature_extractor
            .pad(
                input_features,
                return_tensors="pt",
            )
        )

        # ----------------------------------------------------
        # Labels
        # ----------------------------------------------------

        label_features = [
            {
                "input_ids":
                    feature["labels"]
            }
            for feature in features
        ]

        labels_batch = (
            self.processor
            .tokenizer
            .pad(
                label_features,
                return_tensors="pt",
            )
        )

        labels = (
            labels_batch["input_ids"]
            .masked_fill(
                labels_batch[
                    "attention_mask"
                ].ne(1),
                -100,
            )
        )

        # BOS 제거
        if (
            labels.shape[1] > 0
            and (
                labels[:, 0]
                ==
                self.processor
                .tokenizer
                .bos_token_id
            ).all()
        ):
            labels = labels[:, 1:]

        batch["labels"] = labels

        return batch


# ============================================================
# 4. Dataset Loading
# ============================================================

def load_dataset_from_csv(
    csv_path: Path,
) -> Dataset:

    if not csv_path.exists():

        raise FileNotFoundError(
            f"CSV 파일을 찾을 수 없습니다:\n"
            f"{csv_path.resolve()}"
        )

    df = pd.read_csv(csv_path)

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
            f"필수 컬럼이 없습니다: "
            f"{missing}\n"
            f"현재 컬럼: {list(df.columns)}"
        )

    return Dataset.from_pandas(
        df,
        preserve_index=False,
    )


# ============================================================
# 5. Audio preprocessing
# ============================================================

def prepare_dataset(
    batch,
    processor: WhisperProcessor,
):

    audio_path = batch["audio_path"]

    if not os.path.exists(audio_path):

        raise FileNotFoundError(
            f"음성 파일을 찾을 수 없습니다:\n"
            f"{audio_path}"
        )

    # --------------------------------------------------------
    # Load audio (공통 유틸리티로 16kHz 모노 변환)
    # --------------------------------------------------------

    audio_array, sampling_rate = (
        sf.read(audio_path)
    )
    audio_array, sampling_rate = resample_to_16k_mono(audio_array, sampling_rate)

    # --------------------------------------------------------
    # Whisper feature
    # --------------------------------------------------------

    input_features = (
        processor
        .feature_extractor(
            audio_array,
            sampling_rate=sampling_rate,
        )
        .input_features[0]
    )

    # --------------------------------------------------------
    # Text → tokens
    # --------------------------------------------------------

    labels = (
        processor.tokenizer(
            batch["reference"],
            truncation=True,
            max_length=448,
        )
        .input_ids
    )

    return {
        "input_features":
            input_features,
        "labels":
            labels,
    }


# ============================================================
# 6. Metrics
# ============================================================

def compute_metrics(
    pred,
    processor,
):

    pred_ids = pred.predictions

    # generate 결과가 tuple인 경우
    if isinstance(pred_ids, tuple):

        pred_ids = pred_ids[0]

    label_ids = pred.label_ids.copy()

    # -100 → PAD
    label_ids[
        label_ids == -100
    ] = (
        processor
        .tokenizer
        .pad_token_id
    )

    # IDs → Text

    pred_str = (
        processor
        .batch_decode(
            pred_ids,
            skip_special_tokens=True,
        )
    )

    label_str = (
        processor
        .batch_decode(
            label_ids,
            skip_special_tokens=True,
        )
    )

    # 문장별 CER/WER의 평균이 아니라 corpus-level로 집계한다.
    # (짧은 문장과 긴 문장이 같은 비중으로 반영되는 편향 제거)
    return {
        "wer": corpus_wer(label_str, pred_str),
        "cer": corpus_cer(label_str, pred_str),
    }


# ============================================================
# 7. Main
# ============================================================

def main():

    # ========================================================
    # Arguments
    # ========================================================

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--lr",
        type=float,
        default=1e-5,
    )

    parser.add_argument(
        "--epochs",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--grad-accum",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="재현을 위한 랜덤 시드",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
    )

    parser.add_argument(
        "--train-csv",
        type=str,
        default=None,
        help="커스텀 학습 CSV 경로 (미지정 시 기본 splits/train.csv 사용)",
    )

    parser.add_argument(
        "--val-csv",
        type=str,
        default=None,
        help="커스텀 검증 CSV 경로 (미지정 시 기본 splits/validation.csv 사용)",
    )

    parser.add_argument(
        "--base-model",
        type=str,
        default=None,
        help="베이스 모델 경로 또는 HuggingFace 모델 ID (미지정 시 openai/whisper-medium 사용)",
    )

    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="최대 학습 스텝 수 (지정 시 epochs 대신 사용, 예: 600)",
    )

    parser.add_argument(
        "--save-steps",
        type=int,
        default=100,
        help="체크포인트 저장 주기 (max-steps 사용 시)",
    )

    parser.add_argument(
        "--eval-steps",
        type=int,
        default=100,
        help="검증 주기 (max-steps 사용 시)",
    )

    parser.add_argument(
        "--eval-at-end-only",
        action="store_true",
        help="학습 중 validation 비활성화, 종료 시 1회만 수행",
    )

    parser.add_argument(
        "--resume-from-checkpoint",
        type=str,
        default=None,
        help="체크포인트 경로에서 학습 재개 (예: checkpoint-100)",
    )

    args = parser.parse_args()

    # ========================================================
    # Seed 고정 (재현성)
    # ========================================================

    set_seed(args.seed)

    # ========================================================
    # Output directory
    # ========================================================

    if args.output:

        output_dir = Path(
            args.output
        )

    else:

        output_dir = (
            DEFAULT_OUTPUT_DIR
            / (
                f"lr-{args.lr:.0e}"
                f"_ep-{args.epochs}"
            )
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ========================================================
    # CSV 경로 결정
    # ========================================================

    train_csv = Path(args.train_csv) if args.train_csv else TRAIN_CSV
    val_csv = Path(args.val_csv) if args.val_csv else VALIDATION_CSV

    # ========================================================
    # Header
    # ========================================================

    base_model_id = args.base_model if args.base_model else MODEL_ID

    print()
    print("=" * 70)
    print("Whisper Medium QLoRA Fine-tuning")
    print("=" * 70)

    print(
        f"Model        : {base_model_id}"
    )

    print(
        f"Method       : QLoRA"
    )

    print(
        f"Quantization : 4-bit NF4"
    )

    print(
        f"Learning rate: {args.lr}"
    )

    print(
        f"Epochs       : {args.epochs}"
    )

    print(
        f"Batch size   : {args.batch_size}"
    )

    print(
        f"Grad accum   : {args.grad_accum}"
    )

    print(
        f"Train CSV    : {train_csv}"
    )

    print(
        f"Val CSV      : {val_csv}"
    )

    print(
        f"Effective BS : "
        f"{args.batch_size * args.grad_accum}"
    )

    print(
        f"Seed         : {args.seed}"
    )

    print(
        f"Output       : {output_dir}"
    )

    print("=" * 70)
    print()

    # ========================================================
    # GPU
    # ========================================================

    device = require_cuda()

    gpu_name = (
        torch.cuda
        .get_device_name(0)
    )

    gpu_memory = (
        torch.cuda
        .get_device_properties(0)
        .total_memory
        / 1024**3
    )

    print(
        f"GPU  : {gpu_name}"
    )

    print(
        f"VRAM : {gpu_memory:.1f} GB"
    )

    print()

    # ========================================================
    # Processor
    # ========================================================

    print(
        "Processor 로딩..."
    )

    processor = (
        WhisperProcessor
        .from_pretrained(
            base_model_id,
            language="ko",
            task="transcribe",
        )
    )

    print(
        "Processor 완료"
    )

    print()

    # ========================================================
    # Dataset
    # ========================================================

    print(
        "Dataset 로딩..."
    )

    train_dataset = (
        load_dataset_from_csv(
            train_csv
        )
    )

    validation_dataset = (
        load_dataset_from_csv(
            val_csv
        )
    )

    print(
        f"Train      : "
        f"{len(train_dataset)}"
    )

    print(
        f"Validation : "
        f"{len(validation_dataset)}"
    )

    print()

    # ========================================================
    # Preprocessing
    # ========================================================

    print(
        "Audio preprocessing..."
    )

    train_dataset = (
        train_dataset.map(
            lambda batch:
                prepare_dataset(
                    batch,
                    processor,
                ),
            remove_columns=
                train_dataset.column_names,
            desc="Train",
        )
    )

    validation_dataset = (
        validation_dataset.map(
            lambda batch:
                prepare_dataset(
                    batch,
                    processor,
                ),
            remove_columns=
                validation_dataset.column_names,
            desc="Validation",
        )
    )

    print(
        "Preprocessing 완료"
    )

    print()

    # ========================================================
    # Data Collator
    # ========================================================

    data_collator = (
        DataCollatorSpeechSeq2SeqWithPadding(
            processor=processor
        )
    )

    # ========================================================
    # Metrics
    # ========================================================

    # jiwer 기반 오프라인 지표를 사용한다 (evaluate는 HF hub 다운로드 필요).
    print(
        "Metrics: jiwer (offline)"
    )

    print()

    # ========================================================
    # 4-bit Quantization
    # ========================================================

    print(
        "4-bit Quantization 설정..."
    )

    bnb_config = BitsAndBytesConfig(

        load_in_4bit=True,

        bnb_4bit_quant_type="nf4",

        bnb_4bit_compute_dtype=torch.bfloat16,

        bnb_4bit_use_double_quant=True,
    )

    # ========================================================
    # Model
    # ========================================================

    print(
        "Whisper Medium 4-bit 모델 로딩..."
    )

    model = (
        WhisperForConditionalGeneration
        .from_pretrained(
            base_model_id,

            quantization_config=
                bnb_config,

            device_map={
                "": 0,
            },

            torch_dtype=torch.bfloat16,
        )
    )

    print(
        "4-bit 모델 로딩 완료"
    )

    print()

    # ========================================================
    # Generation settings
    # ========================================================

    model.generation_config.language = (
        "ko"
    )

    model.generation_config.task = (
        "transcribe"
    )

    model.config.use_cache = False

    # ========================================================
    # Prepare model for k-bit training
    # ========================================================

    print(
        "k-bit training 준비..."
    )

    model = prepare_model_for_kbit_training(
        model
    )

    # ========================================================
    # Gradient Checkpointing
    # ========================================================

    model.gradient_checkpointing_enable()

    # ========================================================
    # LoRA
    # ========================================================

    print(
        "LoRA 설정..."
    )

    lora_config = LoraConfig(

        r=8,

        lora_alpha=16,

        lora_dropout=0.05,

        target_modules=[
            "q_proj",
            "v_proj",
        ],

        bias="none",

        task_type="SEQ_2_SEQ_LM",

    )

    # ========================================================
    # Attach adapter
    # ========================================================

    print(
        "LoRA Adapter 추가..."
    )

    model.add_adapter(
        lora_config
    )

    # ========================================================
    # Parameter statistics
    # ========================================================

    trainable_params = 0
    total_params = 0

    for param in model.parameters():

        total_params += param.numel()

        if param.requires_grad:

            trainable_params += (
                param.numel()
            )

    trainable_ratio = (
        trainable_params
        / total_params
        * 100
    )

    print()

    print(
        f"Total parameters     : "
        f"{total_params:,}"
    )

    print(
        f"Trainable parameters : "
        f"{trainable_params:,}"
    )

    print(
        f"Trainable ratio      : "
        f"{trainable_ratio:.4f}%"
    )

    print()

    # ========================================================
    # Training arguments
    # ========================================================

    # max_steps가 지정되면 steps 기반 전략 사용, 아니면 epoch 기반
    use_steps = args.max_steps is not None
    eval_during_training = not args.eval_at_end_only

    training_args = (
        Seq2SeqTrainingArguments(

            output_dir=str(
                output_dir
            ),

            # Batch
            per_device_train_batch_size=(
                args.batch_size
            ),

            per_device_eval_batch_size=(
                args.batch_size
            ),

            gradient_accumulation_steps=(
                args.grad_accum
            ),

            # Learning
            learning_rate=args.lr,

            num_train_epochs=args.epochs if not use_steps else 1,
            max_steps=args.max_steps if use_steps else -1,

            warmup_steps=50,

            # Evaluation
            eval_strategy="steps" if (use_steps and eval_during_training) else ("epoch" if (not use_steps and eval_during_training) else "no"),
            eval_steps=args.eval_steps if (use_steps and eval_during_training) else None,

            save_strategy="steps" if use_steps else "epoch",
            save_steps=args.save_steps if use_steps else None,

            # QLoRA 체크포인트에는 pytorch_model.bin 대신 adapter 파일만 저장되므로
            # load_best_model_at_end=True 는 _load_best_model() 에서 크래시를 유발한다.
            # 최적 에폭은 trainer.state.best_model_checkpoint 로 기록하되,
            # 종료 시점 모델(최종 에폭)을 그대로 저장한다.
            load_best_model_at_end=False,

            metric_for_best_model="cer",

            greater_is_better=False,

            # Generation
            predict_with_generate=True,

            generation_max_length=448,

            # FP16
            fp16=False,
            bf16=True,

            # Gradient checkpointing
            gradient_checkpointing=True,

            # Logging
            logging_steps=10,

            report_to="none",

            # Checkpoint
            save_total_limit=5,

            # Important for custom dataset
            remove_unused_columns=False,
        )
    )

    # ========================================================
    # Trainer
    # ========================================================

    trainer = Seq2SeqTrainer(

        model=model,

        args=training_args,

        train_dataset=train_dataset,

        eval_dataset=validation_dataset if eval_during_training else None,

        data_collator=data_collator,

        processing_class=processor,

        compute_metrics=(
            lambda pred:
                compute_metrics(
                    pred,
                    processor,
                )
        ),
    )

    # ========================================================
    # Train
    # ========================================================

    print()
    print("=" * 70)
    print("QLoRA 학습 시작")
    print("=" * 70)
    print()

    resume_checkpoint = resolve_resume_checkpoint(
        args.resume_from_checkpoint, output_dir
    )
    if resume_checkpoint:
        print(f"체크포인트에서 재개: {resume_checkpoint}")
    elif args.resume_from_checkpoint:
        print(
            f"체크포인트를 찾을 수 없어 처음부터 시작: "
            f"{args.resume_from_checkpoint}"
        )

    train_result = trainer.train(resume_from_checkpoint=resume_checkpoint)

    # ========================================================
    # Training finished
    # ========================================================

    print()
    print("=" * 70)
    print("학습 완료")
    print("=" * 70)
    print()

    # ========================================================
    # Save LoRA Adapter
    # ========================================================

    print(
        "LoRA Adapter 저장..."
    )

    trainer.save_model(
        str(output_dir)
    )

    processor.save_pretrained(
        str(output_dir)
    )

    print(
        f"저장 완료:"
        f" {output_dir}"
    )

    print()

    # ========================================================
    # Evaluation
    # ========================================================

    print("=" * 70)
    print("최종 Validation 평가")
    print("=" * 70)
    print()

    if eval_during_training:
        eval_results = trainer.evaluate()
    else:
        # validation dataset로 직접 평가 수행
        print("학습 중 validation 비활성화됨 -> 수동 평가 수행...")
        eval_results = trainer.evaluate(eval_dataset=validation_dataset)

    print(
        json.dumps(
            eval_results,
            indent=2,
            ensure_ascii=False,
        )
    )

    # ========================================================
    # Experiment log
    # ========================================================

    experiment_log = {

        "model": MODEL_ID,

        "method": "QLoRA",

        "language": "ko",

        "task": "transcribe",

        "quantization": {

            "bits": 4,

            "type": "nf4",

            "double_quant": True,

            "compute_dtype": "bfloat16",
        },

        "lora": {

            "r": 8,

            "alpha": 16,

            "dropout": 0.05,

            "target_modules": [
                "q_proj",
                "v_proj",
            ],
        },

        "learning_rate": args.lr,

        "epochs": args.epochs if not use_steps else None,

        "max_steps": args.max_steps if use_steps else None,

        "eval_at_end_only": args.eval_at_end_only,

        "resume_from_checkpoint": args.resume_from_checkpoint,

        "batch_size": args.batch_size,

        "gradient_accumulation_steps":
            args.grad_accum,

        "seed": args.seed,

        "effective_batch_size":
            (
                args.batch_size
                * args.grad_accum
            ),

        "train_samples":
            len(train_dataset),

        "validation_samples":
            len(validation_dataset),

        "train_csv": str(train_csv),

        "val_csv": str(val_csv),

        "train_split_hash": compute_split_hash(train_csv),

        "val_split_hash": compute_split_hash(val_csv),

        "gpu": gpu_name,

        "total_parameters":
            total_params,

        "trainable_parameters":
            trainable_params,

        "trainable_ratio":
            trainable_ratio,

        "best_checkpoint":
            trainer.state
            .best_model_checkpoint,

        "best_metric":
            trainer.state.best_metric,

        "evaluation":
            eval_results,

        "train_metrics":
            train_result.metrics,
    }

    log_path = (
        output_dir
        / "experiment_log.json"
    )

    with open(
        log_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            experiment_log,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"실험 기록 저장:"
        f" {log_path}"
    )

    print()
    print("=" * 70)
    print("실험 종료")
    print("=" * 70)

    # ========================================================
    # 체크포인트 백업 (재발 방지)
    # ========================================================

    backup_dir = output_dir / ".." / "checkpoint_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    import shutil
    checkpoint_pattern = output_dir / "checkpoint-*"
    backuped = 0
    for cp in output_dir.glob("checkpoint-*"):
        try:
            cp_name = cp.name.replace("/", "_").replace("\\", "_")
            dest = backup_dir / cp_name
            shutil.copytree(cp, dest, dirs_exist_ok=True)
            backuped += 1
        except Exception as e:
            print(f"체크포인트 백업 실패 {cp.name}: {e}")

    print(f"백업 완료: {backuped}개 체크포인트 저장 -> {backup_dir}")


if __name__ == "__main__":
    main()