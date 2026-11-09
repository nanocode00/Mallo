---
title: "주문 수정 화면 연결"
tags: [spec, ui, order]
---

# 주문 수정 화면 연결

## Why

- **페르소나**: 주문 확인 중 수량·온도·옵션을 바꾸려는 고령 사용자
- **상황**: 주문 확인 화면에서 잘못 담긴 내용을 발견하고 음성 또는 텍스트로 수정한다.
- **문제**: OPTION_CHANGE 화면과 입력 요소는 존재하지만 실제 진입 경로가 없어 수정 목적과 결과가 불명확하다.
- **측정 지표**: 수정 선택 시 OPTION_CHANGE 진입률 100%, 성공 시 ORDER_CONFIRM 복귀율 100%, 실패 시 cart 보존율 100%

## Goal

- 기존 ORDER_CONFIRM과 OPTION_CHANGE를 현재 MockNLU/Order Engine 범위 안에서 연결한다.
- 수정 성공 후 갱신된 cart를 다시 확인하고, 실패하면 기존 cart를 유지한 채 재입력한다.
- **성공 기준**: 수량·온도·옵션 수정, 실패, 취소, STT transcript, TTS 회귀 테스트 통과
- **Out of Scope**: NLU intent, dialogue history, reference resolution, line-item ID, clarification, VAD, TTS 종료 후 자동 Listening, Payment, UI 재설계

## What

**Happy Path**

1. ORDER_CONFIRM에서 `수정할게요`를 누른다.
2. cart를 유지한 채 OPTION_CHANGE로 이동한다.
3. 사용자가 기존 마이크 또는 텍스트 입력으로 수정 문장을 보낸다.
4. API의 `success`가 true이면 갱신된 cart와 함께 ORDER_CONFIRM으로 돌아간다.
5. 사용자는 수정된 주문을 다시 최종 확인한다.

**현재 MockNLU 지원 예시**

- `아이스 아메리카노 세 잔으로 바꿔 주세요`
- `아메리카노를 따뜻하게 바꿔 주세요`
- `아메리카노 디카페인으로 줘`
- `아이스 아메리카노 삭제해 주세요`

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | `UNSUPPORTED_UTTERANCE` | backend 응답과 cart를 유지하고 OPTION_CHANGE에 머문다. |
| EC-02 | target ambiguity | backend 응답과 cart를 유지하고 OPTION_CHANGE에 머문다. |
| EC-03 | API 연결 실패 | 기존 cart를 유지하고 OPTION_CHANGE에 머문다. |
| EC-04 | 수정 취소 | API 호출 없이 ORDER_CONFIRM으로 돌아간다. |
| EC-05 | 음성 수정 실패 | transcript를 OPTION_CHANGE에 표시하고 재입력을 허용한다. |

## How

- 기존 `/api/audio`, `/api/order` 응답의 `success`, `cart`, `response_text`를 사용한다.
- `OptionChangeFlow`는 수정 시작·성공·실패·취소의 다음 UI screen만 결정한다.
- cart는 기존 Web server session과 `orderState`에 계속 유지한다.
- NLU, OrderCommand, Order Engine schema는 변경하지 않는다.
- OPTION_CHANGE에도 기존 transcript와 TTS playback status renderer를 재사용한다.

## AC (Given-When-Then)

**AC-01 · 수정 진입**

- GIVEN: cart가 있는 ORDER_CONFIRM 화면이다.
- WHEN: 사용자가 `수정할게요`를 선택한다.
- THEN: cart를 변경하지 않고 OPTION_CHANGE로 이동한다.

**AC-02 · 수정 성공**

- GIVEN: OPTION_CHANGE에서 현재 지원되는 수정 문장을 입력한다.
- WHEN: API가 `success: true`와 갱신된 cart를 반환한다.
- THEN: ORDER_CONFIRM으로 돌아가 갱신된 주문과 총액을 표시한다.

**AC-03 · 수정 실패**

- GIVEN: OPTION_CHANGE에서 미지원 또는 모호한 문장을 입력한다.
- WHEN: API가 `success: false`를 반환하거나 요청이 실패한다.
- THEN: cart를 유지하고 OPTION_CHANGE에 머물며 backend 안내를 표시한다.

**AC-04 · 수정 취소**

- GIVEN: OPTION_CHANGE에 진입했지만 아직 성공한 수정이 없다.
- WHEN: `변경하지 않고 돌아가기`를 누른다.
- THEN: API 호출과 cart 변경 없이 ORDER_CONFIRM으로 돌아간다.

**AC-05 · 기존 음성 UX 회귀 방지**

- GIVEN: 음성으로 수정 명령을 입력한다.
- WHEN: API 응답을 처리한다.
- THEN: STT transcript와 TTS lifecycle을 기존 방식으로 처리하고 자동 Listening은 시작하지 않는다.
