import io
import wave

import numpy as np
import pytest

from adapters.audio import (
    AudioBuffer,
    BufferLimitError,
    EnergyVAD,
    to_wav_bytes,
)

SAMPLE_RATE = 16000
FRAME_SIZE = 480


def silence_frames(duration_s: float) -> list[np.ndarray]:
    count = int(duration_s * SAMPLE_RATE / FRAME_SIZE)
    return [np.zeros(FRAME_SIZE, dtype=np.float32) for _ in range(count)]


def tone_frames(duration_s: float, amplitude: float = 0.3) -> list[np.ndarray]:
    count = int(duration_s * SAMPLE_RATE / FRAME_SIZE)
    frames = []
    for index in range(count):
        start = index * FRAME_SIZE
        phase = 2 * np.pi * 1000 * np.arange(start, start + FRAME_SIZE) / SAMPLE_RATE
        frames.append((amplitude * np.sin(phase)).astype(np.float32))
    return frames


# ------------------------------------------------------------
# AC-01 · AC-02 — AudioBuffer
# ------------------------------------------------------------

def test_buffer_appends_and_resets() -> None:
    buffer = AudioBuffer(sample_rate=SAMPLE_RATE, max_duration=10.0)
    buffer.append(np.zeros(FRAME_SIZE, dtype=np.float32))
    buffer.append(np.zeros(FRAME_SIZE, dtype=np.float32))

    assert buffer.sample_count == 960
    assert buffer.as_array().shape == (960,)
    assert buffer.duration_seconds == pytest.approx(0.06)

    buffer.reset()
    assert buffer.sample_count == 0
    assert buffer.as_array().shape == (0,)


def test_buffer_raises_over_max_duration() -> None:
    buffer = AudioBuffer(sample_rate=SAMPLE_RATE, max_duration=0.05)
    buffer.append(np.zeros(FRAME_SIZE, dtype=np.float32))

    with pytest.raises(BufferLimitError):
        buffer.append(np.zeros(FRAME_SIZE, dtype=np.float32))


def test_buffer_rejects_non_mono() -> None:
    buffer = AudioBuffer(sample_rate=SAMPLE_RATE)
    with pytest.raises(ValueError):
        buffer.append(np.zeros((2, FRAME_SIZE), dtype=np.float32))


# ------------------------------------------------------------
# AC-03 · AC-04 — EnergyVAD
# ------------------------------------------------------------

def test_vad_silence_is_not_speech() -> None:
    vad = EnergyVAD(sample_rate=SAMPLE_RATE)
    assert vad.is_speech(np.zeros(FRAME_SIZE, dtype=np.float32)) is False


def test_vad_tone_is_speech() -> None:
    vad = EnergyVAD(sample_rate=SAMPLE_RATE)
    frame = (0.3 * np.sin(2 * np.pi * 1000 * np.arange(FRAME_SIZE) / SAMPLE_RATE)).astype(np.float32)
    assert vad.is_speech(frame) is True


def test_vad_noisy_frame_requires_min_speech_ratio() -> None:
    vad = EnergyVAD(sample_rate=SAMPLE_RATE, min_speech_ratio=0.5)
    frame = np.zeros(FRAME_SIZE, dtype=np.float32)
    frame[: FRAME_SIZE // 5] = 0.9
    assert vad.is_speech(frame) is False


# ------------------------------------------------------------
# AC-08 — WAV 인코딩
# ------------------------------------------------------------

def test_to_wav_bytes_encodes_valid_wav() -> None:
    samples = (0.5 * np.sin(2 * np.pi * 440 * np.arange(SAMPLE_RATE) / SAMPLE_RATE)).astype(np.float32)

    wav_bytes = to_wav_bytes(samples, sample_rate=SAMPLE_RATE)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == SAMPLE_RATE
        assert wav_file.getnframes() == SAMPLE_RATE
        assert wav_file.readframes(0) == b""
