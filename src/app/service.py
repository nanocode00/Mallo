from __future__ import annotations

from pathlib import Path

from adapters.nlu.mock_nlu import MockNLU
from adapters.stt.mock_stt import MockSTT
from adapters.tts.mock_tts import MockTTS
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.models import Cart, FulfillmentType, OrderCommand, OrderResult, STTResult
from domain.tts_controller import AdaptiveTTSController
from domain.tts_result import TTSResult
from domain.voice_interaction import VoiceInteractionResult
from interfaces.agent import Agent
from interfaces.interaction_logger import InteractionLogger
from interfaces.nlu import NLU
from interfaces.stt import STT
from interfaces.tts import TTS
from orchestrator.voice_pipeline import VoicePipeline


class MalloService:
    def __init__(
        self,
        nlu: NLU,
        agent: Agent,
        tts: TTS,
        stt: STT | None = None,
        tts_controller: AdaptiveTTSController | None = None,
        logger: InteractionLogger | None = None,
        session_id: str | None = None,
    ) -> None:
        # Adapters are immutable/stateless HTTP clients in production and can be
        # shared by lightweight per-browser session services. The order agent
        # and VoicePipeline state below are intentionally not shared.
        self._nlu = nlu
        self._tts = tts
        self._stt = stt
        self._logger = logger
        self._pipeline = VoicePipeline(
            nlu=nlu,
            agent=agent,
            tts=tts,
            stt=stt,
            tts_controller=tts_controller,
            logger=logger,
            session_id=session_id,
        )

    def new_session(self, session_id: str | None = None) -> "MalloService":
        """Create isolated conversation/order state while reusing model adapters."""
        return MalloService(
            nlu=self._nlu,
            agent=ConversationAgent(load_menu()),
            tts=self._tts,
            stt=self._stt,
            logger=self._logger,
            session_id=session_id,
        )

    def handle_text(self, text: str, cart: Cart) -> OrderResult:
        return self._pipeline.handle_text(text, cart)

    def handle_commands(self, commands: list[OrderCommand], cart: Cart) -> OrderResult:
        return self._pipeline.handle_commands(commands, cart)

    @staticmethod
    def start_order(fulfillment_type: FulfillmentType | str) -> Cart:
        try:
            selected = FulfillmentType(fulfillment_type)
        except ValueError as error:
            raise ValueError("이용 방식은 dine_in 또는 takeout이어야 합니다.") from error
        return Cart(fulfillment_type=selected)

    def handle_audio(self, audio: bytes, cart: Cart) -> VoiceInteractionResult:
        return self._pipeline.handle_audio(audio, cart)

    def transcribe(self, audio: bytes) -> STTResult:
        """오디오를 STT로만 변환한다(NLU·Order Engine·TTS 실행 없음)."""
        return self._pipeline.transcribe_audio(audio)

    def interpret_voice_transcript(self, transcript: str, cart: Cart) -> OrderResult:
        """Run an STT-complete voice turn through server-side NLU and Order Engine."""
        return self._pipeline.handle_voice_transcript(transcript, cart)

    @property
    def tts_level(self) -> int:
        return self._pipeline.current_tts_level

    @property
    def last_response(self) -> str:
        return self._pipeline.last_response

    @property
    def last_tts_result(self) -> TTSResult | None:
        return self._pipeline.last_tts_result

    @property
    def last_order_commands(self) -> list[OrderCommand]:
        return self._pipeline.last_order_commands

    @property
    def last_comprehension_signal(self) -> bool:
        return self._pipeline.last_comprehension_signal

    @property
    def last_auto_speed_changed(self) -> bool:
        return self._pipeline.last_auto_speed_changed

    @property
    def auto_slower_notice(self) -> str:
        return self._pipeline.auto_slower_notice

    def remember_replayable_response(self, text: str) -> None:
        self._pipeline.remember_replayable_response(text)

    def synthesize_message(self, text: str) -> TTSResult | None:
        """주문 상태를 변경하지 않고 화면용 system message를 합성한다."""
        return self._pipeline.synthesize_message(text)

    def synthesize_message_at_level(self, text: str, level: int) -> TTSResult | None:
        """지정된 TTS level로 메시지를 합성한다."""
        return self._pipeline.synthesize_message_at_level(text, level)

    def warmup_tts(self) -> None:
        """Load/JIT the configured TTS before the first user-visible prompt."""
        self._pipeline.synthesize_message("안내 준비")

    def repeat_last_message(self) -> TTSResult | None:
        return self._pipeline.repeat_last_message()

    def cycle_tts_level(self) -> TTSResult | None:
        return self._pipeline.cycle_tts_level()

    def set_tts_level(self, level: int) -> TTSResult | None:
        return self._pipeline.set_tts_level(level)

    def reset_session(self) -> None:
        self._pipeline.reset_session()


def build_service(
    *,
    tts_backend: str = "mock",
    tts_ckpt_path: Path | str | None = None,
    tts_config_path: Path | str | None = None,
    tts_device: str = "auto",
    tts_speaker: str = "KR",
    tts_url: str = "http://127.0.0.1:8003/synthesize",
    stt_backend: str = "mock",
    stt_variant: str = "train65",
    stt_device: str | None = None,
    stt_model_path: str | None = None,
    nlu_backend: str = "mock",
    nlu_model_path: Path | str | None = None,
    nlu_prompt_lookup_num_tokens: int = 8,
    nlu_url: str = "http://127.0.0.1:8002/parse",
    nlu: NLU | None = None,
    agent: Agent | None = None,
    logger: InteractionLogger | None = None,
) -> MalloService:
    tts_adapter: TTS
    if tts_backend == "melo":
        from adapters.tts.melotts_adapter import MeloTTSAdapter

        tts_adapter = MeloTTSAdapter(
            device=tts_device,
            config_path=tts_config_path,
            ckpt_path=tts_ckpt_path,
            speaker=tts_speaker,
        )
    elif tts_backend == "qwen3":
        from adapters.tts.qwen3_adapter import Qwen3TTSAdapter

        model_path = tts_ckpt_path or "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
        speaker = tts_speaker if tts_speaker != "KR" else "Ryan"
        tts_adapter = Qwen3TTSAdapter(
            model_id_or_path=model_path,
            device=tts_device,
            speaker=speaker,
        )
    elif tts_backend == "mock":
        tts_adapter = MockTTS()
    elif tts_backend == "http":
        from adapters.tts.http_tts import HTTPClientTTS

        tts_adapter = HTTPClientTTS(url=tts_url)
    else:
        raise ValueError("tts_backend은 mock, melo, qwen3 또는 http여야 합니다.")

    stt_adapter: STT
    if stt_backend == "whisper":
        from adapters.stt.whisper_medium import WhisperMediumSTT

        dev = None if stt_device in (None, "auto") else stt_device
        stt_adapter = WhisperMediumSTT(
            device=dev,
            variant=stt_variant,  # type: ignore[arg-type]
            model_path=stt_model_path,
        )
    elif stt_backend == "http":
        from adapters.stt.http_stt import HTTPClientSTT

        stt_adapter = HTTPClientSTT(
            url=stt_model_path or "http://127.0.0.1:8001/transcribe"
        )
    elif stt_backend == "fastwhisper":
        from adapters.stt.faster_whisper_stt import FasterWhisperSTT

        dev = "cpu" if stt_device == "cpu" else "auto"
        compute_type = "int8" if dev == "cpu" else "float16"
        stt_adapter = FasterWhisperSTT(
            model_size_or_path=stt_model_path or "base",
            device=dev,  # type: ignore[arg-type]
            compute_type=compute_type,  # type: ignore[arg-type]
        )
    elif stt_backend == "mock":
        stt_adapter = MockSTT()
    else:
        raise ValueError("stt_backend은 mock, whisper, fastwhisper 또는 http여야 합니다.")

    if nlu is not None:
        nlu_impl = nlu
    elif nlu_backend == "qwen06b":
        from adapters.nlu.qwen06b_nlu import DEFAULT_SERVICE_MERGED_MODEL, Qwen06BNLU

        nlu_impl = Qwen06BNLU(
            merged_model_path=nlu_model_path or DEFAULT_SERVICE_MERGED_MODEL,
            prompt_lookup_num_tokens=nlu_prompt_lookup_num_tokens,
        )
    elif nlu_backend == "http":
        from adapters.nlu.http_nlu import HTTPClientNLU

        nlu_impl = HTTPClientNLU(url=nlu_url)
    elif nlu_backend == "mock":
        nlu_impl = MockNLU()
    else:
        raise ValueError("nlu_backend은 mock, qwen06b 또는 http여야 합니다.")

    agent_impl = agent or ConversationAgent(load_menu())

    return MalloService(
        nlu=nlu_impl,
        agent=agent_impl,
        tts=tts_adapter,
        stt=stt_adapter,
        logger=logger,
    )


def build_mock_service(
    *,
    canned_stt_text: str = "아이스 아메리카노 두 잔 주세요",
    tts_should_fail: bool = False,
    stt_should_fail: bool = False,
    logger: InteractionLogger | None = None,
) -> MalloService:
    return MalloService(
        nlu=MockNLU(),
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(should_fail=tts_should_fail),
        stt=MockSTT(canned_text=canned_stt_text, should_fail=stt_should_fail),
        logger=logger,
    )
