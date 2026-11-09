from __future__ import annotations

from collections.abc import Iterable, Iterator

import numpy as np

from .buffer import AudioBuffer
from .errors import AudioInputError, BufferLimitError, NoSpeechError
from .recorder import MicrophoneRecorder
from .vad import VAD


class TapToTalk:
    """버튼 입력 기반 음성 녹음.

    첫 발화 프레임부터 녹음을 시작하고, silence_timeout(초) 동안
    연속 무음이면 종료한다. max_duration(초)에 도달하면 즉시 반환한다.
    """

    def __init__(
        self,
        vad: VAD,
        sample_rate: int = 16000,
        max_duration: float = 10.0,
        silence_timeout: float = 1.0,
        min_speech_duration: float = 0.3,
    ) -> None:
        self._vad = vad
        self._sample_rate = sample_rate
        self._max_duration = max_duration
        self._silence_timeout = silence_timeout
        self._min_speech_duration = min_speech_duration

    def record(self, chunks: Iterable[np.ndarray]) -> np.ndarray:
        iterator = iter(chunks)
        start_frame = self._wait_for_speech(iterator)
        buffer, speech_seconds = self._collect_until_stop(iterator, start_frame)

        if speech_seconds < self._min_speech_duration:
            raise NoSpeechError(
                f"발화가 너무 짧습니다 ({speech_seconds:.2f}초)"
            )

        return buffer.as_array()

    def record_from_mic(
        self,
        recorder: MicrophoneRecorder,
    ) -> np.ndarray:
        """마이크 스트림에서 발화를 녹음해 float32 ndarray로 반환한다.

        recorder와 TapToTalk의 sample rate가 다르면 무음 시간·최대 녹음
        시간은 TapToTalk 기준, WAV 헤더는 recorder 기준으로 계산되어
        실제 종료 시간이 설정값과 달라질 수 있으므로, 시작 전에
        일치 여부를 검증한다.
        """
        self._validate_sample_rate(recorder)
        return self.record(
            self._mic_chunks(recorder)
        )

    def record_wav_from_mic(
        self,
        recorder: MicrophoneRecorder,
    ) -> bytes:
        """마이크 스트림에서 발화를 녹음해 STT 계약 호환 WAV bytes로 반환한다."""
        from .wav import to_wav_bytes

        samples = self.record_from_mic(recorder)
        return to_wav_bytes(
            samples,
            sample_rate=recorder.sample_rate,
        )

    def _validate_sample_rate(
        self,
        recorder: MicrophoneRecorder,
    ) -> None:
        if recorder.sample_rate != self._sample_rate:
            raise AudioInputError(
                "TapToTalk과 recorder의 sample rate가 다릅니다: "
                f"TapToTalk {self._sample_rate}Hz vs "
                f"recorder {recorder.sample_rate}Hz"
            )

    def _mic_chunks(
        self,
        recorder: MicrophoneRecorder,
    ) -> Iterator[np.ndarray]:
        return iter(
            recorder.stream_chunks()
        )

    def _wait_for_speech(self, iterator: Iterable[np.ndarray]) -> np.ndarray:
        elapsed_seconds = 0.0

        for frame in iterator:
            frame = np.asarray(frame, dtype=np.float32)
            if frame.size == 0:
                continue
            elapsed_seconds += frame.size / self._sample_rate
            if elapsed_seconds > self._max_duration:
                break
            if self._vad.is_speech(frame):
                return frame

        raise NoSpeechError("발화가 감지되지 않았습니다")

    def _collect_until_stop(
        self,
        iterator: Iterable[np.ndarray],
        start_frame: np.ndarray,
    ) -> tuple[AudioBuffer, float]:
        buffer = AudioBuffer(
            sample_rate=self._sample_rate,
            max_duration=self._max_duration,
        )
        buffer.append(start_frame)
        speech_seconds = start_frame.size / self._sample_rate
        silence_seconds = 0.0

        for frame in iterator:
            frame = np.asarray(frame, dtype=np.float32)
            if frame.size == 0:
                continue
            try:
                buffer.append(frame)
            except BufferLimitError:
                break

            if self._vad.is_speech(frame):
                speech_seconds += frame.size / self._sample_rate
                silence_seconds = 0.0
            else:
                silence_seconds += frame.size / self._sample_rate
                if silence_seconds >= self._silence_timeout:
                    break

        return buffer, speech_seconds
