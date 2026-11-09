import json
import threading
import urllib.request

from app.server import MalloServerApp, _SessionApp, build_server
from app.service import MalloService, build_mock_service
from adapters.tts.mock_tts import MockTTS
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import Cart, FulfillmentType, OrderCommand, Temperature


class _QwenTagFallback:
    def parse(self, text: str, current_order_state: Cart):
        del text, current_order_state
        return [OrderCommand.create(Intent.QUERY_MENU, query_tags=("tea",))]


class _TemperatureMissingAddFallback:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def parse(self, text: str, current_order_state: Cart):
        del current_order_state
        self.calls.append(text)
        return [OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id="americano",
            quantity=2,
            fulfillment_type=FulfillmentType.TAKEOUT,
        )]


def assert_interpret_navigation_contract(payload: dict) -> None:
    """Fields consumed by applyVoiceCommandNavigation() must be endpoint-stable."""
    assert {
        "success",
        "order_commands",
        "cart",
        "tts_audio_base64",
        "response_required",
        "next_listening_mode",
    } <= payload.keys()
    assert {"fulfillment_type", "confirmed", "items", "total_price"} <= payload["cart"].keys()


def test_interpret_response_exposes_server_query_cart_command() -> None:
    payload = _SessionApp(build_mock_service()).interpret_audio_transcript(
        "현재 주문 알려 주세요"
    )

    assert_interpret_navigation_contract(payload)
    assert payload["order_commands"][0]["intent"] == "QUERY_CART"


def test_comprehension_signals_auto_slow_only_on_recent_second_signal_and_keep_replay_source() -> None:
    app = _SessionApp(build_mock_service())

    # STT-sanity and NLU failures are not comprehension evidence.
    for transcript in ("아", "아", "블라블라", "블라블라"):
        result = app.interpret_audio_transcript(transcript)
        assert result["tts_level"] == 0
        assert "speech_prefix" not in result

    original = app.system_message("ORDER")["response_text"]

    first = app.interpret_audio_transcript("못 알아들었어")
    assert first["tts_level"] == 0
    assert first["response_text"] == original
    assert first["order_commands"][0]["intent"] == "REQUEST_CLARIFICATION"
    assert "speech_prefix" not in first

    second = app.interpret_audio_transcript("무슨 말이야?")
    assert second["tts_level"] == 1
    assert second["response_text"] == original
    assert second["speech_prefix"]["response_text"] == "조금 더 천천히 안내해 드릴게요."
    assert second["speech_prefix"]["tts_level"] == 1
    assert second["tts_level"] == 1
    assert second["tts_segments"][0]["tts_audio_base64"] is not None

    app.interpret_audio_transcript("잘 못 들었어")
    fourth = app.interpret_audio_transcript("다시 설명해줘")
    assert fourth["tts_level"] == 2
    assert fourth["speech_prefix"]["response_text"] == "조금 더 천천히 안내해 드릴게요."

    app.interpret_audio_transcript("이해가 안 돼")
    capped = app.interpret_audio_transcript("잘 모르겠어요")
    assert capped["tts_level"] == 2
    assert "speech_prefix" not in capped

    app.reset()
    reset = app.interpret_audio_transcript("못 알아들었어")
    assert reset["tts_level"] == 0
    assert "speech_prefix" not in reset


def test_comprehension_window_expires_after_four_other_successful_semantic_turns() -> None:
    app = _SessionApp(build_mock_service())
    app.system_message("ORDER")
    app.interpret_audio_transcript("못 알아들었어")
    for _ in range(4):
        app.interpret_audio_transcript("다시 말해 주세요")

    expired = app.interpret_audio_transcript("무슨 말이야?")
    assert expired["tts_level"] == 0
    assert "speech_prefix" not in expired

    explicit = app.interpret_audio_transcript("천천히 말해줘")
    assert explicit["tts_level"] == 1
    assert "speech_prefix" not in explicit


def test_interpret_response_keeps_voice_navigation_contract_for_each_result() -> None:
    app = _SessionApp(build_mock_service())

    fulfillment = app.interpret_audio_transcript("포장할게요")
    assert_interpret_navigation_contract(fulfillment)
    assert fulfillment["success"] is True
    assert fulfillment["order_commands"][0]["intent"] == "SET_FULFILLMENT"
    assert fulfillment["cart"]["fulfillment_type"] == "takeout"
    assert fulfillment["cart"]["confirmed"] is False
    assert fulfillment["response_text"] == "포장으로 설정했습니다. 원하시는 메뉴 있으신가요?"

    app.interpret_audio_transcript("아이스 아메리카노 두 잔 주세요")
    confirmed = app.interpret_audio_transcript("주문 확인할게요")
    assert_interpret_navigation_contract(confirmed)
    assert confirmed["success"] is True
    assert confirmed["order_commands"][0]["intent"] == "CONFIRM_ORDER"
    assert confirmed["cart"]["confirmed"] is True

    payment = app.interpret_audio_transcript("카드로 결제할게요")
    assert_interpret_navigation_contract(payment)
    assert payment["success"] is True
    payment_command = payment["order_commands"][0]
    assert payment_command["intent"] == "SELECT_PAYMENT_METHOD"
    assert payment_command["target_item_id"] == "card"
    assert payment_command["fulfillment_type"] is None
    assert payment["cart"]["confirmed"] is True

    failed_confirmation = _SessionApp(build_mock_service()).interpret_audio_transcript("결제할게요")
    assert_interpret_navigation_contract(failed_confirmation)
    assert failed_confirmation["success"] is False
    assert [command["intent"] for command in failed_confirmation["order_commands"]] == ["CONFIRM_ORDER"]
    assert failed_confirmation["cart"]["confirmed"] is False


def test_voice_one_shot_order_interpretation_confirms_only_when_complete_and_cart_is_empty() -> None:
    app = _SessionApp(build_mock_service())

    takeout = app.interpret_audio_transcript("아이스 아메리카노 하나 포장하고 싶어")
    assert_interpret_navigation_contract(takeout)
    assert takeout["success"] is True
    assert [command["intent"] for command in takeout["order_commands"]] == [
        "SET_FULFILLMENT", "ADD_ITEM", "CONFIRM_ORDER",
    ]
    assert takeout["cart"]["fulfillment_type"] == "takeout"
    assert takeout["cart"]["confirmed"] is True
    assert [(item["menu_id"], item["temperature"], item["quantity"]) for item in takeout["cart"]["items"]] == [
        ("americano", "iced", 1),
    ]

    dine_in = _SessionApp(build_mock_service()).interpret_audio_transcript(
        "따뜻한 카페라떼 두 잔 매장에서 먹을게요"
    )
    assert dine_in["success"] is True
    assert dine_in["cart"]["fulfillment_type"] == "dine_in"
    assert dine_in["cart"]["confirmed"] is True
    assert [(item["menu_id"], item["temperature"], item["quantity"]) for item in dine_in["cart"]["items"]] == [
        ("cafe_latte", "hot", 2),
    ]

    missing_temperature = _SessionApp(build_mock_service()).interpret_audio_transcript(
        "카페라떼 두 잔 포장할게요"
    )
    assert missing_temperature["success"] is False
    assert missing_temperature["error_code"] == "MISSING_FIELD"
    assert missing_temperature["cart"]["confirmed"] is False

    missing_quantity = _SessionApp(build_mock_service()).interpret_audio_transcript(
        "아이스 아메리카노 포장할게요"
    )
    assert missing_quantity["success"] is False
    assert missing_quantity["error_code"] == "MISSING_FIELD"
    assert missing_quantity["cart"]["confirmed"] is False

    over_limit = _SessionApp(build_mock_service()).interpret_audio_transcript(
        "아이스 아메리카노 6잔 포장할게요"
    )
    assert over_limit["success"] is False
    assert over_limit["error_code"] == "INVALID_QUANTITY"
    assert over_limit["cart"]["items"] == []
    assert over_limit["cart"]["confirmed"] is False

    existing_cart = _SessionApp(build_mock_service())
    existing_cart.interpret_audio_transcript("아이스 아메리카노 하나 주세요")
    added = existing_cart.interpret_audio_transcript("따뜻한 카페라떼 두 잔 포장할게요")
    assert added["success"] is True
    assert [command["intent"] for command in added["order_commands"]] == ["ADD_ITEM"]
    assert added["cart"]["confirmed"] is False
    assert [(item["menu_id"], item["temperature"], item["quantity"]) for item in added["cart"]["items"]] == [
        ("americano", "iced", 1),
        ("cafe_latte", "hot", 2),
    ]


def test_audio_interpret_dispatch_canonicalizes_qwen_category_tag_before_execution() -> None:
    app = MalloServerApp(MalloService(
        nlu=_QwenTagFallback(),
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
    ))

    payload = app.dispatch(
        "browser-session",
        "interpret_audio_transcript",
        "차는 뭐가 있어?",
    )

    assert_interpret_navigation_contract(payload)
    assert payload["success"] is True
    assert payload["error_code"] is None
    assert payload["order_commands"][0]["intent"] == "QUERY_MENU"
    assert payload["order_commands"][0]["category_id"] == "tea"
    assert payload["order_commands"][0]["query_tags"] is None


def test_http_audio_interpret_canonicalizes_qwen_category_tag_before_execution() -> None:
    service = MalloService(
        nlu=_QwenTagFallback(),
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
    )
    httpd = build_server("127.0.0.1", 0, service=service)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/audio/interpret",
            data=json.dumps({"transcript": "차는 뭐가 있어?"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-Mallo-Session-ID": "browser-session"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert payload["success"] is True
    assert payload["order_commands"][0]["intent"] == "QUERY_MENU"
    assert payload["order_commands"][0]["category_id"] == "tea"
    assert payload["order_commands"][0]["query_tags"] is None


def test_http_audio_interpret_keeps_pending_add_slots_across_quantity_and_temperature_turns() -> None:
    httpd = build_server("127.0.0.1", 0, service=build_mock_service())
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    session_id = "pending-http-session"

    def interpret(transcript: str, active_session_id: str = session_id) -> dict:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/audio/interpret",
            data=json.dumps({"transcript": transcript}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-Mallo-Session-ID": active_session_id},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        quantity = interpret("카페라떼 주세요")
        temperature = interpret("두 잔 주세요")
        completed = interpret("아이스로")
        hot_prompt = interpret("카페라떼 한잔 주세요", "pending-hot-http-session")
        hot_completed = interpret("따뜻하게", "pending-hot-http-session")
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert quantity["error_code"] == "MISSING_FIELD"
    assert quantity["response_text"] == "카페라떼의 수량을 말씀해 주세요."
    assert temperature["error_code"] == "MISSING_FIELD"
    assert temperature["response_text"] == "따뜻하게 드릴까요, 아이스로 드릴까요?"
    assert completed["success"] is True
    assert completed["cart"]["items"] == [{
        "menu_id": "cafe_latte", "name": "카페라떼", "quantity": 2,
        "temperature": "iced", "unit_price": 5200, "total_price": 10400,
        "options": {"size": None, "extra_shots": None, "caffeine": None, "syrup_pumps": None, "ice_amount": None},
    }]
    assert hot_prompt["error_code"] == "MISSING_FIELD"
    assert hot_completed["success"] is True
    assert [(item["menu_id"], item["quantity"], item["temperature"]) for item in hot_completed["cart"]["items"]] == [
        ("cafe_latte", 1, "hot"),
    ]


def test_http_audio_interpret_fallback_temperature_clarification_keeps_pending_slots() -> None:
    fallback = _TemperatureMissingAddFallback()
    service = MalloService(
        nlu=fallback,
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
    )
    httpd = build_server("127.0.0.1", 0, service=service)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    session_id = "fallback-temperature-http-session"

    def interpret(transcript: str) -> dict:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/audio/interpret",
            data=json.dumps({"transcript": transcript}).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-Mallo-Session-ID": session_id},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        prompt = interpret("fallback americano phrase")
        completed = interpret("따뜻한 걸로")
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert prompt["error_code"] == "MISSING_FIELD"
    assert prompt["response_text"] == "따뜻하게 드릴까요, 아이스로 드릴까요?"
    assert completed["success"] is True
    assert completed["cart"]["fulfillment_type"] == "takeout"
    assert completed["cart"]["items"] == [{
        "menu_id": "americano", "name": "아메리카노", "quantity": 2,
        "temperature": Temperature.HOT.value, "unit_price": 4700, "total_price": 9400,
        "options": {"size": None, "extra_shots": None, "caffeine": None, "syrup_pumps": None, "ice_amount": None},
    }]
    assert fallback.calls == ["fallback americano phrase"]


def test_http_audio_interpret_pending_add_does_not_update_existing_item() -> None:
    httpd = build_server("127.0.0.1", 0, service=build_mock_service())
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    session_id = "pending-existing-cart-session"

    def interpret(transcript: str) -> dict:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/audio/interpret",
            data=json.dumps({"transcript": transcript}).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-Mallo-Session-ID": session_id},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        initial = interpret("아이스 아메리카노 두 잔")
        prompt = interpret("카페라떼 한잔 주세요")
        completed = interpret("아이스로")
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert initial["success"] is True
    assert prompt["error_code"] == "MISSING_FIELD"
    assert prompt["response_text"] == "따뜻하게 드릴까요, 아이스로 드릴까요?"
    assert completed["success"] is True
    assert [(item["menu_id"], item["quantity"], item["temperature"]) for item in completed["cart"]["items"]] == [
        ("americano", 2, "iced"), ("cafe_latte", 1, "iced"),
    ]


def test_http_audio_interpret_moves_only_requested_temperature_quantity() -> None:
    httpd = build_server("127.0.0.1", 0, service=build_mock_service())
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()

    def interpret(session_id: str, transcript: str) -> dict:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/audio/interpret",
            data=json.dumps({"transcript": transcript}).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-Mallo-Session-ID": session_id},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def cart_items(payload: dict) -> list[tuple[str, int]]:
        return [(item["temperature"], item["quantity"]) for item in payload["cart"]["items"]]

    try:
        # A: iced x2 -> iced x1 + hot x1
        interpret("partial-a", "아이스 카페라떼 두 잔")
        a = interpret("partial-a", "하나만 따뜻한 걸로 바꿔줘")

        # B: hot x2 -> hot x1 + iced x1
        interpret("partial-b", "따뜻한 카페라떼 두 잔")
        b = interpret("partial-b", "한 잔만 아이스로 바꿔줘")

        # C: iced x3 -> iced x1 + hot x2
        interpret("partial-c", "아이스 카페라떼 세 잔")
        c = interpret("partial-c", "두 잔만 따뜻하게 바꿔줘")

        # D: destination line is merged, while the named iced source is retained.
        interpret("partial-d", "아이스 카페라떼 두 잔")
        interpret("partial-d", "따뜻한 카페라떼 한 잔")
        d = interpret("partial-d", "아이스 카페라떼 하나만 따뜻하게 바꿔줘")

        # E: no menu in a multi-menu cart must remain a clarification.
        interpret("partial-e", "아이스 카페라떼 두 잔")
        interpret("partial-e", "아이스 아메리카노 한 잔")
        e = interpret("partial-e", "하나만 따뜻하게 바꿔줘")
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert a["success"] is True
    assert cart_items(a) == [("iced", 1), ("hot", 1)]
    assert b["success"] is True
    assert cart_items(b) == [("hot", 1), ("iced", 1)]
    assert c["success"] is True
    assert cart_items(c) == [("iced", 1), ("hot", 2)]
    assert d["success"] is True
    assert cart_items(d) == [("iced", 1), ("hot", 2)]
    assert d["cart"]["total_price"] == 15600
    assert e["success"] is False
    assert e["error_code"] == "AMBIGUOUS_TARGET"
    assert cart_items(e) == [("iced", 2), ("iced", 1)]


def test_http_audio_interpret_short_decaf_fragments_do_not_change_order_or_payment() -> None:
    httpd = build_server("127.0.0.1", 0, service=build_mock_service())
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    session_id = "short-decaf-http-session"

    def interpret(transcript: str) -> dict:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/audio/interpret",
            data=json.dumps({"transcript": transcript}).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "X-Mallo-Session-ID": session_id},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        added = interpret("아이스 아메리카노 두 잔 포장")
        confirmed = interpret("주문 확인할게요")
        fragments = [interpret("디"), interpret("디카")]
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert added["success"] is True
    assert confirmed["success"] is True
    for result in fragments:
        assert result["success"] is False
        assert result["order_commands"] == []
        assert result["cart"] == confirmed["cart"]
