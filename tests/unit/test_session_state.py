from __future__ import annotations

from domain.models import Cart, CartItem, ErrorCode, SessionState, SessionStatus, Temperature


def test_initial_session_state() -> None:
    """새 SessionState 생성 시 기본 상태가 올바르게 설정되어야 한다 (AC-01)."""
    state = SessionState()
    assert state.status == SessionStatus.IDLE
    assert state.cart.items == []
    assert state.cart.total_price == 0
    assert state.tts_level == 0
    assert state.error_code is None
    assert "안녕하세요" in state.last_response


def test_session_state_to_dict_empty_cart() -> None:
    """빈 장바구니를 가진 SessionState의 직렬화 결과가 올바른 구조를 가져야 한다 (AC-02)."""
    state = SessionState()
    data = state.to_dict()

    assert data["status"] == "IDLE"
    assert data["cart"]["items"] == []
    assert data["cart"]["total_price"] == 0
    assert data["tts_level"] == 0
    assert data["error_code"] is None


def test_session_state_with_cart_items() -> None:
    """장바구니 항목이 추가된 SessionState가 총액과 함께 올바르게 직렬화되어야 한다 (AC-04)."""
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=2,
                temperature=Temperature.ICED,
                unit_price=4700,
            ),
            CartItem(
                menu_id="caffe_latte",
                quantity=1,
                temperature=Temperature.HOT,
                unit_price=5200,
            ),
        ]
    )
    state = SessionState(
        status=SessionStatus.CONFIRMING,
        cart=cart,
        last_response="아이스 아메리카노 두 잔, 따뜻한 카페라떼 한 잔을 담았습니다.",
        tts_level=1,
        error_code=None,
    )

    data = state.to_dict()
    assert data["status"] == "CONFIRMING"
    assert len(data["cart"]["items"]) == 2
    assert data["cart"]["items"][0]["menu_id"] == "americano"
    assert data["cart"]["items"][0]["temperature"] == "iced"
    assert data["cart"]["items"][0]["options"] == {
        "size": None,
        "extra_shots": None,
        "caffeine": None,
        "syrup_pumps": None,
        "ice_amount": None,
    }
    assert data["cart"]["items"][0]["total_price"] == 9400
    assert data["cart"]["total_price"] == 14600
    assert data["tts_level"] == 1


def test_session_state_with_error() -> None:
    """오류 코드가 포함된 SessionState가 올바르게 직렬화되어야 한다."""
    state = SessionState(
        status=SessionStatus.IDLE,
        error_code=ErrorCode.MENU_NOT_FOUND,
        last_response="존재하지 않는 메뉴입니다.",
    )
    data = state.to_dict()
    assert data["error_code"] == "MENU_NOT_FOUND"


def test_session_status_enum_values() -> None:
    """SessionStatus의 모든 8개 상태 값이 정의되어 있어야 한다."""
    expected = {
        "IDLE",
        "LISTENING",
        "PROCESSING",
        "SPEAKING",
        "CONFIRMING",
        "CLARIFYING",
        "PAYMENT",
        "SESSION_END",
    }
    actual = {s.value for s in SessionStatus}
    assert actual == expected
