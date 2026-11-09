"""
도메인 데이터 QLoRA 파인튜닝 실행
================================

기존 방언 데이터 파인튜닝된 모델을 도메인 데이터로 추가 파인튜닝한다.

실행 방법 (GPU 환경 필요):
    python finetune_domain.py

결과:
    - models/whisper-medium-qlora-domain/ 에 모델 저장
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STT_DIR = Path(__file__).resolve().parent

DOMAIN_TRAIN_CSV = STT_DIR / "stt_data" / "domain_train_finetune" / "train.csv"
DOMAIN_VAL_CSV = STT_DIR / "stt_data" / "domain_train_finetune" / "validation.csv"

# 기존 모델을 베이스로 사용 (화자 단위 split, lr-2e-05, checkpoint-220)
BASE_MODEL = "openai/whisper-medium"

# 출력 디렉토리
OUTPUT_DIR = STT_DIR / "models" / "whisper-medium-qlora-domain"


def main() -> None:
    print("=" * 60)
    print("도메인 데이터 QLoRA 파인튜닝")
    print("=" * 60)

    # 데이터 확인
    if not DOMAIN_TRAIN_CSV.exists():
        print(f"오류: 학습 CSV를 찾을 수 없습니다: {DOMAIN_TRAIN_CSV}")
        print("먼저 synthesize_domain_train.py와 prepare_domain_train.py를 실행하세요.")
        sys.exit(1)

    if not DOMAIN_VAL_CSV.exists():
        print(f"오류: 검증 CSV를找不到 수 없습니다: {DOMAIN_VAL_CSV}")
        sys.exit(1)

    print(f"학습 CSV: {DOMAIN_TRAIN_CSV}")
    print(f"검증 CSV: {DOMAIN_VAL_CSV}")
    print(f"출력: {OUTPUT_DIR}")
    print()

    # 파인튜닝 실행
    cmd = [
        sys.executable,
        str(STT_DIR / "finetune_whisper_qlora.py"),
        "--lr", "2e-5",
        "--epochs", "5",
        "--batch-size", "1",
        "--grad-accum", "8",
        "--seed", "42",
        "--train-csv", str(DOMAIN_TRAIN_CSV),
        "--val-csv", str(DOMAIN_VAL_CSV),
        "--output", str(OUTPUT_DIR),
    ]

    print("실행 명령어:")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=str(STT_DIR))

    if result.returncode == 0:
        print()
        print("=" * 60)
        print("파인튜닝 완료!")
        print(f"모델 저장: {OUTPUT_DIR}")
        print("=" * 60)
    else:
        print()
        print(f"오류: 파인튜닝 실패 (종료 코드: {result.returncode})")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
