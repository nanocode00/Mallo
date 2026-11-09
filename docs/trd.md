---
title: "말로(Mallo) Technical Requirements Document"
tags: [doc]
---

# 말로(Mallo) Technical Requirements Document

## 1. 문서 목적

본 문서는 말로(Mallo) PRD에서 정의한 요구사항을 구현하기 위한 **시스템 아키텍처, 컴포넌트 책임, 데이터 계약, 상태 관리, 오류 처리, 비기능 요구사항 및 기술적 완료 기준​**을 정의한다.

사용자 문제, ICP, 제품 가치, 제품 범위와 P0/P1/P2 우선순위는 PRD를 기준으로 한다. 모델별 데이터·학습 설정·평가 수치와 AC는 해당 기능 Spec을 기준으로 하며 이 문서에서는 기술 경계와 연결 조건만 정의한다. 문서 책임과 충돌 처리 기준은 `docs/documentation-governance.md`를 따른다.

---

# 2. Technical Goals

말로(Mallo) MVP의 기술적 목표는 다음과 같다.

1. 사용자가 `주문하기`로 시작한 세션에서 필요한 턴의 음성을 자동으로 안정적으로 수집한다.
2. 발화 종료를 자동 감지하여 STT에 전달한다.
3. 한국어 주문 발화를 텍스트로 변환한다.
4. 자연어를 제한된 주문 명령으로 구조화한다.
5. 주문 도메인 NLU에 대해 **Baseline과 Fine-tuned 모델을 동일 평가셋에서 비교**하여 파인튜닝 효과를 정량적으로 확인한다.
6. LLM과 실제 주문 상태 변경 로직을 분리한다.
7. 모든 주문 명령을 실행 전에 검증한다.
8. 실패 시 마지막으로 검증된 주문 상태를 보호한다.
9. 외부 LLM API 없이 로컬 우선 환경에서 실행한다.
10. P1에서는 모호한 요청을 별도 Clarification State에서 해결하고 Adaptive TTS를 제공한다.
11. 사용자 응답이 필요한 TTS가 끝나면 자동 Listening으로 전환하고, 수동 마이크는 재입력 Fallback으로 제공한다.
12. 발화 종료부터 첫 음성 재생까지의 Real E2E와 화면 응답·Cold Start·Mock 측정을 구분한다.

## 2.1 Priority and Drop Rule

P0/P1/P2의 범위와 제외 순서는 `docs/prd.md`의 우선순위 정의를 따른다. 이 문서의 `[P0]`, `[P1]`, `[P2]` 표기는 해당 제품 우선순위에 연결된 기술 구현 범위를 표시할 뿐 우선순위를 재정의하지 않는다.

---

# 3. Technical Principles

## TP-01 LLM과 주문 실행 분리

LLM은 자연어 이해만 담당한다.

LLM이 직접 다음 값을 결정하지 않는다.

- 메뉴 존재 여부
- 메뉴 가격
- 옵션 가격
- 총액
- 실제 장바구니 상태

LLM 출력은 반드시 구조화된 `OrderCommand[]` 형태로 전달하고 Order Engine에서 검증한다. 단일 메뉴도 길이 1의 배열을 사용한다.

## TP-02 Menu DB Single Source of Truth

메뉴명, 메뉴 ID, 옵션, 가격 및 판매 여부는 Menu DB를 기준으로 한다.

## TP-03 Invalid Command Must Not Mutate State

Schema Validation 또는 Business Validation에 실패한 명령은 장바구니를 변경할 수 없다.

## TP-04 Session-gated Automatic Listening

말로(Mallo)는 대기 상태에서 항상 듣지 않는다. 사용자가 대기 화면의 `주문하기`를 한 번 눌러 세션을 시작하고 매장/포장을 선택한 뒤, 사용자 응답이 필요한 시스템 TTS가 끝나면 자동으로 Listening을 시작한다.

- TTS 재생과 마이크 입력은 동시에 활성화하지 않는다.
- VAD가 발화 종료를 확정하면 `PROCESSING`으로 전환한다.
- 수동 마이크 버튼은 인식 실패·Timeout·추가 주문의 재입력 Fallback이다.
- Wake Word, Always Listening, Barge-in은 MVP에서 사용하지 않는다.
- 응답이 필요하지 않은 안내, 결제, 주문 완료 단계에서는 자동 Listening을 시작하지 않는다.

## TP-05 Local-first with Explicit Fallback Boundaries

기본 AI Pipeline은 Local PC의 FastAPI에서 STT, NLU, Order Engine, TTS를 실행한다. React Web UI는 Vercel에 배포한다.

- **Deployment Plan B**: Vercel UI에서 Local FastAPI 접근이 브라우저 보안·HTTPS/CORS·네트워크·시연 환경 때문에 불안정할 때 Backend와 AI Pipeline 전체를 External Server로 옮긴다.
- **Latency Provider Fallback**: Real E2E 병목을 확인하고 Local 최적화 후에도 요구사항을 만족하지 못할 때 병목인 STT 또는 TTS Provider만 외부로 바꾼다. NLU는 Local 유지가 우선이다.

두 Fallback은 서로 다른 결정이며, E2E 초과만으로 Deployment Plan B를 자동 적용하지 않는다.

---

# 4. High-level Architecture

```text
User
 ↓
IDLE → 주문하기 → SERVICE_MODE(DINE_IN / TAKE_OUT)
 ↓
TTS 종료 후 Automatic Listening / Manual Mic Fallback
 ↓
VAD / Audio Frontend
 ↓
STT
 ↓
Domain Post-processing
 ↓
Local LLM / NLU
 ↓
OrderCommand[]
 ↓
Schema Validator
 ↓
Order Engine ───────── Menu DB
 ↓
 ├──────────→ CLARIFYING
 │                 ↓
 │          Voice / GUI Selection
 │                 ↓
 └────────→ Session / Cart State
                    ↓
             Response Generator
                    ↓
          Adaptive TTS Controller
                    ↓
                   TTS
                    ↓
                 Speaker

Session State ─────────→ Minimal GUI
```

핵심 원칙은 **AI가 언어를 이해하는 역할, 실제 주문을 실행하는 역할, 음성 출력 방식을 결정하는 역할을 분리하는 것​**이다.

## 4.1 Inference Deployment Architecture

Plan A는 다음 구조다.

```text
GitHub → Vercel → React Web UI
                       ↓
              Local PC / FastAPI
                       ↓
       Local STT → Local NLU → Order Engine → Local TTS
```

- **Vercel**: 최종 사용자용 React Web UI 배포, 팀 공유와 변경사항 확인
- **사용자 단말**: UI 렌더링, 마이크 입력, 오디오 재생, 실제 `first_audio_start`와 화면 응답 시각 기록
- **Local PC / FastAPI**: Frontend API, 세션·주문 상태, STT/NLU/Order Engine/TTS 실행
- **Provider 경계**: STT와 TTS는 Local/External 구현을 교체해도 Frontend와 Order Engine 계약이 바뀌지 않게 분리

Vercel에서 AI Backend나 모델을 직접 실행하는 것은 기본안이 아니다. Plan A 적용 전 HTTPS 페이지의 Local Server 접근, CORS, 브라우저 보안 정책, 마이크 권한과 시연 네트워크를 검증한다.

Plan A가 이 연결 조건을 안정적으로 충족하지 못하면 **Deployment Plan B**로 Backend와 AI Pipeline 전체를 External Server로 옮긴다. External Server는 Plan A와 동급의 기본 구조가 아니라 배포 Fallback이다.

장비·모델 후보와 배포 검증 계획은 [`docs/inference-deployment.md`](inference-deployment.md), 성능 수치와 모델 Provider Fallback은 [`docs/specs/e2e-latency.md`](specs/e2e-latency.md)를 참조한다.

---

# 5. Audio Input

## 5.1 Listening Mode

세션 내부의 기본 모드는 `SYSTEM_PROMPTED`이며, 수동 재입력은 `USER_INITIATED_FALLBACK`으로 구분한다.

### SYSTEM_PROMPTED [P0]

```text
USER_RESPONSE_REQUIRED
 ↓
TTS_PLAYING (microphone off)
 ↓ playback_end
LISTENING (mode = SYSTEM_PROMPTED)
 ↓ speech + VAD End
PROCESSING
```

매장/포장 선택, 메뉴 주문 요청, 확인과 Clarification 등 사용자 응답이 필요한 턴에 사용한다. `SERVICE_MODE`에서 음성으로 매장/포장을 선택할 때도 같은 TTS 종료 후 Listening 규칙을 적용한다.

### USER_INITIATED_FALLBACK [P0]

```text
인식 실패 / Listening Timeout / 추가 주문 재시작
 ↓ Manual Mic
LISTENING (mode = USER_INITIATED_FALLBACK)
 ↓ speech + VAD End
PROCESSING
```

새 음성 세션의 기본 경로가 아니라 자동 Listening을 복구하는 경로다.

---

## 5.2 Audio Frontend Responsibilities

Audio Frontend는 다음을 담당한다.

- TTS Playback 종료 이벤트 이후 SYSTEM_PROMPTED Audio Session 자동 시작
- USER_INITIATED_FALLBACK Audio Session 시작
- 입력 세션 종료
- VAD
- Silence Detection
- Noise Gate
- 필요 시 Noise Suppression
- STT 입력 포맷 변환
- 최대 발화 시간 관리
- 자동 Listening 응답 Window Timeout
- 중복 Audio Session 방지

---

## 5.3 Audio Edge Cases

### A-01 No Speech — USER_INITIATED_FALLBACK

수동 마이크 재입력 이후 일정 시간 동안 유효한 음성이 감지되지 않은 경우:

```text
LISTENING
 ↓
NO_SPEECH
 ↓
Audio Session 종료
 ↓
Cart 유지
 ↓
재입력 안내
```

### A-02 No Speech — SYSTEM_PROMPTED

자동 Listening 이후 일정 시간 동안 발화가 없는 경우:

```text
SYSTEM_PROMPTED LISTENING
 ↓
TIMEOUT
 ↓
Listening 종료
 ↓
질문 상태 유지
```

이를 사용자 오류로 처리하지 않는다.

기존 `pending_command` 또는 `clarification` 상태를 유지하고 사용자가 다음 중 하나를 수행할 수 있도록 한다.

- GUI 선택
- 수동 마이크로 재입력

### A-03 Too Short Speech

지나치게 짧거나 의미 없는 입력은 주문 상태 변경으로 이어지지 않는다.

### A-04 Premature End

유효한 STT 결과를 생성하지 못하면 기존 주문 상태를 유지한다.

### A-05 Maximum Duration

최대 발화 시간을 초과하면 현재 Audio Session을 종료한다.

### A-06 Repeated Manual Mic Input

이미 `LISTENING` 상태이면 수동 마이크 입력으로 새로운 Audio Session을 생성하지 않는다.

### A-07 Listening During TTS

TTS가 재생되는 동안에는 Listening을 시작하지 않는다.

반드시 실제 TTS Playback 종료 이벤트 이후 활성화한다.

이는 시스템 음성이 STT에 다시 입력되는 Echo 문제를 방지하기 위한 요구사항이다.

### A-08 GUI Response During Listening

SYSTEM_PROMPTED Listening 중 사용자가 GUI 후보를 선택하면 현재 Audio Session을 즉시 종료하고 GUI 입력을 우선 처리한다.

GUI 선택과 음성 입력이 동시에 처리되어 동일 Command가 두 번 실행되지 않도록 한다.

---

# 6. STT

## Input

전처리된 음성.

## Output

```text
text
confidence 또는 이에 준하는 품질 정보
latency
```

## Responsibility

- 한국어 주문 인식
- 메뉴명 인식
- 수량 표현 인식
- 옵션 표현 인식
- 실패 판단

모델은 PoC 후 확정한다.

일반 WER/CER와 함께 주문에 직접 영향을 미치는 다음 Token Accuracy를 별도로 측정한다.

- 메뉴
- 수량
- 옵션
- 금액 관련 표현

---

# 7. Domain Post-processing

제한된 Menu DB를 활용하여 STT 결과에 도메인 보정을 적용할 수 있다.

예:

```text
아메리카 너
→
아메리카노
```

단, 후보가 충분히 명확하지 않다면 임의 보정을 수행하지 않는다.

모호한 후보는 이후 Clarification 과정으로 전달할 수 있다.

---

# 8. Local LLM / NLU

## Input

```text
STT text
Session context
Cart summary
Pending clarification
Allowed intent/schema
```

## Output

`OrderCommand[]`

Command 하나는 메뉴 하나만 대상으로 하며 복수 Command는 발화 순서를 유지한다. `quantity`는 증가량이 아니라 실행 후 최종 수량이다.

## Supported Intent

```text
ADD_ITEM
REMOVE_ITEM
UPDATE_QUANTITY
UPDATE_OPTION
QUERY_MENU
QUERY_CART
CONFIRM_ORDER
CANCEL
UNDO
REQUEST_REPEAT
REQUEST_SLOWER
REQUEST_DEFAULT_SPEED
```

LLM은 가격 및 총액을 반환하더라도 주문 계산의 근거로 사용하지 않는다.


## 8.1 NLU Fine-tuning Requirement [P0]

본 프로젝트에서는 Local LLM / NLU를 단순 추론에만 사용하지 않고, **주문 도메인 데이터로 Fine-tuning한 모델을 Baseline과 비교 평가하는 과정을 P0 기술 과제로 포함한다.**

### 목표

Fine-tuning의 목표는 자연어 주문을 `OrderCommand`로 변환하는 과정의 안정성을 개선하는 것이다.

특히 다음 실패를 줄이는 것을 우선 관찰한다.

- Intent 오분류
- Slot 누락 또는 잘못된 추출
- JSON Parsing / Schema Error
- 존재하지 않는 메뉴 ID 출력

### 데이터 범위

학습·검증·평가 데이터는 현재 MVP가 지원하는 주문 Intent와 Menu DB 범위에 맞춘다.
구체적인 1차 데이터 수량, CSV/JSONL 형식, Label, 정제, Split과 검수 기준은
[`docs/specs/nlu-dataset.md`](specs/nlu-dataset.md)를 따른다.

최소 다음 유형을 포함한다.

- 주문 추가·삭제·수정·조회·확정
- 메뉴명·수량·옵션 표현
- 동일 의미의 다양한 한국어 표현
- 잘못된 메뉴 또는 정보가 부족한 요청
- P1 구현 시 Clarification이 필요한 모호한 표현

데이터셋 분할 시 **최종 평가셋은 Fine-tuning 과정에서 사용하지 않는다.**

### 수행 절차

```text
Base Local NLU
 ↓
Baseline Evaluation
 ↓
Order-domain Dataset
 ↓
Fine-tuning
 ↓
Same Held-out Evaluation Set
 ↓
Before / After Comparison
```

구체적인 Fine-tuning 방식과 하이퍼파라미터는 Base Model PoC 이후 확정한다.

### 필수 평가 지표

- Intent Accuracy
- Slot Accuracy
- JSON Schema Valid Rate
- Invalid Menu 출력률
- Latency
- VRAM / RAM 사용량

완료 보고에는 동일 평가셋 기준의 **Baseline / Fine-tuned 결과를 함께 제시**한다.

현재 문서에서는 사전 Baseline 수치가 없으므로 수치형 개선 기준은 PoC 이후 확정한다. 다만 Fine-tuning 수행과 전후 비교 자체는 P0 완료 조건에서 제외하지 않는다.

### Safety Boundary

Fine-tuning은 `Schema Validator`와 `Order Engine Validation`을 대체하지 않는다.

Fine-tuned 모델의 출력도 기존과 동일하게 모든 검증을 통과해야 실제 Cart 상태를 변경할 수 있다.

### STT Fine-tuning

STT Fine-tuning은 P0의 필수 과제로 두지 않는다.

Baseline STT 평가에서 목표 사용자 발화 또는 메뉴명·수량·옵션 인식 문제가 주요 병목으로 확인된 경우 P2 확장 실험으로 수행할 수 있다.


---

# 9. Core Data Contract

## 9.1 OrderCommand Batch

NLU의 정상 출력은 `OrderCommand[]`, 실패 출력은 `OrderCommandError`다. NLU는 언어를 구조화하고, Schema Validator와 Order Engine이 메뉴·옵션·수량·원자성·Confirmation을 결정론적으로 검증한다.

필드, nested option, Intent별 null 규칙과 AC의 Source of Truth는 [`docs/specs/order-command.md`](specs/order-command.md)다. 옵션 값과 가격 계산은 [`docs/specs/beverage-option-adjustments.md`](specs/beverage-option-adjustments.md), 메뉴별 지원 범위는 [`docs/specs/menu-catalog.md`](specs/menu-catalog.md)를 따른다.

---

## 9.2 SessionState

```json
{
  "session_id": "uuid",
  "fulfillment_type": null,
  "cart": [],
  "pending_command": null,
  "clarification": null,
  "tts_level": 0,
  "last_response": "",
  "status": "IDLE",
  "listening_mode": null
}
```

`listening_mode`:

```text
null
SYSTEM_PROMPTED
USER_INITIATED_FALLBACK
```

주요 상태:

```text
IDLE
SERVICE_MODE
LISTENING
PROCESSING
RESULT
CONFIRMING
CLARIFYING
TTS_PLAYING
PAYMENT
COMPLETE
ERROR
```

---

## 9.3 ClarificationContext

```json
{
  "type": "TARGET_ITEM",
  "original_request_id": "uuid",
  "candidates": [
    "americano",
    "cafe_latte"
  ]
}
```

가능한 `type`:

```text
TARGET_ITEM
OPTION
QUANTITY
MENU_CANDIDATE
```

Clarification은 기존 Command를 대체하는 새로운 주문 요청이 아니라 **기존 Command의 미확정 Slot을 해결하기 위한 임시 Context**이다.

후보가 결정되면 원래 Command를 복원하여 다시 Validation 단계로 보낸다.

---

## 9.4 Menu Item

Menu DB는 메뉴 ID·이름·가격·온도·탐색 Metadata와 메뉴별 옵션 허용 범위의 런타임 Single Source of Truth다. 카탈로그 내용과 필드 및 옵션 적용 가능 조합은 [`docs/specs/menu-catalog.md`](specs/menu-catalog.md)를 따른다.

---

# 10. Order Engine

Order Engine만 실제 주문 상태를 변경할 수 있다.

처리 순서:

```text
OrderCommand[]
 ↓
JSON Schema Validation
 ↓
Intent Validation
 ↓
Menu Validation
 ↓
Option Validation
 ↓
Quantity Validation
 ↓
Reference Resolution
 ↓
Confirmation Policy
 ↓
State Transition
```

Confirmation Policy는 NLU가 아니라 Order Engine의 결정론적 규칙이다. 확인 대상 Intent, Pending 처리, 복수 Command 허용 조합과 Batch 원자성은 [`docs/specs/order-engine-operations.md`](specs/order-engine-operations.md)를 따른다.

## 10.1 ADD_ITEM

검증 완료 후 장바구니에 품목을 추가한다.

## 10.2 REMOVE_ITEM

대상이 유효하고 필요한 확인 절차를 통과한 경우에만 제거한다.

## 10.3 UPDATE_QUANTITY

대상이 명확하고 수량이 유효한 경우에만 변경한다.

## 10.4 UPDATE_OPTION

해당 메뉴가 요청 옵션을 지원하는 경우에만 변경한다.

수정·삭제에서 같은 메뉴의 HOT과 ICE가 모두 존재하는데 온도가 생략되면 임의 선택하지 않고 `AMBIGUOUS_TARGET`을 반환한다.

## 10.5 QUERY_CART

장바구니를 변경하지 않고 현재 상태를 반환한다.

## 10.6 CONFIRM_ORDER

최종 주문 내용과 총액을 검증한 후 주문을 확정 상태로 변경한다.

---

# 11. Ambiguity Resolution [P1]

예:

```text
Cart

americano
cafe_latte

User:
"큰 걸로 바꿔줘."
```

두 메뉴가 모두 Size 옵션을 지원한다면 대상이 모호하다.

Order Engine은 임의로 메뉴를 선택하지 않는다.

```text
UPDATE_OPTION
 ↓
Target Resolution
 ↓
2 Candidates
 ↓
CLARIFYING
```

시스템:

> "어떤 메뉴를 큰 사이즈로 변경할까요?"

P1에서는 `CLARIFYING` 질문의 TTS 종료 후 `SYSTEM_PROMPTED LISTENING`으로 전환한다.

사용자는 다음 중 하나로 해결할 수 있다.

```text
Voice:
SYSTEM_PROMPTED LISTENING
 ↓
"아메리카노."

또는

GUI:
[아메리카노]
```

동시에 GUI에는 최소 후보를 표시한다.

```text
어떤 메뉴인가요?

[아메리카노]
[카페라떼]
```

자동 Listening이 Timeout으로 끝난 뒤에도 사용자는 수동 마이크 Fallback 또는 GUI로 같은 후보를 선택할 수 있다.

후보가 결정되면:

```text
CLARIFYING
 ↓
candidate resolved
 ↓
original OrderCommand 복원
 ↓
PROCESSING
 ↓
Validation
```

검증 이후 필요하면 `CONFIRMING`으로 이동하고, 추가 확인이 필요하지 않다면 상태 변경을 실행한다.

---

# 12. Confirmation Model

확인이 필요한 Command는 `pending_command`로 관리한다.

삭제 Command의 기본 흐름:

```text
REMOVE_ITEM americano / iced
 ↓
Validation
 ↓
pending_command
 ↓
CONFIRMING
 ↓
TTS:
"아이스 아메리카노를 삭제할까요?"
 ↓
TTS End
 ↓
SYSTEM_PROMPTED LISTENING
```

사용자는 별도 버튼 조작 없이 음성으로 응답하거나 GUI 확인을 선택한다.

```text
SYSTEM_PROMPTED LISTENING
 ↓
"네."
 ↓
CONFIRM
 ↓
PROCESSING
 ↓
Cart에서 실제 삭제
```

GUI 확인 역시 동일한 Confirmation 결과로 처리한다.

음성과 GUI 이벤트가 동시에 도착하는 경우에도 동일한 `pending_command`를 한 번만 실행해야 한다. Listening Timeout 뒤에는 수동 마이크 Fallback으로 재입력할 수 있다.

확인 정책은 `REMOVE_ITEM`, `CONFIRM_ORDER`, `CANCEL`에만 적용한다. 정책 변경이 필요하면 NLU Prompt가 아니라 Order Engine Spec과 테스트를 변경한다.

---

# 13. Idempotency [P2]

`request_id`를 사용하여 동일한 Command가 반복 실행되는 것을 방지한다.

```text
Command 수신
 ↓
request_id processed?
 ├─ YES → 이전 결과 반환
 └─ NO → 검증 후 실행
```

---

# 14. Adaptive TTS Architecture [P1]

Adaptive TTS는 사용자의 상태를 모델이 추정하여 변경하지 않는다.

별도의 Rule-based Controller가 관리한다.

```text
Explicit User Request
 ↓
AdaptiveTTSController
 ↓
tts_level
 ↓
Response Formatter
 ↓
TTS
```

## 14.1 Level 0

- 기본 속도
- 기본 Pause
- 일반 문장

## 14.2 Level 1

- 발화 속도 감소
- Pause 증가
- 문장 간 분리 강화

## 14.3 Level 2

- 짧은 문장
- 메뉴명 / 수량 분리
- 금액 별도 전달
- 핵심 정보 우선

## 14.4 Transition

```text
SESSION START
 ↓
Level 0

"천천히 말해줘"
 ↓
Level 1

추가적인 느린 안내 요청
 ↓
Level 2

"기본 속도로"
 ↓
Level 0

SESSION END
 ↓
Reset
```

응답 지연 또는 침묵만으로 Level을 변경하지 않는다.

---

# 15. Response Generation

Response Generator는 Order Engine의 결정 결과만 사용자 표현으로 변환한다.

예:

```text
OrderResult

intent = CONFIRM_ORDER
item = americano
quantity = 2
```

Level 0:

> 아메리카노 두 잔, 맞으세요?

Level 2:

> 아메리카노.  
> 두 잔입니다.  
> 맞으세요?

Response Generator와 TTS 모델을 분리하여 TTS 모델을 교체하더라도 주문 로직에 영향을 주지 않도록 한다.

---

# 16. Perceived Latency Feedback

## NFR-05 Perceived Latency Feedback

사용자 발화가 종료되면 모델 추론 완료를 기다리지 않고 즉시 처리 시작 상태를 표시한다.

기본 처리:

```text
Speech End
 ↓
짧은 Earcon
 ↓
PROCESSING 상태
 ↓
"주문을 확인하고 있어요"
```

`주문을 확인하고 있어요`는 시각적 표시를 기본으로 한다.

고정 음성 안내는 처리 시간이 일정 기준 이상 길어지는 경우에만 제공할 수 있다.

불필요한 Auditory Clutter를 방지하기 위해 정상적인 모든 요청마다 장문의 대기 음성을 재생하지 않는다.

사용자의 응답을 기다리는 SYSTEM_PROMPTED Listening 상태에서는 처리 중 Earcon과 구분되는 Listening 상태 표시를 제공한다.

예:

> 🎤 말씀해 주세요

---

# 17. Latency Measurement [P0]

제품 E2E는 정상적인 Warm 주문 Turn의 **사용자 발화 종료 → 첫 음성 응답 실제 재생 시작(Time to First Audio)**이다. 사용자 자체 발화 시간은 포함하지 않는다.

```text
T0 = VAD가 사용자 발화 종료를 확정(input_end)
T1 = Processing Feedback 표시
T2 = STT 완료
T3 = NLU 완료
T4 = Order Engine 완료
T5 = 주문 결과 화면 표시
T6 = TTS 요청
T7 = 첫 음성 실제 재생 시작
T8 = TTS 종료
```

```text
Feedback Latency        = T1 - T0
STT Latency             = T2 - T0
NLU Latency             = T3 - T2
Order Engine Latency    = T4 - T3
Time to Visual Response = T5 - T0
E2E / Time to First Audio = T7 - T0
```

TTS 전체 종료(`T8`)와 TTS 단일 모델의 생성 시간은 E2E 종료점이 아니다. Cold Start, Mock E2E, Component Benchmark와 Adaptive TTS 추가 지연을 각각 구분한다. 수치, 판정과 Latency Provider Fallback은 [`docs/specs/e2e-latency.md`](specs/e2e-latency.md)를 따른다.

---

# 18. Minimal GUI

GUI는 `SessionState`를 기반으로 동작한다.

주요 표시 데이터:

```text
status
cart
pending_command
clarification
last_response
tts_level
listening_mode
```

주요 입력:

- 주문 세션 시작
- 매장/포장 터치 선택
- 수동 마이크 재입력 Fallback
- 확인
- 다시 말하기
- 다시 듣기
- 천천히 듣기
- 기본 속도
- Clarification 후보 선택
- 직원 호출

---

# 19. Error Handling

## E-01 STT Failure

```text
Cart 유지
pending_command 생성 안 함
clarification 생성 안 함
재입력 안내
```

## E-02 Invalid Menu

Menu DB에 존재하지 않는 메뉴는 실행하지 않는다.

## E-03 Ambiguous Reference

P0에서는 여러 후보가 존재하면 `AMBIGUOUS_TARGET`을 반환하고 전체 발화를 다시 입력하도록 안내한다. P1에서만 후보를 만들고 `CLARIFYING` 상태로 전환한다.

음료의 필수 온도가 누락된 경우도 P0에서는 `MISSING_FIELD`, `field=temperature`와 재입력 안내를 반환한다. P1 Clarification을 구현한 경우에만 미완성 Command를 보관하고 온도 후보를 질문한다.

## E-04 Invalid LLM Output

예:

- JSON Parsing Error
- Schema Error
- Unknown Intent
- 필수 Slot 누락

처리:

1. 정형 출력 재시도
2. 실패 시 사용자 재입력 요청
3. 기존 상태 유지

NLU Fine-tuning은 E-04 발생률을 낮추기 위한 학습 과제이지만, Fine-tuning 이후에도 위 검증·재시도·상태 보호 절차를 유지한다.

## E-05 Model Timeout

STT, LLM 또는 TTS 처리 시간이 제한 시간을 초과하면 안전한 오류 상태로 전환한다.

장바구니는 마지막 검증 상태를 유지한다.

## E-06 Repeated Failure

설정된 재시도 한계를 초과하면 직원 호출 기능을 제공한다.

기존 장바구니는 보존한다.

---

# 20. State Machine

기본 상태 전환은 다음과 같다.

```text
IDLE
 │ 주문하기
 ▼
SERVICE_MODE
 │ 매장/포장 질문 TTS 종료
 ▼
SYSTEM_PROMPTED LISTENING
 │ DINE_IN / TAKE_OUT 선택
 ▼
TTS_PLAYING ── playback_end ──→ SYSTEM_PROMPTED LISTENING
                                      │ speech + VAD end
                                      ▼
                                 PROCESSING
                     ┌────────────────┼────────────────┐
                     ▼                ▼                ▼
                  RESULT         CLARIFYING        CONFIRMING
                     │                │                │
                     └──── 응답 필요 TTS_PLAYING ─────┘
                                      │ playback_end
                                      ▼
                             SYSTEM_PROMPTED LISTENING

CONFIRMED ORDER → PAYMENT → COMPLETE → IDLE
```

- 응답이 필요하지 않은 결과 안내 뒤에는 자동 Listening을 시작하지 않는다.
- Timeout은 질문·Cart·Context를 유지한다.
- Timeout, 인식 실패 또는 추가 주문 재시작 시 `USER_INITIATED_FALLBACK LISTENING`을 사용할 수 있다.
- GUI 입력이 Listening 중 들어오면 Audio Session을 종료하고 GUI 입력을 한 번만 처리한다.

## 20.1 CONFIRMING Transition

```text
PROCESSING → CONFIRMING → TTS_PLAYING
                         ↓ playback_end
                 SYSTEM_PROMPTED LISTENING
                         ↓ YES / NO / CORRECTION
                    PROCESSING
```

SYSTEM_PROMPTED Timeout이 발생하면 `pending_command`와 `CONFIRMING` 상태를 유지한다. 사용자는 GUI 또는 수동 마이크 Fallback으로 계속 응답할 수 있다.

## 20.2 CLARIFYING Transition

```text
PROCESSING → CLARIFYING → TTS_PLAYING
                         ↓ playback_end
                 SYSTEM_PROMPTED LISTENING
                         ↓ Voice or GUI Candidate
                    PROCESSING
```

**CLARIFYING에서 직접 IDLE로 돌아가지 않는다.**

Clarification은 원래 Command를 완성하기 위한 중간 단계이므로 후보가 해결되면 기존 Command를 다시 `PROCESSING`으로 전달한다.

---

# 21. Session Lifecycle

새 Session 생성 시:

```text
cart = []
fulfillment_type = null
pending_command = null
clarification = null
tts_level = 0
last_response = ""
status = IDLE
listening_mode = null
```

Audio Session 종료 시 `listening_mode`는 `null`로 초기화한다.

주문 Session 종료 시 다음을 초기화한다.

- Cart
- Fulfillment Type
- Pending Command
- Clarification
- TTS Level
- Last Response
- Listening Mode
- 임시 Audio
- Session Context

---

# 22. Privacy Requirements

## PRIV-01

대기 상태에서는 마이크를 활성화하지 않는다. 사용자가 `주문하기`로 세션을 시작한 뒤에만 음성 입력을 사용할 수 있다.

## PRIV-02

사용자 응답이 필요한 TTS가 끝난 직후 제한된 시간 동안 `SYSTEM_PROMPTED` Listening을 사용한다.

## PRIV-03

`SYSTEM_PROMPTED` Listening은 현재 세션의 주문·확인·Clarification 응답을 받는 용도로만 사용한다.

## PRIV-04

Listening 상태는 화면을 통해 사용자에게 명확히 알려야 한다.

## PRIV-05

Listening Window가 종료되면 마이크 입력도 종료한다.

## PRIV-06

원본 음성은 기본적으로 장기 저장하지 않는다.

## PRIV-07

연구용 음성 저장은 별도 동의와 익명화가 있을 때만 수행한다.

## PRIV-08

연령, 청력 상태 또는 생체정보를 자동 추정하여 TTS 정책을 변경하지 않는다.

---

# 23. Observability

## Audio

- listening_mode
- audio_session_start
- audio_session_end
- vad_end
- system_prompted_listening_start
- listening_timeout
- speech_detected
- response_input_type
- No Speech 여부
- Audio Session Duration

`response_input_type`:

```text
VOICE_USER_INITIATED_FALLBACK
VOICE_SYSTEM_PROMPTED
GUI
```

## STT

- Latency
- 재시도 여부
- 실패 유형

## LLM / NLU

- Intent
- Schema Valid 여부
- Latency
- Retry 여부

## Order Engine

- Command
- Validation Result
- Mutation Result
- Error Code

## Clarification

- Clarification 발생 여부
- 후보 수
- 해결 방식: Voice / GUI
- 해결 성공 여부

## TTS

- Level
- Generation Latency
- First Audio Latency
- 전체 출력 시간

## End-to-End

- Feedback Latency
- Time to Visual Response
- Time to First Audio (`input_end` → 실제 재생 시작)
- Cold Start 여부
- `REAL_E2E` / `MOCK_E2E` / `COMPONENT_BENCHMARK` 구분

이를 통해 사용자 테스트에서 다음도 분석할 수 있다.

- 질문 직후 사용자가 자연스럽게 음성으로 대답하는 비율
- 자동 Listening 중 무응답 비율
- 음성과 GUI 중 어떤 방식을 더 많이 사용하는지
- 수동 마이크 Fallback 사용률

원본 사용자 음성을 로그로 기본 저장하지 않는다.

---

# 24. Performance Requirements

## NFR-01 Immediate State Feedback

사용자가 음성 입력을 마치면 즉시 처리 상태를 표시한다.

## NFR-02 Responsive UI

모델 추론 중에도 GUI는 응답 가능 상태를 유지한다.

## NFR-03 Adaptive TTS Latency

Adaptive TTS로 인한 추가 지연을 별도로 측정한다.

## NFR-04 TTS Quality

느린 TTS에서도 음질과 명료성이 허용 가능한 수준을 유지해야 한다.

## NFR-05 Perceived Latency

Earcon과 시각적 피드백을 이용해 사용자가 시스템 처리 시작 여부를 명확히 인식할 수 있어야 한다.

Warm Time to First Audio는 **1.2초 이내를 Target**, **1.5초 이내를 Requirement**로 한다. Time to Visual Response와 Cold Start는 별도 지표다. 상세 판정은 [`docs/specs/e2e-latency.md`](specs/e2e-latency.md)를 따른다.

---

# 25. Model PoC Gates

## 25.1 STT

측정:

- WER
- CER
- 메뉴명 인식 정확도
- 수량 인식 정확도
- 옵션 인식 정확도
- 소음 환경 성능
- Latency
- 메모리 사용량

P0에서는 Baseline STT가 주문 파이프라인을 성립시키는지 먼저 확인한다.

목표 사용자 발화 또는 주문 핵심 Token 인식이 주요 병목으로 확인되면 STT Fine-tuning을 P2 확장 실험으로 검토한다.

## 25.2 Local LLM / NLU — Baseline vs Fine-tuned [P0]

동일한 Held-out Evaluation Set에서 Baseline 모델과 Fine-tuned 모델을 비교한다.

측정:

- Intent Accuracy
- Slot Accuracy
- JSON Schema Valid Rate
- Invalid Menu 출력률
- Latency
- VRAM / RAM 사용량

반드시 다음 결과를 함께 기록한다.

```text
Baseline
Fine-tuned
Delta
```

Fine-tuning 방식, 학습 데이터 규모 및 수치형 통과 기준은 Base Model과 Baseline 측정 이후 확정한다.

단, **Fine-tuning 수행 및 전후 정량 비교는 P0 DoD에 포함한다.**

## 25.3 TTS [P0/P1]

P0 기본 TTS 측정:

- 자연스러움
- 정보 이해도
- First Audio Latency
- RTF

P1 TTS 연구·차별화 측정:

- 친절체 Fine-tuning 및 Baseline 전후 비교
- 별도 구조의 한국어 TTS 후보와 통제된 조건 비교
- MOS / SIM / TTFB / RTF / RAM / VRAM
- 발화 속도 제어
- Pause 제어
- Adaptive Level 추가 Latency

TTS의 고정 모델, 데이터 구성, 누수 방지, 학습 예산, 합격선, 점수 산식과 동점 처리는 `docs/specs/melotts-friendly-finetuning-poc.md`를 따른다. TRD는 실제 TTS Adapter가 공통 인터페이스와 로컬 자원 경계를 지키는지만 규정한다.

P0는 실제 한국어 기본 TTS로 단일 주문 경로를 성립시키는 것을 우선하며 TTS Fine-tuning 완료를 차단 조건으로 삼지 않는다. 프로젝트의 필수 Fine-tuning 요건은 P0 Local NLU Fine-tuning으로 충족한다. TTS Fine-tuning과 다중 모델 비교는 P1에서 수행하고 모델 선택은 각 PoC 결과 이후 확정한다.

---

# 26. Testing Strategy

## 26.1 Unit Test

- OrderCommand Schema
- Menu Validation
- 가격 계산
- 수량 변경
- 옵션 변경
- 삭제
- 총액 계산
- idempotency
- TTS Level Transition
- Clarification Candidate Resolution
- Audio Session State
- SYSTEM_PROMPTED Listening
- USER_INITIATED_FALLBACK Listening
- Listening Timeout

## 26.2 Integration Test

```text
Audio → STT
STT → NLU
NLU → Order Engine
Order Engine → Clarification
Clarification → Order Engine
Order Engine → Response
Response → TTS
SessionState → GUI
```

추가 확인:

- TTS 종료 전 Listening 금지
- GUI 선택 시 Listening 종료
- 음성/GUI 동시 입력 중복 실행 방지
- Clarification Resolve 후 PROCESSING 복귀
- Confirmation Response 후 PROCESSING 복귀

---

# 27. End-to-End Scenario Tests

## E2E-01 정상 주문

> 아메리카노 두 잔 주세요.

정확한 품목과 수량이 반영되어야 한다.

## E2E-02 수량 수정

> 두 잔으로 바꿔줘.

대상 품목만 수정되어야 한다.

## E2E-03 삭제

> 아까 시킨 콜라는 빼줘.

지정 품목만 삭제되어야 한다.

## E2E-04 존재하지 않는 메뉴

Cart 상태가 변경되어서는 안 된다.

## E2E-05 Ambiguous Request

> 큰 걸로 바꿔줘.

여러 대상이 존재하면 `CLARIFYING` 상태로 이동하고 Voice/GUI 후보를 제공해야 한다.

## E2E-06 GUI Clarification

GUI 후보를 선택하면 기존 모호한 Command가 올바른 대상으로 실행되어야 한다.

## E2E-07 천천히 듣기

TTS Level이 상승하고 현재 세션에 유지되어야 한다.

## E2E-08 Session Reset

새 세션에서 Cart 및 TTS Level이 초기화되어야 한다.

## E2E-09 Duplicate Request [P2]

같은 `request_id`가 반복되어도 한 번만 실행되어야 한다.

## E2E-10 No Speech

자동 Listening 또는 수동 마이크 Fallback 뒤 발화가 없으면 Cart를 변경하지 않고 안전하게 복귀해야 한다.

## E2E-11 Repeated Manual Mic Input

LISTENING 중 수동 마이크 버튼을 반복 입력해도 중복 Audio Session이 생성되지 않아야 한다.

## E2E-12 Processing Feedback

Speech End 직후 모델 처리 완료 전에도 상태 표시와 Earcon이 제공되어야 한다.

## E2E-13 Confirmation Automatic Listening [P0]

시스템이 최종 주문 내용을 안내하고 확정을 요청한다.

TTS 실제 재생 종료 직후 SYSTEM_PROMPTED Listening이 시작되어야 한다.

사용자가 별도의 버튼 조작 없이

> "네."

라고 말하면 정상적으로 주문을 확인해야 한다.

## E2E-14 Clarification Automatic Listening [P1]

시스템:

> "어떤 메뉴를 큰 사이즈로 변경할까요?"

TTS 종료 직후 SYSTEM_PROMPTED Listening이 시작되어야 한다.

> "아메리카노."

라고 응답하면 원래 UPDATE_OPTION Command가 복원되어 PROCESSING으로 이동해야 한다.

## E2E-15 Listening Timeout [P0]

시스템 질문 이후 사용자가 응답하지 않으면 Listening을 종료한다.

다음 상태는 유지한다.

- pending_command
- clarification

Cart는 변경하지 않는다.

## E2E-16 GUI During Listening [P0]

Listening 중 GUI 후보를 선택하면 Audio Session을 종료하고 GUI 선택을 한 번만 처리해야 한다.

## E2E-17 No Listening on Non-question Response [P0]

단순 정보 제공처럼 사용자의 직접적인 응답이 필요하지 않은 TTS가 종료된 경우에는 마이크를 자동 활성화해서는 안 된다.

---

# 28. MVP Technical Definition of Done

말로(Mallo)의 완료 기준은 우선순위별로 구분한다.

일정이 부족한 경우 **P2 → P1 순서로 제외**하며, P0가 모두 충족되어야 MVP 데모가 성립한 것으로 판단한다.

## P0 — 데모 성립 최소선

- 대기 화면의 `주문하기` 한 번으로 주문 Session을 시작할 수 있다.
- 메뉴 주문 전 `DINE_IN` 또는 `TAKE_OUT`을 터치나 음성으로 선택하고 세션 동안 유지한다.
- 사용자 응답이 필요한 TTS가 끝나면 SYSTEM_PROMPTED Listening을 자동으로 시작한다.
- VAD 또는 이에 준하는 방식으로 발화 종료를 판단할 수 있다.
- 인식 실패·Timeout·추가 주문 시 수동 마이크 Fallback을 사용할 수 있다.
- TTS 재생 중에는 마이크가 비활성화되고 Barge-in을 처리하지 않는다.
- 무음 및 잘못된 입력이 기존 주문 상태를 손상시키지 않는다.
- 한국어 주문을 텍스트로 변환할 수 있다.
- 자연어 주문을 구조화된 `OrderCommand[]`로 변환한다.
- 모든 Command가 Schema Validation을 통과해야 실행 가능하다.
- Menu DB가 메뉴 및 가격의 Single Source of Truth다.
- Order Engine만 장바구니를 변경한다.
- 주문 추가·삭제·수정·조회·확정이 가능하다.
- 주문 상태를 음성과 화면으로 확인할 수 있다.
- 처리 시작 피드백이 모델 추론 완료 전에 제공된다.
- 반복 실패 시 기존 Cart를 보호하는 안전한 Fallback을 제공한다.
- 실제 PG 없이 전체 주문 완료 흐름을 시연할 수 있다.
- Local NLU의 Fine-tuning 전 Baseline을 Held-out Evaluation Set에서 측정한다.
- 주문 도메인 데이터로 Local NLU Fine-tuning을 수행한다.
- 동일 평가셋에서 Baseline과 Fine-tuned 모델의 Intent Accuracy, Slot Accuracy, JSON Schema Valid Rate, Invalid Menu 출력률을 비교 기록한다.
- Fine-tuned 모델도 Schema Validator와 Order Engine Validation을 우회할 수 없다.
- Real Warm E2E와 Mock/Component 측정을 구분하고 Time to First Audio를 기록한다.

## P1 — 말로(Mallo) 차별화

- 모호한 요청은 `CLARIFYING` 상태에서 처리된다.
- Clarification 후보를 자동 Listening 음성 또는 GUI로 선택할 수 있다.
- Clarification 해결 후 원래 Command가 `PROCESSING` 단계로 복귀한다.
- 친절한 매장 안내 음성을 목표로 TTS Fine-tuning 또는 도메인 적응을 수행하고 Baseline 및 별도 구조의 후보와 비교한다.
- Adaptive TTS Level 0~2가 동작한다.
- TTS Level은 세션 동안 유지되고 새 세션에서 초기화된다.

## P2 — 있으면 좋은 고도화

- 동일 요청의 중복 실행을 차단한다.
- GUI와 음성 응답이 동시에 발생해도 Command가 중복 실행되지 않는다.
- 필요성이 확인된 경우 Echo Cancellation 또는 동등한 Echo 방지 대책을 적용한다.

---

# 29. Open Technical Decisions

다음 항목은 PoC와 사용자 테스트 이후 확정한다.

- **STT 모델**: `whisper-medium-qlora-domain/merged-bf16` 확정 (2026-08-21, 근거: `docs/specs/stt-model-selection.md`)
- Local LLM 모델
- TTS 모델
- Local NLU Fine-tuning 방식 및 하이퍼파라미터
- Fine-tuning 학습 데이터 규모와 수치형 통과 기준
- STT Fine-tuning P2 수행 여부
- VAD 구현 방식
- Silence Timeout
- Maximum Recording Duration
- 자동 Listening 응답 Window 길이
- Listening 시작 Earcon 사용 여부
- Listening 상태 표시 방식
- Echo Cancellation 필요 여부
- TTS Playback 종료 판단 방식
- Listening 중 Background Speech 처리 정책
- USER_INITIATED_FALLBACK / SYSTEM_PROMPTED VAD 파라미터 차등 적용 여부
- 처리 중 추가 음성 입력 정책
- STT Confidence 정책
- LLM Retry 횟수
- Model Timeout
- Clarification 후보 최대 개수
- Level별 TTS Parameter
- 시연 하드웨어 최소 사양
