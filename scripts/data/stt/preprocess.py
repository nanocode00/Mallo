"""
오디오 전처리 파이프라인
=======================

경상도 방언 데이터(Training)의 오디오를 전처리하여
`stt_data/preprocessed/`에 저장한다.

전처리 순서:
    1. 고역통과 필터 (80Hz) — 저주파 노이즈 제거
    2. noisereduce 스펙트럼 게이팅 — 배경 노이즈 제거
    3. 피크 정규화 (0.95)

전처리 결과는 `stt_data/preprocessed/`에 저장되며,
이후 평가·분할·파인튜닝은 전처리된 오디오를 사용한다.

사용법:
    python preprocess.py                 # Training 전체 전처리
    python preprocess.py --samples 100   # 랜덤 100개만 전처리
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import noisereduce as nr
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

from adapters.stt.common import (
    DEFAULT_SEED,
    DATA_ROOT,
    PREPROCESSED_DIR,
)

HIGH_PASS_CUTOFF = 80.0
PEAK_NORM_LEVEL = 0.95


def high_pass_filter(audio: np.ndarray, sr: int, cutoff: float = HIGH_PASS_CUTOFF) -> np.ndarray:
    """고역통과 필터 (Butterworth 4차) — 저주파 노이즈 제거."""

    sos = butter(4, cutoff, btype="high", fs=sr, output="sos")
    return sosfilt(sos, audio)


def reduce_noise(audio: np.ndarray, sr: int) -> np.ndarray:
    """noisereduce 스펙트럼 게이팅 — 배경 노이즈 제거."""

    return nr.reduce_noise(y=audio, sr=sr)


def peak_normalize(audio: np.ndarray, level: float = PEAK_NORM_LEVEL) -> np.ndarray:
    """피크 정규화 — 최대 진폭을 level(0.95)로 맞춤."""

    peak = np.max(np.abs(audio))
    if peak == 0:
        return audio
    return audio / peak * level


def preprocess_audio(
    audio: np.ndarray,
    sr: int,
) -> np.ndarray:
    """전처리 파이프라인 (HPF → 노이즈 제거 → 피크 정규화)."""

    audio = high_pass_filter(audio, sr)
    audio = reduce_noise(audio, sr)
    audio = peak_normalize(audio)
    return audio


def find_wav_for_json(json_path: Path) -> Path | None:
    """JSON과 같은 stem을 가진 WAV 파일을 찾는다."""

    candidate = json_path.with_suffix(".wav")
    if candidate.exists():
        return candidate

    # 같은 폴더에서 확장자만 다른 경우 검색
    same_stem = [
        f for f in json_path.parent.glob("*.wav")
        if f.stem == json_path.stem
    ]
    return same_stem[0] if same_stem else None


def main() -> None:
    parser = argparse.ArgumentParser(description="경상도 방언 데이터 전처리")
    parser.add_argument("--samples", type=int, default=None, help="전처리할 샘플 수 (기본: 전체)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="랜덤 시드")
    args = parser.parse_args()

    random.seed(args.seed)

    training_jsons = sorted(
        DATA_ROOT.rglob("*.json")
    )
    print(f"Training JSON: {len(training_jsons):,}개")

    if args.samples is not None:
        if len(training_jsons) > args.samples:
            training_jsons = random.sample(training_jsons, args.samples)
        print(f"샘플링: {len(training_jsons)}개")

    PREPROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    success = 0
    failed = 0
    skipped = 0

    for i, json_path in enumerate(training_jsons, start=1):
        wav_path = find_wav_for_json(json_path)
        if wav_path is None:
            print(f"[{i}/{len(training_jsons)}] ⚠️ WAV 없음: {json_path.stem}")
            skipped += 1
            continue

        out_path = PREPROCESSED_DIR / f"{json_path.stem}.wav"
        if out_path.exists():
            skipped += 1
            continue

        try:
            audio, sr = sf.read(str(wav_path), dtype="float32")

            # Stereo → Mono
            if audio.ndim > 1:
                audio = audio.mean(axis=1)

            processed = preprocess_audio(audio, sr)

            sf.write(str(out_path), processed, sr)
            success += 1
        except Exception as exc:
            print(f"[{i}/{len(training_jsons)}] ❌ 실패: {json_path.stem} - {exc}")
            failed += 1

        if i % 100 == 0 or i == len(training_jsons):
            print(f"[{i}/{len(training_jsons)}] 진행 중... 성공: {success} 실패: {failed} 건너뜀: {skipped}")

    print("\n=== 전처리 완료 ===")
    print(f"전체     : {len(training_jsons)}개")
    print(f"성공     : {success}개")
    print(f"실패     : {failed}개")
    print(f"건너뜀   : {skipped}개")
    print(f"저장 위치: {PREPROCESSED_DIR}")


if __name__ == "__main__":
    main()
