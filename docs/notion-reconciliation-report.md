---
title: "말로(Mallo) Notion 8docs 문서 정합화 보고서"
tags: [doc, reconciliation]
---

# Notion Reconciliation Report

이 문서는 2026-08-19 진행된 말로(Mallo) 문서 정합화 작업의 최종 기준, 버전 출처(Provenance), 해결된 충돌, SSOT 구조, 구현-문서 간의 Gap 및 미결정 사항을 종합 기록한 보고서다.

---

## 1. 기준 (Authoritative Inputs & Principles)

본 문서 정합화 작업은 다음 권위 있는 제품 결정(Authoritative Decision Input)과 문서 거버넌스 원칙을 기준으로 수행되었다.

1. **`mallo_notion_8docs_final.zip` (Notion 최종 8개 문서)**
   - `01_deployment_architecture.md`: Vercel React UI + Local PC FastAPI(Plan A) 및 External Server(Deployment Plan B)
   - `02_service_scope_and_menu.md`: 카페 키오스크 10개 메뉴, 옵션 지원 범위(Size, Decaf, Ice amount, Shot, Syrup / Milk 미지원)
   - `03_screen_flow.md`: 대기 → 매장/포장 → 음성 주문 → 주문 결과/추가 질문 → 주문 확인/수정 → 최종 확인 → 결제 → 완료
   - `04_voice_order_scenarios.md`: 대화형 주문 시나리오, Context 유지, 미지원 요청 처리
   - `05_voice_input_result_ui.md`: STT 결과(원문)와 구조화 주문 카드의 시각적 분리 및 강조
   - `06_voice_trigger.md`: `주문하기` 1회 → 매장/포장 선택 → TTS 종료 후 자동 Listening → VAD 발화 종료 → 수동 마이크 Fallback
   - `07_competitor_differentiation.md`: 범용 자동화가 아닌 고령 사용자 맞춤 Voice-first + Minimal GUI 포지셔닝
   - `08_e2e_latency_plan_b.md`: Warm E2E Latency(`input_end → first_audio_start`), Target <= 1.2s, Requirement <= 1.5s, Latency Provider Fallback
2. **`docs/documentation-governance.md`**: 제품 범위(PRD) / 아키텍처(TRD) / 세부 수치·AC(Specs) / 검증(Demo, Test) / 기록(Proposal, Worklog) 책임 분리 원칙

---

## 2. Version Provenance (세 버전 관계 및 Base 결정)

### 2.1 버전 현황

- **Local HEAD (`8d192b9`)**: 작업 시작 시점 기준 `origin/main`보다 18 commits 뒤처진 상태였음. Codex는 이 오래된 local main 위에서 초기 문서 정합화 작업을 수행함.
- **origin/main (`e2eeb22`)**: 18개 commit(PR #104, #105, #107, #109, #110, E-10 데모 리허설 등)을 포함하며, `docs/prd.md`, `docs/specs/order-command.md`, `docs/specs/nlu-dataset.md`, `docs/specs/demo-scenarios.md` 등 주요 문서의 최신 변경사항을 담고 있음.
- **`docs.zip`**: 과거 제공된 스냅샷으로, 로컬 파일시스템에 직접 보관되어 있지 않아 직접 비교는 불가했음 (`docs.zip 직접 비교 불가`).

### 2.2 판정: CASE D

- `origin/main`의 최신 문서와 local HEAD 원본 문서 사이에 실제 내용 변경(특히 안전한 혼합 Intent 순차 실행 계약, E-10 데모 리허설 각주 및 정렬)이 존재함.
- Codex가 수정한 문서군과 upstream에서 변경된 문서군이 겹치므로, 오래된 working tree의 diff를 무조건 overwrite하면 upstream의 유효한 변경사항이 유실되는 **CASE D**로 판정함.

### 2.3 최종 작업 Base 및 경로

- **최종 작업 Base**: 최신 `origin/main` (`e2eeb22`)
- **작업 경로**: `/home/honorbear/AI_Human_7th/proj1-d-reconciliation-origin` (별도 격리 git worktree)
- **보존 조치**:
  - 기존 working tree (`/home/honorbear/AI_Human_7th/proj1-d`) 그대로 보존
  - Codex 초기 작업 패치 (`/home/honorbear/AI_Human_7th/mallo-codex-doc-reconciliation.patch`, 143KB) 생성 및 영구 보존
  - 최신 `origin/main` 위에 upstream 변경사항과 Notion 최종 결정사항을 의미 단위로 완전 병합

---

## 3. 변경된 문서 목록 (Changed Documents)

| # | 문서 경로 | 변경 성격 | 주요 변경 내용 |
|---|---|---|---|
| 1 | `docs/specs/e2e-latency.md` | **신규 생성** | Warm E2E Latency, Time to Visual Response, Cold Start, Mock 격리, Latency Provider Fallback SSOT 정의 |
| 2 | `docs/documentation-governance.md` | 수정 | 문서 책임표 및 Fallback 용어(Deployment Plan B vs Latency Provider Fallback) 정립 |
| 3 | `docs/inference-deployment.md` | 수정 | Plan A(Vercel UI + Local FastAPI) 및 Plan B(External Server) 검증 계획, 모델 교체와의 분리 |
| 4 | `docs/prd.md` | 수정 | P0/P1/P2 범위 정렬, Voice Trigger(`주문하기`→매장/포장→자동 Listening), E2E 요구사항(1.5s), Out of Scope(Barge-in 등) |
| 5 | `docs/proposal.md` | 수정 | 제안서 발표 서사 내 Trigger 방식, 매장/포장 흐름 및 비기능 목표 현실화 |
| 6 | `docs/specs/audio-input.md` | 수정 | 오디오 버퍼 및 VAD 유틸리티 스펙 정합화, Tap-to-talk 용어 명확화 |
| 7 | `docs/specs/audio-input-mic.md` | 수정 | 마이크 캡처, TTS 종료 후 자동 Listening(`SYSTEM_PROMPTED`), 수동 마이크 Fallback(`USER_INITIATED_FALLBACK`) 계약 |
| 8 | `docs/specs/beverage-option-adjustments.md` | 수정 | 샷·시럽(0 이상 정수, 무상한), 카페인(`REGULAR`/`DECAF`), 얼음(`NONE`/`LESS`/`NORMAL`/`MORE`), Size(enum TBD), 우유(미지원) |
| 9 | `docs/specs/demo-scenarios.md` | 수정 | 5턴 시연 흐름에 매장/포장 선선택 반영, E-10 리허설 정합성(15,900원, UPDATE_OPTION 일괄 변경) 유지, E2E 지표 정렬 |
| 10 | `docs/specs/menu-catalog.md` | 수정 | 10개 메뉴 카탈로그, 음료 옵션 정책(`option_policy`), 샷/시럽 무상한, Size 지원 표시(`size_supported`) |
| 11 | `docs/specs/minimal-gui.md` | 수정 | Starbuck 스타일 Minimal GUI 레이아웃, `SessionState` 모델, STT-주문카드 분리, Adaptive TTS 공통 제어 바 |
| 12 | `docs/specs/nlu-add-item.md` | 수정 | `OrderCommand` 옵션 필드 구조 및 `order-command.md` 참조 갱신 |
| 13 | `docs/specs/nlu-dataset.md` | 수정 | 옵션 스키마(Size 포함 5종)와 upstream 혼합 Intent(안전한 2-intent 순차 실행 + `QUERY_CART`) 데이터셋 계약 병합 |
| 14 | `docs/specs/order-command.md` | 수정 | `options` 5개 필드 스키마와 upstream 혼합 Intent 순차 실행 규칙 및 AC-07 병합 |
| 15 | `docs/specs/order-engine-operations.md` | 수정 | 6대 Intent 동작, Size enum 미확정 처리 및 옵션 변경 규칙 정합화 |
| 16 | `docs/specs/order-fulfillment-selection.md` | 수정 | 주문 시작 시 매장/포장 선선택(`DINE_IN`/`TAKE_OUT`), 세션 유지 및 전체 취소 시 리셋 계약 |
| 17 | `docs/specs/stt-result.md` | 수정 | STT 전사 결과 계약의 Trigger 표현(자동 Listening/수동 Fallback) 정렬 |
| 18 | `docs/specs/user-test-protocol.md` | 수정 | 사용자 평가 프로토콜(TASK-0 매장/포장 추가, Group C 자동 Listening, E2E Latency 산식 1.2s/1.5s) |
| 19 | `docs/tasks.md` | 수정 | MVP 범위 내 Trigger 방식 현실화 |
| 20 | `docs/trd.md` | 수정 | 전체 기술 아키텍처, State Machine, Audio Session, Deployment Plan A/B, E2E 계측 및 모델 PoC 게이트 정합화 |
| 21 | `docs/notion-reconciliation-report.md` | **신규 생성** | 본 정합화 결과 보고서 |

---

## 4. 해결한 주요 충돌 (Resolved Conflicts)

### 4.1 Voice Trigger 정책 충돌
- **충돌**: 기존 문서는 매 발화마다 버튼을 누르는 `Tap-to-talk`를 기본 정책으로 서술했으나, 최신 Notion 결정은 대기 화면에서 `주문하기` 1회 후 사용자 응답이 필요한 시스템 안내가 끝나면 자동으로 마이크가 켜지는 `자동 Listening`을 채택함.
- **해결**:
  - `IDLE → 주문하기(1회) → SERVICE_MODE(DINE_IN/TAKE_OUT) → TTS 종료 후 자동 Listening(SYSTEM_PROMPTED) → VAD 발화 종료 → PROCESSING`을 기본 흐름으로 확정함.
  - 수동 마이크 버튼은 인식 실패, 무응답 Timeout, 추가 주문 재시작을 위한 **수동 재입력 Fallback(`USER_INITIATED_FALLBACK`)**으로 정의함.
  - Wake Word, Always Listening, TTS 도중 끼어들기(Barge-in)는 MVP Out of Scope로 명문화함.
  - 기존 코드의 `TapToTalk` 클래스는 단일 오디오 세션 캡처 유틸리티로 유지하되 제품 정책명이 아님을 각 문서에 명시함.

### 4.2 음료 옵션 범위 및 제약 충돌
- **충돌**: 기존 문서에 샷/시럽 `0~3회` 상한, 우유 종류 변경 지원 여부 모호, Size 지원 여부 불일치가 존재함.
- **해결**:
  - **지원 옵션**: Size(지원), Decaf(`REGULAR`/`DECAF`), Ice amount(`NONE`/`LESS`/`NORMAL`/`MORE`), Shot(`extra_shots >= 0`), Syrup(`syrup_pumps >= 0`).
  - **미지원 옵션**: 우유 종류 변경(오트밀크, 저지방 등)은 미지원(Out of Scope)으로 확정 (단, 메뉴 정보 질의 `detail_fields`의 `milk` 성분 질의는 유지).
  - **샷 / 시럽 상한**: 서비스 정책상 최대 횟수 제한 없음 (0 이상의 정수 허용).
  - **Size 결정 보류**: Size는 지원 capability로 확정하되 내부 enum(`REGULAR/LARGE` vs `SMALL/MEDIUM/LARGE`), 메뉴별 기본값, 가격은 최종 확정 전까지 임의 결정하지 않고 스키마에서 `size: null` (enum TBD)로 예약함.

### 4.3 매장 / 포장 (`DINE_IN` / `TAKE_OUT`) 선택 시점
- **충돌**: 메뉴별 개별 옵션으로 넣을 것인지, 결제 직전에 물을 것인지, 주문 시작 시 물을 것인지의 불일치.
- **해결**: 대기 화면에서 `주문하기`를 누른 직후, 메뉴 주문 전에 **터치 또는 음성으로 매장/포장을 먼저 선택**하는 `SERVICE_MODE`로 확정함.

### 4.4 배포 Fallback vs Latency Provider Fallback 분리
- **충돌**: 과거 문서에서 External Server 이전과 STT/TTS 외부 API 교체가 모두 `Plan B`로 혼용됨.
- **해결**:
  - **`Deployment Plan B`**: Vercel React UI에서 Local PC FastAPI 접근이 브라우저 보안/HTTPS/CORS/네트워크 문제로 실패할 때 Backend + AI Pipeline 전체를 External Server로 이전하는 배포 Fallback.
  - **`Latency Provider Fallback`**: Real E2E가 1.5초를 초과하고 Local 최적화로도 해결되지 않을 때 병목 구간(STT 또는 TTS)의 Provider만 외부 API로 교체하는 모델 Fallback (NLU는 Local 유지 우선).

### 4.5 E2E Latency 측정 기준 및 목표 수치
- **충돌**: TTS 단일 모델 생성 시간(0.2s 등)과 E2E Latency 혼용, 목표 수치 불일치.
- **해결**:
  - 기본 E2E 구간: Warm 상태에서 **사용자 발화 종료(`input_end`) → Mallo의 첫 음성 응답 실제 재생 시작(`first_audio_start`)**.
  - **Target (목표치)**: `<= 1.2초`
  - **Requirement (요구치)**: `<= 1.5초`
  - `Time to Visual Response`와 `Cold Start`는 별도 지표로 분리.
  - Mock Pipeline 및 단일 컴포넌트 벤치마크는 Real E2E 판정에서 제외.
  - 상세 SSOT로서 `docs/specs/e2e-latency.md`를 신규 제정함.

### 4.6 Upstream 혼합 Intent 순차 실행과 옵션 스키마 병합
- **충돌**: `origin/main`의 최신 PR #109, #110에서 추가된 안전한 혼합 Intent 순차 실행(`ADD_ITEM`, `REMOVE_ITEM`, `UPDATE_QUANTITY`, `UPDATE_OPTION` 최대 2개 + `QUERY_CART`)이 Codex 패치에서 누락될 위험이 있었음.
- **해결**: Upstream의 혼합 Intent 순차 실행 규칙 및 데이터셋 계약을 100% 보존하면서, 5개 옵션 하위 필드(`size`, `extra_shots`, `caffeine`, `syrup_pumps`, `ice_amount`) 스키마를 결합함.

### 4.7 데모 시나리오 가격 및 E-10 리허설 정합성
- **충돌**: 데모 시나리오 Turn 2/3 가격 오기(16,200원 vs 15,900원) 및 Order Engine 단일 Intent 제약 반영.
- **해결**: 아메리카노 2잔(9,400원) + 바스크 치즈 케이크 1개(6,500원) = **15,900원**으로 메뉴 카탈로그와 100% 일치시킴. Turn 4 발화를 `UPDATE_OPTION` 일괄 온도 변경("아메리카노를 아이스로 바꿔줘")으로 정렬함.

---

## 5. Source of Truth (SSOT 책임 구조)

```text
[제품 범위 및 상위 정책]
docs/prd.md
  │
  ├─── [시스템 구조 및 공통 인터페이스]
  │    docs/trd.md ─── docs/inference-deployment.md (배포 검증 보조)
  │
  ├─── [기능별 상세 규격 및 AC (Specs)]
  │    ├── docs/specs/e2e-latency.md (E2E 성능 및 Provider Fallback SSOT)
  │    ├── docs/specs/order-command.md (Command 스키마 및 Batch 순차실행 SSOT)
  │    ├── docs/specs/beverage-option-adjustments.md (옵션 값 및 제약 SSOT)
  │    ├── docs/specs/menu-catalog.md (10개 메뉴 및 option_policy SSOT)
  │    ├── docs/specs/order-fulfillment-selection.md (매장/포장 SSOT)
  │    ├── docs/specs/audio-input-mic.md (마이크 및 자동 Listening SSOT)
  │    ├── docs/specs/minimal-gui.md (Minimal GUI 화면 및 상태 SSOT)
  │    └── docs/specs/nlu-dataset.md (NLU 3,000행 데이터셋 계약 SSOT)
  │
  ├─── [시연 및 사용자 검증]
  │    ├── docs/specs/demo-scenarios.md (5턴 데모 시연 스크립트)
  │    └── docs/specs/user-test-protocol.md (사용자 평가 프로토콜)
  │
  └─── [작업 관리 및 과거 이력]
       ├── docs/tasks.md (실행 상태 백로그)
       ├── docs/worklog.md / docs/worklogs/*.md (의사결정 이력)
       └── docs/notion-reconciliation-report.md (정합화 결과 보고서)
```

---

## 6. 구현과 문서 간의 남은 Gap (Implementation Gaps)

1. **Frontend 프레임워크 및 배포**:
   - 현재 구현: FastAPI 백엔드와 연동되는 가벼운 웹/프로토타입 서버 (`src/app/server.py`).
   - 문서 목표: Vercel에 배포되는 React 기반 Starbuck-style Minimal GUI.
2. **음성 입력 오케스트레이션**:
   - 현재 구현: `src/adapters/audio/tap_to_talk.py`의 단위 세션 VAD 녹음 유틸리티.
   - 문서 목표: TTS 실제 재생 종료 이벤트를 감지하여 자동으로 Listening을 여는 `VoiceInputController` 및 세션 오케스트레이터 완성.
3. **옵션 확장 런타임 적용**:
   - 현재 구현: `UPDATE_OPTION`에서 온도(HOT/ICED) 위주 처리.
   - 문서 목표: `options` 객체(샷, 디카페인, 시럽, 얼음 양)를 `CartItem` 및 `ConversationAgent`에서 완전 검증·저장하는 런타임 로직 확장.
4. **Real Pipeline E2E 계측기 연동**:
   - 현재 구현: Mock 파이프라인 기반 지연시간 측정 스크립트 (`scripts/measure_e2e_latency.py`).
   - 문서 목표: 브라우저 재생 시작 이벤트(`first_audio_start`)와 VAD 입력 종료(`input_end`)를 실시간 monotonic clock으로 연동하는 계측 체계.

---

## 7. 미결정 사항 (Open Decisions)

1. **Size enum 체계**:
   - 후보: `Regular` / `Large` vs `Small` / `Medium` / `Large`.
   - 결정 주체 및 시점: UI 디자인 및 메뉴 정책 최종 합의 시 결정 (현재는 `size: null`로 예약).
2. **E2E 최종 집계 판정 통계**:
   - 후보: 턴별 평균, p95, 최댓값 중 어느 지표를 최종 DoD 판정선으로 삼을지.
   - 결정 시점: 사용자 테스트 및 실측 벤치마크 데이터 확보 후 확정.
3. **Vercel UI ↔ Local PC FastAPI 보안/연결 방식**:
   - 후보: Private Network Access(PNA) 헤더, 로컬 터널링(ngrok 등), 로컬 도메인 TLS 인증서.
   - 결정 시점: 시연 장비 및 네트워크 리허설 시 검증.
4. **VAD 무음 판정 Threshold**:
   - 후보: 기본 1.0초 외에 고령 사용자 발화 간격을 고려한 최적 침묵 시간(Silence Timeout).
   - 결정 시점: 파일럿 사용자 테스트(E-01) 수행 후 튜닝.

---

## 8. Upstream 18 commits 반영 내역

- **PR #104 (NLU 파일럿 사전검수)**: NLU 어댑터 및 에러 핸들링 보완사항 문서 정렬.
- **PR #105 (잔여 실패 테스트 수정)**: Windows 환경 호환성 및 오염 복원 테스트 반영.
- **PR #107, #109, #110 (혼합 Intent 안내, 순차 실행, 데이터 계약)**: `ADD_ITEM`, `REMOVE_ITEM`, `UPDATE_QUANTITY`, `UPDATE_OPTION` 안전한 2-intent 순차 실행 및 `QUERY_CART` 계약을 `order-command.md`, `nlu-dataset.md`, `prd.md`에 완벽 보존.
- **E-10 데모 리허설**: `test_demo_rehearsal.py` 3건 통과 기준(Turn 4 일괄 온도 변경, 총액 15,900원)을 `demo-scenarios.md` 및 `tasks.md`에 반영.

---

## 9. 검증 결과 (Validation)

- **테스트 실행**: 회귀 테스트 및 데모 리허설 테스트 검증 완료 (`pytest` 전체 통과).
- **문서 무결성**: 21개 전체 문서의 마크다운 포맷, 헤더 구조, 깨짐 및 절단 없음 확인.
- **코드 무변경**: Python 코드 파일에 대한 변경 없음 (문서만 수정).
- **Git 상태**: `origin/main` 기반의 독립 worktree에서 깨끗한 diff 유지 (임의 커밋하지 않음).
