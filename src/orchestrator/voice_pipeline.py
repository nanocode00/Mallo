from __future__ import annotations

import threading
import time
import logging
import re
from collections import Counter, deque
from dataclasses import replace

from jsonschema import ValidationError

from domain.errors import MIXED_INTENT_USER_MESSAGE
from domain.intents import Intent
from domain.models import (
    Cart,
    ErrorCode,
    ErrorModule,
    OrderCommand,
    OrderCommandError,
    OrderCommandErrorCode,
    OrderResult,
    Temperature,
    create_error_response,
    get_default_error_response,
)
from domain.session_log import SessionGroup, SessionLogEvent, SessionLogEventType
from domain.session_state import SessionState
from domain.stt_result import STTResult
from domain.text_transformer import AdaptiveTextTransformer
from domain.tts_controller import AdaptiveTTSController
from domain.tts_result import TTSResult
from domain.voice_interaction import VoiceInteractionResult
from interfaces.interaction_logger import InteractionLogger
from interfaces.agent import Agent
from interfaces.nlu import NLU, NLUFailure
from interfaces.stt import STT, STTFailure
from interfaces.tts import TTS, TTSFailure
from orchestrator.rule_first_nlu import RuleFirstNLU
from utils.schema_validation import (
    validate_order_command_error,
    validate_order_commands,
    validate_stt_result,
)

logger = logging.getLogger(__name__)


class VoicePipeline:
    _COMPREHENSION_WINDOW_TURNS = 4
    _AUTO_SLOWER_NOTICE = "조금 더 천천히 안내해 드릴게요."
    _TTS_CONTROL_INTENTS = frozenset(
        {
            Intent.REQUEST_REPEAT,
            Intent.REQUEST_CLARIFICATION,
            Intent.REQUEST_SLOWER,
            Intent.REQUEST_DEFAULT_SPEED,
        }
    )

    def __init__(
        self,
        nlu: NLU,
        agent: Agent,
        tts: TTS,
        stt: STT | None = None,
        tts_controller: AdaptiveTTSController | None = None,
        logger: InteractionLogger | None = None,
        session_id: str | None = None,
        participant_id: str = "dev",
        group: SessionGroup = SessionGroup.GROUP_C_MALLO,
        task_id: str | None = None,
    ) -> None:
        self._nlu = RuleFirstNLU(nlu)
        self._agent = agent
        self._tts = tts
        self._stt = stt
        self._stt_lock = threading.Lock()
        self._tts_controller = tts_controller or AdaptiveTTSController()
        self._logger = logger
        self._participant_id = participant_id
        self._group = group
        self._task_id = task_id
        self._step_index = 0
        self._session_id = session_id or self._new_session_id()
        self._default_last_response = SessionState().last_response
        self._last_response = self._default_last_response
        self._last_tts_result: TTSResult | None = None
        self._last_tts_output_text: str | None = None
        self._last_order_commands: list[OrderCommand] = []
        self._successful_semantic_turn = 0
        self._comprehension_turns: deque[int] = deque()
        self._last_comprehension_signal = False
        self._last_auto_speed_changed = False

    @staticmethod
    def _new_session_id() -> str:
        import secrets
        import time

        return f"sess_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"

    def _log_interaction(
        self,
        event_type: SessionLogEventType,
        *,
        text: str | None,
        order_result: OrderResult,
        commands: list[OrderCommand] | None = None,
        latencies_ms: tuple[float, float, float, float, float] | None = None,
        audio_duration_ms: float | None = None,
        stt_confidence: float | None = None,
        cart_before: Cart | None = None,
    ) -> None:
        if self._logger is None:
            return
        self._step_index += 1
        latencies: dict[str, float] | None = None
        if latencies_ms is not None:
            stt_ms, nlu_ms, agent_ms, tts_ms, total_ms = latencies_ms
            latencies = {
                "stt_seconds": round(stt_ms / 1000, 3),
                "nlu_seconds": round(nlu_ms / 1000, 3),
                "agent_seconds": round(agent_ms / 1000, 3),
                "order_engine_seconds": round(agent_ms / 1000, 3),
                "tts_seconds": round(tts_ms / 1000, 3),
                "total_e2e_seconds": round(total_ms / 1000, 3),
            }
        event = SessionLogEvent(
            session_id=self._session_id,
            participant_id=self._participant_id,
            group=self._group,
            timestamp=SessionLogEvent.now_iso(),
            event_type=event_type,
            step_index=self._step_index,
            is_success=order_result.success,
            task_id=self._task_id,
            audio_input_duration_seconds=(
                round(audio_duration_ms / 1000, 3)
                if audio_duration_ms is not None
                else None
            ),
            stt_transcription=text,
            stt_confidence=stt_confidence,
            nlu_intent=commands[0].intent.value if commands else None,
            nlu_source=self._nlu.last_source,
            order_commands=(
                [command.to_dict() for command in commands]
                if commands
                else None
            ),
            order_state_before=(
                SessionLogEvent.cart_to_state(cart_before)
                if cart_before is not None
                else None
            ),
            order_state_after=SessionLogEvent.cart_to_state(order_result.cart),
            tts_level=self._tts_controller.current_level,
            response_text=(
                order_result.debug_response_text or order_result.response_text
            ),
            tts_output_text=self._last_tts_output_text,
            latencies=latencies,
            error_code=(
                order_result.error_code.value
                if order_result.error_code is not None
                else None
            ),
        )
        self._logger.log_event(event)

    @property
    def current_tts_level(self) -> int:
        return self._tts_controller.current_level

    @property
    def last_response(self) -> str:
        return self._last_response

    @property
    def last_tts_result(self) -> TTSResult | None:
        return self._last_tts_result

    @property
    def last_order_commands(self) -> list[OrderCommand]:
        return list(self._last_order_commands)

    @property
    def last_comprehension_signal(self) -> bool:
        return self._last_comprehension_signal

    @property
    def last_auto_speed_changed(self) -> bool:
        return self._last_auto_speed_changed

    @property
    def auto_slower_notice(self) -> str:
        return self._AUTO_SLOWER_NOTICE

    def remember_replayable_response(self, text: str) -> None:
        """Keep a system prompt available to semantic repeat/clarification."""
        self._last_response = text

    def reset_session(self) -> None:
        self._log_interaction(
            SessionLogEventType.SESSION_RESET,
            text=None,
            order_result=OrderResult(True, Cart(), "", None),
        )
        self._tts_controller.reset()
        reset_agent = getattr(self._agent, "reset_session", None)
        if callable(reset_agent):
            reset_agent()
        self._nlu.reset_session()
        self._step_index = 0
        self._session_id = self._new_session_id()
        self._last_response = self._default_last_response
        self._last_tts_result = None
        self._last_tts_output_text = None
        self._last_order_commands = []
        self._successful_semantic_turn = 0
        self._comprehension_turns.clear()
        self._last_comprehension_signal = False
        self._last_auto_speed_changed = False

    def synthesize_message(self, text: str, *, remember_response: bool = True) -> TTSResult | None:
        """주문/NLU를 거치지 않는 사용자 안내를 현재 TTS level로 합성한다."""
        result = self._synthesize_result(
            OrderResult(True, Cart(), text),
            remember_response=remember_response,
        )
        return self._last_tts_result if result.success else None

    def synthesize_message_at_level(self, text: str, level: int) -> TTSResult | None:
        """지정된 TTS level로 메시지를 합성한다."""
        try:
            tts_res = self._tts.synthesize(text, level=level)
            return tts_res if isinstance(tts_res, TTSResult) else None
        except TTSFailure:
            return None

    def repeat_last_message(self) -> TTSResult | None:
        return self.synthesize_message(self._last_response, remember_response=False)

    def cycle_tts_level(self) -> TTSResult | None:
        self._tts_controller.cycle_level()
        return self.synthesize_message("이 속도로 안내합니다.", remember_response=False)

    def set_tts_level(self, level: int) -> TTSResult | None:
        self._tts_controller.set_level(level)
        return self.synthesize_message("이 속도로 안내합니다.", remember_response=False)

    def handle_text(self, text: str, cart: Cart) -> OrderResult:
        """텍스트 입력을 받아 NLU -> Order Engine -> Adaptive TTS 파이프라인을 실행한다."""
        self._last_tts_result = None
        self._last_order_commands = []
        self._last_comprehension_signal = False
        self._last_auto_speed_changed = False
        normalized = text.strip()
        if not normalized:
            err = get_default_error_response(ErrorCode.EMPTY_INPUT)
            result = OrderResult(
                False,
                cart.copy(),
                err.user_message,
                err.error_code,
                error_response=err,
            )
            result = self._synthesize_result(result, remember_response=True)
            self._log_interaction(
                SessionLogEventType.ERROR_RECOVERY,
                text=normalized,
                order_result=result,
                cart_before=cart,
            )
            return result

        try:
            nlu_started = time.perf_counter()
            nlu_result = self._nlu.parse(normalized, cart.copy())
            self._log_nlu_application(
                normalized,
                nlu_result,
                (time.perf_counter() - nlu_started) * 1000,
            )
            if isinstance(nlu_result, OrderCommandError):
                validate_order_command_error(nlu_result)
                result = self._nlu_error_result(nlu_result, cart)
                result = self._synthesize_result(result, remember_response=True)
                self._log_interaction(
                    SessionLogEventType.ERROR_RECOVERY,
                    text=normalized,
                    order_result=result,
                    cart_before=cart,
                )
                return result
            commands = nlu_result
            validate_order_commands(commands)
            self._last_order_commands = list(commands)
            self._record_successful_semantic_turn()
        except NLUFailure as exc:
            self._log_nlu_application(normalized, exc.error, None)
            result = self._nlu_error_result(exc.error, cart)
            result = self._synthesize_result(result, remember_response=True)
            self._log_interaction(
                SessionLogEventType.ERROR_RECOVERY,
                text=normalized,
                order_result=result,
                cart_before=cart,
            )
            return result
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            logger.warning(
                "[NLU] failure input=%r source=%s error_type=%s",
                normalized, self._nlu.last_source or "unknown", type(exc).__name__,
            )
            result = self._nlu_error_result(
                OrderCommandError(
                    code=OrderCommandErrorCode.SCHEMA_ERROR,
                    message="주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요.",
                ),
                cart,
            )
            result = self._synthesize_result(result, remember_response=True)
            self._log_interaction(
                SessionLogEventType.ERROR_RECOVERY,
                text=normalized,
                order_result=result,
                cart_before=cart,
            )
            return result

        if commands[0].intent in self._TTS_CONTROL_INTENTS:
            result = self._execute_tts_control(commands, cart)
            self._log_interaction(
                SessionLogEventType.TTS_SPEED_CONTROL,
                text=normalized,
                order_result=result,
                commands=commands,
                cart_before=cart,
            )
            return result

        result = self._agent.execute(commands, cart)
        result = self._synthesize_result(result, remember_response=True)
        self._log_interaction(
            SessionLogEventType.ORDER_INTERACTION,
            text=normalized,
            order_result=result,
            commands=commands,
            cart_before=cart,
        )
        return result

    def _log_nlu_application(
        self,
        text: str,
        nlu_result: list[OrderCommand] | OrderCommandError,
        latency_ms: float | None,
    ) -> None:
        """Emit launcher-visible semantic QA logs without tokens or secrets."""
        source = self._nlu.last_source or "unknown"
        latency = f"{latency_ms:.1f}" if latency_ms is not None else "unknown"
        if isinstance(nlu_result, OrderCommandError):
            logger.info(
                "[NLU] input=%r source=%s error=%s latency_ms=%s",
                text, source, nlu_result.code.value, latency,
            )
            return
        commands = []
        for command in nlu_result:
            payload = command.to_dict()
            payload.pop("request_id", None)
            commands.append(payload)
        logger.info(
            "[NLU] input=%r source=%s commands=%s latency_ms=%s",
            text, source, commands, latency,
        )

    def handle_commands(self, commands: list[OrderCommand], cart: Cart) -> OrderResult:
        """Execute touch semantic commands without invoking NLU."""
        self._last_tts_result = None
        self._last_order_commands = list(commands)
        self._last_comprehension_signal = False
        self._last_auto_speed_changed = False
        try:
            validate_order_commands(commands)
        except (TypeError, ValueError, ValidationError):
            return self._nlu_error_result(OrderCommandError(
                code=OrderCommandErrorCode.SCHEMA_ERROR,
                message="주문 형식을 확인할 수 없습니다.",
            ), cart)
        result = self._agent.execute(commands, cart)
        if result.success and any(command.intent is Intent.ADD_ITEM for command in commands):
            add_commands = [c for c in commands if c.intent is Intent.ADD_ITEM]
            item_texts = []
            for cmd in add_commands:
                menu_item = getattr(self._agent, "_menu", {}).get(cmd.target_item_id) if cmd.target_item_id else None
                if menu_item:
                    is_selectable = len(menu_item.temperature_options) >= 2
                    temp_label = (
                        {
                            Temperature.HOT: "따뜻한 ",
                            Temperature.ICED: "아이스 ",
                            None: "",
                        }[cmd.temperature]
                        if is_selectable
                        else ""
                    )
                    full_name = f"{temp_label}{menu_item.name}"
                    particle = getattr(self._agent, "_korean_particle", lambda w, p="을를": "를")(full_name, "을를")
                    item_texts.append(f"{full_name}{particle} 장바구니에 담았습니다.")
            if item_texts:
                result = replace(result, response_text=" ".join(item_texts))
        return self._synthesize_result(result, remember_response=True)

    def handle_voice_transcript(self, transcript: str, cart: Cart) -> OrderResult:
        """Continue an STT-complete voice turn without allowing the UI to parse it."""
        # `/api/audio/interpret` exposes this list to the UI for navigation.
        # A rejected short STT fragment must never inherit the preceding turn's
        # command (for example, a prior CONFIRM_ORDER) into that response.
        self._last_order_commands = []
        if self._is_sane_transcript(transcript):
            return self.handle_text(transcript, cart)
        err = create_error_response(
            ErrorCode.UNSUPPORTED_UTTERANCE,
            module=ErrorModule.STT,
            user_message="잘 듣지 못했습니다. 다시 말씀해 주세요.",
            retryable=True,
        )
        result = OrderResult(False, cart.copy(), err.user_message, err.error_code, error_response=err)
        return self._synthesize_result(result, remember_response=True)

    def _handle_text_with_timing(
        self, text: str, cart: Cart,
    ) -> tuple[OrderResult, float, float, float, list[OrderCommand] | None]:
        """handle_text와 동일하나 (order_result, nlu_ms, agent_ms, tts_ms, commands)를 반환한다."""
        nlu_ms = 0.0
        agent_ms = 0.0
        tts_ms = 0.0
        commands: list[OrderCommand] | None = None

        normalized = text.strip()
        if not normalized:
            err = get_default_error_response(ErrorCode.EMPTY_INPUT)
            result = OrderResult(
                False,
                cart.copy(),
                err.user_message,
                err.error_code,
                error_response=err,
            )
            t0 = time.perf_counter()
            result = self._synthesize_result(result, remember_response=True)
            tts_ms = (time.perf_counter() - t0) * 1000
            return (
                result,
                nlu_ms, agent_ms, tts_ms, commands,
            )

        try:
            t0 = time.perf_counter()
            nlu_result = self._nlu.parse(normalized, cart.copy())
            nlu_ms = (time.perf_counter() - t0) * 1000
            self._log_nlu_application(normalized, nlu_result, nlu_ms)

            if isinstance(nlu_result, OrderCommandError):
                validate_order_command_error(nlu_result)
                result = self._nlu_error_result(nlu_result, cart)
                t0 = time.perf_counter()
                result = self._synthesize_result(result, remember_response=True)
                tts_ms = (time.perf_counter() - t0) * 1000
                return (
                    result,
                    nlu_ms, agent_ms, tts_ms, commands,
                )
            commands = nlu_result
            validate_order_commands(commands)
            self._record_successful_semantic_turn()
        except NLUFailure as exc:
            self._log_nlu_application(normalized, exc.error, nlu_ms)
            result = self._nlu_error_result(exc.error, cart)
            t0 = time.perf_counter()
            result = self._synthesize_result(result, remember_response=True)
            tts_ms = (time.perf_counter() - t0) * 1000
            return (
                result,
                nlu_ms, agent_ms, tts_ms, commands,
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            logger.warning(
                "[NLU] failure input=%r source=%s error_type=%s latency_ms=%.1f",
                normalized, self._nlu.last_source or "unknown", type(exc).__name__, nlu_ms,
            )
            result = self._nlu_error_result(
                OrderCommandError(
                    code=OrderCommandErrorCode.SCHEMA_ERROR,
                    message="주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요.",
                ),
                cart,
            )
            t0 = time.perf_counter()
            result = self._synthesize_result(result, remember_response=True)
            tts_ms = (time.perf_counter() - t0) * 1000
            return (
                result,
                nlu_ms, agent_ms, tts_ms, commands,
            )

        if commands[0].intent in self._TTS_CONTROL_INTENTS:
            result = self._execute_tts_control(commands, cart)
            return (result, nlu_ms, agent_ms, tts_ms, commands)

        t0 = time.perf_counter()
        result = self._agent.execute(commands, cart)
        agent_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        result = self._synthesize_result(result, remember_response=True)
        tts_ms = (time.perf_counter() - t0) * 1000

        return (result, nlu_ms, agent_ms, tts_ms, commands)

    def _execute_tts_control(
        self,
        commands: list[OrderCommand],
        cart: Cart,
    ) -> OrderResult:
        command = commands[0]
        if (
            len(commands) != 1
            or command.target_item_id is not None
            or command.category_id is not None
            or command.quantity is not None
            or command.temperature is not None
            or command.query_tags is not None
            or command.detail_fields is not None
            or command.options is not None
        ):
            err = get_default_error_response(ErrorCode.INVALID_COMMAND)
            return OrderResult(
                False,
                cart.copy(),
                err.user_message,
                err.error_code,
                error_response=err,
            )

        if command.intent is Intent.REQUEST_CLARIFICATION:
            self._last_comprehension_signal = True
            self._comprehension_turns.append(self._successful_semantic_turn)
            if len(self._comprehension_turns) >= 2:
                previous_level = self._tts_controller.current_level
                self._tts_controller.increase_level()
                self._last_auto_speed_changed = self._tts_controller.current_level != previous_level
                # Consume the threshold even at L2, so later turns cannot
                # repeatedly re-trigger the same automatic event.
                self._comprehension_turns.clear()
        else:
            self._tts_controller.handle_intent(command.intent)
        result = OrderResult(
            success=True,
            cart=cart.copy(),
            response_text=self._last_response,
        )
        return self._synthesize_result(result, remember_response=False)

    def _record_successful_semantic_turn(self) -> None:
        """Advance only after NLU yielded a validated intent, never on failure."""
        self._successful_semantic_turn += 1
        minimum_turn = self._successful_semantic_turn - self._COMPREHENSION_WINDOW_TURNS + 1
        while self._comprehension_turns and self._comprehension_turns[0] < minimum_turn:
            self._comprehension_turns.popleft()

    def transcribe_audio(self, audio: bytes) -> STTResult:
        """오디오를 STT로만 변환한다(NLU·Order Engine·TTS 실행 없음). 데모/검증용."""
        if self._stt is None:
            raise STTFailure("STT 어댑터가 설정되지 않았습니다.")
        with self._stt_lock:
            raw_stt = self._stt.transcribe(audio)
        if isinstance(raw_stt, str):
            return STTResult(text=raw_stt)
        if isinstance(raw_stt, STTResult):
            return raw_stt
        return STTResult(text=str(raw_stt))

    def handle_audio(self, audio: bytes, cart: Cart) -> VoiceInteractionResult:
        """오디오 입력을 받아 STT -> NLU -> Order Engine -> Adaptive TTS 전체 파이프라인을 실행한다."""
        self._last_tts_result = None
        self._last_tts_output_text = None
        self._last_order_commands = []
        self._last_comprehension_signal = False
        self._last_auto_speed_changed = False
        e2e_start = time.perf_counter()
        cart_before = cart.copy()

        if self._stt is None:
            raise STTFailure("STT 어댑터가 설정되지 않았습니다.")
        if not audio:
            err = get_default_error_response(ErrorCode.EMPTY_INPUT)
            stt_res = STTResult(text="", confidence=0.0, duration_ms=0.0, is_final=True)
            order_res = OrderResult(
                False,
                cart.copy(),
                err.user_message,
                err.error_code,
                error_response=err,
            )
            tts_start = time.perf_counter()
            order_res = self._synthesize_result(order_res, remember_response=True)
            tts_ms = (time.perf_counter() - tts_start) * 1000
            self._log_interaction(
                SessionLogEventType.ERROR_RECOVERY,
                text=None,
                order_result=order_res,
                latencies_ms=(0.0, 0.0, 0.0, tts_ms, (time.perf_counter() - e2e_start) * 1000),
                audio_duration_ms=stt_res.duration_ms,
                stt_confidence=stt_res.confidence,
                cart_before=cart_before,
            )
            return VoiceInteractionResult(
                stt_result=stt_res,
                order_result=order_res,
                tts_result=self._last_tts_result,
                tts_latency_ms=tts_ms,
                total_e2e_latency_ms=(time.perf_counter() - e2e_start) * 1000,
            )

        stt_start = time.perf_counter()
        try:
            with self._stt_lock:
                raw_stt = self._stt.transcribe(audio)
            if isinstance(raw_stt, str):
                stt_res = STTResult(text=raw_stt)
            elif isinstance(raw_stt, STTResult):
                stt_res = raw_stt
            else:
                stt_res = STTResult(text=str(raw_stt))
            validate_stt_result(stt_res)
        except STTFailure:
            err = create_error_response(
                ErrorCode.UNSUPPORTED_UTTERANCE,
                module=ErrorModule.STT,
                user_message="음성을 인식하지 못했습니다. 다시 말씀해 주세요.",
                retryable=True,
            )
            stt_res = STTResult(text="", confidence=0.0, duration_ms=0.0, is_final=True)
            order_res = OrderResult(
                False,
                cart.copy(),
                err.user_message,
                err.error_code,
                error_response=err,
            )
            tts_start = time.perf_counter()
            order_res = self._synthesize_result(order_res, remember_response=True)
            tts_ms = (time.perf_counter() - tts_start) * 1000
            self._log_interaction(
                SessionLogEventType.ERROR_RECOVERY,
                text=None,
                order_result=order_res,
                latencies_ms=((time.perf_counter() - stt_start) * 1000, 0.0, 0.0, tts_ms, (time.perf_counter() - e2e_start) * 1000),
                audio_duration_ms=stt_res.duration_ms,
                stt_confidence=stt_res.confidence,
                cart_before=cart_before,
            )
            return VoiceInteractionResult(
                stt_result=stt_res,
                order_result=order_res,
                tts_result=self._last_tts_result,
                stt_latency_ms=(time.perf_counter() - stt_start) * 1000,
                tts_latency_ms=tts_ms,
                total_e2e_latency_ms=(time.perf_counter() - e2e_start) * 1000,
            )
        stt_ms = (time.perf_counter() - stt_start) * 1000

        if not self._is_sane_transcript(stt_res.text):
            err = create_error_response(
                ErrorCode.UNSUPPORTED_UTTERANCE,
                module=ErrorModule.STT,
                user_message="잘 듣지 못했습니다. 다시 말씀해 주세요.",
                retryable=True,
            )
            order_res = OrderResult(
                False, cart.copy(), err.user_message, err.error_code, error_response=err,
            )
            tts_start = time.perf_counter()
            order_res = self._synthesize_result(order_res, remember_response=True)
            tts_ms = (time.perf_counter() - tts_start) * 1000
            total_e2e_ms = (time.perf_counter() - e2e_start) * 1000
            logger.info(
                "audio pipeline rejected transcript=%r confidence=%s commands=%s error_code=%s reason=transcript_sanity",
                stt_res.text, stt_res.confidence, None, order_res.error_code,
            )
            self._log_interaction(
                SessionLogEventType.ERROR_RECOVERY,
                text=stt_res.text,
                order_result=order_res,
                latencies_ms=(stt_ms, 0.0, 0.0, tts_ms, total_e2e_ms),
                audio_duration_ms=stt_res.duration_ms,
                stt_confidence=stt_res.confidence,
                cart_before=cart_before,
            )
            return VoiceInteractionResult(
                stt_result=stt_res,
                order_result=order_res,
                tts_result=self._last_tts_result,
                stt_latency_ms=stt_ms,
                tts_latency_ms=tts_ms,
                total_e2e_latency_ms=total_e2e_ms,
            )

        order_res, nlu_ms, agent_ms, tts_ms, commands = self._handle_text_with_timing(
            stt_res.text, cart,
        )
        self._last_order_commands = list(commands or [])
        logger.info("audio pipeline transcript=%r confidence=%s commands=%s error_code=%s", stt_res.text, stt_res.confidence, [command.to_dict() for command in commands] if commands else None, order_res.error_code)
        total_e2e_ms = (time.perf_counter() - e2e_start) * 1000
        event_type = (
            SessionLogEventType.TTS_SPEED_CONTROL
            if (commands and commands[0].intent in self._TTS_CONTROL_INTENTS)
            else (
                SessionLogEventType.ERROR_RECOVERY
                if not order_res.success
                else SessionLogEventType.ORDER_INTERACTION
            )
        )
        self._log_interaction(
            event_type,
            text=stt_res.text,
            order_result=order_res,
            commands=commands,
            latencies_ms=(stt_ms, nlu_ms, agent_ms, tts_ms, total_e2e_ms),
            audio_duration_ms=stt_res.duration_ms,
            stt_confidence=stt_res.confidence,
            cart_before=cart_before,
        )
        return VoiceInteractionResult(
            stt_result=stt_res,
            order_result=order_res,
            tts_result=self._last_tts_result,
            stt_latency_ms=stt_ms,
            nlu_latency_ms=nlu_ms,
            agent_latency_ms=agent_ms,
            tts_latency_ms=tts_ms,
            total_e2e_latency_ms=total_e2e_ms,
        )

    @staticmethod
    def _is_sane_transcript(text: str) -> bool:
        """Reject noise-like STT hallucinations before they reach NLU.

        Confidence is deliberately not used: repeated or nearly empty content can
        still be returned with a high model confidence.
        """
        normalized = re.sub(r"[^가-힣A-Za-z0-9]+", " ", text).strip()
        compact = normalized.replace(" ", "")
        if len(compact) < 2:
            return False
        words = normalized.split()
        if len(words) >= 4 and max(Counter(words).values()) / len(words) >= 0.6:
            return False
        # Whisper noise hallucinations can arrive without spaces, e.g. 마치마치마치.
        for period in range(1, len(compact) // 2 + 1):
            if len(compact) // period >= 3 and len(compact) % period == 0:
                if compact == compact[:period] * (len(compact) // period):
                    return False
        for width in (1, 2, 3):
            grams = [compact[index:index + width] for index in range(len(compact) - width + 1)]
            if len(grams) >= 4 and max(Counter(grams).values()) / len(grams) >= 0.6:
                return False
        return True

    def _synthesize_result(
        self,
        result: OrderResult,
        *,
        remember_response: bool,
    ) -> OrderResult:
        if remember_response:
            self._last_response = result.response_text
        level = self._tts_controller.current_level
        tts_text = AdaptiveTextTransformer.transform(result.response_text, level)
        self._last_tts_output_text = tts_text
        try:
            tts_res = self._tts.synthesize(tts_text, level=level)
            if isinstance(tts_res, TTSResult):
                self._last_tts_result = tts_res
            else:
                self._last_tts_result = None
        except TTSFailure:
            self._last_tts_result = None
            err = get_default_error_response(ErrorCode.TTS_FAILED)
            return OrderResult(
                False,
                result.cart,
                result.response_text,
                ErrorCode.TTS_FAILED,
                error_response=err,
            )
        return result

    @staticmethod
    def _nlu_error_result(error: OrderCommandError, cart: Cart) -> OrderResult:
        error_code = ErrorCode(error.code.value)
        user_message = (
            MIXED_INTENT_USER_MESSAGE
            if error_code is ErrorCode.MIXED_INTENT
            else error.message
        )
        if user_message == "지원하지 않는 주문입니다.":
            user_message = "잘 이해하지 못했어요. 다시 말씀해 주세요."
        details = {
            "command_index": error.command_index,
            "field": error.field,
            "candidates": list(error.candidates) if error.candidates else None,
        }
        err = create_error_response(
            error_code,
            module=ErrorModule.NLU,
            user_message=user_message,
            retryable=error.retryable,
            details=details,
        )
        return OrderResult(
            False,
            cart.copy(),
            user_message,
            error_code,
            error_response=err,
        )
