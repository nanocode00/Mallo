from __future__ import annotations

import numpy as np

from .errors import BufferLimitError


class AudioBuffer:
    """모노 float32 오디오 프레임을 누적하는 버퍼."""

    def __init__(
        self,
        sample_rate: int = 16000,
        max_duration: float = 10.0,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate는 양수여야 합니다")
        if max_duration <= 0:
            raise ValueError("max_duration은 양수여야 합니다")
        self._sample_rate = sample_rate
        self._max_duration = max_duration
        self._samples: list[np.ndarray] = []

    def append(self, samples: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("모노(1차원) 오디오만 지원합니다")
        if self.sample_count + samples.size > self._max_samples:
            raise BufferLimitError(
                f"최대 녹음 시간({self._max_duration}초)을 초과했습니다"
            )
        self._samples.append(samples)

    @property
    def sample_count(self) -> int:
        return sum(samples.size for samples in self._samples)

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self._sample_rate

    @property
    def _max_samples(self) -> int:
        return int(self._max_duration * self._sample_rate)

    def as_array(self) -> np.ndarray:
        if not self._samples:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._samples)

    def reset(self) -> None:
        self._samples = []
