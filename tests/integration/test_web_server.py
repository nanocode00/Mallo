from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request

import pytest

from app.server import build_server


def _command(intent: str, **values):
    return {
        "intent": intent, "target_item_id": None, "category_id": None,
        "quantity": None, "temperature": None, "query_tags": None,
        "detail_fields": None, "options": None, "fulfillment_type": None,
        **values,
    }


def _start_server():
    httpd = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return httpd, port


def _post(port, path, payload=None, raw=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = raw if raw is not None else json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_session(port, session_id, path, payload=None, raw=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = raw if raw is not None else json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "X-Mallo-Session-ID": session_id},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_session(port, session_id, path="/api/state"):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"X-Mallo-Session-ID": session_id},
    )
    with urllib.request.urlopen(request) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_raw(port, path, body):
    """원시 바디를 POST하고 (status, parsed_body) 튜플을 반환한다."""
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def test_order_then_state_reflects_cart() -> None:
    httpd, port = _start_server()
    try:
        order = _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        assert order["success"] is True
        assert order["cart"]["items"][0]["menu_id"] == "americano"
        assert order["cart"]["total_price"] == 9400
        assert order["response_required"] is True
        assert order["next_listening_mode"] == "SYSTEM_PROMPTED"

        state = _get(port, "/api/state")
        assert state["cart"]["total_price"] == 9400
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("fulfillment_type", ["dine_in", "takeout"])
def test_fulfillment_selection_is_stored_and_preserved_in_order(
    fulfillment_type: str,
) -> None:
    httpd, port = _start_server()
    try:
        selected = _post(
            port,
            "/api/fulfillment",
            {"fulfillment_type": fulfillment_type},
        )
        assert selected["success"] is True
        assert selected["cart"]["fulfillment_type"] == fulfillment_type

        state = _get(port, "/api/state")
        assert state["cart"]["fulfillment_type"] == fulfillment_type

        order = _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        assert order["cart"]["fulfillment_type"] == fulfillment_type

        audio = _post(port, "/api/audio", raw=b"dummy-wav-bytes")
        assert audio["cart"]["fulfillment_type"] == fulfillment_type
    finally:
        httpd.shutdown()


def test_invalid_fulfillment_does_not_reset_existing_session() -> None:
    httpd, port = _start_server()
    try:
        _post(port, "/api/fulfillment", {"fulfillment_type": "takeout"})
        _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})

        failed = _post(port, "/api/fulfillment", {"fulfillment_type": "delivery"})

        assert failed["success"] is False
        assert failed["cart"]["fulfillment_type"] == "takeout"
        assert failed["cart"]["items"][0]["quantity"] == 2
    finally:
        httpd.shutdown()


def test_multi_turn_order_accumulates_in_session() -> None:
    httpd, port = _start_server()
    try:
        _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        second = _post(port, "/api/order", {"text": "따뜻한 카페라떼 한 잔 주세요"})
        assert second["cart"]["total_price"] == 14600
        assert len(second["cart"]["items"]) == 2
    finally:
        httpd.shutdown()


def test_pending_temperature_add_keeps_the_requested_menu_and_quantity() -> None:
    httpd, port = _start_server()
    try:
        _post(
            port,
            "/api/commands",
            {"commands": [
                _command("ADD_ITEM", target_item_id="americano", quantity=2, temperature="iced"),
                _command("ADD_ITEM", target_item_id="cafe_latte", quantity=2, temperature="iced"),
            ]},
        )

        prompt = _post(port, "/api/order", {"text": "카페라떼 두 잔 더 추가"})
        completed = _post(port, "/api/order", {"text": "따뜻하게"})

        assert prompt["success"] is False
        assert prompt["error_code"] == "MISSING_FIELD"
        assert completed["success"] is True
        assert [(item["menu_id"], item["temperature"], item["quantity"]) for item in completed["cart"]["items"]] == [
            ("americano", "iced", 2),
            ("cafe_latte", "iced", 2),
            ("cafe_latte", "hot", 2),
        ]
    finally:
        httpd.shutdown()


def test_no_change_reply_preserves_cart_and_quantity_limit_is_explicit() -> None:
    httpd, port = _start_server()
    try:
        added = _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        unchanged = _post(port, "/api/order", {"text": "변경할 거 없어요"})
        rejected = _post(port, "/api/order", {"text": "아이스 아메리카노 6잔 추가"})

        assert unchanged["success"] is True
        assert unchanged["cart"] == added["cart"]
        assert rejected["success"] is False
        assert rejected["error_code"] == "INVALID_QUANTITY"
        assert rejected["response_text"] == "메뉴별 수량은 최대 5개까지 주문할 수 있습니다."
        assert rejected["cart"] == added["cart"]
    finally:
        httpd.shutdown()


def test_quantity_forms_stay_consistent_across_order_add_change_and_pending_turns() -> None:
    httpd, port = _start_server()
    try:
        ordered = _post(port, "/api/order", {"text": "아이스 아메리카노 한 잔 주세요"})
        added = _post(port, "/api/order", {"text": "아이스 아메리카노 2개 더 추가"})
        changed = _post(port, "/api/order", {"text": "아이스 아메리카노 세잔 세잔으로 바꿔 주세요"})
        prompt = _post(port, "/api/order", {"text": "카페라떼 2개 추가"})
        completed = _post(port, "/api/order", {"text": "따뜻하게"})

        assert ordered["cart"]["items"][0]["quantity"] == 1
        assert added["cart"]["items"][0]["quantity"] == 3
        assert changed["cart"]["items"][0]["quantity"] == 3
        assert prompt["error_code"] == "MISSING_FIELD"
        assert [(item["menu_id"], item["temperature"], item["quantity"]) for item in completed["cart"]["items"]] == [
            ("americano", "iced", 3),
            ("cafe_latte", "hot", 2),
        ]
    finally:
        httpd.shutdown()


def test_tts_control_changes_level() -> None:
    httpd, port = _start_server()
    try:
        _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        ctrl = _post(port, "/api/tts-control", {"intent": "REQUEST_SLOWER"})
        assert ctrl["tts_level"] == 1
        assert ctrl["tts_audio_base64"] is not None
        assert ctrl["response_required"] is False
        assert ctrl["next_listening_mode"] is None
    finally:
        httpd.shutdown()


def test_audio_endpoint_returns_latencies_and_cart() -> None:
    httpd, port = _start_server()
    try:
        result = _post(port, "/api/audio", raw=b"dummy-wav-bytes")
        assert result["transcript"] == "아이스 아메리카노 두 잔 주세요"
        assert result["confidence"] == 0.98
        assert result["tts_audio_base64"] is not None
        assert result["latencies_ms"]["total_e2e"] >= 0
        assert result["cart"]["items"][0]["menu_id"] == "americano"
        assert result["response_required"] is True
        assert result["next_listening_mode"] == "SYSTEM_PROMPTED"
    finally:
        httpd.shutdown()


def test_clarification_response_requests_system_prompted_listening() -> None:
    httpd, port = _start_server()
    try:
        result = _post(port, "/api/order", {"text": "아메리카노 한 잔 주세요"})
        assert result["success"] is False
        assert result["response_required"] is True
        assert result["next_listening_mode"] == "SYSTEM_PROMPTED"
    finally:
        httpd.shutdown()


@pytest.mark.parametrize(
    ("message_id", "text", "response_required"),
    [
        ("WELCOME", "어서오세요. 말로 카페입니다.", False),
        ("SERVICE_MODE", "어떻게 이용하시겠어요? 매장 이용 또는 포장을 선택해 주세요.", True),
        ("ORDER", "원하시는 메뉴를 말씀해 주세요.", True),
        ("ORDER_REVIEW", "주문 내용을 확인해 주세요.", True),
        ("PAYMENT", "결제 방법을 선택해 주세요.", True),
        ("COMPLETE", "주문이 완료되었습니다.", False),
        ("STAFF", "직원을 호출했습니다. 잠시만 기다려 주세요.", False),
        ("PAYMENT_EMPTY_CART", "장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.", False),
    ],
)
def test_system_message_uses_one_text_for_screen_and_tts(
    message_id: str, text: str, response_required: bool,
) -> None:
    httpd, port = _start_server()
    try:
        result = _post(port, "/api/system-message", {"message_id": message_id})
        tts = httpd.mallo_app.service._pipeline._tts  # type: ignore[attr-defined]

        assert result["response_text"] == text
        assert result["tts_audio_base64"] is not None
        assert any(call[0] in (text, "어떻게 이용하시겠어요?", "매장 이용 또는 포장을 선택해 주세요.") for call in tts.calls)
        assert result["response_required"] is response_required
        assert result["next_listening_mode"] == (
            "SYSTEM_PROMPTED" if response_required else None
        )
    finally:
        httpd.shutdown()


def test_fulfillment_returns_spoken_order_prompt() -> None:
    httpd, port = _start_server()
    try:
        result = _post(port, "/api/fulfillment", {"fulfillment_type": "dine_in"})
        assert result["response_text"] == "원하시는 메뉴를 말씀해 주세요."
        assert result["tts_audio_base64"] is not None
        assert result["response_required"] is True
        assert result["next_listening_mode"] == "SYSTEM_PROMPTED"
    finally:
        httpd.shutdown()


def test_failed_order_response_is_spoken_and_requests_retry() -> None:
    httpd, port = _start_server()
    try:
        result = _post(port, "/api/order", {"text": "알아들을 수 없는 주문"})
        tts = httpd.mallo_app.service._pipeline._tts  # type: ignore[attr-defined]

        assert result["success"] is False
        assert result["response_text"] == "잘 이해하지 못했어요. 다시 말씀해 주세요."
        assert result["tts_audio_base64"] is not None
        assert tts.calls[-1][0] == result["response_text"]
        assert result["response_required"] is True
        assert result["next_listening_mode"] == "SYSTEM_PROMPTED"
    finally:
        httpd.shutdown()


def test_second_consecutive_failure_offers_touch_or_staff_without_voice_loop() -> None:
    httpd, port = _start_server()
    try:
        first = _post(port, "/api/order", {"text": "알아들을 수 없는 주문"})
        second = _post(port, "/api/order", {"text": "여전히 알아들을 수 없는 주문"})
        tts = httpd.mallo_app.service._pipeline._tts  # type: ignore[attr-defined]

        assert first["response_required"] is True
        assert second["response_text"] == "잘 이해하지 못했어요. 화면에서 메뉴를 선택하시거나 직원을 불러드릴 수 있습니다."
        assert second["response_required"] is False
        assert second["next_listening_mode"] is None
        assert any(part in call[0] for call in tts.calls for part in ("잘 이해하지 못했어요.", "화면에서 메뉴를 선택하시거나 직원을 불러드릴 수 있습니다."))
    finally:
        httpd.shutdown()


def test_accessibility_speed_cycles_without_replaying_last_message() -> None:
    httpd, port = _start_server()
    try:
        ordered = _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        last_message = ordered["response_text"]
        tts = httpd.mallo_app.service._pipeline._tts  # type: ignore[attr-defined]

        for expected_level in (1, 2, 0):
            result = _post(port, "/api/accessibility", {"action": "CYCLE_SPEED"})
            assert result["tts_level"] == expected_level
            assert result["response_text"] == "이 속도로 안내합니다."
            assert tts.calls[-1][0] == "이 속도로 안내합니다."
            assert _get(port, "/api/state")["last_response"] == last_message

        repeated = _post(port, "/api/accessibility", {"action": "REPEAT"})
        assert repeated["response_text"] == last_message
        assert repeated["tts_level"] == 0
        assert tts.calls[-1][0] == last_message
    finally:
        httpd.shutdown()


def test_adaptive_tts_segment_payloads_are_stable_and_repeat_current_message() -> None:
    """L2 chunks retain their own text/level and REPEAT never falls back to WELCOME."""
    httpd, port = _start_server()
    try:
        _post(port, "/api/accessibility", {"action": "SET_SPEED_2"})
        service_mode = _post(port, "/api/system-message", {"message_id": "SERVICE_MODE"})
        tts = httpd.mallo_app.service._pipeline._tts  # type: ignore[attr-defined]

        segments = service_mode["tts_segments"]
        assert [segment["chunk_id"] for segment in segments] == ["SERVICE_MODE:0", "SERVICE_MODE:1"]
        assert [segment["segment_index"] for segment in segments] == [0, 1]
        assert [segment["synthesis_text"] for segment in segments] == [
            "어떻게 이용하시겠어요?", "매장 이용 또는 포장을 선택해 주세요.",
        ]
        assert {segment["gap_ms"] for segment in segments} == {480}

        call_start = len(tts.calls)
        for segment in segments:
            reply = _post(port, "/api/tts", {
                "text": segment["synthesis_text"], "already_chunked": True, "tts_level": 2,
            })
            assert reply["synthesis_text"] == segment["synthesis_text"]
            assert reply["tts_level"] == 2
        assert tts.calls[call_start:] == [
            ("어떻게 이용하시겠어요?", 2),
            ("매장 이용 또는 포장을 선택해 주세요.", 2),
        ]

        # The speed preview must not replace SERVICE_MODE as the replay source.
        _post(port, "/api/accessibility", {"action": "CYCLE_SPEED"})
        _post(port, "/api/accessibility", {"action": "CALL_STAFF"})
        repeated = _post(port, "/api/accessibility", {"action": "REPEAT", "level": 0})
        assert repeated["response_text"] == service_mode["response_text"]
        assert "어서오세요" not in repeated["response_text"]
        assert repeated["tts_level"] == 0
        assert [segment["chunk_id"] for segment in repeated["tts_segments"]] == ["SERVICE_MODE:0", "SERVICE_MODE:1"]
    finally:
        httpd.shutdown()


def test_staff_accessibility_action_is_informational_spoken_message() -> None:
    httpd, port = _start_server()
    try:
        result = _post(port, "/api/accessibility", {"action": "CALL_STAFF"})
        assert result["response_text"] == "직원을 호출했습니다. 잠시만 기다려 주세요."
        assert result["tts_audio_base64"] is not None
        assert result["response_required"] is False
        assert result["next_listening_mode"] is None
    finally:
        httpd.shutdown()


def test_frontend_wires_audio_transcript_to_confirmation_screen() -> None:
    httpd, port = _start_server()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/app.js") as resp:
            script = resp.read().decode("utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            page = resp.read().decode("utf-8")

        assert 'sttState.transcript = typeof stt.transcript === "string"' in script
        assert 'sttState.confidence = typeof stt.confidence === "number"' in script
        assert 'callApi("/api/audio/stt"' in script
        assert 'callApi("/api/audio/interpret"' in script
        assert 'callApi("/api/stt"' not in script
        assert "MalloUICommandRouter.route" in script
        assert script.count('sttState.transcript = ""') >= 3
        assert 'id="liveTranscript"' in page
        assert "내가 말한 내용" not in page
        assert "주문 내용" in page
        assert "주문 내용을 확인해 주세요" in page
        assert 'id="screenOrderReview"' in page
        assert 'src="tts-player.js"' in page
        assert 'classList.toggle("is-tts-playing", isPlaying)' in script
        assert 'src="option-change-flow.js"' in page
        assert 'src="ui-command-router.js"' in page
        assert "수정할게요" in page
        assert "변경하지 않고 돌아가기" in page
        assert 'src="service-mode-flow.js"' in page
        assert 'src="menu-metadata.js"' in page
        assert 'id="screenServiceMode"' in page
        assert 'id="btnDineIn"' in page
        assert 'id="btnTakeout"' in page
        assert 'id="btnGlobalHome"' in page
        assert 'id="ttsSpeedStatus"' in page
        welcome = page.split('id="screenWelcome"', 1)[1].split('id="screenServiceMode"', 1)[0]
        assert "response-bar" in welcome
        assert "어서오세요. 말로 카페입니다." in welcome
        assert 'resetSession().then(() => {' in script
        assert 'id="textInputWelcome"' not in page
        assert 'id="btnSendWelcome"' not in page
        assert 'id="textInputListening"' not in page
        assert 'id="btnSendListening"' not in page
        assert "말씀하셔도 됩니다" not in page
        assert 'goToScreen(serviceModeFlow.start())' in script
        assert 'callApi("/api/order"' in script
        assert 'callApi("/api/commands"' in script
        assert 'processUtteranceText(card.dataset.orderText, "ORDER"' not in script
        assert 'id="screenOrder"' in page
        assert 'id="voiceOverlay"' in page
        assert 'id="btnViewCart"' in page
        assert 'id="screenListening"' not in page
        assert 'id="screenProcessing"' not in page
        assert 'class="item-quantity">× ${item.quantity}' in script
        assert "포장 주문" in script
    finally:
        httpd.shutdown()


def test_supported_option_change_commands_update_cart_and_failures_preserve_it() -> None:
    httpd, port = _start_server()
    try:
        _post(port, "/api/fulfillment", {"fulfillment_type": "takeout"})
        added = _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        quantity = _post(port, "/api/order", {"text": "아이스 아메리카노 세 잔으로 바꿔 주세요"})
        temperature = _post(port, "/api/order", {"text": "아메리카노를 따뜻하게 바꿔 주세요"})
        option = _post(port, "/api/order", {"text": "아메리카노 디카페인으로 줘"})
        failed = _post(port, "/api/order", {"text": "아니 두 잔이라고"})

        assert added["cart"]["items"][0]["quantity"] == 2
        assert quantity["cart"]["items"][0]["quantity"] == 3
        assert temperature["cart"]["items"][0]["temperature"] == "hot"
        assert option["success"] is False
        assert failed["success"] is False
        assert failed["error_code"] == "UNSUPPORTED_UTTERANCE"
        assert option["cart"] == temperature["cart"]
        assert failed["cart"] == option["cart"]
        assert failed["cart"]["fulfillment_type"] == "takeout"
    finally:
        httpd.shutdown()


def test_text_order_accepts_general_iced_americano_phrase() -> None:
    httpd, port = _start_server()
    try:
        result = _post(port, "/api/order", {"text": "아이스 아메리카노 하나 줘"})

        assert result["success"] is True
        assert result["cart"]["items"] == [
            {
                "menu_id": "americano",
                "name": "아메리카노",
                "temperature": "iced",
                "quantity": 1,
                "options": {
                    "size": None,
                    "extra_shots": None,
                    "caffeine": None,
                    "syrup_pumps": None,
                    "ice_amount": None,
                },
                "unit_price": 4700,
                "total_price": 4700,
            }
        ]
    finally:
        httpd.shutdown()


def test_text_order_exposes_tts_audio_without_removing_existing_fields() -> None:
    httpd, port = _start_server()
    try:
        result = _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        assert result["success"] is True
        assert result["response_text"] == "아이스 아메리카노 두 잔을 담았습니다."
        assert result["cart"]["total_price"] == 9400
        assert result["tts_audio_base64"] is not None
    finally:
        httpd.shutdown()


def test_failed_order_synthesizes_its_own_retry_message() -> None:
    httpd, port = _start_server()
    try:
        successful = _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        failed = _post(port, "/api/order", {"text": "지원하지 않는 발화"})

        assert successful["tts_audio_base64"] is not None
        assert failed["success"] is False
        assert failed["tts_audio_base64"] is not None
        tts = httpd.mallo_app.service._pipeline._tts  # type: ignore[attr-defined]
        assert tts.calls[-1][0] == failed["response_text"]
    finally:
        httpd.shutdown()


def test_reset_clears_session_cart() -> None:
    httpd, port = _start_server()
    try:
        _post(port, "/api/fulfillment", {"fulfillment_type": "dine_in"})
        _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        reset = _post(port, "/api/reset", {})
        assert reset["status"] == "reset"
        state = _get(port, "/api/state")
        assert state["cart"]["items"] == []
        assert state["cart"]["fulfillment_type"] is None
    finally:
        httpd.shutdown()


def test_http_sessions_isolate_cart_fulfillment_and_reset() -> None:
    httpd, port = _start_server()
    try:
        session_a = "11111111-1111-4111-8111-111111111111"
        session_b = "22222222-2222-4222-8222-222222222222"
        _post_session(port, session_a, "/api/fulfillment", {"fulfillment_type": "takeout"})
        _post_session(port, session_a, "/api/commands", {"commands": [_command("ADD_ITEM", target_item_id="americano", quantity=1, temperature="iced")]})
        _post_session(port, session_b, "/api/fulfillment", {"fulfillment_type": "dine_in"})
        _post_session(port, session_b, "/api/commands", {"commands": [_command("ADD_ITEM", target_item_id="cafe_latte", quantity=2, temperature="hot")]})

        state_a = _get_session(port, session_a)
        state_b = _get_session(port, session_b)
        assert state_a["cart"]["fulfillment_type"] == "takeout"
        assert [item["menu_id"] for item in state_a["cart"]["items"]] == ["americano"]
        assert state_b["cart"]["fulfillment_type"] == "dine_in"
        assert [item["menu_id"] for item in state_b["cart"]["items"]] == ["cafe_latte"]

        _post_session(port, session_a, "/api/reset", {})
        assert _get_session(port, session_a)["cart"]["items"] == []
        assert [item["menu_id"] for item in _get_session(port, session_b)["cart"]["items"]] == ["cafe_latte"]
    finally:
        httpd.shutdown()


def test_same_session_concurrent_updates_are_serialized_without_lost_update() -> None:
    httpd, port = _start_server()
    try:
        session_id = "33333333-3333-4333-8333-333333333333"
        commands = [
            _command("ADD_ITEM", target_item_id="americano", quantity=1, temperature="iced"),
            _command("ADD_ITEM", target_item_id="cafe_latte", quantity=1, temperature="hot"),
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(_post_session, port, session_id, "/api/commands", {"commands": [command]})
                for command in commands
            ]
            [future.result() for future in futures]

        state = _get_session(port, session_id)
        assert {item["menu_id"] for item in state["cart"]["items"]} == {"americano", "cafe_latte"}
    finally:
        httpd.shutdown()


def test_concurrent_sessions_do_not_cross_order_state() -> None:
    httpd, port = _start_server()
    try:
        sessions = {
            "44444444-4444-4444-8444-444444444444": "americano",
            "55555555-5555-4555-8555-555555555555": "cafe_latte",
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _post_session,
                    port,
                    session_id,
                    "/api/commands",
                    {"commands": [_command("ADD_ITEM", target_item_id=menu_id, quantity=1, temperature="iced")]},
                )
                for session_id, menu_id in sessions.items()
            ]
            [future.result() for future in futures]
        for session_id, menu_id in sessions.items():
            assert [item["menu_id"] for item in _get_session(port, session_id)["cart"]["items"]] == [menu_id]
    finally:
        httpd.shutdown()


def test_static_index_is_served() -> None:
    httpd, port = _start_server()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            body = resp.read().decode("utf-8")
        assert "<html" in body.lower()
        assert 'src="runtime-config.js"' in body
        assert 'src="api-url.js"' in body

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/runtime-config.js") as resp:
            runtime_config = resp.read().decode("utf-8")
            assert resp.headers.get_content_type() == "application/javascript"
        assert "MALLO_API_BASE_URL" in runtime_config

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api-url.js") as resp:
            api_url = resp.read().decode("utf-8")
        assert "function apiUrl(path)" in api_url
    finally:
        httpd.shutdown()


def test_cors_preflight_allows_static_web_gateway_calls() -> None:
    httpd, port = _start_server()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/audio",
            method="OPTIONS",
            headers={
                "Origin": "https://mallo-kiosk.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == "*"
            assert "POST" in response.headers["Access-Control-Allow-Methods"]
            assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]
            assert "X-Mallo-Session-ID" in response.headers["Access-Control-Allow-Headers"]
            assert "X-Mallo-Request-ID" in response.headers["Access-Control-Allow-Headers"]
    finally:
        httpd.shutdown()


def test_gateway_logs_client_request_id_and_elapsed_time(caplog) -> None:
    httpd, port = _start_server()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/state",
            headers={
                "X-Mallo-Session-ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "X-Mallo-Request-ID": "req-1234abcd",
            },
        )
        with caplog.at_level(logging.DEBUG, logger="app.server"):
            with urllib.request.urlopen(request) as response:
                assert response.status == 200
                assert response.headers["Access-Control-Allow-Headers"].endswith("X-Mallo-Request-ID")

        messages = [record.getMessage() for record in caplog.records]
        assert any("gateway request start request_id=req-1234abcd" in message for message in messages)
        assert any("gateway request end request_id=req-1234abcd" in message and "elapsed_ms=" in message for message in messages)
    finally:
        httpd.shutdown()


def test_menu_metadata_and_image_assets_are_served() -> None:
    httpd, port = _start_server()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/menu-metadata.js") as resp:
            metadata = resp.read().decode("utf-8")
            assert resp.headers.get_content_type() == "application/javascript"
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/assets/menu/americano.png"
        ) as resp:
            image = resp.read()
            assert resp.headers.get_content_type() == "image/png"
            assert resp.headers.get("Content-Type") == "image/png"

        assert "assets/menu/americano.png" in metadata
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        httpd.shutdown()


@pytest.mark.parametrize(
    "asset",
    [
        "assets/icons/replay.svg",
        "assets/icons/speed.svg",
        "assets/icons/staff.svg",
        "assets/icons/home.svg",
        "assets/icons/microphone.svg",
        "assets/mascot/mallo-guide.svg",
    ],
)
def test_product_svg_assets_are_served_with_svg_mime(asset: str) -> None:
    httpd, port = _start_server()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/{asset}") as resp:
            body = resp.read()
            assert resp.status == 200
            assert resp.headers.get_content_type() == "image/svg+xml"
            assert body.startswith(b"<svg")
            assert b"viewBox=" in body
    finally:
        httpd.shutdown()


def test_microphone_input_monitor_is_served() -> None:
    httpd, port = _start_server()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/microphone-input-monitor.js"
        ) as resp:
            script = resp.read().decode("utf-8")
            assert resp.headers.get_content_type() == "application/javascript"
        assert "MicrophoneInputMonitor" in script
    finally:
        httpd.shutdown()


def test_static_asset_path_traversal_is_blocked() -> None:
    import urllib.error

    httpd, port = _start_server()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/assets/../server.py")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 404

        req_encoded = urllib.request.Request(
            f"http://127.0.0.1:{port}/assets/%2e%2e/server.py"
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_encoded)
        assert exc_info.value.code == 404
    finally:
        httpd.shutdown()


def test_gui_confirm_then_reset_cycle() -> None:
    # UI-09/UI-10/UI-11: 주문 확정은 cart를 유지하고, 새 주문(reset)이 비운다.
    httpd, port = _start_server()
    try:
        _post(port, "/api/commands", {"commands": [_command("SET_FULFILLMENT", fulfillment_type="takeout")]})
        _post(port, "/api/commands", {"commands": [_command("ADD_ITEM", target_item_id="americano", quantity=2, temperature="iced")]})
        confirmed = _post(port, "/api/commands", {"commands": [_command("CONFIRM_ORDER")]})
        assert "9,400" in confirmed["response_text"]
        assert confirmed["cart"]["confirmed"] is True
        # 확정 후에도 서버 세션 cart는 결제 완료 화면 표시 전까지 유지된다.
        state_after_confirm = _get(port, "/api/state")
        assert state_after_confirm["cart"]["total_price"] == 9400
        assert state_after_confirm["cart"]["confirmed"] is True

        reset = _post(port, "/api/reset", {})
        assert reset["status"] == "reset"
        state_after_reset = _get(port, "/api/state")
        assert state_after_reset["cart"]["items"] == []
    finally:
        httpd.shutdown()


def test_confirm_without_fulfillment_is_rejected() -> None:
    httpd, port = _start_server()
    try:
        _post(port, "/api/commands", {"commands": [_command("ADD_ITEM", target_item_id="americano", quantity=1, temperature="iced")]})
        result = _post(port, "/api/commands", {"commands": [_command("CONFIRM_ORDER")]})
        assert result["success"] is False
        assert result["cart"]["confirmed"] is False
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("fulfillment_type", ["dine_in", "takeout"])
def test_service_mode_click_payload_sets_fulfillment_via_commands(
    fulfillment_type: str,
) -> None:
    """web/app.js selectFulfillment()가 보내는 실제 semantic payload 회귀."""
    httpd, port = _start_server()
    try:
        payload = {
            "commands": [
                {
                    "intent": "SET_FULFILLMENT",
                    "target_item_id": None,
                    "category_id": None,
                    "quantity": None,
                    "temperature": None,
                    "query_tags": None,
                    "detail_fields": None,
                    "options": None,
                    "fulfillment_type": fulfillment_type,
                }
            ]
        }
        result = _post(port, "/api/commands", payload)
        assert result["success"] is True
        assert result["error_code"] is None
        assert result["cart"]["fulfillment_type"] == fulfillment_type
    finally:
        httpd.shutdown()


def test_commands_bypass_nlu_and_support_both_fulfillment_orders() -> None:
    httpd, port = _start_server()
    try:
        pipeline = httpd.mallo_app.service._pipeline  # type: ignore[attr-defined]
        calls = []
        original = pipeline._nlu.parse
        pipeline._nlu.parse = lambda *args: (calls.append(args), original(*args))[1]
        for commands in (
            [_command("ADD_ITEM", target_item_id="americano", quantity=1, temperature="iced"), _command("SET_FULFILLMENT", fulfillment_type="takeout")],
            [_command("SET_FULFILLMENT", fulfillment_type="dine_in"), _command("ADD_ITEM", target_item_id="americano", quantity=1, temperature="iced")],
        ):
            _post(port, "/api/reset", {})
            for command in commands:
                _post(port, "/api/commands", {"commands": [command]})
            confirmed = _post(port, "/api/commands", {"commands": [_command("CONFIRM_ORDER")]})
            assert confirmed["success"] is True and confirmed["cart"]["confirmed"] is True
        assert calls == []
    finally:
        httpd.shutdown()


def test_audio_uses_stt_nlu_and_order_engine_pipeline() -> None:
    httpd, port = _start_server()
    try:
        pipeline = httpd.mallo_app.service._pipeline  # type: ignore[attr-defined]
        calls = []
        original_stt = pipeline._stt.transcribe
        original_nlu = pipeline._nlu.parse
        original_agent = pipeline._agent.execute
        pipeline._stt.transcribe = lambda audio: (calls.append("stt"), original_stt(audio))[1]
        pipeline._nlu.parse = lambda text, cart: (calls.append("nlu"), original_nlu(text, cart))[1]
        pipeline._agent.execute = lambda commands, cart: (calls.append("engine"), original_agent(commands, cart))[1]
        result = _post(port, "/api/audio", raw=b"audio")
        assert result["success"] is True
        assert calls == ["stt", "nlu", "engine"]
    finally:
        httpd.shutdown()


def test_split_audio_turn_shows_stt_before_server_nlu_and_engine() -> None:
    httpd, port = _start_server()
    try:
        pipeline = httpd.mallo_app.service._pipeline  # type: ignore[attr-defined]
        calls = []
        original_stt = pipeline._stt.transcribe
        original_nlu = pipeline._nlu.parse
        original_agent = pipeline._agent.execute
        pipeline._stt.transcribe = lambda audio: (calls.append("stt"), original_stt(audio))[1]
        pipeline._nlu.parse = lambda text, cart: (calls.append("nlu"), original_nlu(text, cart))[1]
        pipeline._agent.execute = lambda commands, cart: (calls.append("engine"), original_agent(commands, cart))[1]

        stt = _post(port, "/api/audio/stt", raw=b"audio")
        assert stt["text"] == "아이스 아메리카노 두 잔 주세요"
        assert calls == ["stt"]

        result = _post(port, "/api/audio/interpret", {"transcript": stt["text"]})
        assert result["success"] is True
        assert calls == ["stt", "nlu", "engine"]
    finally:
        httpd.shutdown()


def test_audio_interpret_pending_new_menu_never_replaces_existing_cart_item() -> None:
    httpd, port = _start_server()
    try:
        session_id = "pending-new-menu"
        first = _post_session(
            port, session_id, "/api/audio/interpret", {"transcript": "아이스 아메리카노 두 잔"},
        )
        pending = _post_session(
            port, session_id, "/api/audio/interpret", {"transcript": "카페라떼 한잔 주세요"},
        )
        completed = _post_session(
            port, session_id, "/api/audio/interpret", {"transcript": "아이스로"},
        )

        assert first["order_commands"][0]["intent"] == "ADD_ITEM"
        assert [(item["menu_id"], item["temperature"], item["quantity"]) for item in first["cart"]["items"]] == [
            ("americano", "iced", 2)
        ]
        assert pending["success"] is False
        assert pending["error_code"] == "MISSING_FIELD"
        assert pending["order_commands"] == []
        assert pending["cart"] == first["cart"]
        assert [(item["menu_id"], item["temperature"], item["quantity"]) for item in completed["cart"]["items"]] == [
            ("americano", "iced", 2),
            ("cafe_latte", "iced", 1),
        ]
        assert completed["order_commands"][0]["intent"] == "ADD_ITEM"
        assert completed["order_commands"][0]["target_item_id"] == "cafe_latte"
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("change", [_command("ADD_ITEM", target_item_id="cafe_latte", quantity=1, temperature="hot"), _command("SET_FULFILLMENT", fulfillment_type="takeout")])
def test_confirmed_cart_changes_invalidate_confirmation(change) -> None:
    httpd, port = _start_server()
    try:
        _post(port, "/api/commands", {"commands": [_command("SET_FULFILLMENT", fulfillment_type="dine_in")]})
        _post(port, "/api/commands", {"commands": [_command("ADD_ITEM", target_item_id="americano", quantity=1, temperature="iced")]})
        _post(port, "/api/commands", {"commands": [_command("CONFIRM_ORDER")]})
        changed = _post(port, "/api/commands", {"commands": [change]})
        assert changed["success"] is True and changed["cart"]["confirmed"] is False
    finally:
        httpd.shutdown()


def test_state_exposes_tts_level() -> None:
    httpd, port = _start_server()
    try:
        _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        _post(port, "/api/tts-control", {"intent": "REQUEST_SLOWER"})
        state = _get(port, "/api/state")
        assert state["tts_level"] == 1
    finally:
        httpd.shutdown()


def test_build_service_and_server_with_custom_service() -> None:
    from app.service import build_service

    service = build_service(tts_backend="mock", stt_backend="mock", stt_device="auto")
    httpd = build_server("127.0.0.1", 0, service=service)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        order = _post(port, "/api/order", {"text": "아이스 아메리카노 두 잔 주세요"})
        assert order["success"] is True
        assert order["cart"]["items"][0]["quantity"] == 2
    finally:
        httpd.shutdown()


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except (ImportError, OSError):  # 손상된 설치는 ImportError가 아니라 OSError로 실패한다
        return False


@pytest.mark.skipif(
    not _torch_available(),
    reason="torch을 임포트할 수 없는 환경에서는 Whisper 백엔드 빌드를 건너뜁니다",
)
def test_build_service_stt_and_tts_device_resolution() -> None:
    from app.service import build_service

    # Whisper STT with auto device should resolve to None -> cuda/cpu (not string 'auto')
    service = build_service(
        tts_backend="mock",
        stt_backend="whisper",
        stt_device="auto",
    )
    assert hasattr(service._pipeline._stt, "device")
    assert service._pipeline._stt.device in ("cuda", "cpu")  # type: ignore[union-attr]


_JSON_ENDPOINTS = ("/api/order", "/api/fulfillment", "/api/tts-control")


@pytest.mark.parametrize("payload", [[], ["text"], "text", None, 123, 1.5, True])
def test_non_object_json_body_returns_400(payload) -> None:
    """문법상 유효하지만 object가 아닌 JSON도 400으로 거절한다."""
    httpd, port = _start_server()
    try:
        for path in _JSON_ENDPOINTS:
            status, body = _post_raw(port, path, json.dumps(payload).encode("utf-8"))
            assert status == 400, f"{path} with {payload!r}"
            assert body == {"error": "invalid json"}
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("path", _JSON_ENDPOINTS)
def test_malformed_json_bytes_return_400(path: str) -> None:
    httpd, port = _start_server()
    try:
        status, body = _post_raw(port, path, b"{not-json")
        assert status == 400
        assert body == {"error": "invalid json"}
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("path", _JSON_ENDPOINTS)
def test_invalid_utf8_body_returns_400_and_handler_survives(path: str) -> None:
    """UTF-8 디코딩에 실패하는 본문도 400으로 거절하고 이후 요청을 계속 처리한다."""
    httpd, port = _start_server()
    try:
        status, body = _post_raw(port, path, b"\xff")
        assert status == 400
        assert body == {"error": "invalid json"}
        order = _post(port, "/api/order", {"text": "아이스 아메리카노 한 잔 주세요"})
        assert order["success"] is True
        assert order["cart"]["items"][0]["menu_id"] == "americano"
    finally:
        httpd.shutdown()


@pytest.mark.parametrize(
    "bad_body", [b"[]", b"null", b'"just a string"', b"{oops"]
)
def test_handler_survives_bad_requests_and_serves_valid_order(bad_body: bytes) -> None:
    """잘못된 요청 후에도 핸들러 스레드가 살아 있고 정상 요청을 처리한다."""
    httpd, port = _start_server()
    try:
        status, _ = _post_raw(port, "/api/order", bad_body)
        assert status == 400
        order = _post(port, "/api/order", {"text": "아이스 아메리카노 한 잔 주세요"})
        assert order["success"] is True
        assert order["cart"]["items"][0]["menu_id"] == "americano"
    finally:
        httpd.shutdown()
