---
title: "E-08 — 최종 발표 및 데모 시나리오 스펙"
tags: [spec]
---

# E-08 — 최종 발표 및 데모 시나리오 스펙

이 문서는 말로(Mallo) 최종 프로젝트 발표 및 실시간 라이브 시연을 위한 **대표 주문 데모 시나리오(E-08)**를 정의한다.

---

## 1. Why

- **페르소나**: 최종 평가위원, 동료 수강생 및 실시간 시연을 진행하는 발표자
- **상황**: 3~5분의 제한된 발표 시간 안에 말로(Mallo)의 핵심 차별점(Voice-first 대화 + Adaptive TTS 친절체 + 결정론적 주문 엔진)을 안정적으로 증명해야 함
- **문제**:
  1. 실제 음성 환경에서 주변 소음이나 긴장으로 인한 오발화 시연 실패 위험
  2. 단순 주문만 보여주면 "기존 키오스크와 무엇이 다른가"를 청중에게 전달하기 어려움
  3. 메뉴 탐색, 복합 주문, 수정, 어조 적응이 하나의 매끄러운 스토리로 연결되어야 함
- **측정 지표**: 데모 시연 완주율 100%, Real Warm E2E Target `<= 1.2초`·Requirement `<= 1.5초`, 관객의 핵심 가치(대화형 탐색/Context 유지/Adaptive TTS) 인지율 100%

---

## 2. Goal

- **해결 목표**: 말로(Mallo)의 5대 핵심 가치를 3분 이내에 청중이 직관적으로 체감할 수 있는 완결된 라이브 데모 흐름을 제공한다.
- **성공 기준**:
  1. 5개 핵심 턴(탐색 ➔ 복합 주문 ➔ Adaptive 속도 제어 ➔ 옵션 수정 ➔ 결제 확정)이 중단 없이 순차 성공한다.
  2. 시연 중 Adaptive TTS Level이 Level 0(1.0x)에서 Level 1(0.85x)로 자연스럽게 전환되어 발화 속도 변화가 뚜렷이 들린다.
  3. 실제 마이크·모델·UI·오디오 재생 경로의 Warm Time to First Audio를 측정하고 Target/Requirement 판정을 구분한다. Mock 또는 TTS 단일 모델 수치를 Real E2E로 사용하지 않는다.
- **Out of Scope**:
  - 실제 신용카드 IC 칩 결제 단말기 연동 (화면 가상 결제로 대체)
  - 10개 MVP 메뉴 카탈로그 외의 외부 메뉴 주문

---

## 3. What (3분 대표 시연 스크립트)

### 3.1 Happy Path (5-Turn Demo Script)

공통 시작은 `IDLE → 주문하기 → 매장/포장 선택`이다. 사용자는 `[포장]`을 누르거나 `포장이요`라고 말해 `TAKE_OUT`을 선택한다. 이후 사용자 응답이 필요한 안내는 TTS 종료 후 자동 Listening으로 이어진다.

| 턴 (#) | 시연 단계 | 사용자 발화 (Voice Input) | 시스템 응답 텍스트 & TTS 동작 | 주요 시연 포인트 |
|---|---|---|---|---|
| **Turn 1** | **메뉴 탐색** | "따뜻한 음료 뭐 있어요?" | "따뜻한 음료에는 아메리카노, 카페라떼, 바닐라라떼, 말차라떼, 밀크티, 캐모마일티가 있습니다." *(Level 0)* | 조건 기반 메뉴 탐색과 Contextual Menu Area |
| **Turn 2** | **복합 주문** | "아메리카노 따뜻한 거 두 잔이랑 바스크 치즈 케이크 하나 주세요" | "따뜻한 아메리카노 2잔과 바스크 치즈 케이크 1개를 담았습니다. 총 15,900원입니다." *(Level 0)* | 복수 메뉴·온도·수량 동시 처리 |
| **Turn 3** | **Voice UX 속도 제어** | "말이 좀 빠른데 천천히 다시 말해줘" | "따뜻한 아메리카노 2잔, 그리고 바스크 치즈 케이크 1개입니다. 총 15,900원입니다." *(Level 1, 표준 쉼표 Pause)* | Adaptive TTS와 Context 유지 |
| **Turn 4** | **옵션 수정** | "아메리카노를 아이스로 바꿔줘" | "아메리카노를 아이스 음료로 변경했습니다. 아이스 아메리카노 2잔, 케이크 1개입니다." *(Level 1 유지)* | `UPDATE_OPTION` 온도 변경 |
| **Turn 5** | **주문 확정 및 결제** | "주문 다 했어, 결제할게" | `TAKE_OUT`, 메뉴·옵션·총 15,900원을 확인한 뒤 가상 결제 화면으로 전환 | 시작 시 선택한 이용 방식 유지·최종 확인 |

> **시연 스크립트 정렬 각주**: 현재 Order Engine은 턴당 단일 Intent만 허용한다(`domain/conversation.py`). 따라서 "아메리카노 하나는 아이스로"(REMOVE+ADD, 2 Intent) 식의 온도별 분리는 지원하지 않으므로, Turn 4는 주문된 아메리카노 **전체를 아이스로 일괄 변경**하는 발화로 정렬했고 AC-03도 이에 맞춰 정의한다. 동일 메뉴를 온도별로 나누는 시연이 필요하면 엔진의 다중 Intent 허용 확장이 선행되어야 한다.

---

### 3.2 Edge Cases & Fallback (시연 장애 방지 대책)

| # | 상황 (Edge Case) | 시연 중 처리 방식 (Fallback) |
|---|---|---|
| **EC-01** | 시연장 마이크 하울링/노이즈로 STT 인식 불량 | 수동 마이크 재입력 1회 수행, 실패 시 터치/텍스트 Fallback 또는 직원 호출 |
| **EC-02** | 시연 도중 모호한 수정 ("아니 라떼로 줘") | 기존 Cart를 유지하고 카페라떼·바닐라라떼·말차라떼 중 필요한 후보만 Clarification |
| **EC-03** | Vercel UI에서 Local FastAPI 접근 불가 | 사전 검증한 Deployment Plan B의 External Server endpoint로 전환 |
| **EC-04** | 시연 시간 초과 임박 (3분 경과) | Turn 4를 생략하고 Turn 2 ➔ Turn 3 ➔ Turn 5로 1분 30초 단축 시연 |

---

## 4. How

- **시연 환경**: Vercel React UI + Local PC FastAPI/AI Pipeline(Plan A), 외장 스피커/마이크
- **배포 Fallback**: Plan A 연결 조건 실패 시 Backend와 AI Pipeline을 External Server로 이동
- **데이터셋 & 카탈로그**: `docs/specs/menu-catalog.md`의 공식 10개 메뉴
- **음성 엔진**: 현재 검증된 TTS Provider와 Adaptive TTS Level 0~2 계약 사용

---

## 5. Acceptance Criteria (AC)

- **AC-01 (데모 스크립트 정합성)**: 공통 시작과 5개 턴의 사용자 발화·기대 응답이 PRD, 메뉴 카탈로그, Order Engine 규칙과 일치해야 한다.
- **AC-02 (Adaptive Level 전이 검증)**: Turn 3에서 `REQUEST_SLOWER`가 인식되어 Level 1로 상승하고 속도가 0.85x로 감소해야 한다.
- **AC-03 (수정 동작 무결성)**: Turn 4 실행 후 장바구니에 `iced americano: 2`, `basque_cheesecake: 1`과 `TAKE_OUT`이 유지돼야 한다.
- **AC-04 (Trigger)**: 사용자 응답이 필요한 각 안내의 실제 TTS 재생 종료 후 자동 Listening이 시작되고, 수동 마이크는 실패 시에만 사용한다.
- **AC-05 (Latency)**: Real Warm E2E를 `docs/specs/e2e-latency.md` 경계로 기록하고 `<=1.2초` Target과 `<=1.5초` Requirement를 구분한다.
