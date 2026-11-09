from __future__ import annotations

from domain.intents import Intent


class AdaptiveTTSController:
    """Adaptive TTS Level 상태 머신 및 세션 제어기 (Level 0, 1, 2)."""

    def __init__(self, initial_level: int = 0) -> None:
        self._level: int = int(initial_level)
        if self._level not in (0, 1, 2):
            raise ValueError(f"Invalid initial TTS level: {self._level}. Must be 0, 1, or 2.")

    @property
    def current_level(self) -> int:
        """현재 세션의 TTS Level (0, 1, 2) 반환."""
        return self._level

    def increase_level(self) -> int:
        """TTS Level을 1단계 상승 (최대 Level 2 상한선 유지)."""
        if self._level < 2:
            self._level += 1
        return self._level

    def decrease_level(self) -> int:
        """TTS Level을 1단계 하강 (최소 Level 0 하한선 유지)."""
        if self._level > 0:
            self._level -= 1
        return self._level

    def set_level(self, level: int) -> int:
        """TTS Level을 명시적으로 설정."""
        lvl = int(level)
        if lvl not in (0, 1, 2):
            raise ValueError(f"Invalid TTS level: {level}. Must be 0, 1, or 2.")
        self._level = lvl
        return self._level

    def reset(self) -> None:
        """신규 주문 세션 시작 시 Level 0으로 초기화."""
        self._level = 0

    def cycle_level(self) -> int:
        """접근성 버튼용 0 → 1 → 2 → 0 순환."""
        self._level = (self._level + 1) % 3
        return self._level

    def handle_intent(self, intent: Intent | str) -> int:
        """NLU Intent에 따라 Level 전이를 수행하고 변경된 Level 반환."""
        intent_value = intent.value if isinstance(intent, Intent) else intent

        if intent_value == Intent.REQUEST_SLOWER.value:
            return self.increase_level()
        elif intent_value == Intent.REQUEST_DEFAULT_SPEED.value:
            self._level = 0
            return self._level

        # 기타 일반 Intent는 레벨을 변경하지 않음
        return self._level
