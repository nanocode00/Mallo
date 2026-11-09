"""
데이터셋 분할 스크립트 (Train / Validation / Test)

- 500개 전처리 데이터를 Train / Validation / Test로 분할
- Test 세트는 파인튜닝에 사용하지 않음 (사용자 요구사항)
- 분할 비율: Train 70% / Validation 15% / Test 15%
- 재현 가능한 랜덤 시드 사용
- **화자 단위 분할**: 같은 화자(speakergs*)가 여러 분할에 섞이지 않도록
  화자 그룹을 셔플한 뒤 파일 수 비율로 분배 (평가 공정성)
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import pandas as pd

from adapters.stt.common import (
    set_seed,
    DEFAULT_SEED,
    DATA_ROOT,
    PREPROCESSED_DIR,
    SPLITS_DIR,
)

TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
# TEST_RATIO = 0.15 (나머지)

SPEAKER_RE = re.compile(r"(speakergs\d+)")


def extract_speaker(file_name: str) -> str:
    """파일명에서 화자 ID를 추출한다."""

    match = SPEAKER_RE.search(file_name)
    if match is None:
        raise ValueError(f"화자 ID를 찾을 수 없습니다: {file_name}")
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STT 데이터셋 분할 스크립트 (Train / Validation / Test)")
    parser.add_argument("--raw-dir", type=Path, default=DATA_ROOT, help="AIHub 원본 JSON 디렉터리")
    parser.add_argument("--preprocessed-dir", type=Path, default=PREPROCESSED_DIR, help="전처리 WAV 디렉터리")
    parser.add_argument("--output-dir", type=Path, default=SPLITS_DIR, help="분할 CSV 저장 디렉터리")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="랜덤 시드")
    args = parser.parse_args(argv)

    set_seed(args.seed)

    # 전처리된 파일 목록
    preprocessed_files = sorted(args.preprocessed_dir.rglob("*.wav"))
    print(f"전처리된 파일: {len(preprocessed_files)}개")

    # JSON 파일명 → 경로 매핑 (파일명 기반, 빠른 조회)
    json_map = {
        jf.stem: jf
        for jf in args.raw_dir.rglob("*.json")
        if "Training" in jf.parts
    }
    print(f"JSON 매핑 완료: {len(json_map):,}개")

    # JSON에서 정답 텍스트 추출
    records = []
    for wav_path in preprocessed_files:
        stem = wav_path.stem

        json_path = json_map.get(stem)
        if json_path is None:
            print(f"[SKIP] JSON 없음: {stem}")
            continue

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        reference = data["transcription"]["dialect"]

        records.append(
            {
                "file": stem,
                "audio_path": str(wav_path),
                "reference": reference,
                "speaker": extract_speaker(stem),
            }
        )

    print(f"유효한 레코드: {len(records)}개")
    if not records:
        print("[안내] 분할 대상 레코드가 없습니다.")
        return 0

    # 화자 단위 그룹핑
    by_speaker: dict[str, list[dict]] = {}
    for record in records:
        by_speaker.setdefault(record["speaker"], []).append(record)

    print(f"화자 수: {len(by_speaker)}명")

    # 화자 그룹 셔플 후 파일 수 비율로 분배
    speakers = list(by_speaker.keys())
    random.shuffle(speakers)

    n_train = int(len(records) * TRAIN_RATIO)
    n_val = int(len(records) * VAL_RATIO)

    train_records: list[dict] = []
    val_records: list[dict] = []
    test_records: list[dict] = []

    for speaker in speakers:
        group = by_speaker[speaker]

        if len(train_records) < n_train:
            train_records.extend(group)
        elif len(val_records) < n_val:
            val_records.extend(group)
        else:
            test_records.extend(group)

    print(f"\n=== 분할 결과 ===")
    print(f"Train      : {len(train_records)}개 ({len(train_records) / len(records) * 100:.1f}%)")
    print(f"Validation : {len(val_records)}개 ({len(val_records) / len(records) * 100:.1f}%)")
    print(f"Test       : {len(test_records)}개 ({len(test_records) / len(records) * 100:.1f}%)")

    # 저장 (speaker 컬럼은 CSV에서 제외 — 학습/평가에 불필요)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for name, data in [
        ("train", train_records),
        ("validation", val_records),
        ("test", test_records),
    ]:
        df = pd.DataFrame(data)
        df = df.drop(columns=["speaker"])
        csv_path = args.output_dir / f"{name}.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"저장: {csv_path} ({len(df)}개)")

    # 분할 정보 저장
    info = {
        "seed": args.seed,
        "split_unit": "speaker",
        "total": len(records),
        "train": len(train_records),
        "validation": len(val_records),
        "test": len(test_records),
        "speakers": len(by_speaker),
        "train_speakers": len(set(r["speaker"] for r in train_records)),
        "validation_speakers": len(set(r["speaker"] for r in val_records)),
        "test_speakers": len(set(r["speaker"] for r in test_records)),
    }
    info_path = args.output_dir / "split_info.json"
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    print(f"분할 정보 저장: {info_path}")
    return 0


if __name__ == "__main__":
    main()
