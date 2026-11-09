"""
분할 데이터셋 화자 누출(leakage) 검사
=====================================

train / validation / test CSV에 같은 화자(speakergs*)가
여러 분할에 섞여 있는지 확인한다.

화자 ID는 파일명의 `speakergs<번호>` 패턴에서 추출한다.

사용법:
    python check_split_leakage.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from adapters.stt.common import (
    TRAIN_CSV,
    VALIDATION_CSV,
    TEST_CSV,
)

SPEAKER_RE = re.compile(r"(speakergs\d+)")


def extract_speaker(file_name: str) -> str | None:
    """파일명에서 화자 ID를 추출한다."""

    match = SPEAKER_RE.search(file_name)
    return match.group(1) if match else None


def load_speakers(csv_path: Path) -> tuple[pd.DataFrame, set[str]]:
    """CSV를 읽고 화자 ID 집합을 반환한다."""

    df = pd.read_csv(csv_path)
    speakers = set()
    missing = 0

    for file_name in df["file"]:
        speaker = extract_speaker(str(file_name))
        if speaker is None:
            missing += 1
        else:
            speakers.add(speaker)

    return df, speakers


def main() -> None:
    splits = [
        ("train", TRAIN_CSV),
        ("validation", VALIDATION_CSV),
        ("test", TEST_CSV),
    ]

    loaded = {}
    for name, path in splits:
        if not path.exists():
            print(f"[SKIP] 파일 없음: {path}")
            sys.exit(1)

        df, speakers = load_speakers(path)
        loaded[name] = (df, speakers)
        print(f"{name:12s}: {len(df)}개 파일 / {len(speakers)}명 화자")

    print("\n=== 화자 누출 검사 ===")

    leaked = False
    pairs = [
        ("train", "validation"),
        ("train", "test"),
        ("validation", "test"),
    ]

    for name_a, name_b in pairs:
        _, speakers_a = loaded[name_a]
        _, speakers_b = loaded[name_b]
        overlap = speakers_a & speakers_b

        if overlap:
            leaked = True
            print(f"[FAIL] {name_a} ∩ {name_b}: {len(overlap)}명 화자 중복")
            print(f"       예: {sorted(overlap)[:5]}")
        else:
            print(f"[OK] {name_a} ∩ {name_b}: 중복 없음")

    if leaked:
        print("\n결과: 화자 누출 발생 → split_dataset.py를 화자 단위로 재실행하세요.")
        sys.exit(1)

    print("\n결과: 화자 누출 없음")


if __name__ == "__main__":
    main()
