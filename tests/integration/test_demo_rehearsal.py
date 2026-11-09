"""E-10 최종 데모 리허설.

E-08(데모 시나리오) 5-Turn Happy Path를 통합 파이프라인(MalloService)과
실제 Web 백엔드(ThreadingHTTPServer) 양쪽에서 발표 순서대로 실행해
AC-01(인텐트 정합성) ~ AC-04(오프라인 로컬 실행)를 검증한다.
"""
from __future__ import annotations

import json
import threading
import urllib.request

from adapters.nlu.mock_nlu import MockNLU
from adapters.stt.mock_stt import MockSTT
from adapters.tts.mock_tts import MockTTS
from app.server import build_server
from app.service import build_mock_service
from domain.intents import Intent
from domain.models import Cart, FulfillmentType, Temperature


# (발화, 기대 Intent) — E-08 5-Turn Happy Path
DEMO_TURNS = [
    ("따뜻한 음료 뭐 있어요?", Intent.QUERY_MENU),
    ("아메리카노 따뜻한 거 두 잔이랑 바스크 치즈 케이크 하나 주세요", Intent.ADD_ITEM),
    ("말이 좀 빠른데 천천히 다시 말해줘", Intent.REQUEST_SLOWER),
    ("아메리카노를 아이스로 바꿔줘", Intent.UPDATE_OPTION),
    ("주문 다 했어, 결제할게", Intent.CONFIRM_ORDER),
]


def _find(cart: Cart, menu_id: str, temperature: Temperature | None):
    for item in cart.items:
        if item.menu_id == menu_id and item.temperature == temperature:
            return item
    return None


def test_demo_turns_recognize_expected_intents():
    """AC-01: 5턴 발화가 현재 NLU Intent와 100% 일치해야 한다."""
    svc = build_mock_service()
    cart = Cart()
    for text, expected in DEMO_TURNS:
        parsed = svc._pipeline._nlu.parse(text, cart)
        assert isinstance(parsed, list) and parsed, f"NLU 인식 실패: {text}"
        assert parsed[0].intent == expected, f"{text} -> {parsed[0].intent}"


def test_demo_rehearsal_runs_end_to_end():
    """AC-02/AC-03/AC-04: 서비스 파이프라인에서 5턴을 중단 없이 완주한다."""
    svc = build_mock_service()

    # AC-04: 오프라인 로컬 실행 — 외부 네트워크 호출 없이 mock 어댑터만 사용
    from orchestrator.rule_first_nlu import RuleFirstNLU
    assert isinstance(svc._pipeline._nlu, (MockNLU, RuleFirstNLU))
    assert isinstance(svc._pipeline._tts, MockTTS)
    assert isinstance(svc._pipeline._stt, MockSTT)

    cart = Cart(fulfillment_type=FulfillmentType.DINE_IN)

    # Turn 1 — 메뉴 탐색 (QUERY_MENU, cart 미변경, Level 0)
    res = svc.handle_text(DEMO_TURNS[0][0], cart)
    cart = res.cart
    assert res.success
    assert cart.items == []
    assert svc.tts_level == 0

    # Turn 2 — 복합 주문 (hot americano x2 + basque_cheesecake x1)
    res = svc.handle_text(DEMO_TURNS[1][0], cart)
    cart = res.cart
    assert res.success
    hot = _find(cart, "americano", Temperature.HOT)
    cake = _find(cart, "basque_cheesecake", None)
    assert hot is not None and hot.quantity == 2
    assert cake is not None and cake.quantity == 1

    # Turn 3 — Voice UX 속도 제어 → Level 1 상승 (AC-02)
    res = svc.handle_text(DEMO_TURNS[2][0], cart)
    cart = res.cart
    assert res.success
    assert svc.tts_level == 1

    # Turn 4 — 옵션/온도 수정 → 전체 아이스 변경 (AC-03)
    res = svc.handle_text(DEMO_TURNS[3][0], cart)
    cart = res.cart
    assert res.success
    assert _find(cart, "americano", Temperature.HOT) is None
    iced = _find(cart, "americano", Temperature.ICED)
    assert iced is not None and iced.quantity == 2
    assert _find(cart, "basque_cheesecake", None).quantity == 1

    # Turn 5 — 주문 확정 (Level 1 유지)
    res = svc.handle_text(DEMO_TURNS[4][0], cart)
    cart = res.cart
    assert res.success
    assert svc.tts_level == 1


def test_demo_rehearsal_over_http_server():
    """실제 Web 백엔드(ThreadingHTTPServer)에서 발표 순서대로 완주한다."""
    httpd = build_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{port}"

    def post(text: str) -> dict:
        request = urllib.request.Request(
            f"{base}/api/order",
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())

    def state() -> dict:
        with urllib.request.urlopen(f"{base}/api/state") as response:
            return json.loads(response.read())

    try:
        req_ful = urllib.request.Request(
            f"{base}/api/fulfillment",
            data=json.dumps({"fulfillment_type": "dine_in"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_ful) as response:
            assert json.loads(response.read())["success"] is True

        # Turn 1 → Level 0
        post(DEMO_TURNS[0][0])
        assert state()["tts_level"] == 0

        # Turn 2 → hot americano x2, cheesecake x1
        post(DEMO_TURNS[1][0])
        items = {(i["menu_id"], i["temperature"]): i["quantity"] for i in state()["cart"]["items"]}
        assert items[("americano", "hot")] == 2
        assert items[("basque_cheesecake", None)] == 1

        # Turn 3 → Level 1
        post(DEMO_TURNS[2][0])
        assert state()["tts_level"] == 1

        # Turn 4 → 아이스 americano x2, cheesecake x1
        post(DEMO_TURNS[3][0])
        items = {(i["menu_id"], i["temperature"]): i["quantity"] for i in state()["cart"]["items"]}
        assert ("americano", "hot") not in items
        assert items[("americano", "iced")] == 2
        assert items[("basque_cheesecake", None)] == 1

        # Turn 5 → Level 1 유지, 확정 성공
        result = post(DEMO_TURNS[4][0])
        assert result["success"] is True
        assert state()["tts_level"] == 1
    finally:
        httpd.shutdown()
