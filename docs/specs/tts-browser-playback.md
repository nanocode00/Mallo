---
title: "TTS 브라우저 재생 lifecycle"
tags: [spec, tts, ui]
---

# TTS 브라우저 재생 lifecycle

## Why

- **페르소나**: 화면 읽기보다 음성 안내가 편한 고령 사용자
- **상황**: 음성 또는 텍스트 주문 후 말로의 주문 안내를 듣고, 필요하면 다시 듣거나 속도를 조절한다.
- **문제**: 백엔드는 TTS audio를 생성하지만 브라우저가 재생하지 않고 `ttsState`도 실제 오디오 상태와 연결되지 않는다.
- **측정 지표**: audio payload 수신 시 재생 시도율 100%, 실제 오디오 이벤트와 UI 상태 일치율 100%

## Goal

- 음성·텍스트·TTS control 응답의 `tts_audio_base64`를 브라우저에서 재생한다.
- 실제 오디오 lifecycle을 `loading`, `playing`, `completed`, `error` 상태로 표시한다.
- 다시 듣기와 Adaptive TTS level 변경 결과로 생성된 최신 audio를 재생한다.
- **성공 기준**: 재생 controller 자동 테스트와 전체 회귀 테스트 통과
- **Out of Scope**: 재생 종료 후 자동 Listening, VAD, OPTION_CHANGE flow 변경, NLU, clarification, 부분 정정, 결제 변경, UI 재설계, 시작음·종료음

## What

**Happy Path**

1. API가 `tts_audio_base64`를 반환한다.
2. 브라우저가 base64를 WAV Blob과 object URL로 변환한다.
3. 재생 준비 중 `loading`, 시작 시 `playing`, 종료 시 `completed`가 된다.
4. UI가 재생 중 "말로가 안내하고 있어요"를 표시한다.
5. 다시 듣기 또는 속도 변경 시 control API의 새 audio를 재생한다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | audio가 없거나 빈 문자열 | 이전 audio가 있으면 control 요청에서만 replay하고, 없으면 `error` 처리한다. |
| EC-02 | base64 decode 또는 재생 실패 | `error` 상태와 안내를 표시하고 주문 화면은 유지한다. |
| EC-03 | 새 audio 수신 | 이전 audio를 pause하고 object URL을 revoke한 뒤 교체한다. |
| EC-04 | 세션 reset | 현재 audio와 object URL을 정리하고 `idle`로 초기화한다. |
| EC-05 | 재생 완료 | `completed`만 표시하며 마이크를 자동 시작하지 않는다. |

## How

- 기존 API 필드를 유지하고 `/api/order`, `/api/tts-control`에도 `tts_audio_base64`를 추가한다.
- `web/tts-player.js`가 Audio 객체, Blob URL, 상태 전환과 resource 정리를 담당한다.
- `web/app.js`는 controller callback을 기존 `ttsState.status/error`에 반영한다.
- 화면에는 `aria-live="polite"` 상태 영역을 추가한다.

## AC (Given-When-Then)

**AC-01 · API audio 계약**

- GIVEN: TTS가 audio bytes를 생성한다.
- WHEN: 음성·텍스트·TTS control API가 성공한다.
- THEN: 기존 필드와 함께 `tts_audio_base64`를 반환한다.

**AC-02 · lifecycle**

- GIVEN: 유효한 audio payload가 있다.
- WHEN: 브라우저가 재생한다.
- THEN: 상태가 `loading → playing → completed`로 전환된다.

**AC-03 · 재생 실패**

- GIVEN: audio가 없거나 decode/play가 실패한다.
- WHEN: 재생을 시도한다.
- THEN: 상태가 `error`가 되고 화면 및 주문 상태는 유지된다.

**AC-04 · 다시 듣기와 Adaptive TTS**

- GIVEN: 직전 안내 audio가 있고 사용자가 다시 듣기 또는 속도 변경을 요청한다.
- WHEN: control API가 새 audio를 반환한다.
- THEN: 새 level의 audio로 교체해 재생하며, 새 audio가 없으면 직전 audio를 replay한다.

**AC-05 · resource 정리와 자동 Listening 금지**

- GIVEN: audio가 재생 중이거나 완료됐다.
- WHEN: 새 audio를 받거나 세션을 reset한다.
- THEN: 이전 resource를 정리하며 `startListening()`을 호출하지 않는다.
