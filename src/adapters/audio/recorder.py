from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from .errors import AudioInputError


class MicrophoneRecorder:
    """sounddevice 기반 마이크 캡처.

    sounddevice는 사용 시점에 lazy import한다 — 마이크가 없는
    환경에서도 모듈 import는 성공해야 한다.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        device: int | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._device = device

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def frame_size(self) -> int:
        return int(self._sample_rate * self._frame_ms / 1000)

    def stream_chunks(self) -> Iterator[np.ndarray]:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioInputError("sounddevice가 설치되지 않았습니다") from exc

        try:
            with sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.frame_size,
                device=self._device,
            ) as stream:
                while True:
                    frame, _ = stream.read(self.frame_size)
                    yield frame[:, 0]
        except Exception as exc:
            raise AudioInputError("마이크 장치를 사용할 수 없습니다") from exc
