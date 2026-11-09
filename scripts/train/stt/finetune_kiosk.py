"""
키오스크 주문 데이터 QLoRA 파인튜닝
=================================

기존 도메인 파인튜닝된 모델을 키오스크 주문 데이터로 추가 파인튜닝한다.

실행 방법 (GPU 환경 필요):
    # 테스트 실행 (600 steps, 약 0.32 epoch)
    python finetune_kiosk.py --max-steps 600 --save-steps 100 --eval-steps 100

    # 정식 실행 (3 epochs)
    python finetune_kiosk.py --epochs 3

결과:
    - models/whisper-medium-qlora-kiosk/ 에 모델 저장
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STT_DIR = Path(__file__).resolve().parent

KIOSK_TRAIN_CSV = STT_DIR / "stt_data" / "kiosk" / "train.csv"
KIOSK_VAL_CSV = STT_DIR / "stt_data" / "kiosk" / "validation.csv"

# 기존 도메인 파인튜닝된 모델을 베이스로 사용
BASE_MODEL = str(
    STT_DIR
    / "models"
    / "whisper-medium-qlora-domain"
    / "merged-bf16"
)

# 출력 디렉토리
OUTPUT_DIR = STT_DIR / "models" / "whisper-medium-qlora-kiosk"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="키오스크 데이터 QLoRA 파인튜닝")
    parser.add_argument("--lr", type=float, default=2e-5, help="Learning rate")
    parser.add_argument("--epochs", type=int, default=3, help="Epochs (max-steps 미지정 시)")
    parser.add_argument("--batch-size", type=int, default=1, help="Batch size")
    parser.add_argument("--grad-accum", type=int, default=8, help="Gradient accumulation steps")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--max-steps", type=int, default=None, help="최대 학습 스텝 수 (지정 시 epochs 대신 사용, 예: 600)")
    parser.add_argument("--save-steps", type=int, default=100, help="체크포인트 저장 주기 (max-steps 사용 시)")
    parser.add_argument("--eval-steps", type=int, default=100, help="검증 주기 (max-steps 사용 시)")
    parser.add_argument("--eval-at-end-only", action="store_true", help="학습 중 validation 비활성화, 종료 시 1회만 수행")
    parser.add_argument("--output", type=str, default=None, help="출력 디렉토리 (미지정시 기본값)")
    parser.add_argument("--base-model", type=str, default=None, help="베이스 모델 경로 (미지정시 domain merged-bf16)")

    args = parser.parse_args()

    print("=" * 60)
    print("키오스크 주문 데이터 QLoRA 파인튜닝")
    print("=" * 60)

    # 데이터 확인
    if not KIOSK_TRAIN_CSV.exists():
        print(f"오류: 학습 CSV를 찾을 수 없습니다: {KIOSK_TRAIN_CSV}")
        print("먼저 preprocess_kiosk.py를 실행하세요.")
        sys.exit(1)

    if not KIOSK_VAL_CSV.exists():
        print(f"오류: 검증 CSV를 찾을 수 없습니다: {KIOSK_VAL_CSV}")
        print("먼저 preprocess_kiosk.py를 실행하세요.")
        sys.exit(1)

    # 베이스 모델 확인
    base_model = args.base_model if args.base_model else BASE_MODEL
    base_path = Path(base_model)
    if not base_path.exists():
        print(f"경고: 베이스 모델을 찾을 수 없습니다: {base_path}")
        print("openai/whisper-medium를 베이스로 사용합니다.")
        base_model = "openai/whisper-medium"

    output_dir = Path(args.output) if args.output else OUTPUT_DIR

    print(f"학습 CSV:  {KIOSK_TRAIN_CSV}")
    print(f"검증 CSV:  {KIOSK_VAL_CSV}")
    print(f"베이스:    {base_model}")
    print(f"출력:      {output_dir}")
    print(f"LR:        {args.lr}")
    print(f"Epochs:    {args.epochs if not args.max_steps else 'N/A (max-steps 사용)'}")
    print(f"Max Steps: {args.max_steps if args.max_steps else 'N/A'}")
    print(f"Batch:     {args.batch_size}")
    print(f"Grad Accum: {args.grad_accum}")
    print(f"Seed:      {args.seed}")
    print()

    # 파인튜닝 실행
    cmd = [
        sys.executable,
        str(STT_DIR / "finetune_whisper_qlora.py"),
        "--lr", str(args.lr),
        "--batch-size", str(args.batch_size),
        "--grad-accum", str(args.grad_accum),
        "--seed", str(args.seed),
        "--train-csv", str(KIOSK_TRAIN_CSV),
        "--val-csv", str(KIOSK_VAL_CSV),
        "--base-model", base_model,
        "--output", str(output_dir),
    ]

    if args.max_steps:
        cmd.extend(["--max-steps", str(args.max_steps)])
        cmd.extend(["--save-steps", str(args.save_steps)])
        cmd.extend(["--eval-steps", str(args.eval_steps)])
    else:
        cmd.extend(["--epochs", str(args.epochs)])

    if args.eval_at_end_only:
        cmd.append("--eval-at-end-only")

    print("실행 명령어:")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=str(STT_DIR))

    if result.returncode == 0:
        print()
        print("=" * 60)
        print("파인튜닝 완료!")
        print(f"모델 저장: {output_dir}")
        print("=" * 60)
    else:
        print()
        print(f"오류: 파인튜닝 실패 (종료 코드: {result.returncode})")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()