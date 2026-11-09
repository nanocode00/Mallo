"""
STT 실험 공용 유틸리티
======================

STT 실험 스크립트들이 공유하는 설정을 모아둔 모듈입니다.

- CUDA DLL 경로 설정 (cuBLAS / cuDNN)
- 데이터 · 모델 경로 상수 (cwd 무관, 이 파일 위치 기준)
- 시드 고정
- CUDA 사용 가능 여부 확인
- 오디오 유틸리티 (리샘플링, 모노 변환, 경로 해석)

사용 예:
    from common import (
        setup_cuda_dll_paths,
        set_seed,
        require_cuda,
        resample_to_16k_mono,
        resolve_audio_path,
        DEFAULT_SEED,
        DATA_ROOT,
        PREPROCESSED_DIR,
        SPLITS_DIR,
        TRAIN_CSV,
        VALIDATION_CSV,
        TEST_CSV,
        MODELS_DIR,
        MODEL_ID,
    )

    setup_cuda_dll_paths()
"""

from __future__ import annotations

import math
import os
import random
import re
import sys
from pathlib import Path


# ============================================================
# 경로 상수 (이 파일 위치 기준 → 실행 디렉토리와 무관)
# ============================================================

DEFAULT_SEED = 42

STT_DIR = Path(__file__).resolve().parent

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data" / "stt"
MODELS_DIR = PROJECT_ROOT / "models" / "stt"

DATA_ROOT = DATA_DIR / "raw"
PREPROCESSED_DIR = DATA_DIR / "processed"
SPLITS_DIR = DATA_DIR / "splits"

TRAIN_CSV = SPLITS_DIR / "train.csv"
VALIDATION_CSV = SPLITS_DIR / "validation.csv"
TEST_CSV = SPLITS_DIR / "test.csv"

BASELINE_RESULTS_CSV = DATA_DIR / "baseline_results.csv"
PREPROCESSED_RESULTS_CSV = DATA_DIR / "preprocessed_results.csv"


MODEL_ID = "openai/whisper-medium"


# ============================================================
# CUDA DLL PATH
# ============================================================

def setup_cuda_dll_paths() -> None:
    """
    PyTorch 배포판에 포함된 cuBLAS / cuDNN DLL 경로를 PATH에 등록한다.

    PyTorch wheel에는 nvidia/cublas, nvidia/cudnn 패키지가 함께 설치되지만
    DLL 경로가 자동 등록되지 않는 환경이 있어, 실행 전에 PATH를 보정해야 한다.
    """

    python_dir = Path(sys.executable).parent
    venv_dir = python_dir.parent

    cuda_dll_dirs = [
        venv_dir
        / "Lib"
        / "site-packages"
        / "nvidia"
        / "cublas"
        / "bin",

        venv_dir
        / "Lib"
        / "site-packages"
        / "nvidia"
        / "cudnn"
        / "bin",
    ]

    for dll_dir in cuda_dll_dirs:

        if not dll_dir.exists():
            continue

        os.environ["PATH"] = (
            f"{dll_dir};"
            f"{os.environ['PATH']}"
        )

        if hasattr(os, "add_dll_directory"):

            try:
                os.add_dll_directory(
                    str(dll_dir)
                )
            except Exception:
                pass


def require_cuda() -> str:
    """
    CUDA 사용 가능 여부를 확인하고 device 문자열("cuda")을 반환한다.
    """

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA GPU를 사용할 수 없습니다."
        )

    return "cuda"


# ============================================================
# 시드 고정
# ============================================================

def set_seed(seed: int) -> None:
    """
    Python / NumPy / PyTorch 시드를 고정한다.
    """

    random.seed(seed)

    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass

    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
    except ImportError:
        pass


# ============================================================
# 오디오 유틸리티
# ============================================================

def resample_to_16k_mono(
    audio: "np.ndarray",
    sample_rate: int,
) -> tuple["np.ndarray", int]:
    """
    오디오를 16kHz 모노(float32)로 변환한다.

    - Stereo → Mono (채널 평균)
    - 16kHz가 아닌 경우 polyphase 리샘플링(scipy.signal.resample_poly)으로
      선형 보간(np.interp) 대비 앨리어싱·왜곡을 줄인다.

    Returns:
        (audio_16k_mono, 16000)
    """
    import numpy as np

    # Stereo → Mono
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # 16kHz 리샘플링 (Whisper 요구사항)
    if sample_rate != 16000:
        from scipy import signal
        # up/down 비율을 최대공약수로 약분해 resample_poly에 전달
        gcd = math.gcd(sample_rate, 16000)
        up = 16000 // gcd
        down = sample_rate // gcd
        target_len = int(round(len(audio) * 16000 / sample_rate))
        audio = signal.resample_poly(audio, up, down).astype(audio.dtype)
        # resample_poly는 FIR 윈도우로 인해 길이가 근사치로 나오므로 정확히 맞춤
        if len(audio) > target_len:
            audio = audio[:target_len]
        elif len(audio) < target_len:
            audio = np.pad(audio, (0, target_len - len(audio)))
        sample_rate = 16000

    return audio, sample_rate


def resolve_audio_path(
    audio_path: str | Path,
    base_dir: Path | None = None,
) -> Path:
    """
    STT 오디오 파일 경로를 현재 실행 환경(Linux/WSL/Windows)에 맞게 해석한다.

    - 절대경로로 이미 존재하는 경우 그대로 resolve하여 반환
    - 상대경로인 경우 base_dir, PROJECT_ROOT, DATA_DIR 순으로 검색
    - 다른 환경(Windows 절대경로, 레거시 디렉토리 구조 등)이 포함된 경우:
      * 백슬래시(\) 정규화 및 Windows 드라이브 문자(예: C:) 제거
      * 레거시 500 preprocessed 경로:
        'src/adapters/stt/stt_data/preprocessed' -> 'data/stt/reproduction/legacy500/preprocessed'
      * 레거시 train65_v1 경로:
        'src/adapters/stt/stt_data/train65_v1' -> 'data/stt/processed/train65_v1'
      * 일반적인 'stt_data/' -> 'data/stt/'
      * 파일명이 'data/stt/reproduction/legacy500/preprocessed/'에 존재하면 반환
    - 파일을 찾지 못하더라도 예외를 발생시키지 않고 가장 합리적인 후보 Path 반환
    """
    if not audio_path:
        return Path(audio_path)

    raw_path_str = str(audio_path).strip()

    # 1. 이미 존재하는 경로인지 검사 (직접 일치)
    direct_path = Path(raw_path_str)
    try:
        if direct_path.is_file():
            return direct_path.resolve()
    except (OSError, ValueError):
        pass

    # 2. 상대 경로인 경우 기본 위치들과 결합
    candidates = []
    if base_dir:
        candidates.append(base_dir / direct_path)
    candidates.extend([
        PROJECT_ROOT / direct_path,
        DATA_DIR / direct_path,
    ])
    for cand in candidates:
        try:
            if cand.is_file():
                return cand.resolve()
        except (OSError, ValueError):
            pass

    # 3. 경로 문자열 정규화 (Windows 백슬래시 및 드라이브 문자 처리)
    normalized = raw_path_str.replace("\\", "/")
    if re.match(r"^[a-zA-Z]:", normalized):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")

    # repo root 식별자(proj1-d) 이후 상대경로 추출
    rel_part = normalized
    if "proj1-d/" in normalized:
        rel_part = normalized.split("proj1-d/", 1)[1]

    filename = Path(normalized).name
    mapped_candidates = []

    # 레거시 preprocessed 경로 (Legacy 500)
    if "stt_data/preprocessed" in normalized or "reproduction/legacy500" in normalized:
        mapped_candidates.append(DATA_DIR / "reproduction" / "legacy500" / "preprocessed" / filename)
        mapped_candidates.append(DATA_DIR / "reproduction" / "legacy500" / "original" / filename)
        mapped_candidates.append(DATA_DIR / "processed" / filename)

    # 레거시 train65_v1 경로
    if "train65_v1" in normalized:
        sub = normalized.split("train65_v1/", 1)[1]
        mapped_candidates.append(DATA_DIR / "processed" / "train65_v1" / sub)

    # 일반적인 stt_data -> data/stt 매핑
    if "stt_data/" in normalized:
        sub = normalized.split("stt_data/", 1)[1]
        mapped_candidates.append(DATA_DIR / sub)

    # PROJECT_ROOT 기준 rel_part
    mapped_candidates.append(PROJECT_ROOT / rel_part)

    # 레거시 500 디렉토리 확인 (filename 기반)
    mapped_candidates.append(DATA_DIR / "reproduction" / "legacy500" / "preprocessed" / filename)

    for cand in mapped_candidates:
        try:
            if cand.is_file():
                return cand.resolve()
        except (OSError, ValueError):
            pass

    # 찾지 못한 경우 mapped_candidates의 첫 번째 또는 direct_path 반환
    return mapped_candidates[0] if mapped_candidates else direct_path
