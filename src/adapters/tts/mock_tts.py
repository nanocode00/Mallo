import io
import math
import struct
import wave

from domain.tts_result import TTSResult
from interfaces.tts import TTSFailure


def _generate_mock_wav(duration_s: float = 0.3, sample_rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        n_samples = max(1, int(duration_s * sample_rate))
        samples = [0] * n_samples
        wf.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return buf.getvalue()


class MockTTS:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[tuple[str, int]] = []
        self._cached_wav = _generate_mock_wav()

    def synthesize(self, text: str, level: int = 0) -> TTSResult:
        if self.should_fail:
            raise TTSFailure("Mock TTS failed")
        self.calls.append((text, level))
        return TTSResult(
            text=text,
            level=level,
            sample_rate=24000,
            duration_ms=len(text) * 100.0,
            latency_ms=10.0,
            audio=self._cached_wav,
        )


