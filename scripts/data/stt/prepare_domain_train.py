"""
도메인 학습 데이터를 Whisper 파인튜닝 형식으로 변환
===================================================

도메인 학습 CSV를 기존 파인튜닝 스크립트가 기대하는 형식으로 변환하고,
train/validation 분할을 수행한다.

출력:
    - stt_data/domain_train_finetune/train.csv
    - stt_data/domain_train_finetune/validation.csv

사용법:
    python prepare_domain_train.py
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

STT_DIR = Path(__file__).resolve().parent
INPUT_CSV = STT_DIR / "stt_data" / "domain_train_v2" / "domain_train.csv"
OUTPUT_DIR = STT_DIR / "stt_data" / "domain_train_finetune"

SEED = 42
VAL_RATIO = 0.15


def main() -> None:
    random.seed(SEED)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # CSV 로드
    rows = []
    with open(INPUT_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["status"] != "success":
                continue
            rows.append(row)

    print(f"로드된 학습 데이터: {len(rows)}개")

    # 경로 절대 경로로 변환
    for row in rows:
        audio_path = Path(row["audio_path"])
        if not audio_path.is_absolute():
            audio_path = STT_DIR / audio_path
        row["audio_path"] = str(audio_path.resolve())

    # 셔플 후 분할
    random.shuffle(rows)
    val_count = int(len(rows) * VAL_RATIO)
    val_rows = rows[:val_count]
    train_rows = rows[val_count:]

    print(f"Train: {len(train_rows)}개")
    print(f"Validation: {len(val_rows)}개")

    # CSV 저장
    for split_name, split_rows in [("train", train_rows), ("validation", val_rows)]:
        output_path = OUTPUT_DIR / f"{split_name}.csv"
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["file", "audio_path", "reference"])
            for row in split_rows:
                file_id = row["id"]
                audio_path = row["audio_path"]
                reference = row["text"]
                writer.writerow([file_id, audio_path, reference])
        print(f"저장: {output_path}")

    print("\n완료!")


if __name__ == "__main__":
    main()
