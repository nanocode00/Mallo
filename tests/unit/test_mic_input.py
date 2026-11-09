import io
import sys
import types
import wave

import numpy as np
import pytest

from adapters.audio import (
    AudioInputError,
    EnergyVAD,
    MicrophoneRecorder,
    NoSpeechError,
    TapToTalk,
)

SAMPLE_RATE = 16000
FRAME_SIZE = 480


def _install_fake_sounddevice(monkeypatch) -> types.ModuleType:
    """sounddevice가 없는 환경에서도 동작하도록 sys.modules에 가짜 모듈을 주입한다.

    recorder.py는 사용 시점에 `import sounddevice`를 수행하므로,
    sys.modules에 미리 넣어두면 실제 설치 유무와 무관하게 테스트할 수 있다.
    """
    module = types.ModuleType("sounddevice")

    class PortAudioError(RuntimeError):
        pass

    module.PortAudioError = PortAudioError

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        module,
    )
    return module


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
# AC-05 · AC-06 · AC-07 — TapToTalk
# ------------------------------------------------------------

def test_tap_to_talk_stops_after_silence() -> None:
    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
    )
    chunks = tone_frames(0.48) + silence_frames(1.5)

    result = tt.record(chunks)

    duration = result.size / SAMPLE_RATE
    assert 1.4 <= duration <= 1.6


def test_tap_to_talk_raises_without_speech() -> None:
    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
    )
    with pytest.raises(NoSpeechError):
        tt.record(silence_frames(11.0))


def test_tap_to_talk_returns_at_max_duration() -> None:
    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
    )
    result = tt.record(tone_frames(11.0))

    duration = result.size / SAMPLE_RATE
    assert 9.9 <= duration <= 10.0


def test_tap_to_talk_discards_pre_speech_silence() -> None:
    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
    )
    chunks = silence_frames(2.0) + tone_frames(0.48) + silence_frames(1.5)

    result = tt.record(chunks)

    duration = result.size / SAMPLE_RATE
    assert 1.4 <= duration <= 1.6


def test_tap_to_talk_rejects_too_short_utterance() -> None:
    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
        min_speech_duration=0.3,
    )
    with pytest.raises(NoSpeechError):
        tt.record(tone_frames(0.06) + silence_frames(1.5))


# ------------------------------------------------------------
# AC-09 · AC-10 — MicrophoneRecorder + 마이크 연결 API
# ------------------------------------------------------------

def test_recorder_raises_when_sounddevice_missing(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sounddevice":
            raise ImportError("sounddevice 미설치 시뮬레이션")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)

    recorder = MicrophoneRecorder(sample_rate=SAMPLE_RATE)
    with pytest.raises(AudioInputError):
        next(recorder.stream_chunks())


def test_recorder_raises_when_device_unsupported(monkeypatch) -> None:
    fake_sd = _install_fake_sounddevice(monkeypatch)

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, blocksize):
            raise fake_sd.PortAudioError("장치 초기화 실패")

    fake_sd.InputStream = FakeStream

    recorder = MicrophoneRecorder(sample_rate=SAMPLE_RATE)
    with pytest.raises(AudioInputError):
        next(recorder.stream_chunks())


def test_recorder_raises_when_device_missing(monkeypatch) -> None:
    fake_sd = _install_fake_sounddevice(monkeypatch)

    def raise_device_error(*args, **kwargs):
        raise fake_sd.PortAudioError("장치가 없습니다")

    fake_sd.InputStream = raise_device_error

    recorder = MicrophoneRecorder(sample_rate=SAMPLE_RATE)
    with pytest.raises(AudioInputError):
        next(recorder.stream_chunks())


def test_recorder_yields_frames_from_stream(monkeypatch) -> None:
    import itertools

    fake_sd = _install_fake_sounddevice(monkeypatch)

    class FakeStream:
        def __init__(self, **kwargs):
            self._frames = [
                np.zeros((FRAME_SIZE, 1), dtype=np.float32),
                np.zeros((FRAME_SIZE, 1), dtype=np.float32),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, blocksize):
            if not self._frames:
                raise RuntimeError("no more frames")
            return self._frames.pop(0), True

    fake_sd.InputStream = FakeStream

    recorder = MicrophoneRecorder(sample_rate=SAMPLE_RATE)
    frames = list(itertools.islice(recorder.stream_chunks(), 2))
    assert len(frames) == 2
    assert all(frame.shape == (FRAME_SIZE,) for frame in frames)


def test_tap_to_talk_record_from_mic(monkeypatch) -> None:
    fake_sd = _install_fake_sounddevice(monkeypatch)

    frames = iter(tone_frames(0.48) + silence_frames(1.5))

    class FakeStream:
        def __init__(self, **kwargs):
            self._frames = frames

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, blocksize):
            try:
                return self._frames.__next__()[:, None], True
            except StopIteration:
                raise RuntimeError("no more frames")

    fake_sd.InputStream = FakeStream

    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
    )
    result = tt.record_from_mic(
        MicrophoneRecorder(sample_rate=SAMPLE_RATE)
    )
    duration = result.size / SAMPLE_RATE
    assert 1.4 <= duration <= 1.6


def test_tap_to_talk_record_wav_from_mic(monkeypatch) -> None:
    fake_sd = _install_fake_sounddevice(monkeypatch)

    frames = iter(tone_frames(0.48) + silence_frames(1.5))

    class FakeStream:
        def __init__(self, **kwargs):
            self._frames = frames

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, blocksize):
            try:
                return self._frames.__next__()[:, None], True
            except StopIteration:
                raise RuntimeError("no more frames")

    fake_sd.InputStream = FakeStream

    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
    )
    wav_bytes = tt.record_wav_from_mic(
        MicrophoneRecorder(sample_rate=SAMPLE_RATE)
    )
    assert isinstance(wav_bytes, bytes)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == SAMPLE_RATE


def test_recorder_frame_size() -> None:
    recorder = MicrophoneRecorder(sample_rate=SAMPLE_RATE, frame_ms=30)
    assert recorder.frame_size == FRAME_SIZE
    assert recorder.sample_rate == SAMPLE_RATE


# ------------------------------------------------------------
# sample rate 계약 — record_from_mic()에서 recorder와 TapToTalk 일치 검증
# ------------------------------------------------------------

def test_record_from_mic_raises_on_sample_rate_mismatch() -> None:
    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
    )
    recorder = MicrophoneRecorder(sample_rate=48000)

    with pytest.raises(AudioInputError):
        tt.record_from_mic(recorder)


def test_record_wav_from_mic_raises_on_sample_rate_mismatch() -> None:
    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
    )
    recorder = MicrophoneRecorder(sample_rate=48000)

    with pytest.raises(AudioInputError):
        tt.record_wav_from_mic(recorder)


def test_record_from_mic_succeeds_with_matching_sample_rate(monkeypatch) -> None:
    fake_sd = _install_fake_sounddevice(monkeypatch)

    frames = iter(tone_frames(0.48) + silence_frames(1.5))

    class FakeStream:
        def __init__(self, **kwargs):
            self._frames = frames

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, blocksize):
            try:
                return self._frames.__next__()[:, None], True
            except StopIteration:
                raise RuntimeError("no more frames")

    fake_sd.InputStream = FakeStream

    tt = TapToTalk(
        EnergyVAD(sample_rate=SAMPLE_RATE),
        sample_rate=SAMPLE_RATE,
        max_duration=10.0,
        silence_timeout=1.0,
    )
    result = tt.record_from_mic(
        MicrophoneRecorder(sample_rate=SAMPLE_RATE)
    )
    assert result.size > 0
