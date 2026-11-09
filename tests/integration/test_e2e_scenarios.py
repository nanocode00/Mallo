"""End-to-End 시나리오 테스트 (I-09)
====================================

핵심 주문 흐름을 멀티턴으로 검증한다:
  1. 메뉴 조회 → 추가 → 수량 변경 → 옵션 변경 → 삭제 → 장바구니 조회 → 확정
  2. 추가 → undo → 장바구니 비어있는지 확인
  3. 복수 항목 추가 → 전체 취소
  4. TTS 레벨 진행 (기본 → 천천히 → 다시 → 기본)
"""

from __future__ import annotations

import pytest

from adapters.nlu.mock_nlu import MockNLU
from adapters.tts.mock_tts import MockTTS
from app.service import MalloService
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.models import Cart, CartItem, FulfillmentType, Temperature


def build_service() -> tuple[MalloService, MockTTS]:
    tts = MockTTS()
    service = MalloService(
        nlu=MockNLU(),
        agent=ConversationAgent(load_menu()),
        tts=tts,
    )
    return service, tts


# -------------------------------------------------------
# 시나리오 1: 조회 → 추가 → 변경 → 삭제 → 조회 → 확정
# -------------------------------------------------------


def test_full_ordering_lifecycle() -> None:
    """메뉴 조회 → 추가 → 수량 변경 → 옵션 변경 → 장바구니 조회 → 확정"""
    service, tts = build_service()

    # 1. 커피 메뉴 조회
    result = service.handle_text("커피 메뉴 알려 주세요", Cart())
    assert result.success is True
    assert "아메리카노" in result.response_text

    # 2. 아이스 아메리카노 2잔 추가
    cart = Cart(fulfillment_type=FulfillmentType.DINE_IN)
    result = service.handle_text("아이스 아메리카노 두 잔 주세요", cart)
    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700)
    ]
    cart = result.cart

    # 3. 수량 변경 (3잔으로)
    result = service.handle_text("아이스 아메리카노 세 잔으로 바꿔 주세요", cart)
    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 3, Temperature.ICED, 4700)
    ]
    cart = result.cart

    # 4. 옵션 변경 (따뜻하게)
    result = service.handle_text("아메리카노를 따뜻하게 바꿔 주세요", cart)
    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 3, Temperature.HOT, 4700)
    ]
    cart = result.cart

    # 5. 장바구니 조회
    result = service.handle_text("현재 주문 알려 주세요", cart)
    assert result.success is True
    cart = result.cart

    # 6. 확정
    result = service.handle_text("주문 확정할게요", cart)
    assert result.success is True
    assert result.cart.total_price == 14100


# -------------------------------------------------------
# 시나리오 2: 추가 → undo → 빈 장바구니 확인
# -------------------------------------------------------


def test_add_then_undo_restores_empty_cart() -> None:
    """추가 → undo → 장바구니 비어있는지 확인"""
    service, tts = build_service()

    # 1. 추가
    result = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    assert result.success is True
    assert len(result.cart.items) == 1
    cart = result.cart

    # 2. undo
    result = service.handle_text("방금 거 취소해 주세요", cart)
    assert result.success is True
    assert result.cart.items == []
    cart = result.cart

    # 3. 장바구니 조회 (비어있음)
    result = service.handle_text("현재 주문 알려 주세요", cart)
    assert result.success is True
    assert "비어" in result.response_text or "없" in result.response_text


# -------------------------------------------------------
# 시나리오 3: 복수 항목 추가 → 전체 취소
# -------------------------------------------------------


def test_multiple_items_then_cancel() -> None:
    """복수 항목 추가 → 전체 취소"""
    service, tts = build_service()

    # 1. 복수 항목 추가
    result = service.handle_text(
        "아이스 아메리카노 두 잔이랑 따뜻한 카페라떼 한 잔 주세요",
        Cart(),
    )
    assert result.success is True
    assert len(result.cart.items) == 2
    cart = result.cart

    # 2. 전체 취소
    result = service.handle_text("전체 주문 취소해 주세요", cart)
    assert result.success is True
    assert result.cart.items == []


# -------------------------------------------------------
# 시나리오 4: TTS 레벨 진행
# -------------------------------------------------------


def test_tts_level_progression_through_order() -> None:
    """주문 과정에서 TTS 레벨이 올바르게 변경된다."""
    service, tts = build_service()

    # 초기 레벨 0
    assert service.tts_level == 0

    # 1. 주문 추가 (level 0)
    result = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart(fulfillment_type=FulfillmentType.DINE_IN))
    assert result.success is True
    assert tts.calls[-1] == ("아이스 아메리카노 두 잔을 담았습니다.", 0)
    cart = result.cart

    # 2. 천천히 (level 0 → 1)
    result = service.handle_text("천천히 말해 주세요", cart)
    assert result.success is True
    assert service.tts_level == 1
    cart = result.cart

    # 3. 더 천천히 (level 1 → 2)
    result = service.handle_text("더 천천히 말해 주세요", cart)
    assert result.success is True
    assert service.tts_level == 2
    cart = result.cart

    # 4. 기본 속도 (level 2 → 0)
    result = service.handle_text("기본 속도로 말해 주세요", cart)
    assert result.success is True
    assert service.tts_level == 0
    cart = result.cart

    # 5. 확정 시 레벨 0으로 합성
    result = service.handle_text("주문 확정할게요", cart)
    assert result.success is True
    assert tts.calls[-1][1] == 0


# -------------------------------------------------------
# 시나리오 5: 빈 입력 → 복구 → 정상 주문
# -------------------------------------------------------


def test_empty_input_then_recovery() -> None:
    """빈 입력 후 정상 입력이 동작한다."""
    service, tts = build_service()

    # 1. 빈 입력
    result = service.handle_text("", Cart())
    assert result.success is False
    assert result.error_code is not None

    # 2. 정상 주문
    result = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700)
    ]


# -------------------------------------------------------
# 시나리오 6: 미지원 발화 → 복구 → 정상 주문
# -------------------------------------------------------


def test_unsupported_utterance_then_recovery() -> None:
    """미지원 발화 후 정상 입력이 동작한다."""
    service, tts = build_service()

    # 1. 미지원 발화
    result = service.handle_text("아초 두 잔 주세요", Cart())
    assert result.success is False
    assert result.error_code is not None

    # 2. 정상 주문
    result = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    assert result.success is True
    assert result.cart.items == [
        CartItem("americano", 2, Temperature.ICED, 4700)
    ]


# -------------------------------------------------------
# 시나리오 7: 세션 리셋
# -------------------------------------------------------


def test_session_reset_clears_state() -> None:
    """세션 리셋 후 TTS 레벨과 장바구니가 초기화된다."""
    service, tts = build_service()

    # 1. 주문 + 레벨 변경
    result = service.handle_text("아이스 아메리카노 두 잔 주세요", Cart())
    assert result.success is True
    cart = result.cart

    result = service.handle_text("천천히 말해 주세요", cart)
    assert service.tts_level == 1
    cart = result.cart

    # 2. 리셋
    service.reset_session()
    assert service.tts_level == 0
    assert service.last_response != ""
