---
title: "T-31 — Adaptive TTS Intent 실제 실행"
tags: [spec]
---

# T-31 — Adaptive TTS Intent 실제 실행

## Why

- **페르소나**: 시스템 안내를 다시 또는 천천히 듣고 싶은 고령 사용자
- **상황**: Controller의 Level 전이는 구현됐지만 Orchestrator가 항상 Level 0으로 합성한다.
- **문제**: `REQUEST_REPEAT`, `REQUEST_SLOWER`, `REQUEST_DEFAULT_SPEED`가 실제 음성에 반영되지 않는다.
- **측정 지표**: Intent 실행률 100%, Level 전이 정확도 100%, Cart 비변경률 100%

## Goal

- 세 TTS Intent를 마지막 안내 재합성과 세션 Level에 연결한다.
- 후속 일반 응답에도 변경 Level을 유지한다.
- **Out of Scope**: GUI 버튼 연결, 장기 사용자 프로필, 실제 TTS 모델 속도 Benchmark

## What

1. `REQUEST_REPEAT`와 `REQUEST_SLOWER`는 Level을 한 단계 올리고 마지막 안내를 다시 합성한다.
2. `REQUEST_DEFAULT_SPEED`는 Level 0으로 복귀하고 마지막 안내를 다시 합성한다.
3. 첫 제어 요청은 Session 기본 인사말을 사용한다.
4. Level 2에서는 더 상승하지 않는다.
5. 세 Intent는 Cart를 변경하지 않는다.

## How

- `VoicePipeline`이 세션별 `AdaptiveTTSController`와 마지막 안내 원문을 소유한다.
- TTS 제어 Intent는 Order Engine에 전달하지 않고 Orchestrator가 처리한다.
- 합성 전 `AdaptiveTextTransformer`를 현재 Level로 적용한다.
- `MalloService.reset_session()`이 Level 0과 기본 인사말을 복원한다.

## AC

### AC-01 · 반복·느리게

- **GIVEN**: 직전 안내와 Level 0이 있다.
- **WHEN**: 반복 또는 느리게 요청을 실행한다.
- **THEN**: Level 1로 전이하고 직전 안내를 Level 1로 다시 합성한다.

### AC-02 · 기본 속도

- **GIVEN**: Level 1 또는 2 세션이 있다.
- **WHEN**: 기본 속도 요청을 실행한다.
- **THEN**: Level 0으로 복귀하고 직전 안내를 다시 합성한다.

### AC-03 · 세션 유지·초기화

- **GIVEN**: Level이 변경된 세션이 있다.
- **WHEN**: 일반 주문 또는 `reset_session()`을 실행한다.
- **THEN**: 일반 주문은 현재 Level을 사용하고 reset 후 Level 0을 사용한다.
