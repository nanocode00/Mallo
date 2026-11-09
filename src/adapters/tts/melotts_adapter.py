from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from domain.korean_normalizer import normalize_korean_text_for_tts
from domain.tts_result import TTSResult
from interfaces.tts import TTSFailure


class MeloTTSAdapter:
    """MeloTTS 한국어 (사전학습 / 파인튜닝) 어댑터."""

    def __init__(
        self,
        device: str = "auto",
        config_path: Path | str | None = None,
        ckpt_path: Path | str | None = None,
        speaker: str = "KR",
    ) -> None:
        self.device = device
        self.config_path = str(config_path) if config_path else None
        self.ckpt_path = str(ckpt_path) if ckpt_path else None
        self.speaker = speaker
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from melo.api import TTS

                use_hf = self.config_path is None and self.ckpt_path is None
                self._model = TTS(
                    language="KR",
                    device=self.device,
                    use_hf=use_hf,
                    config_path=self.config_path,
                    ckpt_path=self.ckpt_path,
                )
            except Exception as e:
                raise TTSFailure(f"MeloTTS 모델 로드 실패: {e}") from e
        return self._model

    def synthesize(self, text: str, level: int = 0) -> TTSResult:
        if not text or not text.strip():
            return TTSResult(
                text="",
                level=level,
                sample_rate=44100,
                duration_ms=0.0,
                latency_ms=0.0,
                audio=b"",
            )

        # 텍스트 내 수사 및 분절기호 사전 정규화
        normalized_text = normalize_korean_text_for_tts(text)

        # Level별 발화 속도 정책: Level 0 -> 1.0x, Level 1 -> 0.85x, Level 2 -> 0.75x
        if level == 0:
            speed = 1.0
        elif level == 1:
            speed = 0.85
        elif level == 2:
            speed = 0.75
        else:
            speed = 1.0

        try:
            import soundfile as sf

            model = self._get_model()
            spk2id = getattr(model.hps.data, "spk2id", None)
            if spk2id is None:
                speaker_id = 0
            elif isinstance(spk2id, dict):
                speaker_id = spk2id.get(self.speaker, 0)
            else:
                speaker_id = getattr(spk2id, self.speaker, 0)

            t0 = time.perf_counter()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_path = tmp_file.name

            try:
                model.tts_to_file(normalized_text, speaker_id, tmp_path, speed=speed)
                latency_ms = (time.perf_counter() - t0) * 1000.0

                data, sr = sf.read(tmp_path)
                with open(tmp_path, "rb") as f:
                    audio_bytes = f.read()

                duration_ms = (len(data) / sr) * 1000.0 if sr > 0 else 0.0

                return TTSResult(
                    text=normalized_text,
                    level=level,
                    sample_rate=sr,
                    duration_ms=duration_ms,
                    latency_ms=latency_ms,
                    audio=audio_bytes,
                )
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        except Exception as e:
            if isinstance(e, TTSFailure):
                raise
            raise TTSFailure(f"MeloTTS 음성 합성 실패: {e}") from e
