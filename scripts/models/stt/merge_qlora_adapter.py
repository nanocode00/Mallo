"""
QLoRA 어댑터 BF16 머지
======================

4-bit QLoRA 어댑터(peft)를 BF16 베이스 모델에 머지해
추론 속도 병목(4-bit 역양자화)을 제거한 모델을 만든다.

배경:
    - S-14 재평가 결과 4-bit QLoRA 추론 latency가 Baseline의 ~2.2배
      (1.137s vs 0.513s) 였다.
    - 4-bit는 추론 시 매 레이어마다 dequantize → 계산이 느려진다.
    - 어댑터를 BF16 베이스에 머지하면 별도 dequantize 없이
      native BF16 계산으로 떨어져 latency가 Baseline 수준으로 줄어든다.

동작:
    1. 베이스(openai/whisper-medium)를 BF16으로 로드
    2. QLoRA 어댑터 부착 → merge_and_unload()
    3. BF16 머지 모델 + processor 저장 (models/.../merged-bf16/)
       — 머지 모델만으로 서빙 가능하도록 processor도 같은 디렉터리에 저장한다.

사용법 (GPU venv에서):
    python merge_qlora_adapter.py
    python merge_qlora_adapter.py --checkpoint <어댑터 경로>
"""

from __future__ import annotations

import argparse
import gc
import sys
from pathlib import Path

import torch

from peft import PeftModel

from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
)

from adapters.stt.common import (
    setup_cuda_dll_paths,
    MODELS_DIR,
    MODEL_ID,
)


setup_cuda_dll_paths()

# 화자 단위 split(seed 42)으로 재학습한 어댑터.
# 구버전 파일 단위 split으로 학습한 checkpoint는 test 누출 가능성이 있어 사용하지 않는다.
DEFAULT_ADAPTER_PATH = (
    MODELS_DIR
    / "whisper-medium-qlora-speaker-split"
    / "lr-2e-05_ep-5"
    / "checkpoint-220"
)

OUTPUT_DIR_NAME = "merged-bf16"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="QLoRA 어댑터를 BF16 베이스에 머지 후 저장"
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=str(DEFAULT_ADAPTER_PATH),
        help="머지할 QLoRA 어댑터 경로",
    )
    args = parser.parse_args()

    adapter_path = Path(args.checkpoint)
    if not adapter_path.exists():
        raise FileNotFoundError(
            f"어댑터 경로를 찾을 수 없습니다: {adapter_path.resolve()}"
        )

    output_dir = adapter_path.parent / OUTPUT_DIR_NAME

    print("=" * 70)
    print("QLoRA 어댑터 BF16 머지")
    print("=" * 70)
    print(f"베이스     : {MODEL_ID}")
    print(f"어댑터     : {adapter_path}")
    print(f"출력 경로  : {output_dir}")
    print()

    print("베이스 모델(BF16) 로딩...")
    base_model = (
        WhisperForConditionalGeneration
        .from_pretrained(
            MODEL_ID,
            torch_dtype=torch.bfloat16,
        )
        .to("cuda")
    )

    print("어댑터 부착...")
    peft_model = PeftModel.from_pretrained(
        base_model,
        str(adapter_path),
    )
    peft_model.eval()

    print("머지(may take a few minutes)...")
    merged_model = peft_model.merge_and_unload()
    merged_model = merged_model.to(dtype=torch.bfloat16)
    merged_model.eval()

    merged_dtype = next(merged_model.parameters()).dtype
    print(f"머지 완료 | dtype: {merged_dtype}")

    del peft_model, base_model
    gc.collect()
    torch.cuda.empty_cache()

    print(f"저장: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    merged_model.save_pretrained(str(output_dir))

    print("processor 저장...")
    processor = WhisperProcessor.from_pretrained(
        MODEL_ID,
        language="ko",
        task="transcribe",
    )
    processor.save_pretrained(str(output_dir))

    del merged_model, processor
    gc.collect()
    torch.cuda.empty_cache()

    print("=" * 70)
    print("완료")
    print("=" * 70)


if __name__ == "__main__":
    main()
