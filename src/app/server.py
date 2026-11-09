from __future__ import annotations

import argparse
import base64
import json
import logging
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from urllib.parse import urlparse

_SRC_DIR = str(Path(__file__).resolve().parents[1])
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from app.service import MalloService, build_mock_service, build_service
from adapters.logging.file_interaction_logger import FileInteractionLogger
from config.settings import load_menu
from domain.intents import Intent
from domain.adaptive_response_realizer import AdaptiveResponseRealizer, RealizedResponse
from domain.models import (
    BeverageOptions,
    Cart,
    CartItem,
    FulfillmentType,
    OrderCommand,
    Temperature,
)
from domain.text_transformer import AdaptiveTextTransformer
from domain.voice_interaction import VoiceInteractionResult
from interfaces.stt import STTFailure

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SidecarGatewayConfig:
    """Gateway가 외부에 노출할 sidecar proxy/health 경로."""

    stt_url: str = "http://127.0.0.1:8001/transcribe"
    nlu_url: str = "http://127.0.0.1:8002/parse"
    tts_url: str = "http://127.0.0.1:8003/synthesize"
    timeout: int = 120

    @property
    def health_urls(self) -> dict[str, str]:
        return {
            "stt": self.stt_url.rsplit("/", 1)[0] + "/health",
            "nlu": self.nlu_url.rsplit("/", 1)[0] + "/health",
            "tts": self.tts_url.rsplit("/", 1)[0] + "/health",
        }

_TTS_CONTROL_PHRASES = {
    "REQUEST_REPEAT": "다시 말해 주세요",
    "REQUEST_SLOWER": "천천히 말해 주세요",
    "REQUEST_DEFAULT_SPEED": "기본 속도로 말해 주세요",
}

_SYSTEM_MESSAGES = {
    "WELCOME": ("어서오세요. 말로 카페입니다.", False),
    "SERVICE_MODE": ("어떻게 이용하시겠어요? 매장 이용 또는 포장을 선택해 주세요.", True),
    "ORDER": ("원하시는 메뉴를 말씀해 주세요.", True),
    "ORDER_REVIEW": ("주문 내용을 확인해 주세요.", True),
    "PAYMENT": ("결제 방법을 선택해 주세요.", True),
    "COMPLETE": ("주문이 완료되었습니다.", False),
    "STAFF": ("직원을 호출했습니다. 잠시만 기다려 주세요.", False),
    "RECEIPT": ("영수증을 출력하고 있습니다.", False),
    "PAYMENT_EMPTY_CART": ("장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.", False),
    "PAYMENT_FULFILLMENT_REQUIRED": ("매장 이용 또는 포장을 먼저 선택해 주세요.", False),
    "PAYMENT_CONFIRMATION_REQUIRED": ("주문을 먼저 확정해 주세요.", False),
    "HOME_CONFIRM": ("주문을 취소하고 처음으로 돌아갈까요? 담아둔 메뉴가 모두 사라집니다.", False),
}


_PREDEFINED_SEGMENTS: dict[str, list[str]] = {
    "SERVICE_MODE": [
        "어떻게 이용하시겠어요?",
        "매장 이용 또는 포장을 선택해 주세요.",
    ],
    "어떻게 이용하시겠어요? 매장 이용 또는 포장을 선택해 주세요.": [
        "어떻게 이용하시겠어요?",
        "매장 이용 또는 포장을 선택해 주세요.",
    ],
    "커피 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, 바닐라라떼 3,400원입니다. 논커피 메뉴는 자몽에이드 3,500원, 말차라떼 3,500원입니다. 티 메뉴는 밀크티 3,500원, 캐모마일티 3,700원, 아이스티 4,700원입니다. 디저트 메뉴는 크로플 아이스크림 5,500원, 바스크 치즈 케이크 6,500원입니다.": [
        "커피 메뉴는 아메리카노 4,700원,",
        "카페라떼 5,200원, 바닐라라떼 3,400원입니다.",
        "논커피 메뉴는 자몽에이드 3,500원,",
        "말차라떼 3,500원입니다.",
        "티 메뉴는 밀크티 3,500원,",
        "캐모마일티 3,700원, 아이스티 4,700원입니다.",
        "디저트 메뉴는 크로플 아이스크림 5,500원,",
        "바스크 치즈 케이크 6,500원입니다.",
    ],
    "커피 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, 바닐라라떼 3,400원입니다.": [
        "커피 메뉴는 아메리카노 4,700원,",
        "카페라떼 5,200원, 바닐라라떼 3,400원입니다.",
    ],
    "논커피 메뉴는 자몽에이드 3,500원, 말차라떼 3,500원입니다.": [
        "논커피 메뉴는 자몽에이드 3,500원,",
        "말차라떼 3,500원입니다.",
    ],
    "티 메뉴는 밀크티 3,500원, 캐모마일티 3,700원, 아이스티 4,700원입니다.": [
        "티 메뉴는 밀크티 3,500원,",
        "캐모마일티 3,700원, 아이스티 4,700원입니다.",
    ],
    "디저트 메뉴는 크로플 아이스크림 5,500원, 바스크 치즈 케이크 6,500원입니다.": [
        "디저트 메뉴는 크로플 아이스크림 5,500원,",
        "바스크 치즈 케이크 6,500원입니다.",
    ],
    "포장 주문입니다. 총 결제 금액은 4,700원입니다. 결제를 진행해 주세요.": [
        "포장 주문입니다.",
        "총 결제 금액은 4,700원입니다.",
        "결제를 진행해 주세요.",
    ],
    "매장 주문입니다. 총 결제 금액은 4,700원입니다. 결제를 진행해 주세요.": [
        "매장 주문입니다.",
        "총 결제 금액은 4,700원입니다.",
        "결제를 진행해 주세요.",
    ],
    "주문을 취소하고 처음으로 돌아갈까요? 담아둔 메뉴가 모두 사라집니다.": [
        "주문을 취소하고 처음으로 돌아갈까요?",
        "담아둔 메뉴가 모두 사라집니다.",
    ],
    "HOME_CONFIRM": [
        "주문을 취소하고 처음으로 돌아갈까요?",
        "담아둔 메뉴가 모두 사라집니다.",
    ],
    "아이스 아메리카노를 장바구니에 담았습니다. 무엇을 더 주문하시겠어요?": [
        "아이스 아메리카노를 장바구니에 담았습니다.",
        "무엇을 더 주문하시겠어요?",
    ],
    "잘 이해하지 못했어요. 화면에서 메뉴를 선택하시거나 직원을 불러드릴 수 있습니다.": [
        "잘 이해하지 못했어요.",
        "화면에서 메뉴를 선택하시거나 직원을 불러드릴 수 있습니다.",
    ],
}


class _SessionApp:
    """백엔드 파이프라인을 Web/GUI 요청에 연결하는 어댑터.

    이 객체 하나가 한 브라우저 세션의 mutable 주문/대화 상태만 보유한다.
    """

    def __init__(self, service: MalloService) -> None:
        self._service = service
        self._menu_by_id = {item.id: item for item in load_menu()}
        self._cart = Cart()
        self._consecutive_failures = 0
        # This is the canonical source for server-side repeat.  It is updated
        # only by actual conversational/system messages, never speed previews.
        self._last_replayable_text: str | None = None
        self._last_replayable_message_id: str | None = None
        self._last_replayable_result = None
        self._last_replayable_commands: tuple[OrderCommand, ...] = ()
        self._response_realizer = AdaptiveResponseRealizer(self._menu_by_id)

    def _display_segments(self, text: str, message_id: str | None = None) -> list[str]:
        """Response Bar 전용 canonical display segments.

        TTS chunk 수와 무관하게 항상 전체 목록을 보존한다.
        """
        segments = _PREDEFINED_SEGMENTS.get(message_id or "") or _PREDEFINED_SEGMENTS.get(text)
        if segments:
            return list(segments)
        if len(text) > 36 and any(sep in text for sep in (". ", "? ", "! ", ", ")):
            import re
            parts = [p.strip() for p in re.split(r"(?<=[.?!,])\s+", text) if p.strip()]
            if len(parts) > 1:
                return parts
        return [text]

    def _synthesize_segments(self, text: str, message_id: str | None = None, level: int | None = None, display_segments: list[str] | tuple[str, ...] | None = None) -> list[dict]:
        tts_level = self._service.tts_level if level is None else level
        gap_ms = AdaptiveTextTransformer.get_gap_ms(tts_level)
        display_segs = list(display_segments) if display_segments else self._display_segments(text, message_id)
        tts_chunks = (
            [AdaptiveTextTransformer.transform_to_chunks(segment, level=0)[0] for segment in display_segs]
            if tts_level == 0
            else AdaptiveTextTransformer.transform_to_chunks(text, level=tts_level)
        )
        if not tts_chunks:
            tts_chunks = [AdaptiveTextTransformer.transform_to_chunks(text, level=0)[0]]

        # Numeric TTS normalization means source lookup must compare normalized
        # strings. The cursor keeps mapping stable when two chunks share words.
        normalized_segments = [
            AdaptiveTextTransformer.transform_to_chunks(segment, level=0)[0]
            for segment in display_segs
        ]
        spans: list[tuple[int, int]] = []
        cursor = 0
        for segment in normalized_segments:
            spans.append((cursor, cursor + len(segment)))
            cursor += len(segment) + 1
        normalized_text = " ".join(normalized_segments)
        source_cursor = 0
        result_chunks = []
        for c_idx, c_text in enumerate(tts_chunks):
            start = normalized_text.find(c_text, source_cursor)
            if start < 0:
                start = source_cursor
            source_cursor = max(source_cursor, start + len(c_text))
            segment_index = next(
                (idx for idx, (left, right) in enumerate(spans) if left <= start < right),
                len(display_segs) - 1,
            )
            audio = None
            if c_idx == 0:
                tts_res = self._service.synthesize_message_at_level(c_text, level=tts_level)
                audio = self._encode_tts_audio(tts_res)
            result_chunks.append({
                "chunk_id": f"{message_id or 'message'}:{c_idx}",
                "chunk_index": c_idx,
                "segment_index": segment_index,
                "text": c_text,
                "display_text": display_segs[segment_index],
                "tts_text": c_text,
                "synthesis_text": c_text,
                "tts_audio_base64": audio,
                "gap_ms": gap_ms,
            })
        return result_chunks

    @property
    def service(self) -> MalloService:
        return self._service

    def handle_text(self, text: str, level: int | None = None) -> dict:
        result = self._service.handle_text(text, self._cart)
        self._cart = result.cart
        self._consecutive_failures = 0 if result.success else self._consecutive_failures + 1
        tts_level = self._service.tts_level if level is None else level
        payload = self._order_payload(result, level=tts_level)
        if not result.success and self._consecutive_failures >= 2:
            message = "잘 이해하지 못했어요. 화면에서 메뉴를 선택하시거나 직원을 불러드릴 수 있습니다."
            tts_result = self._service.synthesize_message(message)
            payload["response_text"] = message
            payload["display_segments"] = self._display_segments(message)
            payload["tts_audio_base64"] = self._encode_tts_audio(tts_result)
            payload["tts_segments"] = self._synthesize_segments(message)
            payload["response_required"] = False
            payload["next_listening_mode"] = None
        return payload

    def handle_audio(self, audio: bytes) -> dict:
        result = self._service.handle_audio(audio, self._cart)
        self._cart = result.order_result.cart
        logger.info("audio result transcript=%r confidence=%s error_code=%s", result.stt_result.text, result.stt_result.confidence, result.order_result.error_code)
        return self._voice_payload(result)

    def handle_commands(self, payloads: list[object]) -> dict:
        try:
            commands = [OrderCommand.from_nlu_payload(value) for value in payloads if isinstance(value, dict)]
            if len(commands) != len(payloads): raise ValueError
        except (TypeError, ValueError):
            return {"success": False, "response_text": "주문 형식을 확인할 수 없습니다.", "cart": self._cart_payload(self._cart)}
        result = self._service.handle_commands(commands, self._cart)
        self._cart = result.cart
        return self._order_payload(result, level=self._service.tts_level)

    def select_fulfillment(self, fulfillment_type: str) -> dict:
        try:
            cart = self._service.start_order(fulfillment_type)
        except (TypeError, ValueError):
            return {
                "success": False,
                "error": "unknown fulfillment type",
                "cart": self._cart_payload(self._cart),
            }
        self._cart = cart
        message = self.system_message("ORDER")
        return {
            "success": True,
            "cart": self._cart_payload(self._cart),
            **message,
        }

    def order(self, text: str) -> dict:
        result = self._service.handle_text(text, self._cart)
        self._cart = result.cart
        return self._order_payload(result, level=self._service.tts_level)

    def synthesize_tts(self, text: str, level: int | None = None, already_chunked: bool = False) -> dict:
        tts_level = self._service.tts_level if level is None else level
        transformed = text if already_chunked else AdaptiveTextTransformer.transform(text, level=tts_level)
        tts_result = self._service.synthesize_message_at_level(transformed, level=tts_level)
        audio = self._encode_tts_audio(tts_result)
        gap_ms = AdaptiveTextTransformer.get_gap_ms(tts_level)
        return {
            "success": bool(audio),
            "text": text,
            "tts_text": transformed,
            "synthesis_text": transformed,
            "tts_level": tts_level,
            "tts_audio_base64": audio,
            "gap_ms": gap_ms,
        }

    def system_message(self, message_id: str, *, remember_for_repeat: bool = True) -> dict:
        definition = _SYSTEM_MESSAGES.get(message_id)
        if definition is None:
            return {"error": "unknown system message"}
        text, response_required = definition
        if remember_for_repeat:
            self._last_replayable_text = text
            self._last_replayable_message_id = message_id
            self._last_replayable_result = None
            self._last_replayable_commands = ()
            self._service.remember_replayable_response(text)
        logger.info("[System message] synthesis start message_id=%s text=%r", message_id, text)
        segments = self._synthesize_segments(text, message_id=message_id)
        if segments and segments[0]["tts_audio_base64"]:
            audio = segments[0]["tts_audio_base64"]
        else:
            tts_result = self._service.synthesize_message(text)
            audio = self._encode_tts_audio(tts_result)
        gap_ms = AdaptiveTextTransformer.get_gap_ms(self._service.tts_level)
        logger.info(
            "[System message] synthesis completed message_id=%s has_audio=%s audio_base64_length=%d segments_count=%d",
            message_id, bool(audio), len(audio or ""), len(segments),
        )
        return {
            "message_id": message_id,
            "response_text": text,
            "display_segments": self._display_segments(text, message_id),
            "tts_level": self._service.tts_level,
            "tts_audio_base64": audio,
            "tts_segments": segments,
            "gap_ms": gap_ms,
            "response_required": response_required,
            "next_listening_mode": (
                "SYSTEM_PROMPTED" if response_required else None
            ),
        }

    def accessibility_action(
        self,
        action: str,
        level: int | None = None,
        replay_source: dict | None = None,
    ) -> dict:
        segments = []
        if action == "REPEAT":
            # Never fall back to pipeline/session-state ``last_response``:
            # it can still hold a legacy bootstrap greeting. A repeat has one
            # source only: the last replayable canonical message.
            source_message_id = self._last_replayable_message_id
            text = self._last_replayable_text
            if isinstance(replay_source, dict):
                candidate_id = replay_source.get("message_id")
                candidate_text = replay_source.get("response_text")
                definition = _SYSTEM_MESSAGES.get(candidate_id)
                # A fixed system message may safely recover after server-side
                # session loss, but only when its canonical text matches.
                if definition and candidate_text == definition[0]:
                    source_message_id = candidate_id
                    text = definition[0]
            if not text:
                return {"error": "no replayable message"}
            tts_level = self._service.tts_level if level is None else level
            if level is not None and level != self._service.tts_level:
                self._service.set_tts_level(level)
                tts_level = level
            realized = None
            if self._last_replayable_result is not None:
                realized = self._response_realizer.realize(
                    self._last_replayable_result,
                    self._last_replayable_commands,
                    level=tts_level,
                )
                text = realized.text
            segments = self._synthesize_segments(
                text,
                message_id=source_message_id,
                level=tts_level,
                display_segments=(realized.display_segments if realized else None),
            )
            if segments and segments[0]["tts_audio_base64"]:
                audio = segments[0]["tts_audio_base64"]
            else:
                transformed = AdaptiveTextTransformer.transform(text, level=tts_level)
                tts_result = self._service.synthesize_message_at_level(transformed, level=tts_level)
                audio = self._encode_tts_audio(tts_result)
        elif action == "CYCLE_SPEED":
            text = "이 속도로 안내합니다."
            tts_result = self._service.cycle_tts_level()
            audio = self._encode_tts_audio(tts_result)
        elif action in ("SET_SPEED_0", "SET_SPEED_1", "SET_SPEED_2"):
            text = "이 속도로 안내합니다."
            target_level = int(action[-1])
            tts_result = self._service.set_tts_level(target_level)
            audio = self._encode_tts_audio(tts_result)
        elif action == "CALL_STAFF":
            return self.system_message("STAFF", remember_for_repeat=False)
        elif action == "RECEIPT":
            return self.system_message("RECEIPT")
        else:
            return {"error": "unknown accessibility action"}
        gap_ms = AdaptiveTextTransformer.get_gap_ms(self._service.tts_level)
        return {
            "message_id": source_message_id if action == "REPEAT" else None,
            "response_text": text,
            "display_segments": (
                list(realized.display_segments)
                if action == "REPEAT" and realized and realized.display_segments
                else self._display_segments(text, source_message_id if action == "REPEAT" else None)
            ),
            "tts_level": self._service.tts_level,
            "tts_audio_base64": audio,
            "tts_segments": segments,
            "gap_ms": gap_ms,
            "response_required": False,
            "next_listening_mode": None,
        }

    def transcribe(self, audio: bytes) -> dict:
        try:
            result = self._service.transcribe(audio)
        except STTFailure as error:
            return {"error": str(error), "received_bytes": len(audio)}
        return {
            "text": result.text,
            "confidence": result.confidence,
            "alternatives": list(result.alternatives or ()),
            "latency_ms": result.duration_ms,
            "received_bytes": len(audio),
        }

    def interpret_audio_transcript(self, transcript: str) -> dict:
        """Continue a browser-obtained STT turn through server-side NLU and engine."""
        t0 = time.perf_counter()
        result = self._service.interpret_voice_transcript(transcript, self._cart)
        t_nlu = time.perf_counter()
        self._cart = result.cart
        voice_fulfillment_prompt = self._voice_fulfillment_prompt(result)
        if voice_fulfillment_prompt is not None:
            self._service.synthesize_message(voice_fulfillment_prompt)
        payload = self._order_payload(result, level=self._service.tts_level)
        if voice_fulfillment_prompt is not None:
            payload["response_text"] = voice_fulfillment_prompt
            payload["display_segments"] = self._display_segments(voice_fulfillment_prompt)
            payload["tts_segments"] = self._synthesize_segments(
                voice_fulfillment_prompt, level=self._service.tts_level,
            )
            payload["tts_audio_base64"] = (
                payload["tts_segments"][0]["tts_audio_base64"]
                if payload["tts_segments"] else None
            )
        t_end = time.perf_counter()
        logger.info(
            "[Voice Interpret Timing] transcript=%r nlu_engine_ms=%.1f s1_synthesis_ms=%.1f total_interpret_ms=%.1f segments_count=%d",
            transcript, (t_nlu - t0) * 1000, (t_end - t_nlu) * 1000, (t_end - t0) * 1000, len(payload.get("tts_segments") or []),
        )
        return payload

    def _voice_fulfillment_prompt(self, result) -> str | None:
        """Keep touch fulfillment feedback unchanged while continuing a voice turn."""
        commands = self._service.last_order_commands
        if (
            not result.success
            or len(commands) != 1
            or commands[0].intent is not Intent.SET_FULFILLMENT
        ):
            return None
        label = {
            FulfillmentType.DINE_IN: "매장",
            FulfillmentType.TAKEOUT: "포장",
        }.get(commands[0].fulfillment_type)
        return f"{label}으로 설정했습니다. 원하시는 메뉴 있으신가요?" if label else None

    def tts_control(self, intent: str) -> dict:
        phrase = _TTS_CONTROL_PHRASES.get(intent, _TTS_CONTROL_PHRASES["REQUEST_REPEAT"])
        result = self._service.handle_text(phrase, self._cart)
        self._cart = result.cart
        return self._order_payload(
            result,
            level=self._service.tts_level,
            response_required=False,
        )

    def reset(self) -> dict:
        self._service.reset_session()
        self._cart = Cart()
        self._consecutive_failures = 0
        self._last_replayable_text = None
        self._last_replayable_message_id = None
        self._last_replayable_result = None
        self._last_replayable_commands = ()
        return {"status": "reset"}

    def session_handoff(self, payload: dict) -> dict:
        """Synchronize a local touch order cart into the server session."""
        if not isinstance(payload, dict):
            return {
                "success": False,
                "error": "invalid_payload",
                "message": "Payload must be a JSON object",
            }

        # 1. Validate fulfillment_type
        raw_fulfillment = payload.get("fulfillment_type")
        fulfillment_type: FulfillmentType | None = None
        if raw_fulfillment:
            try:
                fulfillment_type = FulfillmentType(raw_fulfillment)
            except ValueError:
                return {
                    "success": False,
                    "error": "invalid_fulfillment_type",
                    "message": f"Unknown fulfillment type: {raw_fulfillment}",
                }

        # 2. Validate items
        raw_items = payload.get("items")
        if raw_items is not None and not isinstance(raw_items, list):
            return {
                "success": False,
                "error": "invalid_items",
                "message": "items must be a list",
            }

        reconstructed_items: list[CartItem] = []
        for raw_item in raw_items or []:
            if not isinstance(raw_item, dict):
                return {
                    "success": False,
                    "error": "invalid_item",
                    "message": "Each item must be an object",
                }
            menu_id = raw_item.get("menu_id")
            if not menu_id or menu_id not in self._menu_by_id:
                return {
                    "success": False,
                    "error": "invalid_menu_id",
                    "message": f"Menu item not found: {menu_id}",
                }

            menu_item = self._menu_by_id[menu_id]

            # Validate quantity
            try:
                quantity = int(raw_item.get("quantity", 1))
                if quantity <= 0 or quantity > 99:
                    raise ValueError
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "error": "invalid_quantity",
                    "message": f"Invalid quantity for {menu_id}",
                }

            # Validate temperature
            raw_temp = raw_item.get("temperature")
            temperature: Temperature | None = None
            if raw_temp:
                try:
                    temperature = Temperature(raw_temp)
                except ValueError:
                    return {
                        "success": False,
                        "error": "invalid_temperature",
                        "message": f"Invalid temperature for {menu_id}",
                    }
            elif menu_item.temperature_options:
                temperature = menu_item.temperature_options[0]

            # If item has temperature options, check if chosen temp is valid
            if (
                menu_item.temperature_options
                and temperature not in menu_item.temperature_options
            ):
                return {
                    "success": False,
                    "error": "unsupported_temperature",
                    "message": f"{temperature.value if temperature else 'None'} not available for {menu_id}",
                }

            # Validate options
            raw_options = raw_item.get("options")
            options = BeverageOptions()
            if isinstance(raw_options, dict):
                try:
                    options = BeverageOptions.from_mapping(raw_options)
                except (ValueError, TypeError):
                    options = BeverageOptions()

            # Reconstruct unit price from menu definition!
            unit_price = menu_item.base_price
            reconstructed_items.append(
                CartItem(
                    menu_id=menu_id,
                    quantity=quantity,
                    temperature=temperature,
                    unit_price=unit_price,
                    options=options,
                )
            )

        # 3. Construct new Cart
        confirmed = bool(payload.get("confirmed", False))
        reconstructed_cart = Cart(
            items=reconstructed_items,
            fulfillment_type=fulfillment_type,
            confirmed=confirmed,
        )

        # 4. Save to session
        self._cart = reconstructed_cart

        logger.info(
            "session handoff completed items_count=%d total_price=%d fulfillment=%s confirmed=%s",
            len(reconstructed_cart.items),
            reconstructed_cart.total_price,
            reconstructed_cart.fulfillment_type,
            reconstructed_cart.confirmed,
        )

        return {
            "success": True,
            "cart": self._cart_payload(self._cart),
            "response_text": "",
            "response_required": False,
            "next_listening_mode": None,
            "tts_audio_base64": None,
            "tts_level": self._service.tts_level,
        }

    def state(self) -> dict:
        return {
            "tts_level": self._service.tts_level,
            "last_response": self._service.last_response,
            "cart": self._cart_payload(self._cart),
        }

    def _cart_payload(self, cart: Cart) -> dict:
        return {
            "fulfillment_type": (
                cart.fulfillment_type.value
                if cart.fulfillment_type is not None
                else None
            ),
            "total_price": cart.total_price,
            "confirmed": cart.confirmed,
            "items": [
                {
                    "menu_id": item.menu_id,
                    "name": (
                        self._menu_by_id[item.menu_id].name
                        if item.menu_id in self._menu_by_id
                        else item.menu_id
                    ),
                    "temperature": (
                        item.temperature.value if item.temperature is not None else None
                    ),
                    "quantity": item.quantity,
                    "options": item.options.to_dict(),
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                }
                for item in cart.items
            ],
        }

    @staticmethod
    def _listening_contract(result, response_required: bool | None = None) -> dict:
        required = True if response_required is None else response_required
        return {
            "response_required": required,
            "next_listening_mode": "SYSTEM_PROMPTED" if required else None,
        }

    def _order_payload(
        self,
        result,
        *,
        level: int,
        response_required: bool | None = None,
    ) -> dict:
        realized = self._response_realizer.realize(
            result, self._service.last_order_commands, level=level,
        )
        self._last_replayable_text = realized.text
        self._last_replayable_message_id = None
        self._last_replayable_result = result
        self._last_replayable_commands = tuple(self._service.last_order_commands)
        display_segments = list(realized.display_segments) if realized.display_segments else self._display_segments(realized.text)
        segments = self._synthesize_segments(
            realized.text, level=level, display_segments=display_segments,
        )
        audio = segments[0]["tts_audio_base64"] if segments else self._encode_tts_audio(self._service.last_tts_result)
        payload = {
            "success": result.success,
            "response_text": realized.text,
            "display_segments": display_segments,
            "error_code": (
                result.error_code.value if result.error_code is not None else None
            ),
            "tts_level": level,
            "gap_ms": AdaptiveTextTransformer.get_gap_ms(level),
            "order_commands": [
                command.to_dict() for command in self._service.last_order_commands
            ],
            "cart": self._cart_payload(result.cart),
            "tts_audio_base64": audio,
            "tts_segments": segments,
            **self._listening_contract(result, response_required),
        }
        if self._service.last_auto_speed_changed:
            # The notice is a presentation prefix only.  The body remains the
            # canonical replayable response and is synthesized at the newly
            # selected level.
            notice = self._service.auto_slower_notice
            payload["speech_prefix"] = {
                "response_text": notice,
                "display_segments": [notice],
                "tts_level": level,
                "tts_audio_base64": None,
                "tts_segments": self._synthesize_segments(notice, level=level),
                "gap_ms": AdaptiveTextTransformer.get_gap_ms(level),
            }
        return payload

    @staticmethod
    def _encode_tts_audio(tts_result) -> str | None:
        if tts_result is None or tts_result.audio is None:
            return None
        return base64.b64encode(tts_result.audio).decode("ascii")

    def _voice_payload(self, result: VoiceInteractionResult) -> dict:
        order = result.order_result
        audio_b64 = self._encode_tts_audio(result.tts_result)
        realized = self._response_realizer.realize(
            order, self._service.last_order_commands, level=self._service.tts_level,
        )
        self._last_replayable_text = realized.text
        self._last_replayable_message_id = None
        self._last_replayable_result = order
        self._last_replayable_commands = tuple(self._service.last_order_commands)
        display_segments = list(realized.display_segments) if realized.display_segments else self._display_segments(realized.text)
        segments = self._synthesize_segments(
            realized.text, level=self._service.tts_level, display_segments=display_segments,
        )
        return {
            "success": order.success,
            "response_text": realized.text,
            "display_segments": display_segments,
            "error_code": (
                order.error_code.value if order.error_code is not None else None
            ),
            "transcript": result.stt_result.text,
            "confidence": result.stt_result.confidence,
            "tts_level": self._service.tts_level,
            "gap_ms": AdaptiveTextTransformer.get_gap_ms(self._service.tts_level),
            "order_commands": [
                command.to_dict() for command in self._service.last_order_commands
            ],
            "cart": self._cart_payload(order.cart),
            "latencies_ms": {
                "stt": round(result.stt_latency_ms, 1),
                "nlu": round(result.nlu_latency_ms, 1),
                "agent": round(result.agent_latency_ms, 1),
                "tts": round(result.tts_latency_ms, 1),
                "total_e2e": round(result.total_e2e_latency_ms, 1),
            },
            "tts_audio_base64": segments[0]["tts_audio_base64"] if segments else audio_b64,
            "tts_segments": segments,
            **self._listening_contract(order),
        }


@dataclass
class SessionContext:
    app: _SessionApp
    lock: threading.RLock
    last_accessed: float


class SessionManager:
    """Owns per-browser mutable state; shared model HTTP adapters stay outside it."""

    LEGACY_SESSION_ID = "__legacy_no_header__"

    def __init__(self, service: MalloService, *, idle_ttl_seconds: int = 3600) -> None:
        self._service = service
        self._idle_ttl_seconds = idle_ttl_seconds
        self._contexts: dict[str, SessionContext] = {}
        self._lock = threading.RLock()

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._contexts)

    def _cleanup_locked(self, now: float) -> None:
        for session_id in [
            key for key, context in self._contexts.items()
            if now - context.last_accessed > self._idle_ttl_seconds
        ]:
            del self._contexts[session_id]

    def get(self, session_id: str | None) -> SessionContext:
        key = session_id.strip() if session_id else self.LEGACY_SESSION_ID
        now = time.monotonic()
        with self._lock:
            self._cleanup_locked(now)
            context = self._contexts.get(key)
            if context is None:
                # Compatibility fallback for older local clients and existing tests.
                service = self._service if key == self.LEGACY_SESSION_ID else self._service.new_session(key)
                context = SessionContext(_SessionApp(service), threading.RLock(), now)
                self._contexts[key] = context
            context.last_accessed = now
            return context


class MalloServerApp:
    """Session dispatcher for the web gateway.

    An absent X-Mallo-Session-ID intentionally maps to a single legacy session.
    The production web client sends a UUID on every stateful request.
    """

    def __init__(self, service: MalloService, *, session_ttl_seconds: int = 3600) -> None:
        self._service = service
        self._sessions = SessionManager(service, idle_ttl_seconds=session_ttl_seconds)

    @property
    def service(self) -> MalloService:
        return self._service

    @property
    def session_count(self) -> int:
        return self._sessions.session_count

    def dispatch(self, session_id: str | None, method: str, *args) -> dict:
        context = self._sessions.get(session_id)
        with context.lock:
            context.last_accessed = time.monotonic()
            return getattr(context.app, method)(*args)


class MalloHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "MalloServer/0.1"

    @property
    def app(self) -> MalloServerApp:
        return self.server.mallo_app  # type: ignore[attr-defined]

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Mallo-Session-ID, X-Mallo-Request-ID",
        )

    def _session_id(self) -> str | None:
        """Header is optional only for legacy local/test clients."""
        return self.headers.get("X-Mallo-Session-ID") or None

    def _request_id(self) -> str:
        return self.headers.get("X-Mallo-Request-ID", "-")

    def _request_started(self) -> None:
        self._request_started_at = time.perf_counter()
        logger.debug(
            "gateway request start request_id=%s method=%s path=%s",
            self._request_id(), self.command, self.path,
        )

    def _request_finished(self, status: int) -> None:
        started = getattr(self, "_request_started_at", None)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1) if started else None
        logger.debug(
            "gateway request end request_id=%s method=%s path=%s status=%s elapsed_ms=%s",
            self._request_id(), self.command, self.path, status, elapsed_ms,
        )

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._write_body(body)
            self._request_finished(status)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("client disconnected before JSON response write path=%s", self.path)

    def _write_body(self, body: bytes) -> None:
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("client disconnected before response write path=%s", self.path)

    def _sidecar_health(self) -> dict:
        config = getattr(self.server, "sidecar_gateway", None)
        if config is None:
            return {"status": "ready", "stt": "ready", "nlu": "ready", "tts": "ready", "warmed": True}
        statuses: dict[str, str] = {}
        for name, url in config.health_urls.items():
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    payload = json.loads(response.read())
                statuses[name] = "ready" if response.status == 200 and payload.get("ok", False) and payload.get("warmed", False) else "unavailable"
            except (OSError, ValueError, urllib.error.URLError):
                statuses[name] = "unavailable"
        warmed = all(value == "ready" for value in statuses.values())
        return {"status": "ready" if warmed else "degraded", **statuses, "warmed": warmed}

    def _proxy_sidecar(self, url: str, raw: bytes) -> None:
        config = getattr(self.server, "sidecar_gateway", None)
        if config is None:
            self._send_json({"error": "sidecar gateway is not configured"}, status=503)
            return
        request = urllib.request.Request(url, data=raw, method="POST")
        request.add_header("Content-Type", self.headers.get("Content-Type", "application/octet-stream"))
        request.add_header("X-Mallo-Request-ID", self._request_id())
        try:
            with urllib.request.urlopen(request, timeout=config.timeout) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            body, status = error.read(), error.code
        except (OSError, urllib.error.URLError) as error:
            logger.error("sidecar proxy failed url=%s error=%s", url, error)
            self._send_json({"error": "sidecar unavailable"}, status=503)
            return
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._write_body(body)
            self._request_finished(status)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("client disconnected before sidecar response write path=%s", self.path)

    def _serve_static(self, name: str) -> None:
        try:
            target = (WEB_DIR / name).resolve()
            if not target.is_relative_to(WEB_DIR.resolve()) or not target.is_file():
                self._send_json({"error": "not found"}, status=404)
                return
        except (ValueError, OSError):
            self._send_json({"error": "not found"}, status=404)
            return

        body = target.read_bytes()
        try:
            self.send_response(200)
            if name.endswith(".png"):
                self.send_header("Content-Type", "image/png")
            elif name.endswith(".svg"):
                self.send_header("Content-Type", "image/svg+xml")
            elif name.endswith(".webp"):
                self.send_header("Content-Type", "image/webp")
            elif name.endswith(".html"):
                self.send_header("Content-Type", "text/html; charset=utf-8")
            elif name.endswith(".js"):
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
            elif name.endswith(".css"):
                self.send_header("Content-Type", "text/css; charset=utf-8")
            else:
                self.send_header("Content-Type", "application/octet-stream")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._write_body(body)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("client disconnected before static response write path=%s", self.path)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._request_started()
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._serve_static("index.html")
        elif parsed.path in (
            "/app.js",
            "/runtime-config.js",
            "/api-url.js",
            "/menu-metadata.js",
            "/service-mode-flow.js",
            "/option-change-flow.js",
            "/tts-player.js",
            "/microphone-input-monitor.js",
            "/ui-command-router.js",
            "/styles.css",
            "/senior-ui.css",
        ):
            self._serve_static(parsed.path.lstrip("/"))
        elif parsed.path.startswith("/styles/"):
            self._serve_static(parsed.path.lstrip("/"))
        elif parsed.path.startswith("/assets/"):
            self._serve_static(parsed.path.lstrip("/"))
        elif parsed.path == "/stt-demo.html":
            self._serve_static("stt-demo.html")
        elif parsed.path == "/api/state":
            self._send_json(self.app.dispatch(self._session_id(), "state"))
        elif parsed.path == "/health":
            health = self._sidecar_health()
            self._send_json(health, status=200 if health["status"] == "ready" else 503)
        else:
            self._send_json({"error": "not found"}, status=404)

    def _parse_json_object(self, raw: bytes) -> dict | None:
        """JSON 본문을 파싱하고 object(dict)일 때만 반환한다."""
        try:
            data = json.loads(raw or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def do_POST(self) -> None:  # noqa: N802
        self._request_started()
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""

        config = getattr(self.server, "sidecar_gateway", None)
        if parsed.path == "/stt":
            self._proxy_sidecar(config.stt_url if config else "", raw)
        elif parsed.path == "/nlu":
            self._proxy_sidecar(config.nlu_url if config else "", raw)
        elif parsed.path == "/tts":
            self._proxy_sidecar(config.tts_url if config else "", raw)
        elif parsed.path == "/api/order":
            data = self._parse_json_object(raw)
            if data is None:
                self._send_json({"error": "invalid json"}, status=400)
            level = data.get("level") if "level" in data else data.get("tts_level")
            args = [data.get("text", "")]
            if level is not None:
                args.append(level)
            self._send_json(self.app.dispatch(self._session_id(), "handle_text", *args))
        elif parsed.path == "/api/commands":
            data = self._parse_json_object(raw)
            if data is None or not isinstance(data.get("commands"), list):
                self._send_json({"error": "invalid commands"}, status=400)
                return
            self._send_json(self.app.dispatch(self._session_id(), "handle_commands", data["commands"]))
        elif parsed.path == "/api/stt":
            self._send_json(self.app.dispatch(self._session_id(), "transcribe", raw))
        elif parsed.path == "/api/audio/stt":
            self._send_json(self.app.dispatch(self._session_id(), "transcribe", raw))
        elif parsed.path == "/api/audio/interpret":
            data = self._parse_json_object(raw)
            if data is None or not isinstance(data.get("transcript"), str):
                self._send_json({"error": "invalid transcript"}, status=400)
                return
            self._send_json(self.app.dispatch(self._session_id(), "interpret_audio_transcript", data["transcript"]))
        elif parsed.path == "/api/audio":
            self._send_json(self.app.dispatch(self._session_id(), "handle_audio", raw))
        elif parsed.path == "/api/fulfillment":
            data = self._parse_json_object(raw)
            if data is None:
                self._send_json({"error": "invalid json"}, status=400)
                return
            self._send_json(
                self.app.dispatch(self._session_id(), "select_fulfillment", data.get("fulfillment_type", ""))
            )
        elif parsed.path in ("/api/tts", "/api/synthesize"):
            data = self._parse_json_object(raw)
            if data is None or not isinstance(data.get("text"), str):
                self._send_json({"error": "invalid json"}, status=400)
                return
            text = data.get("text", "")
            level = data.get("tts_level")
            self._send_json(self.app.dispatch(
                self._session_id(), "synthesize_tts", text, level,
                bool(data.get("already_chunked", False)),
            ))
        elif parsed.path == "/api/tts-control":
            data = self._parse_json_object(raw)
            if data is None:
                self._send_json({"error": "invalid json"}, status=400)
                return
            self._send_json(self.app.dispatch(self._session_id(), "tts_control", data.get("intent", "REQUEST_REPEAT")))
        elif parsed.path == "/api/system-message":
            data = self._parse_json_object(raw)
            if data is None:
                self._send_json({"error": "invalid json"}, status=400)
                return
            message_id = data.get("message_id", "")
            logger.info("[System message] request received message_id=%r", message_id)
            payload = self.app.dispatch(self._session_id(), "system_message", message_id)
            self._send_json(payload, status=404 if "error" in payload else 200)
        elif parsed.path == "/api/accessibility":
            data = self._parse_json_object(raw)
            if data is None:
                self._send_json({"error": "invalid json"}, status=400)
                return
            args = [data.get("action", "")]
            if "level" in data:
                args.append(data.get("level"))
            if "replay_source" in data:
                while len(args) < 2:
                    args.append(None)
                args.append(data.get("replay_source"))
            payload = self.app.dispatch(self._session_id(), "accessibility_action", *args)
            self._send_json(payload, status=404 if "error" in payload else 200)
        elif parsed.path in ("/api/session/handoff", "/api/handoff"):
            data = self._parse_json_object(raw)
            if data is None:
                self._send_json({"error": "invalid json"}, status=400)
                return
            payload = self.app.dispatch(self._session_id(), "session_handoff", data)
            self._send_json(payload, status=200 if payload.get("success", False) else 400)
        elif parsed.path == "/api/reset":
            self._send_json(self.app.dispatch(self._session_id(), "reset"))
        else:
            self._send_json({"error": "not found"}, status=404)

    def log_message(self, *args) -> None:  # silence default logging
        return None


def build_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    service: MalloService | None = None,
    sidecar_gateway: SidecarGatewayConfig | None = None,
    debug_log_path: Path | str | None = None,
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), MalloHTTPRequestHandler)
    if service is None:
        service = (
            build_mock_service(logger=FileInteractionLogger(Path(debug_log_path)))
            if debug_log_path is not None
            else build_mock_service()
        )
    httpd.mallo_app = MalloServerApp(service)  # type: ignore[attr-defined]
    httpd.sidecar_gateway = sidecar_gateway  # type: ignore[attr-defined]
    return httpd


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Mallo Web backend server")
    parser.add_argument("--host", default="127.0.0.1", help="Server host IP")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument(
        "--tts",
        choices=["mock", "melo", "qwen3", "http"],
        default="mock",
        help="TTS backend (mock, melo, qwen3)",
    )
    parser.add_argument(
        "--tts-ckpt",
        default=None,
        help="Path to fine-tuned TTS checkpoint (e.g. models/tts/mallo-friendly/G_2800.pth)",
    )
    parser.add_argument(
        "--tts-config",
        default=None,
        help="Path to TTS model config.json (e.g. models/tts/mallo-friendly/config.json)",
    )
    parser.add_argument(
        "--tts-device",
        default="auto",
        help="Device for TTS (auto, cpu, cuda:0)",
    )
    parser.add_argument(
        "--tts-speaker",
        default="KR",
        help="Speaker ID for TTS (e.g. KR, 10)",
    )
    parser.add_argument("--tts-url", default="http://127.0.0.1:8003/synthesize")
    parser.add_argument(
        "--stt",
        choices=["mock", "whisper", "fastwhisper", "http"],
        default="mock",
        help="STT backend (mock, whisper, fastwhisper, http-sidecar)",
    )
    parser.add_argument(
        "--stt-variant",
        choices=["baseline", "qlora", "train65", "peft"],
        default="train65",
        help="Whisper variant (train65 default; qlora/baseline rollback; peft deprecated alias)",
    )
    parser.add_argument(
        "--stt-device",
        default="auto",
        help="Device for STT (auto, cpu, cuda)",
    )
    parser.add_argument(
        "--stt-model",
        default=None,
        help=(
            "custom Whisper merged path, fastwhisper model path, or HTTP STT URL"
        ),
    )
    parser.add_argument("--nlu", choices=["mock", "qwen06b", "http"], default="mock")
    parser.add_argument("--nlu-model", default=None)
    parser.add_argument("--nlu-url", default="http://127.0.0.1:8002/parse")
    parser.add_argument("--sidecar-gateway", action="store_true")
    parser.add_argument(
        "--debug-log",
        type=Path,
        default=None,
        help="Append real microphone QA JSONL events (e.g. logs/qa-20260826.jsonl)",
    )
    args = parser.parse_args()

    interaction_logger = (
        FileInteractionLogger(args.debug_log) if args.debug_log is not None else None
    )
    service = build_service(
        tts_backend=args.tts,
        tts_ckpt_path=args.tts_ckpt,
        tts_config_path=args.tts_config,
        tts_device=args.tts_device,
        tts_speaker=args.tts_speaker,
        tts_url=args.tts_url,
        stt_backend=args.stt,
        stt_variant=args.stt_variant,
        stt_device=args.stt_device,
        stt_model_path=args.stt_model,
        nlu_backend=args.nlu,
        nlu_model_path=args.nlu_model,
        nlu_url=args.nlu_url,
        logger=interaction_logger,
    )

    httpd = build_server(
        args.host,
        args.port,
        service=service,
        sidecar_gateway=(
            SidecarGatewayConfig(stt_url=args.stt_model or "http://127.0.0.1:8001/transcribe", nlu_url=args.nlu_url, tts_url=args.tts_url)
            if args.sidecar_gateway else None
        ),
    )
    print(
        f"Mallo server running at http://{args.host}:{args.port} "
        f"[TTS={args.tts}, STT={args.stt}, NLU={args.nlu}]"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
