"""Qwen3-1.7B NLU NF4 QLoRA 또는 BF16-native LoRA 학습 CLI."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from adapters.nlu.qwen_training_data import DEFAULT_OUTPUT_DIR, REPOSITORY_ROOT


MODEL_ID = "Qwen/Qwen3-1.7B"
MODEL_REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
DEFAULT_RUN_DIR = REPOSITORY_ROOT / "models/nlu/qwen3-1.7b-qlora"
MODEL_DOWNLOAD_BYTES = 4_077_751_381
WARMUP_RATIO = 0.03
REQUIRED_PACKAGES = (
    "torch",
    "transformers",
    "trl",
    "peft",
    "accelerate",
    "bitsandbytes",
    "datasets",
)


class TrainingEnvironmentError(RuntimeError):
    """실제 QLoRA 학습 환경이 요구사항을 충족하지 않는다."""


@dataclass(frozen=True)
class TrainingConfig:
    train_path: Path = DEFAULT_OUTPUT_DIR / "train.jsonl"
    validation_path: Path = DEFAULT_OUTPUT_DIR / "validation.jsonl"
    output_dir: Path = DEFAULT_RUN_DIR
    model_id: str = MODEL_ID
    revision: str = MODEL_REVISION
    max_length: int = 2048
    epochs: float = 3.0
    learning_rate: float = 2e-4
    micro_batch_size: int = 2
    gradient_accumulation_steps: int = 8
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    seed: int = 42
    training_precision: str = "nf4"
    allow_download: bool = False

    def validate(self) -> None:
        for path in (self.train_path, self.validation_path):
            if not path.is_file():
                raise TrainingEnvironmentError(f"학습 입력 파일이 없습니다: {path}")
        train_ids = self._split_ids(self.train_path, "train")
        validation_ids = self._split_ids(self.validation_path, "validation")
        overlap = sorted(train_ids & validation_ids)
        if overlap:
            raise TrainingEnvironmentError(
                f"동일 sample_id가 Train과 Validation에 동시에 있습니다: {overlap[:3]}"
            )
        if self.epochs <= 0 or self.learning_rate <= 0:
            raise TrainingEnvironmentError("epoch와 learning rate는 양수여야 합니다")
        if self.micro_batch_size < 1 or self.gradient_accumulation_steps < 1:
            raise TrainingEnvironmentError("batch 설정은 1 이상이어야 합니다")
        if self.training_precision not in {"nf4", "bf16"}:
            raise TrainingEnvironmentError("training precision은 nf4 또는 bf16이어야 합니다")

    @staticmethod
    def _split_ids(path: Path, expected: str) -> set[str]:
        """파일명이 아니라 행별 metadata.split으로 Split 역할을 검증한다."""

        ids: set[str] = set()
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise TrainingEnvironmentError(
                        f"{path.name} {number}행 JSON 파싱 실패: {error}"
                    ) from error
                metadata = record.get("metadata") if isinstance(record, dict) else None
                sample_id = record.get("sample_id") if isinstance(record, dict) else None
                split = metadata.get("split") if isinstance(metadata, dict) else None
                if split != expected or not isinstance(sample_id, str):
                    hint = ""
                    if split == "test":
                        hint = " (Test Split은 학습이나 checkpoint 선택에 사용할 수 없습니다)"
                    elif split is None:
                        hint = " (metadata.split 필드가 없습니다)"
                    raise TrainingEnvironmentError(
                        f"{path.name} {number}행({sample_id})의 metadata.split은 "
                        f"'{expected}'여야 하는데 '{split}'입니다{hint}"
                    )
                ids.add(sample_id)
        if not ids:
            raise TrainingEnvironmentError(f"{path.name}에 행이 없습니다")
        return ids


@dataclass(frozen=True)
class HardwareReport:
    cuda_available: bool
    device_count: int
    device_name: str | None
    compute_capability: tuple[int, int] | None
    total_vram_bytes: int | None
    bf16_supported: bool
    package_versions: dict[str, str | None]

    @property
    def training_ready(self) -> bool:
        return bool(
            self.cuda_available
            and self.device_count > 0
            and self.compute_capability is not None
            and self.compute_capability >= (6, 0)
        )


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package in REQUIRED_PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def detect_hardware() -> HardwareReport:
    """모델을 로드하지 않고 PyTorch CUDA 환경만 검사한다."""

    try:
        import torch
    except ImportError:
        return HardwareReport(False, 0, None, None, None, False, _package_versions())
    available = torch.cuda.is_available()
    count = torch.cuda.device_count() if available else 0
    if not count:
        return HardwareReport(False, 0, None, None, None, False, _package_versions())
    properties = torch.cuda.get_device_properties(0)
    return HardwareReport(
        True,
        count,
        properties.name,
        torch.cuda.get_device_capability(0),
        properties.total_memory,
        torch.cuda.is_bf16_supported(),
        _package_versions(),
    )


def require_training_hardware(report: HardwareReport) -> None:
    if not report.cuda_available or report.device_count == 0:
        raise TrainingEnvironmentError("CUDA GPU가 없어 QLoRA 학습을 시작할 수 없습니다")
    if report.compute_capability is None or report.compute_capability < (6, 0):
        raise TrainingEnvironmentError("NF4 학습에는 Compute Capability 6.0 이상이 필요합니다")


def optimizer_step_count(config: TrainingConfig) -> int:
    """현재 데이터와 batch 설정으로 단일 GPU optimizer step 수를 계산한다."""

    with config.train_path.open(encoding="utf-8") as train_file:
        train_rows = sum(1 for line in train_file if line.strip())
    if train_rows == 0:
        raise TrainingEnvironmentError("학습 입력이 비어 있습니다")
    batches_per_epoch = math.ceil(train_rows / config.micro_batch_size)
    updates_per_epoch = math.ceil(batches_per_epoch / config.gradient_accumulation_steps)
    return math.ceil(updates_per_epoch * config.epochs)


def sft_arguments(config: TrainingConfig, *, bf16: bool) -> dict[str, Any]:
    """테스트 가능한 TRL SFTConfig 인자 사전을 반환한다."""

    return {
        "output_dir": str(config.output_dir / "checkpoints"),
        "num_train_epochs": config.epochs,
        "learning_rate": config.learning_rate,
        "per_device_train_batch_size": config.micro_batch_size,
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "gradient_checkpointing": True,
        "optim": "paged_adamw_8bit" if config.training_precision == "nf4" else "adamw_torch_fused",
        "lr_scheduler_type": "cosine",
        "warmup_steps": math.ceil(optimizer_step_count(config) * WARMUP_RATIO),
        "weight_decay": 0.01,
        "max_grad_norm": 1.0,
        "eval_strategy": "steps",
        "eval_steps": 50,
        "save_strategy": "steps",
        "save_steps": 50,
        "save_total_limit": None,
        "logging_steps": 10,
        "load_best_model_at_end": False,
        "max_length": config.max_length,
        "assistant_only_loss": True,
        "packing": False,
        "bf16": bf16,
        "fp16": not bf16,
        "seed": config.seed,
        "report_to": "none",
    }


def dry_run_report(config: TrainingConfig, hardware: HardwareReport) -> dict[str, Any]:
    config.validate()
    return {
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "hardware": asdict(hardware) | {"training_ready": hardware.training_ready},
        "model_download": {
            "required_bytes": MODEL_DOWNLOAD_BYTES,
            "allowed": config.allow_download,
            "local_files_only": not config.allow_download,
        },
        "sft_arguments": sft_arguments(config, bf16=hardware.bf16_supported),
    }


def run_training(config: TrainingConfig, hardware: HardwareReport) -> Path:
    """사전 검사를 통과한 단일 GPU에서 NF4 QLoRA 또는 BF16 LoRA SFT를 실행한다."""

    config.validate()
    require_training_hardware(hardware)
    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer
    except ImportError as error:
        raise TrainingEnvironmentError(f"NLU 학습 의존성이 없습니다: {error.name}") from error

    compute_dtype = torch.bfloat16 if hardware.bf16_supported else torch.float16
    if config.training_precision == "bf16" and not hardware.bf16_supported:
        raise TrainingEnvironmentError("BF16-native LoRA 학습에는 BF16 지원 GPU가 필요합니다")
    load_options = {
        "revision": config.revision,
        "local_files_only": not config.allow_download,
    }
    tokenizer = AutoTokenizer.from_pretrained(config.model_id, **load_options)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    model_options: dict[str, Any] = {
        "device_map": {"": 0},
        "dtype": compute_dtype,
        "attn_implementation": "sdpa",
        **load_options,
    }
    if config.training_precision == "nf4":
        model_options["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        )
    model = AutoModelForCausalLM.from_pretrained(config.model_id, **model_options)
    model.config.use_cache = False
    if config.training_precision == "nf4":
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    lora = LoraConfig(
        task_type="CAUSAL_LM",
        target_modules="all-linear",
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        bias="none",
    )
    train_dataset = load_dataset("json", data_files=str(config.train_path), split="train")
    validation_dataset = load_dataset("json", data_files=str(config.validation_path), split="train")
    trainer = SFTTrainer(
        model=model,
        args=SFTConfig(**sft_arguments(config, bf16=hardware.bf16_supported)),
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        processing_class=tokenizer,
        peft_config=lora,
    )
    result = trainer.train()
    adapter_dir = config.output_dir / "final-adapter"
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    manifest = dry_run_report(config, hardware) | {
        "train_metrics": result.metrics,
        "best_model_checkpoint": trainer.state.best_model_checkpoint,
        "best_metric": trainer.state.best_metric,
    }
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "training-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return adapter_dir


def finalize_adapter(run_dir: Path, checkpoint_dir: Path) -> Path:
    """semantic 평가로 선택한 checkpoint를 final-adapter로 확정한다."""
    if not (checkpoint_dir / "adapter_config.json").is_file():
        raise TrainingEnvironmentError(f"PEFT adapter checkpoint가 아닙니다: {checkpoint_dir}")
    target = run_dir / "final-adapter"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(checkpoint_dir, target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=TrainingConfig.train_path)
    parser.add_argument("--validation", type=Path, default=TrainingConfig.validation_path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--micro-batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--training-precision", choices=("nf4", "bf16"), default="nf4")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    config = TrainingConfig(
        train_path=args.train,
        validation_path=args.validation,
        output_dir=args.output_dir,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        micro_batch_size=args.micro_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        training_precision=args.training_precision,
        allow_download=args.allow_download,
    )
    hardware = detect_hardware()
    if args.dry_run:
        print(json.dumps(dry_run_report(config, hardware), ensure_ascii=False, indent=2, default=str))
        return 0
    adapter_dir = run_training(config, hardware)
    print(f"학습 완료: {adapter_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
