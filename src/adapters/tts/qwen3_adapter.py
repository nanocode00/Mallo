from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

from domain.tts_result import TTSResult
from interfaces.tts import TTSFailure


class Qwen3TTSAdapter:
    """Qwen3-TTS 0.6B (사전학습 / 파인튜닝) 어댑터."""

    def __init__(
        self,
        model_id_or_path: Path | str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        device: str = "auto",
        speaker: str = "Ryan",
        max_new_tokens: int = 300,
    ) -> None:
        self.model_path = str(model_id_or_path)
        self.device = device
        self.speaker = speaker
        self.max_new_tokens = max_new_tokens
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                import torch
                from qwen_tts import Qwen3TTSModel

                dev = self.device
                if dev == "auto":
                    dev = "cuda:0" if torch.cuda.is_available() else "cpu"
                dtype = torch.bfloat16 if "cuda" in dev else torch.float32

                self._model = Qwen3TTSModel.from_pretrained(
                    self.model_path,
                    device_map=dev,
                    dtype=dtype,
                )
            except Exception as e:
                raise TTSFailure(f"Qwen3-TTS 모델 로드 실패: {e}") from e
        return self._model

    def synthesize(self, text: str, level: int = 0) -> TTSResult:
        if not text or not text.strip():
            return TTSResult(
                text="",
                level=level,
                sample_rate=24000,
                duration_ms=0.0,
                latency_ms=0.0,
                audio=b"",
            )

        try:
            import soundfile as sf

            model = self._get_model()
            t0 = time.perf_counter()
            wavs, sr = model.generate_custom_voice(
                text=text,
                speaker=self.speaker,
                max_new_tokens=self.max_new_tokens,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0

            audio_data = wavs[0]
            buffer = io.BytesIO()
            sf.write(buffer, audio_data, sr, format="WAV")
            audio_bytes = buffer.getvalue()

            duration_ms = (len(audio_data) / sr) * 1000.0 if sr > 0 else 0.0

            return TTSResult(
                text=text,
                level=level,
                sample_rate=sr,
                duration_ms=duration_ms,
                latency_ms=latency_ms,
                audio=audio_bytes,
            )
        except Exception as e:
            if isinstance(e, TTSFailure):
                raise
            raise TTSFailure(f"Qwen3-TTS 음성 합성 실패: {e}") from e
