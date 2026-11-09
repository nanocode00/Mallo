"""
Whisper Medium STT Adapter
==========================

Baseline 및 두 BF16 merged Whisper Medium 모델을 지원한다.

모델 선택:
    - variant="train65": Train65 merged BF16 (기본값)
    - variant="qlora": 기존 QLoRA 파인튜닝 + 도메인 추가 학습 BF16 merged (rollback)
    - variant="baseline": openai/whisper-medium (BF16)

사용법:
    from adapters.stt.whisper_medium import WhisperMediumSTT

    # QLoRA merged 모델 (기본)
    stt = WhisperMediumSTT()

    # Baseline 모델
    stt = WhisperMediumSTT(variant="baseline")

    result = stt.transcribe(audio_bytes)
    print(result.text, result.duration_ms)

    # 컨텍스트 매니저 사용
    with WhisperMediumSTT() as stt:
        result = stt.transcribe(audio_bytes)
"""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf
import torch

from interfaces.stt import STTFailure, STTResult

# common.py에서 CUDA 설정 및 유틸리티 재사용
from adapters.stt.common import (
    setup_cuda_dll_paths,
    resample_to_16k_mono,
)

# ============================================================
# 로거
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# 상수
# ============================================================

MODEL_ID = "openai/whisper-medium"

# QLoRA merged 모델 경로 (도메인 추가 학습, BF16 머지)
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QLORA_MERGED_PATH = _REPO_ROOT / "models" / "stt" / "archive" / "team-handoff-domain" / "merged-bf16"
DEFAULT_TRAIN65_MERGED_PATH = _REPO_ROOT / "models" / "stt" / "final-train65-merged-bf16"



# 추론 최대 토큰 수 (Whisper Medium decoder 최대 448)
MAX_NEW_TOKENS = 440

# 기본 추론 dtype
DEFAULT_DTYPE = torch.bfloat16


def _decode_with_av(audio: bytes) -> tuple[np.ndarray, int]:
    """
    libsndfile이 디코딩하지 못하는 컨테이너를 PyAV(FFmpeg)로 디코딩한다.

    브라우저 MediaRecorder 기본 출력인 webm/opus 등은 libsndfile로
    읽을 수 없으므로 이 폴백을 거친다.

    Returns:
        (mono float32 samples, sample_rate)
    """
    try:
        import av
    except ImportError as exc:
        raise STTFailure(
            "webm/opus 등 압축 오디오 디코딩에는 PyAV(av) 패키지가 필요합니다"
        ) from exc

    chunks: list[np.ndarray] = []
    sample_rate = 0
    try:
        container = av.open(io.BytesIO(audio))
        resampler = av.AudioResampler(format="flt", layout="mono")
        for frame in container.decode(audio=0):
            if not sample_rate:
                sample_rate = int(frame.sample_rate)
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray().reshape(-1))
        container.close()
    except Exception as exc:
        raise STTFailure(f"오디오 디코딩 실패: {exc}") from exc

    if not sample_rate or not chunks:
        raise STTFailure("디코딩 가능한 오디오 스트림이 없습니다")

    return np.concatenate(chunks).astype(np.float32), sample_rate


# ============================================================
# WhisperMediumSTT
# ============================================================

class WhisperMediumSTT:
    """
    Whisper Medium 기반 STT 어댑터.

    Args:
        variant: "train65" (Train65 merged BF16, 기본값), "qlora" (기존 merged
                 rollback), 또는 "baseline" (openai/whisper-medium)
        qlora_path: train65 또는 qlora merged model의 custom path. 기존 호출
                    호환성을 위한 이름이며 새 코드에서는 ``model_path``를 쓴다.
        model_path: train65 또는 qlora merged model의 custom path.
        device: 추론 디바이스. "cuda" 또는 "cpu".
        dtype: 추론 dtype. 기본값은 bfloat16.
        num_return_sequences: 대체 후보 수 (기본값 1).
                              2 이상이면 beam search를 사용하여 서로 다른 후보를 생성한다.
    """

    def __init__(
        self,
        variant: Literal["baseline", "qlora", "train65", "peft"] = "train65",
        qlora_path: str | Path | None = None,
        model_path: str | Path | None = None,
        device: str | None = None,
        dtype: torch.dtype = DEFAULT_DTYPE,
        num_return_sequences: int = 1,
    ) -> None:
        setup_cuda_dll_paths()

        if variant == "peft":
            logger.warning("variant='peft'는 deprecated alias입니다; 'train65'를 사용하세요.")
            variant = "train65"
        self.variant = variant
        self.dtype = dtype
        self.num_return_sequences = num_return_sequences

        # 디바이스 자동 선택
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        # 모델/프로세서 로드
        self._processor = None
        self._model = None
        if qlora_path is not None and model_path is not None:
            raise ValueError("qlora_path와 model_path는 함께 지정할 수 없습니다.")
        default_path = DEFAULT_TRAIN65_MERGED_PATH if variant == "train65" else DEFAULT_QLORA_MERGED_PATH
        self._model_path = Path(model_path or qlora_path) if (model_path or qlora_path) else default_path
        self._qlora_path = self._model_path  # legacy diagnostic/test compatibility
        self.model_source = "not-loaded"

        logger.info(
            "WhisperMediumSTT 초기화: variant=%s, device=%s, dtype=%s",
            variant,
            self.device,
            self.dtype,
        )

    # --------------------------------------------------------
    # 컨텍스트 매니저
    # --------------------------------------------------------

    def __enter__(self) -> WhisperMediumSTT:
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: object) -> None:
        self.unload()

    # --------------------------------------------------------
    # 지연 로드 (Lazy loading)
    # --------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """모델과 프로세서가 로드되지 않았으면 로드한다."""
        if self._model is not None:
            return

        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        if self.variant == "baseline":
            logger.info("Baseline 모델 로딩: %s", MODEL_ID)
            self._processor = WhisperProcessor.from_pretrained(
                MODEL_ID,
                language="ko",
                task="transcribe",
            )
            self._model = (
                WhisperForConditionalGeneration
                .from_pretrained(MODEL_ID, torch_dtype=self.dtype)
                .to(self.device)
            )
        elif self.variant in {"train65", "qlora"}:
            if not self._model_path.exists():
                raise FileNotFoundError(
                    f"{self.variant} merged 모델 경로를 찾을 수 없습니다:\n"
                    f"{self._model_path.resolve()}"
                )
            logger.info("%s merged 모델 로딩: %s", self.variant, self._model_path)
            # 머지 번들에 processor가 포함되어 있으므로 번들에서 로드
            self._processor = WhisperProcessor.from_pretrained(
                str(self._model_path),
                language="ko",
                task="transcribe",
            )
            self._model = (
                WhisperForConditionalGeneration
                .from_pretrained(
                    str(self._model_path),
                    torch_dtype=self.dtype,
                )
                .to(self.device)
            )
            self.model_source = f"merged:{self._model_path.resolve()}"
        else:
            raise ValueError(
                f"지원하지 않는 variant: {self.variant}. "
                f"'train65', 'qlora' 또는 'baseline'을 사용하세요."
            )

        self._model.eval()
        if self.variant == "baseline":
            self.model_source = f"base:{MODEL_ID}"
        logger.info(
            "모델 로딩 완료: variant=%s source=%s device=%s dtype=%s",
            self.variant,
            self.model_source,
            self.device,
            self.dtype,
        )

    # --------------------------------------------------------
    # 오디오 전처리
    # --------------------------------------------------------

    @staticmethod
    def _load_audio_from_bytes(audio: bytes) -> tuple[np.ndarray, int]:
        """바이트 스트림에서 오디오를 로드하고 16kHz 모노로 변환한다."""
        audio_stream = io.BytesIO(audio)
        try:
            audio_array, sampling_rate = sf.read(audio_stream)
        except sf.LibsndfileError:
            # webm/opus 등 브라우저 MediaRecorder 출력은 libsndfile이
            # 디코딩하지 못하므로 PyAV 폴백을 사용한다.
            audio_array, sampling_rate = _decode_with_av(audio)

        # 오디오 포맷 검증
        if audio_array.ndim not in (1, 2):
            raise STTFailure(
                f"지원되지 않는 오디오 차원성: {audio_array.ndim}차원"
            )

        if sampling_rate <= 0:
            raise STTFailure("유효하지 않은 샘플 레이트")

        # 16kHz 모노 변환 (공통 유틸리티 사용)
        audio_array, sampling_rate = resample_to_16k_mono(audio_array, sampling_rate)

        return audio_array, sampling_rate

    # --------------------------------------------------------
    # 신뢰도 추출
    # --------------------------------------------------------

    def _get_eos_token_ids(self) -> set[int]:
        """모델 config에서 EOS 토큰 id 집합을 가져온다."""
        if self._model is None:
            return set()
        eos = getattr(self._model.config, "eos_token_id", None)
        if eos is None:
            return set()
        if isinstance(eos, (list, tuple, set)):
            return {int(x) for x in eos}
        return {int(eos)}

    def _compute_confidence(
        self,
        scores: tuple[torch.Tensor, ...] | None,
        predicted_ids: torch.Tensor,
    ) -> float | None:
        """생성된 토큰들의 평균 신뢰도(confidence)를 계산한다.

        ``scores``는 ``generate()``의 ``output_scores``(스텝별 logits 튜플)이며,
        각 항목은 (vocab,) 또는 (batch, vocab) 형태이다. 메인 시퀀스
        (``predicted_ids``의 첫 번째 행)에 대해 각 스텝에서 예측된 토큰의
        softmax 확률을 모아 평균낸다. EOS 토큰 이후 스텝은 집계에서 제외한다.

        정렬 주의: Whisper는 language/task/``<|notimestamps|>`` 등 강제 디코더
        prefix를 ``sequences`` 앞에 삽입한다. ``scores[i]``는 이 prefix **이후**
        i번째 생성 토큰(``sequences[i + offset]``)을 예측하므로, ``offset``만큼
        시프트하여 정확한 토큰과 매칭해야 한다. ``offset``은
        ``len(sequences) - len(scores)``(강제 prefix 길이)로 복원한다.

        신뢰도가 낮거나 계산 불가한 경우 ``None``을 반환한다.
        """
        if not scores:
            return None
        if predicted_ids is None or predicted_ids.shape[0] == 0:
            return None

        main_ids = predicted_ids[0] if predicted_ids.dim() > 1 else predicted_ids
        eos_ids = self._get_eos_token_ids()

        # 강제 디코더 prefix 길이(offset)만큼 시퀀스 인덱스를 시프트
        offset = main_ids.shape[0] - len(scores)
        if offset < 0:
            offset = 0

        probs: list[float] = []
        for step, logits in enumerate(scores):
            idx = step + offset
            if idx >= main_ids.shape[0]:
                break
            # logits 정규화: (vocab,) 또는 (batch, vocab)
            if logits.dim() == 1:
                step_logits = logits.unsqueeze(0)
            else:
                step_logits = logits[:1]
            step_probs = torch.softmax(step_logits.float(), dim=-1)
            token_id = int(main_ids[idx].item())
            if token_id in eos_ids:
                break
            probs.append(float(step_probs[0, token_id].item()))

        if not probs:
            return None
        confidence = float(np.mean(probs))
        # 신뢰도가 너무 낮으면 None 반환 (임계값 0.1)
        if confidence < 0.1:
            return None
        return confidence

    # --------------------------------------------------------
    # STT 인터페이스 구현
    # --------------------------------------------------------

    def transcribe(self, audio: bytes, language: str = "ko") -> STTResult:
        """
        오디오 바이트를 텍스트로 변환한다.

        Args:
            audio: WAV 포맷 오디오 바이트
            language: 언어 코드 (기본값: "ko")

        Returns:
            STTResult: text, confidence, duration_ms, alternatives 포함

        Raises:
            STTFailure: 오디오 디코딩 또는 추론 실패 시
        """
        self._ensure_loaded()

        # 오디오 로드
        try:
            audio_array, sampling_rate = self._load_audio_from_bytes(audio)
        except Exception as e:
            raise STTFailure(
                f"오디오 디코딩 실패: {e}"
            ) from e

        # 30초 초과 오디오는 Whisper 윈도우 단위로 분할 후 각각 추론
        chunks = self._split_into_chunks(audio_array, sampling_rate)

        chunk_texts: list[str] = []
        chunk_confidences: list[float] = []
        first_outputs: object | None = None
        first_predicted_ids: torch.Tensor | None = None
        total_latency = 0.0

        for index, chunk in enumerate(chunks):
            text, outputs, predicted_ids, latency = self._transcribe_chunk(chunk, language)
            total_latency += latency
            chunk_texts.append(text)

            if outputs.scores:
                conf = self._compute_confidence(outputs.scores, predicted_ids)
                if conf is not None:
                    chunk_confidences.append(conf)

            if index == 0:
                first_outputs = outputs
                first_predicted_ids = predicted_ids

        transcription = " ".join(t for t in (c.strip() for c in chunk_texts) if t)

        # 대체 후보 생성 (첫 청크 기준, num_return_sequences > 1)
        alternatives = ()
        if (
            first_outputs is not None
            and first_predicted_ids is not None
            and self.num_return_sequences > 1
            and first_predicted_ids.shape[0] > 1
        ):
            alt_texts = self._processor.batch_decode(
                first_predicted_ids[1:],
                skip_special_tokens=True,
            )
            # 메인 결과와 동일한 텍스트는 제외
            seen = {transcription}
            alt_list = []
            for alt in alt_texts:
                alt_stripped = alt.strip()
                if alt_stripped and alt_stripped not in seen:
                    alt_list.append(alt_stripped)
                    seen.add(alt_stripped)
            alternatives = tuple(alt_list)

        confidence = float(np.mean(chunk_confidences)) if chunk_confidences else None

        return STTResult(
            text=transcription,
            confidence=confidence,
            duration_ms=round(total_latency * 1000, 1),
            alternatives=alternatives,
        )

    @staticmethod
    def _split_into_chunks(
        audio_array: np.ndarray,
        sampling_rate: int,
        chunk_seconds: int = 30,
    ) -> list[np.ndarray]:
        """길이가 30초를 초과하는 오디오를 Whisper 윈도우 단위로 분할한다."""
        chunk_samples = int(chunk_seconds * sampling_rate)
        if len(audio_array) <= chunk_samples:
            return [audio_array]
        return [
            audio_array[start : start + chunk_samples]
            for start in range(0, len(audio_array), chunk_samples)
        ]

    def _transcribe_chunk(
        self,
        audio_array: np.ndarray,
        language: str,
    ) -> tuple[str, object, torch.Tensor, float]:
        """단일 오디오 청크를 추론하고 (텍스트, outputs, predicted_ids, latency)를 반환한다."""
        input_features = (
            self._processor
            .feature_extractor(audio_array, sampling_rate=16000)
            .input_features[0]
        )
        input_features = torch.tensor(input_features).unsqueeze(0).to(
            device=self.device, dtype=self.dtype
        )

        start_time = time.perf_counter()
        try:
            with torch.no_grad():
                generate_kwargs: dict = dict(
                    input_features=input_features,
                    max_new_tokens=MAX_NEW_TOKENS,
                    language=(f"<|{language.lower()}|>" if len(language) == 2 else language),
                    task="transcribe",
                    num_return_sequences=self.num_return_sequences,
                    return_dict_in_generate=True,
                    output_scores=True,
                )
                # num_return_sequences > 1이면 beam search 필요
                # (greedy는 동일 시퀀스 반복)
                if self.num_return_sequences > 1:
                    generate_kwargs["num_beams"] = self.num_return_sequences
                outputs = self._model.generate(**generate_kwargs)
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                torch.cuda.empty_cache()
                raise STTFailure(
                    "GPU 메모리 부족 — 오디오 길이를 줄이거나 나중에 다시 시도하세요."
                ) from e
            raise STTFailure(
                f"STT 추론 실패: {e}"
            ) from e

        latency = time.perf_counter() - start_time

        sequences = outputs.sequences
        predicted_ids = sequences if sequences.dim() == 2 else sequences[0].unsqueeze(0)

        transcription = self._processor.batch_decode(
            predicted_ids[:1],
            skip_special_tokens=True,
        )[0].strip()

        return transcription, outputs, predicted_ids, latency

    # --------------------------------------------------------
    # 유틸리티
    # --------------------------------------------------------

    def unload(self) -> None:
        """모델을 메모리에서 해제한다."""
        if self._model is not None:
            del self._model
            self._model = None
        if self._processor is not None:
            del self._processor
            self._processor = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("모델 메모리 해제 완료")

    def __repr__(self) -> str:
        return (
            f"WhisperMediumSTT(variant={self.variant!r}, "
            f"device={self.device!r})"
        )
