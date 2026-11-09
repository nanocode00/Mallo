from __future__ import annotations

import pytest

from domain.intents import Intent
from domain.models import AdaptiveTTSController


def test_initial_controller_state() -> None:
    """새 컨트롤러 생성 시 기본 Level은 0이어야 한다 (AC-01)."""
    controller = AdaptiveTTSController()
    assert controller.current_level == 0


def test_increase_level_on_request_slower() -> None:
    """REQUEST_SLOWER 수신 시 0->1->2로 순차 상승하고 최대 2를 유지해야 한다 (AC-02, EC-01)."""
    controller = AdaptiveTTSController()

    # 0 -> 1
    assert controller.handle_intent(Intent.REQUEST_SLOWER) == 1
    assert controller.current_level == 1

    # 1 -> 2
    assert controller.handle_intent(Intent.REQUEST_SLOWER) == 2
    assert controller.current_level == 2

    # 2 -> 2 (상한선 유지)
    assert controller.handle_intent(Intent.REQUEST_SLOWER) == 2
    assert controller.current_level == 2


def test_request_repeat_keeps_current_level() -> None:
    """재안내만으로는 TTS 속도를 바꾸지 않아야 한다."""
    controller = AdaptiveTTSController(initial_level=1)

    assert controller.handle_intent(Intent.REQUEST_REPEAT) == 1
    assert controller.handle_intent(Intent.REQUEST_REPEAT) == 1
    assert controller.current_level == 1


def test_reset_to_default_speed() -> None:
    """REQUEST_DEFAULT_SPEED 수신 시 즉시 Level 0으로 복귀해야 한다 (AC-03)."""
    controller = AdaptiveTTSController(initial_level=2)
    assert controller.current_level == 2

    assert controller.handle_intent(Intent.REQUEST_DEFAULT_SPEED) == 0
    assert controller.current_level == 0


def test_reset_clears_level() -> None:
    """신규 세션 reset() 호출 시 Level 0으로 초기화되어야 한다 (AC-04)."""
    controller = AdaptiveTTSController(initial_level=2)
    assert controller.current_level == 2

    controller.reset()
    assert controller.current_level == 0


def test_decrease_level_respects_lower_bound() -> None:
    """decrease_level() 호출 시 0 미만으로 내려가지 않아야 한다 (EC-02)."""
    controller = AdaptiveTTSController(initial_level=1)

    assert controller.decrease_level() == 0
    assert controller.decrease_level() == 0
    assert controller.current_level == 0


def test_set_level_valid_and_invalid() -> None:
    """set_level()은 유효한 레벨만 설정하고 잘못된 값은 거부해야 한다 (EC-04)."""
    controller = AdaptiveTTSController()

    assert controller.set_level(1) == 1
    assert controller.set_level(2) == 2

    with pytest.raises(ValueError, match="Invalid TTS level"):
        controller.set_level(3)

    with pytest.raises(ValueError, match="Invalid TTS level"):
        controller.set_level(-1)


def test_other_intents_do_not_change_level() -> None:
    """TTS와 무관한 Intent는 Level을 변경하지 않아야 한다 (EC-03)."""
    controller = AdaptiveTTSController(initial_level=1)

    assert controller.handle_intent(Intent.ADD_ITEM) == 1
    assert controller.handle_intent(Intent.CONFIRM_ORDER) == 1
    assert controller.current_level == 1


def test_cycle_level_wraps_from_two_to_zero() -> None:
    controller = AdaptiveTTSController()

    assert [controller.cycle_level() for _ in range(3)] == [1, 2, 0]
