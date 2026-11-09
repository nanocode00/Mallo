from __future__ import annotations

import io
import wave

import numpy as np


def to_wav_bytes(samples: np.ndarray, sample_rate: int = 16000) -> bytes:
    """float32 모노 샘플을 PCM16 WAV bytes로 인코딩한다."""
    samples = np.clip(
        np.asarray(samples, dtype=np.float32).reshape(-1),
        -1.0,
        1.0,
    )
    pcm16 = (samples * 32767).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16.tobytes())

    return buffer.getvalue()
