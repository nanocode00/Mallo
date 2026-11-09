from __future__ import annotations

import io
from typing import Literal

import soundfile as sf

from adapters.stt.common import resample_to_16k_mono
from domain.stt_result import STTResult
from interfaces.stt import STTFailure


class FasterWhisperSTT:
    """Faster-Whisper(CTranslate2) 기반 STT 어댑터.

    transformers 버전과 무관하게 동작하므로 MeloTTS(transformers 4.27)와
    단일 프로세스에서 공존할 수 있다. ``model_size_or_path`` 에는 HF 모델명 또는
    ``ct2-transformers-converter`` 로 변환한 디렉터를 지정한다.
    """

    def __init__(
        self,
        model_size_or_path: str,
        device: Literal["auto", "cuda", "cpu"] = "auto",
        compute_type: Literal["auto", "float16", "int8"] = "auto",
    ) -> None:
        from faster_whisper import WhisperModel

        resolved_device = device if device != "auto" else "auto"
        resolved_compute = compute_type if compute_type != "auto" else (
            "int8" if resolved_device == "cpu" else "float16"
        )
        self.model = WhisperModel(
            model_size_or_path, device=resolved_device, compute_type=resolved_compute
        )

    def transcribe(self, audio: bytes, language: str = "ko") -> STTResult:
        try:
            data, sr = sf.read(io.BytesIO(audio))
            resampled, target_sr = resample_to_16k_mono(data, sr)
            duration_ms = (len(resampled) / target_sr) * 1000.0 if target_sr else 0.0

            segments, _info = self.model.transcribe(
                resampled, language=language, beam_size=1
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return STTResult(text=text, duration_ms=duration_ms)
        except Exception as exc:  # noqa: BLE001
            raise STTFailure(str(exc)) from exc
