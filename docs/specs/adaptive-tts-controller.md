---
title: "T-16~T-19 — Adaptive TTS Controller (Level 상태 관리 및 전이)"
tags: [spec]
---

# T-16~T-19 — Adaptive TTS Controller (Level 상태 관리 및 전이)

> 이 문서는 사용자의 음성 요청(NLU Intent) 또는 GUI 버튼 입력에 따라 세션별 Adaptive TTS Level(0: 기본, 1: 느리게/Pause, 2: 단문분절/강조)을 제어하고 초기화하는 `AdaptiveTTSController` 기준 계약이다.

## Why

- **페르소나**: 고령 사용자, 세션 오케스트레이터 개발자, GUI 제어 연동 개발자
- **상황**:
  - 사용자가 안내를 잘 알아듣지 못해 "천천히 말해줘"(`REQUEST_SLOWER`), "다시 말해줘"(`REQUEST_REPEAT`)라고 하거나, "보통 속도로 해줘"(`REQUEST_DEFAULT_SPEED`)라고 요청했을 때 현재 주문 세션의 TTS 모드를 변경하여 후속 안내 음성에 일관되게 적용해야 한다.
  - 주문이 완료되거나 새 세션이 시작되면 이전 사용자의 Level 설정이 남아있지 않고 기본 Level 0으로 안전하게 초기화되어야 한다.
- **문제**:
  - 중앙 집중식 상태 머신이 없으면 매 턴마다 기본값으로 리셋되거나, 반대로 세션 종료 후에도 느린 모드가 남아 다음 사용자의 경험을 해칠 수 있다.
- **측정 지표**:
  - Intent 기반 Level 전이 정확도 100%
  - 세션 Reset 시 Level 0 초기화율 100%
  - 상태 전이 소요 시간 < 1ms

## Goal

- **해결 목표**:
  - `AdaptiveTTSController` 도메인 상태 관리 클래스를 구현한다.
  - Level 상승 조건(`REQUEST_SLOWER`, GUI 느리게 버튼)을 처리한다.
  - Level 하강 조건(`REQUEST_DEFAULT_SPEED`, GUI 기본속도 버튼)을 처리한다.
  - 신규 세션 시작 시 `reset()`을 통해 Level 0으로 안전하게 초기화한다.
- **성공 기준**:
  - 상태 전이 단위 테스트(AC-01 ~ AC-04) 100% 통과.
- **Out of Scope**:
- 생체 정보나 사용자의 나이를 임의로 추정하여 자동으로 Level을 변경하는 행위. 단, 현재 세션에서 NLU가 명확히 분류한 `REQUEST_CLARIFICATION`의 짧은 반복은 안내 이해 실패의 직접 신호로 취급한다.

## What

### Happy Path (Level 전이 규칙)

| 현재 Level | 이벤트 / Intent | 전이 후 Level | 비고 |
|---|---|---|---|
| Level 0 | `REQUEST_SLOWER` ("천천히 말해줘") | **Level 1** | 발화 속도 0.85x 및 Pause 강화 |
| Level 1 | `REQUEST_SLOWER` ("더 천천히 말해줘") | **Level 2** | 발화 속도 0.75x, 단문 분절 및 핵심 정보 강조 |
| Level 2 | `REQUEST_SLOWER` | **Level 2** | 최대 레벨 유지 (상한선) |
| 임의의 Level | `REQUEST_REPEAT` ("다시 말해줘") | **현재 Level 유지** | 재안내·오류 복구만으로 속도를 변경하지 않음 |
| Level 1 또는 2 | `REQUEST_DEFAULT_SPEED` ("기본 속도로", "빨리") | **Level 0** | 즉시 기본 레벨(Level 0)로 복귀 |
| 임의의 Level | `reset()` (신규 주문 세션 시작) | **Level 0** | 기본값 초기화 |
| Level 0 또는 1 | 최근 4개의 성공적으로 해석된 의미 turn 안에서 두 번째 `REQUEST_CLARIFICATION` | **한 단계 증가** | 첫 신호는 원문 재안내, 두 번째에서만 음성 알림 후 새 Level로 재안내 |
| Level 2 | 위 조건 | **Level 2** | 자동 복귀·상한 초과 없음 |

### Edge Cases (최소 4개 + 처리 방식)

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 이미 Level 2인 상태에서 `increase_level()` 호출 | `Level 2` 유지 (상한선 초과 방지) |
| EC-02 | 이미 Level 0인 상태에서 `decrease_level()` 호출 | `Level 0` 유지 (하한선 미만 방지) |
| EC-03 | TTS 제어와 무관한 일반 Intent(예: `ADD_ITEM`)가 전달된 경우 | 현재 Level을 변경하지 않고 그대로 유지 |
| EC-04 | 직접 `set_level(level)`로 유효하지 않은 값(예: 3, -1) 전달 | `ValueError` 발생 |
| EC-05 | STT 실패, NLU 실패, timeout/no speech, 시스템 재질문 | comprehension history에 추가하거나 Level을 바꾸지 않음 |

### Comprehension signal 및 presentation 계약

- `REQUEST_CLARIFICATION`은 주문/NLU 경로에서 의미적으로 분류하는 별도 intent다. 원시 STT 문자열을 frontend regex로 처리하지 않는다.
- history window는 **성공적으로 의미 해석된 최근 4개 사용자 turn**이다. 실패 turn은 signal도 window turn도 아니므로, 시스템이 사용자를 못 알아들은 경우를 사용자의 이해 실패로 오인하지 않는다.
- 첫 signal은 현재 replayable 안내를 현재 Level로 다시 제공한다. 두 번째 signal로 Level이 실제 바뀌면 history를 즉시 reset하고, `조금 더 천천히 안내해 드릴게요.`를 speech-only로 먼저 재생한 뒤 원래 안내를 새 Level로 재생한다.
- 이 알림은 Response Bar 또는 replay source를 바꾸지 않으며, 자동 감속 후에도 자동 가속은 없다. `reset()`은 Level과 history 모두 지운다.

## How

### 1. AdaptiveTTSController 클래스 정의 (`src/domain/tts_controller.py`)

```python
class AdaptiveTTSController:
    def __init__(self, initial_level: int = 0) -> None:
        self._level: int = initial_level

    @property
    def current_level(self) -> int:
        return self._level

    def increase_level(self) -> int:
        if self._level < 2:
            self._level += 1
        return self._level

    def decrease_level(self) -> int:
        if self._level > 0:
            self._level -= 1
        return self._level

    def reset(self) -> None:
        self._level = 0

    def set_level(self, level: int) -> int:
        if level not in (0, 1, 2):
            raise ValueError(f"Invalid TTS level: {level}. Must be 0, 1, or 2.")
        self._level = level
        return self._level

    def handle_intent(self, intent: Intent | str) -> int:
        intent_value = intent.value if isinstance(intent, Intent) else intent
        if intent_value == Intent.REQUEST_SLOWER.value:
            return self.increase_level()
        elif intent_value == Intent.REQUEST_DEFAULT_SPEED.value:
            self._level = 0
            return self._level
        return self._level
```

## AC (Given-When-Then)

### AC-01 · 신규 컨트롤러 생성 및 초기 상태
- **GIVEN**: 새 `AdaptiveTTSController`가 생성되었을 때
- **WHEN**: `current_level`을 조회한다
- **THEN**: 기본값 `0` (Level 0)이어야 한다.

### AC-02 · REQUEST_SLOWER에 의한 순차적 레벨 상승
- **GIVEN**: 초기 Level 0 상태에서
- **WHEN**: `handle_intent(Intent.REQUEST_SLOWER)`를 연속 3회 호출한다
- **THEN**: 레벨이 0 -> 1 -> 2 -> 2(상한선 유지)로 전이된다.

### AC-03 · REQUEST_DEFAULT_SPEED에 의한 기본 레벨 복귀
- **GIVEN**: Level 2 상태에서
- **WHEN**: `handle_intent(Intent.REQUEST_DEFAULT_SPEED)`를 호출한다
- **THEN**: 레벨이 즉시 `0`으로 복귀한다.

### AC-04 · 새 세션 reset() 시 Level 0 초기화
- **GIVEN**: Level 2로 설정된 컨트롤러가 주어졌을 때
- **WHEN**: `reset()`을 호출한다
- **THEN**: `current_level`이 `0`으로 초기화된다.
