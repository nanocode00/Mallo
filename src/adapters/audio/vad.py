from __future__ import annotations

from typing import Protocol

import numpy as np


class VAD(Protocol):
    """오디오 프레임 단위 발화/무음 판정 인터페이스."""

    def is_speech(self, frame: np.ndarray) -> bool: ...


class EnergyVAD:
    """RMS 임계값 기반 에너지 VAD (순수 numpy, 외부 의존성 없음)."""

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        threshold_db: float = -35.0,
        min_speech_ratio: float = 0.5,
    ) -> None:
        self._frame_size = int(sample_rate * frame_ms / 1000)
        self._threshold = 10 ** (threshold_db / 20)
        self._min_speech_ratio = min_speech_ratio

    @property
    def frame_size(self) -> int:
        return self._frame_size

    def is_speech(self, frame: np.ndarray) -> bool:
        if frame.size == 0:
            return False
        speech_ratio = float(
            np.count_nonzero(np.abs(frame) >= self._threshold)
        ) / frame.size
        return speech_ratio >= self._min_speech_ratio
