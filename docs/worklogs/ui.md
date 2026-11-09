---
title: "Minimal GUI 작업 로그 (`UI-*`)"
tags: [worklog]
---

# Minimal GUI 작업 로그 (`UI-*`)

Minimal GUI 영역에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다.

## 2026-08-17

### UI-01~UI-06 Starbuck-style Voice-first Minimal GUI 구현

- 고령 사용자의 시각·인지 부담을 최소화하는 스타벅스 키오스크 스타일(Dark Green `#006241`, Warm Cream `#F7F5F0`, High-contrast Typography)의 Minimal GUI를 구현했다.
- **UI-01**: 단일 화면 반응형 Semantic HTML5 레이아웃 (`web/index.html`, `web/styles.css`)
- **UI-02**: 실시간 장바구니 항목(메뉴명, HOT/ICE 뱃지, 수량, 단가) 및 총 결제 금액 렌더링
- **UI-03**: 시스템 실시간 안내 자막 카드 (`response-card`)
- **UI-04**: 대형 원형 음성 입력 버튼 (`Tap-to-talk`) 및 키보드 입력창
- **UI-05**: 음성 UX 제어 바 (`[다시 듣기]`, `[천천히 듣기]`, `[보통 속도]`, `[직원 호출]`)
- **UI-06**: 상단 시스템 상태 인디케이터 및 `SessionState` 도메인 모델 (`src/domain/session_state.py`)
- 스펙 문서 `docs/specs/minimal-gui.md` 작성 및 단위 테스트 65개 통과를 확인했다.

## 2026-08-19

### I-04 + UI-07~11 GUI 주문 확정·결제·리셋 흐름 구현

- I-10 Web 백엔드를 기반으로 `web/index.html`·`web/styles.css`·`web/app.js`에 주문 확인/수정/확정/결제완료/리셋 흐름을 상태 머신(ORDERING→CONFIRMING→COMPLETE)으로 구현했다.
- **I-04**: 다시 듣기/천천히/보통 속도 버튼이 `/api/tts-control`을 호출하고, 헤더 `TTS Lv.0/1/2` 배지가 `/api/state`의 `tts_level`과 동기화된다.
- **UI-07**: `#confirmModal`에 장바구니 품목(메뉴명·온도·수량·금액)과 총액을 `/api/state` 기준으로 렌더링하는 주문 확인 화면.
- **UI-08**: 모달의 `수정하기` 버튼이 편집 단계로 복귀.
- **UI-09**: `주문 확정` 버튼이 `/api/order {text:"주문 확정할게요"}`을 호출해 명시적 확정.
- **UI-10**: 확정 성공 시 `#completeScreen` 가상 결제 완료 화면(실제 PG 없음) 표시.
- **UI-11**: `새 주문 시작하기` 버튼이 `/api/reset`을 호출하고 cart·TTS 레벨·화면을 초기화.
- `tests/integration/test_web_server.py`에 confirm→reset 사이클 및 `/api/state` TTS 레벨 노출 검증 2건을 추가해 총 8건 통과.

