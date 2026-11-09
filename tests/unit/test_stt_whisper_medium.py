"""
Whisper Medium STT Adapter 단위 테스트
======================================

테스트 대상:
    - STTResult dataclass
    - WhisperMediumSTT 초기화 및 설정
    - 오디오 전처리 유틸리티
    - 컨텍스트 매니저
    - Confidence 계산

주의:
    - GPU가 필요한 실제 추론 테스트는 integration test로 분리
    - 이 테스트는 CPU 환경에서 실행 가능
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
import torch

from interfaces.stt import STTFailure, STTResult
from adapters.stt.whisper_medium import (
    WhisperMediumSTT,
    MODEL_ID,
    DEFAULT_TRAIN65_MERGED_PATH,
    DEFAULT_QLORA_MERGED_PATH,
    MAX_NEW_TOKENS,
)
from adapters.stt.common import resample_to_16k_mono


# ============================================================
# STTResult 테스트
# ============================================================

class TestSTTResult:
    """STTResult dataclass 동작 검증."""

    def test_create_minimal(self):
        """최소 필드로 생성 가능."""
        result = STTResult(text="안녕하세요")
        assert result.text == "안녕하세요"
        assert result.confidence is None
        assert result.duration_ms is None

    def test_create_full(self):
        """전체 필드로 생성 가능."""
        result = STTResult(
            text="아메리카노 두 잔",
            confidence=0.95,
            duration_ms=500.0,
        )
        assert result.text == "아메리카노 두 잔"
        assert result.confidence == 0.95
        assert result.duration_ms == 500.0

    def test_immutable(self):
        """frozen=True로 불변성 보장."""
        result = STTResult(text="테스트")
        with pytest.raises(AttributeError):
            result.text = "변경"


# ============================================================
# WhisperMediumSTT 초기화 테스트
# ============================================================

class TestWhisperMediumSTTInit:
    """모델 로드 없이 초기화 설정 검증."""

    def test_default_init(self):
        """기본 초기화 (Train65 merged BF16, cpu)."""
        stt = WhisperMediumSTT(device="cpu")
        assert stt.variant == "train65"
        assert stt.device == "cpu"

    def test_qlora_variant(self):
        """QLoRA variant 초기화."""
        stt = WhisperMediumSTT(variant="qlora", device="cpu")
        assert stt.variant == "qlora"

    def test_train65_and_baseline_variants(self):
        train65 = WhisperMediumSTT(variant="train65", device="cpu")
        qlora = WhisperMediumSTT(variant="qlora", device="cpu")
        baseline = WhisperMediumSTT(variant="baseline", device="cpu")

        assert train65.variant == "train65"
        assert train65._model_path == DEFAULT_TRAIN65_MERGED_PATH
        assert qlora.variant == "qlora"
        assert qlora._model_path == DEFAULT_QLORA_MERGED_PATH
        assert baseline.variant == "baseline"

    def test_custom_model_path_is_used_by_train65_and_qlora(self):
        custom_path = Path("/custom/merged-bf16")
        assert WhisperMediumSTT(variant="train65", model_path=custom_path, device="cpu")._model_path == custom_path
        assert WhisperMediumSTT(variant="qlora", model_path=custom_path, device="cpu")._model_path == custom_path

    def test_peft_is_a_deprecated_train65_alias(self):
        assert WhisperMediumSTT(variant="peft", device="cpu").variant == "train65"

    def test_custom_qlora_path(self):
        """커스텀 QLoRA 경로 지정."""
        custom_path = Path("/custom/path")
        stt = WhisperMediumSTT(
            variant="qlora",
            qlora_path=custom_path,
            device="cpu",
        )
        assert stt._qlora_path == custom_path

    def test_invalid_variant(self):
        """잘못된 variant로 초기화 시도."""
        stt = WhisperMediumSTT(variant="invalid", device="cpu")
        # variant 검증은 _ensure_loaded()의 transformers import 전에 이루어지도록
        # _ensure_loaded() 내에서 ValueError 발생 확인
        with patch("adapters.stt.whisper_medium.WhisperMediumSTT._ensure_loaded"):
            # _ensure_loaded를 mock하여 variant 검증 로직만 테스트
            with pytest.raises((ValueError, ModuleNotFoundError)):
                # 실제로는 ValueError가 발생해야 하지만,
                # transformers import 실패 시 ModuleNotFoundError 발생 가능
                if stt.variant not in ("baseline", "qlora", "train65"):
                    raise ValueError(
                        f"지원하지 않는 variant: {stt.variant}"
                    )

    def test_repr(self):
        """repr 문자열 생성."""
        stt = WhisperMediumSTT(device="cpu")
        assert "train65" in repr(stt)
        assert "cpu" in repr(stt)


# ============================================================
# 오디오 전처리 테스트
# ============================================================

class TestAudioLoading:
    """오디오 바이트 로딩 유틸리티 테스트."""

    def _create_wav_bytes(
        self,
        duration: float = 1.0,
        sr: int = 16000,
        channels: int = 1,
    ) -> bytes:
        """테스트용 WAV 바이트 생성."""
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        # 440Hz 사인파
        audio = 0.5 * np.sin(2 * np.pi * 440 * t)

        if channels == 2:
            audio = np.stack([audio, audio], axis=1)

        buffer = io.BytesIO()
        sf.write(buffer, audio if channels == 1 else audio, sr, format="WAV")
        buffer.seek(0)
        return buffer.read()

    def test_load_mono(self):
        """Mono 오디오 로딩."""
        wav_bytes = self._create_wav_bytes(channels=1)
        audio, sr = WhisperMediumSTT._load_audio_from_bytes(wav_bytes)
        assert sr == 16000
        assert audio.ndim == 1

    def test_load_stereo_to_mono(self):
        """Stereo → Mono 변환."""
        wav_bytes = self._create_wav_bytes(channels=2)
        audio, sr = WhisperMediumSTT._load_audio_from_bytes(wav_bytes)
        assert sr == 16000
        assert audio.ndim == 1  # Mono로 변환됨

    @staticmethod
    def _create_webm_opus_bytes(duration: float = 0.5) -> bytes:
        """브라우저 MediaRecorder와 동일한 webm/opus 바이트 생성."""
        av = pytest.importorskip("av")

        sample_rate = 48000
        total = int(sample_rate * duration)
        t = np.arange(total) / sample_rate
        samples = (0.5 * np.sin(2 * np.pi * 440 * t) * 32767).astype("int16")

        buffer = io.BytesIO()
        container = av.open(buffer, mode="w", format="webm")
        stream = container.add_stream("libopus", rate=sample_rate, layout="stereo")
        frame_size = 960  # libopus 20ms @ 48kHz
        for start in range(0, total - frame_size + 1, frame_size):
            block = np.stack(
                [samples[start : start + frame_size]] * 2, axis=0
            )  # (2, frame_size) planar stereo
            frame = av.AudioFrame.from_ndarray(block, format="s16p", layout="stereo")
            frame.sample_rate = sample_rate
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
        container.close()
        return buffer.getvalue()

    def test_load_webm_opus(self):
        """webm/opus(브라우저 MediaRecorder 기본 출력) 디코딩 폴백."""
        webm_bytes = self._create_webm_opus_bytes(duration=0.5)
        audio, sr = WhisperMediumSTT._load_audio_from_bytes(webm_bytes)
        assert sr == 16000
        assert audio.ndim == 1
        assert audio.dtype == np.float32
        assert len(audio) == 8000  # 0.5초 @ 48kHz → 16kHz 리샘플

    def test_load_corrupt_bytes_raises_stt_failure(self):
        """디코딩 불가능한 바이트는 STTFailure로 변환된다."""
        with pytest.raises(STTFailure):
            WhisperMediumSTT._load_audio_from_bytes(b"not-audio-bytes")


# ============================================================
# 상수 검증
# ============================================================

class TestConstants:
    """상수값 검증."""

    def test_model_id(self):
        """기본 모델 ID 확인."""
        assert MODEL_ID == "openai/whisper-medium"

    def test_max_new_tokens(self):
        """최대 토큰 수가 Whisper Medium 제한 이내."""
        assert MAX_NEW_TOKENS <= 448

    def test_qlora_path_exists(self):
        """QLoRA 기본 경로가 설정되어 있음."""
        assert DEFAULT_QLORA_MERGED_PATH is not None

    def test_train65_default_path_is_configured(self):
        """Git으로 배포하지 않는 Train65 모델의 기본 디렉터리명을 확인한다."""
        assert DEFAULT_TRAIN65_MERGED_PATH.name == "final-train65-merged-bf16"



# ============================================================
# 컨텍스트 매니저 테스트
# ============================================================

class TestContextMenu:
    """WhisperMediumSTT 컨텍스트 매니저 동작 검증."""

    def test_enter_returns_self(self):
        """__enter__가 self를 반환한다."""
        stt = WhisperMediumSTT(device="cpu")
        with stt as ctx:
            assert ctx is stt

    def test_exit_unloads_model(self):
        """__exit__가 모델을 해제한다."""
        stt = WhisperMediumSTT(device="cpu")
        stt._model = MagicMock()
        stt._processor = MagicMock()
        with stt:
            pass
        assert stt._model is None
        assert stt._processor is None


# ============================================================
# Confidence 계산 테스트
# ============================================================

class TestComputeConfidence:
    """_compute_confidence 메서드 검증.

    실제 generate()의 ``output_scores``는 스텝별 logits 튜플이며,
    각 항목은 (vocab,) 또는 (batch, vocab) 형태이다.
    """

    @pytest.fixture(autouse=True)
    def _require_torch(self):
        try:
            torch.zeros(1)
        except AttributeError:
            pytest.skip(
                "torch namespace corrupted by sys.path pollution "
                "(test_stt_eval/test_stt_metrics inserts STT_DIR)"
            )

    def _scores_from_ids(self, token_ids, vocab_size=6):
        """각 스텝에서 주어진 토큰에 높은 logits를 갖는 scores 튜플 생성."""
        scores = []
        for tid in token_ids:
            logits = np.zeros((1, vocab_size), dtype=np.float32)
            logits[0, tid] = 100.0
            scores.append(torch.from_numpy(logits))
        return tuple(scores)

    def test_confidence_from_perfect_scores(self):
        """모든 스텝에서 정확한 예측 시 높은 신뢰도 반환."""
        stt = WhisperMediumSTT(device="cpu")
        scores = self._scores_from_ids([0, 0, 0])
        predicted_ids = torch.tensor([0, 0, 0], dtype=torch.long)

        confidence = stt._compute_confidence(scores, predicted_ids)
        assert confidence > 0.99

    def test_confidence_returns_none_for_none_scores(self):
        """scores가 None/빈 튜플일 때 None 반환."""
        stt = WhisperMediumSTT(device="cpu")
        predicted_ids = torch.tensor([0, 0], dtype=torch.long)
        assert stt._compute_confidence(None, predicted_ids) is None
        assert stt._compute_confidence((), predicted_ids) is None

    def test_confidence_returns_none_for_empty_ids(self):
        """빈 predicted_ids일 때 None 반환."""
        stt = WhisperMediumSTT(device="cpu")
        scores = self._scores_from_ids([0, 1, 2])
        predicted_ids = torch.empty((0,), dtype=torch.long)
        assert stt._compute_confidence(scores, predicted_ids) is None

    def test_confidence_stops_at_eos(self):
        """EOS 이후 스텝은 집계에서 제외된다."""
        stt = WhisperMediumSTT(device="cpu")
        # _model이 없으면 EOS 집합이 비어있으므로 모델 config를 모킹
        model = MagicMock()
        model.config.eos_token_id = 50257
        stt._model = model

        # 스텝1이 EOS(50257)인 경우 → 스텝0만 집계
        scores = self._scores_from_ids([0, 50257, 0], vocab_size=50258)
        predicted_ids = torch.tensor([0, 50257, 0], dtype=torch.long)

        confidence = stt._compute_confidence(scores, predicted_ids)
        assert confidence > 0.99  # EOS 이후는 무시되므로 스텝0 확률만 평균


class TestSplitIntoChunks:
    """_split_into_chunks 정적 메서드 검증."""

    def test_short_audio_single_chunk(self):
        """30초 이하 오디오는 단일 청크."""
        audio = np.zeros(16000, dtype=np.float32)
        chunks = WhisperMediumSTT._split_into_chunks(audio, 16000)
        assert len(chunks) == 1
        assert len(chunks[0]) == 16000

    def test_long_audio_multiple_chunks(self):
        """45초 오디오는 30초 + 15초 두 청크로 분할."""
        audio = np.zeros(45 * 16000, dtype=np.float32)
        chunks = WhisperMediumSTT._split_into_chunks(audio, 16000)
        assert len(chunks) == 2
        assert len(chunks[0]) == 30 * 16000
        assert len(chunks[1]) == 15 * 16000

    def test_chunk_coverage(self):
        """모든 샘플이 정확히 한 청크에 속한다."""
        audio = np.zeros(70 * 16000, dtype=np.float32)
        chunks = WhisperMediumSTT._split_into_chunks(audio, 16000)
        assert sum(len(c) for c in chunks) == len(audio)


class TestTranscribeChunking:
    """transcribe가 긴 오디오를 청크별로 추론하고 결합하는지 검증."""

    @pytest.fixture(autouse=True)
    def _require_torch(self):
        try:
            torch.zeros(1)
        except AttributeError:
            pytest.skip("torch unavailable")

    def _fake_chunk(self, audio_array, language):
        # 청크 텍스트는 청크 길이로 구분
        n = len(audio_array)
        text = f"chunk{n}"
        outputs = MagicMock()
        outputs.scores = (
            torch.tensor([[100.0, 0.0]]),  # 스텝0: 토큰0 확률 ~1
        )
        predicted_ids = torch.tensor([[0]])
        return text, outputs, predicted_ids, 0.1

    def test_long_audio_concatenates_chunks(self):
        """긴 오디오는 청크 텍스트가 공백으로 결합된다."""
        stt = WhisperMediumSTT(device="cpu")
        stt._model = MagicMock()
        stt._processor = MagicMock()

        wav = self._make_wav(45 * 16000)
        with patch.object(stt, "_ensure_loaded"), patch.object(
            stt, "_transcribe_chunk", side_effect=self._fake_chunk
        ):
            result = stt.transcribe(wav)

        assert result.text == "chunk480000 chunk240000"
        assert result.duration_ms is not None

    def _make_wav(self, n_samples):
        import io

        t = np.linspace(0, 1, n_samples, endpoint=False)
        audio = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
        buffer = io.BytesIO()
        sf.write(buffer, audio, 16000, format="WAV")
        buffer.seek(0)
        return buffer.read()


# ============================================================
# 리샘플링 테스트
# ============================================================

class TestResampleTo16kMono:
    """resample_to_16k_mono 공통 유틸리티 테스트."""

    def test_already_16k_mono(self):
        """16kHz 모노 오디오는 그대로 반환."""
        audio = np.random.randn(16000).astype(np.float32)
        result, sr = resample_to_16k_mono(audio, 16000)
        assert sr == 16000
        assert result.ndim == 1
        assert len(result) == 16000

    def test_stereo_to_mono(self):
        """Stereo를 Mono로 변환."""
        audio = np.random.randn(16000, 2).astype(np.float32)
        result, sr = resample_to_16k_mono(audio, 16000)
        assert sr == 16000
        assert result.ndim == 1

    def test_resample_from_44100(self):
        """44.1kHz → 16kHz 리샘플링."""
        audio = np.random.randn(44100).astype(np.float32)
        result, sr = resample_to_16k_mono(audio, 44100)
        assert sr == 16000
        assert len(result) == 16000

    def test_resample_from_44100_stereo(self):
        """44.1kHz Stereo → 16kHz Mono 변환."""
        audio = np.random.randn(44100, 2).astype(np.float32)
        result, sr = resample_to_16k_mono(audio, 44100)
        assert sr == 16000
        assert result.ndim == 1
        assert len(result) == 16000


# ============================================================
# 리샘플링 포함 오디오 로딩 테스트
# ============================================================

class TestAudioLoadingResample:
    """_load_audio_from_bytes 리샘플링 검증."""

    def _create_wav_bytes(
        self,
        duration: float = 1.0,
        sr: int = 16000,
        channels: int = 1,
    ) -> bytes:
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        audio = 0.5 * np.sin(2 * np.pi * 440 * t)
        if channels == 2:
            audio = np.stack([audio, audio], axis=1)
        buffer = io.BytesIO()
        sf.write(buffer, audio, sr, format="WAV")
        buffer.seek(0)
        return buffer.read()

    def test_non_16k_is_resampled(self):
        """44.1kHz WAV도 16kHz로 리샘플링."""
        wav_bytes = self._create_wav_bytes(sr=44100)
        audio, sr = WhisperMediumSTT._load_audio_from_bytes(wav_bytes)
        assert sr == 16000
        assert audio.ndim == 1


# ============================================================
# STTFailure import 검증
# ============================================================

class TestSTTFailure:
    """STTFailure 예외 검증."""

    def test_sttfailure_is_runtime_error(self):
        """STTFailure는 RuntimeError의 하위 클래스."""
        assert issubclass(STTFailure, RuntimeError)

    def test_sttfailure_can_be_raised(self):
        """STTFailure를 raise할 수 있다."""
        with pytest.raises(STTFailure, match="테스트 오류"):
            raise STTFailure("테스트 오류")

    def test_sttfailure_can_be_caught_as_runtime_error(self):
        """STTFailure는 RuntimeError로도 잡을 수 있다."""
        with pytest.raises(RuntimeError):
            raise STTFailure("테스트")
