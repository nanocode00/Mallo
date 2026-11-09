---
title: "말로(Mallo) 작업 티켓 및 3인 역할 분담"
tags: [doc]
---

# 말로(Mallo) 작업 티켓 및 3인 역할 분담

> 이 문서는 말로(Mallo) MVP의 작업 백로그를 관리하기 위한 기준 문서다.
> Jira를 사용하지 않더라도 각 작업은 고유 Ticket ID로 추적하며, Git branch / commit / PR / 회의 기록에서 동일한 ID를 사용한다.
> 제품 범위와 우선순위는 `docs/prd.md`, 기술 경계는 `docs/trd.md`, 상세 수치와 AC는 기능별 Spec을 따른다. 이 문서는 이를 재정의하지 않고 실행 상태만 관리한다.

## 1. Ticket ID 규칙

| Prefix | 영역 | 기본 담당 |
|---|---|---|
| `C-*` | Common / Architecture | 전원 |
| `T-*` | Adaptive TTS / Voice UX | A |
| `N-*` | Local LLM / NLU | B |
| `O-*` | Order Engine / Menu DB | B |
| `S-*` | STT / Audio | C |
| `UI-*` | Minimal GUI | C |
| `I-*` | Integration / Service | C 중심, 전원 협업 |
| `E-*` | Evaluation / User Test / Demo | 전원 |

예시:

```text
Ticket: T-05 Baseline TTS 구현
Branch: feat/T-05-baseline-tts
Commit: feat: [T-05] 기본 TTS 서비스 구현
PR: feat: [T-05] 기본 TTS 서비스 구현
```

## 2. 상태 관리 규칙

Markdown에서는 체크박스와 상태 접미사를 함께 사용한다.

- `[ ]` TODO — 아직 수행할 작업
- 작업 시작 시 해당 줄 끝에 `— IN PROGRESS` 표기
- `[x]` — 완료되어 닫힌 작업
- 막힌 작업은 `— BLOCKED: 사유`를 추가
- 구현하지 않기로 최종 범위를 축소한 작업은 `[x] ... — NOT PLANNED: 사유`로 닫는다. 이 표기는 **기능 구현 완료를 의미하지 않고, 기능동결에서 범위 제외가 확정됐음을 의미한다.**

예:

```md
- [ ] **I-08** 전체 End-to-End Latency 측정 — IN PROGRESS
- [ ] **E-06** 최종 사용자 평가 진행 — BLOCKED: 외부 참가자 필요
- [x] **N-23** Size 음성 표현 NLU 연결 — NOT PLANNED: 최종 일정에서 Size 지원 제외
- [x] **C-11** OrderCommand JSON Schema 확정
```

## 3. 기준 문서 연결

- 제품 범위·P0/P1/P2·Do Not Build: [`docs/prd.md`](prd.md)
- 시스템 Pipeline·모듈 책임·공통 인터페이스: [`docs/trd.md`](trd.md)
- 기능별 모델·데이터·수치·Edge Case·AC: [`docs/specs/`](specs/)
- 현재 결정의 배경과 수행 결과: [`docs/worklog.md`](worklog.md), [`docs/worklogs/`](worklogs/)
- 기능동결 시점의 상태 정합화: [`docs/final-ticket-reconciliation.md`](final-ticket-reconciliation.md)

이 문서에는 위 계약을 복사하지 않는다. 각 티켓에는 상태, 담당, 의존성과 한두 문장의 완료 기준 및 관련 Spec/AC 링크만 기록한다.

## 4. 3인 역할 분담

| 담당 | 소유 영역 | 책임 |
|---|---|---|
| A | Adaptive TTS / Voice UX | TTS 모델, Level 0~2, Adaptive Controller, TTS 평가 |
| B | Local LLM / NLU / Order Engine | 주문 이해, Dataset, Fine-tuning, Menu DB, 주문 상태/검증 |
| C | STT / Audio / GUI / Integration | 자동 Listening·수동 마이크 Fallback, STT, Audio Processing, UI, 전체 시스템 통합 |

---

# 5. 전체 Ticket Backlog

## 5.1 공통 / 설계

**기본 담당:** 전원

- [x] **C-01** MVP 범위 최종 확정
  - 완료 기준: 지원 기능과 Do Not Build 범위를 팀 전원이 합의한다.
  - 결과: 팀 합의를 완료했으며, 지원 범위와 제외 범위 및 P0/P1/P2 우선순위는 `docs/prd.md`를 따른다.
- [x] **C-02** 가상 카페 콘셉트 결정
  - 완료 기준: MVP에서 사용할 하나의 가상 매장 콘셉트를 확정한다.
  - 결과: MVP 매장 범위를 `docs/prd.md`에 확정했다.
- [x] **C-03** 메뉴 약 10개 확정
  - 완료 기준: 테스트와 데모에 사용할 메뉴 목록을 확정한다.
  - 결정: `docs/specs/menu-catalog.md`의 메뉴 10개를 사용한다.
- [x] **C-04** 메뉴 가격 확정
  - 완료 기준: 모든 MVP 메뉴의 가격 데이터를 확정한다.
  - 결정: `docs/specs/menu-catalog.md`의 MVP 시연용 고정 가격을 사용한다.
- [x] **C-05** 메뉴 옵션 종류 확정
  - 완료 기준: Size, Hot/Ice 등 MVP에서 검토할 옵션을 확정한다.
  - 결과: 메뉴별 옵션 Schema와 가격 계산 규칙은 `docs/specs/menu-catalog.md`, `docs/specs/beverage-option-adjustments.md`에 정의했다. 단, **Size 음성 주문/변경은 최종 일정 축소로 서비스 범위에서 제외**했으며 Schema에 존재하는 옵션과 최종 지원 기능을 구분한다.
- [x] **C-06** Menu Schema 확정
  - 완료 기준: 메뉴 ID, 이름, 가격, 옵션 등을 포함하는 공통 Schema를 확정한다.
  - 결정: Category, MenuItem, TemperaturePolicy 계약은 `docs/specs/menu-catalog.md`를 따른다.
- [x] **C-07** Intent 목록 확정
  - 완료 기준: QUERY_MENU, ADD_ITEM 등 지원 Intent를 확정한다.
  - 결과: Intent 목록과 wire format은 `docs/specs/order-command.md`에 확정했다.
- [x] **C-08** Slot 목록 확정
  - 완료 기준: menu_id, quantity, options 등 Slot 정의를 확정한다.
  - 결과: Slot과 어댑터 책임은 `docs/specs/order-command.md`에 확정했다.
- [x] **C-09** Intent별 필수/선택 필드 정의
  - 완료 기준: 각 Intent에서 필요한 필드와 선택 필드를 문서화한다.
  - 결과: Intent별 필드 규칙은 `docs/specs/order-command.md`에 확정했다.
- [x] **C-10** OrderCommand Error Schema 정의
  - 완료 기준: 모호하거나 잘못된 NLU 출력에 대한 오류 형식을 정의한다.
  - 결과: `schemas/order-command-error.schema.json`, `src/domain/order_command_error.py`, `docs/specs/order-command-error.md`에 NLU 오류 구조화 계약을 구현했다.

- [x] **C-11** OrderCommand JSON Schema 확정
  - 완료 기준: NLU와 Order Engine 사이의 최종 JSON 계약을 확정한다.
  - 결과: `schemas/order-command.schema.json`에 12개 Intent의 `OrderCommand[]` 계약을 구현했다.
- [x] **C-12** STT 반환 형식 정의
  - 완료 기준: STT가 반환할 text 및 부가 정보 형식을 확정한다.
  - 결과: `schemas/stt-result.schema.json`, `src/domain/stt_result.py`, `src/interfaces/stt.py`, `docs/specs/stt-result.md`에 STTResult 및 STTFailure 계약을 정의했다.

- [x] **C-13** NLU 입출력 형식 정의
  - 완료 기준: text/current_state 입력과 OrderCommand 출력을 확정한다.
  - 결정: 현재 주문 상태의 복사본을 NLU에 전달한다. 정상 출력은 `OrderCommand[]`, 실패 출력은 `OrderCommandError`다.
- [x] **C-14** Order Engine 입출력 형식 정의
  - 완료 기준: OrderCommand/state 입력과 new_state/response_text 출력을 확정한다.
  - 결정: Batch 전체 검증 후 실행하며 Cart 변경은 Order Engine이 담당한다. 최종 주문 확정은 ORDER_REVIEW의 명시적 확인 흐름을 사용하고 별도 Pending Confirmation 상태 머신은 최종 MVP에 도입하지 않는다.
- [x] **C-15** TTS 입출력 형식 정의
  - 완료 기준: response_text/tts_level 입력과 audio 출력을 확정한다.
  - 결과: `schemas/tts-result.schema.json`, `src/domain/tts_result.py`, `src/interfaces/tts.py`, `docs/specs/tts-result.md`에 TTSResult, TTSLevel 및 TTSFailure 계약을 정의했다.

- [x] **C-16** 공통 Error Response 정의
  - 완료 기준: 모듈별 오류를 통합 서비스가 다룰 수 있는 공통 형식으로 정한다.
  - 결과: `schemas/error-response.schema.json`, `src/domain/errors.py`, `docs/specs/error-response.md`를 정의하고 `OrderResult` 및 `VoicePipeline`과 연동했다.

- [x] **C-17** 모듈 연결 방식 결정
  - 완료 기준: Python 함수, REST API 등 모듈 연결 방식을 확정한다.
  - 결정: MVP에서는 동일 프로세스 내 Python 함수 호출을 사용한다. 상세 근거는 `docs/worklog.md`를 참고한다.
- [x] **C-18** Repository 구조 결정
  - 완료 기준: docs, src, tests 및 모듈별 디렉토리 구조를 확정한다.
  - 결정: 회의안에 따라 `src` 아래 app/interfaces/adapters/domain/orchestrator/config/utils 계층과 unit/integration 테스트 구조를 사용한다. 상세 내용은 `docs/specs/mock-e2e-pipeline.md`를 참고한다.
- [x] **C-19** Mock End-to-End Pipeline 구축
  - 완료 기준: 실제 AI 모델 없이 text→Mock NLU→Order Engine→Baseline TTS 흐름을 동작시킨다.
  - 결과: text→Mock NLU→결정론적 Agent→Mock TTS 흐름과 AC 테스트 10개를 구현했다.

## 5.2 Adaptive TTS / Voice UX

**기본 담당:** A

- [x] **T-01** TTS 후보 모델 조사
  - 완료 기준: 한국어 지원, 로컬 실행, 라이선스와 제어 가능성을 비교한다.
- [x] **T-02** TTS 후보 모델 로컬 실행 테스트
  - 완료 기준: 후보 모델을 실제 개발 환경에서 최소 1회 이상 실행한다.
  - 결과: 후보 모델 실행을 검증했다. 조건과 결과는 `docs/worklogs/tts.md`를 따른다.
- [x] **T-03** TTS 후보 VRAM / Latency / RTF 비교
  - 완료 기준: 동일 문장 기준으로 자원 사용량과 속도를 기록한다.
  - 결과: 자원·성능 측정을 완료했다. 측정 계약은 `docs/specs/tts-benchmark.md`, 결과는 `docs/worklogs/tts.md`를 따른다.
- [x] **T-04** TTS 후보 기본 음질 비교
  - 완료 기준: 후보별 자연스러움과 명료도를 비교해 Baseline 후보를 정한다.
  - 결과: Baseline 및 Fine-tuned 비교 청음 스위트를 구축하고 PoC 최우선 모델(MeloTTS Friendly)을 선정했다.
- [x] **T-05** Baseline TTS 구현
  - 완료 기준: 입력 텍스트를 정상적으로 한국어 음성으로 출력할 수 있게 한다.
  - 결과: MeloTTS 및 Qwen3-TTS 프로덕션 어댑터(`src/adapters/tts/`)를 구현했다.
- [x] **T-06** TTS 서비스 인터페이스 구현
  - 완료 기준: 다른 모듈에서 text와 level을 전달해 호출할 수 있게 한다.
  - 결과: `src/interfaces/tts.py`에 `TTS` 프로토콜 및 `TTSFailure`를 정의하고 파이프라인에 연결했다.
- [x] **T-07** Baseline TTS Latency 측정
  - 완료 기준: 대표 문장 세트에 대한 기본 지연 시간을 기록한다.
  - 결과: 측정을 완료했다. 수치와 실행 환경은 `docs/worklogs/tts.md`를 따른다.
- [x] **T-08** Adaptive TTS Level 0 규칙 정의
  - 완료 기준: 기본 속도와 기본 문장 구조를 확정한다.
  - 결과: Level 0 규칙을 `docs/specs/adaptive-text-transformer.md`에 확정했다.
- [x] **T-09** Level 0 기본 발화 속도 확정
  - 완료 기준: Baseline 발화 속도를 수치 또는 설정값으로 고정한다.
  - 결과: 기본 속도를 `docs/specs/adaptive-tts-controller.md`에 확정하고 구현했다.
- [x] **T-10** Level 1 발화 속도 설정
  - 완료 기준: 느린 안내 요청 시 적용할 속도 감소 정책을 구현한다.
  - 결과: Level 1 속도를 `docs/specs/adaptive-tts-controller.md`에 확정하고 구현했다.
- [x] **T-11** Level 1 Pause 처리 구현
  - 완료 기준: 문장 및 핵심 정보 사이 Pause 증가를 구현한다.
  - 결과: `docs/specs/adaptive-text-transformer.md`의 Pause 규칙을 구현했다.
- [x] **T-12** Level 0/1 Latency 비교
  - 완료 기준: 적응 적용 전후 추가 지연을 측정한다.
  - 결과: MeloTTS Friendly에서 Level별 100회 합성을 비교해 Level 1의 평균 추가 지연 40.7ms, p95 추가 지연 54.8ms를 확인했다. 측정 계약과 결과는 `docs/specs/adaptive-tts-latency.md`, `docs/worklogs/tts.md`를 따른다.
- [x] **T-13** Level 2 문장 분절 규칙 정의
  - 완료 기준: 긴 응답을 짧은 정보 단위로 나누는 규칙을 정의한다.
  - 결과: 분절 규칙을 `docs/specs/adaptive-text-transformer.md`에 확정했다.
- [x] **T-14** Level 2 핵심 정보 강조 구조 정의
  - 완료 기준: 메뉴명, 수량, 가격 중심으로 재구성하는 형식을 정한다.
  - 결과: 강조 규칙을 `docs/specs/adaptive-text-transformer.md`에 확정했다.
- [x] **T-15** Level 2 Text Transformation 구현
  - 완료 기준: response_text를 Level 2 형식으로 변환하는 로직을 구현한다.
  - 결과: `src/domain/text_transformer.py`에 `AdaptiveTextTransformer`를 구현하고 AC 테스트를 통과했다.

- [x] **T-16** TTS Level 상태 관리 구현
  - 완료 기준: 현재 세션의 Level 0~2 상태를 관리한다.
  - 결과: `src/domain/tts_controller.py`에 `AdaptiveTTSController` 상태 머신을 구현했다.
- [x] **T-17** TTS Level 상승 조건 구현
  - 완료 기준: 다시 말해줘/천천히 말해줘 등의 명시적 요청을 반영한다.
  - 결과: 상승 전이를 `docs/specs/adaptive-tts-controller.md`에 확정하고 구현했다.
- [x] **T-18** TTS Level 하강 조건 구현
  - 완료 기준: 기본 속도/좀 빨리 등의 요청을 반영한다.
  - 결과: 하강 전이를 `docs/specs/adaptive-tts-controller.md`에 확정하고 구현했다.
- [x] **T-19** 새 세션 TTS Level Reset 구현
  - 완료 기준: 신규 주문 세션 시작 시 Level 0으로 초기화한다.
  - 결과: `reset()` 호출 시 Level 0으로 초기화되도록 구현했다.

- [x] **T-20** GUI TTS 제어 버튼 연동
  - 완료 기준: 다시 듣기/천천히/기본 속도 버튼과 Controller를 연결한다.
  - 결과: Minimal GUI(다시 듣기, 천천히, 보통 속도 버튼)와 백엔드 `/api/tts-control` 및 Controller를 연동했다.
- [x] **T-21** TTS 평가 문장 세트 제작
  - 완료 기준: 주문 확인, 가격, 수량 등 대표 문장을 평가용으로 구성한다.
- [x] **T-22** TTS RTF 측정 코드 작성
  - 완료 기준: 동일 조건에서 반복 측정 가능한 Benchmark 코드를 만든다.
- [x] **T-23** TTS MOS 평가 양식 준비
  - 완료 기준: 자연스러움/명료도 평가 항목과 기록 양식을 만든다.
- [ ] **T-24** Adaptive TTS Level별 이해도 비교
  - 완료 기준: Level 0/1/2의 주문 정보 이해도 차이를 평가한다.
- [x] **T-25** AI Hub 친절체 데이터 감사 및 30분 adaptation package 생성 `[P1]`
  - 완료 기준: TTS Fine-tuning Spec의 데이터 감사·split·누수 방지 AC를 통과한다.
  - 결과: 데이터 감사와 manifest 생성을 완료했다. 입력·선정 계약은 `docs/specs/melotts-friendly-finetuning-poc.md`, 수행 결과는 `docs/worklogs/tts.md`를 따른다.
- [x] **T-26** MeloTTS 친절체 Fine-tuning 실행 `[P1]`
  - 완료 기준: TTS Fine-tuning Spec의 MeloTTS 학습·checkpoint·추론 AC를 통과한다.
  - 결과: MeloTTS Korean VITS2 기반 2,000 steps 학습 완료 (`G_2000.pth`), 친절체 어조 전이 및 추론 검증 완료.
- [x] **T-27** Qwen3-TTS 비교 모델 실행 `[P1]`
  - 완료 기준: TTS Fine-tuning Spec의 Qwen3-TTS 스모크 테스트·학습·fallback·추론 AC를 통과한다.
  - 결과: Qwen3-TTS 0.6B Base 모델 10 epoch SFT 완료(Loss 2.19), calm_friendly 화자 등록 및 추론 검증 완료.
- [x] **T-28** TTS 다중 모델 품질·성능 비교 `[P1]`
  - 완료 기준: TTS Fine-tuning Spec의 동일 조건 평가와 최종 모델 선택 AC를 통과하고 결과표를 연결한다.
  - 결과: 후보 비교와 PoC 모델 선정을 완료했다. 평가 계약은 `docs/specs/tts-model-comparison.md`, 수치와 선정 근거는 `docs/worklogs/tts.md`를 따른다.
- [x] **T-29** AI Hub 학습 산출물 공유 범위 문의 `[P1 외부 공개 전 필수]`
  - 완료 기준: TTS Fine-tuning Spec의 라이선스 후속 문의 AC를 통과하고 답변 일자를 worklog에 기록한다.
  - 결과: 2026-08-27 20:21 접수, 2026-08-28 09:04:31 AI Hub 관리자 답변 수신. 학습 결과 모델·생성 음성 활용 가능 범위, 원천·라벨링·재가공 데이터 재배포 금지, 출처 표기 조건을 확인했다. 상세는 `docs/aihub-tts-license-inquiry.md`를 따른다.
- [ ] **T-30** TTS 사용성 테스트 인계 `[P1]`
  - 완료 기준: TTS Fine-tuning Spec의 사용성 테스트 인계 AC를 통과하고 개선 근거를 연결한다.
- [x] **T-31** Adaptive TTS Intent 실행 연결
  - 완료 기준: 반복·느리게·기본속도 Intent가 마지막 안내 재생과 세션 Level에 반영된다.

## 5.3 Local LLM / NLU

**기본 담당:** B

**데이터셋 기준:** [`docs/specs/nlu-dataset.md`](specs/nlu-dataset.md) (N-05~N-14)

> 최종 상태: NLU 3,000행 데이터셋(Train 2,400 / Validation 300 / Test 300), Qwen3 QLoRA 학습 파이프라인, Web 런타임 연결 및 최종 후보 평가까지 반영됐다. N-05~N-22는 PR #205, #211, #214와 관련 worklog를 근거로 완료 처리한다. N-23 Size 음성 연결은 기능동결에서 제외했다.

- [x] **N-01** Intent 목록 구현용 정리
  - 완료 기준: 확정된 Intent를 NLU 코드와 Dataset에서 동일하게 사용하도록 정리한다.
- [x] **N-02** Slot 목록 구현용 정리
  - 완료 기준: 확정된 Slot 이름과 타입을 코드 기준으로 고정한다.
- [x] **N-03** Intent별 필수 Slot 정의
  - 완료 기준: Validation 가능한 형태로 필수 Slot 규칙을 정리한다.
- [x] **N-04** Ambiguous Case 정의
  - 완료 기준: 메뉴/수량/옵션이 모호한 입력 사례와 처리 방식을 정의한다.
- [x] **N-05** 메뉴 추가 표현 수집
  - 완료 기준: ADD_ITEM 학습/평가용 다양한 한국어 표현을 수집한다.
- [x] **N-06** 메뉴 삭제 표현 수집
  - 완료 기준: REMOVE_ITEM 관련 다양한 표현을 수집한다.
- [x] **N-07** 수량 변경 표현 수집
  - 완료 기준: UPDATE_QUANTITY 관련 다양한 표현을 수집한다.
- [x] **N-08** 옵션 변경 표현 수집
  - 완료 기준: UPDATE_OPTION 관련 다양한 표현을 수집한다.
- [x] **N-09** 메뉴·주문 조회·확정·취소 표현 수집
  - 완료 기준: QUERY_MENU/QUERY_CART/CONFIRM_ORDER/CANCEL 관련 다양한 표현을 수집한다.
- [x] **N-10** Adaptive TTS 요청 표현 수집
  - 완료 기준: REQUEST_REPEAT/REQUEST_SLOWER/REQUEST_DEFAULT_SPEED 관련 표현을 수집한다.
- [x] **N-11** Raw 주문 문장 정제
  - 완료 기준: 중복, 오탈자, 비정상 데이터를 정리한다.
- [x] **N-12** OrderCommand JSON Label 생성
  - 완료 기준: 각 입력 문장에 정답 Structured Output을 부여한다.
- [x] **N-13** Train / Validation / Test 분할
  - 완료 기준: 데이터 누수를 막도록 학습/검증/테스트 세트를 분할한다.
- [x] **N-14** Dataset 중복 및 누수 검사
  - 완료 기준: 유사 문장이 서로 다른 split에 과도하게 중복되지 않는지 검사한다.
- [x] **N-15** Local LLM 후보 선정
  - 완료 기준: 로컬 실행 가능한 소형 모델 중 Baseline 모델을 선정한다.
- [x] **N-16** Baseline Prompt 작성
  - 완료 기준: 자연어 주문을 JSON으로 변환하는 기본 Prompt를 만든다.
- [x] **N-17** Structured Output 구현
  - 완료 기준: 모델 출력이 OrderCommand Schema를 따르도록 파싱/제약을 구현한다.
- [x] **N-18** Baseline NLU 평가
  - 완료 기준: Intent/Slot/Schema 준수율을 측정해 기준 성능을 확보한다.
- [x] **N-19** Fine-tuning Dataset 최종 정리
  - 완료 기준: Baseline 오류 분석을 반영해 학습 데이터를 확정한다.
- [x] **N-20** Local LLM Fine-tuning 실행
  - 완료 기준: 선정 모델을 주문 도메인 데이터로 Fine-tuning한다.
- [x] **N-21** Baseline vs Fine-tuning 비교
  - 완료 기준: 동일 Test Set으로 성능과 지연을 비교한다.
- [x] **N-22** NLU 오류 유형 분석
  - 완료 기준: Intent 오류, Slot 누락, Hallucination, Schema 오류 등을 분류한다.
  - 결과: Qwen3-0.6B 서비스 후보는 Intent 100%, Slot 96.78%, Error Code 96.67%, Schema Valid 100%, Warm p95 1.182s를 기록했다. Qwen3-1.7B는 reference 평가에서 Error Code Accuracy 70%, Warm p95 8.40s로 production gate를 통과하지 못했다. 상세는 `docs/final-quantitative-results.md`와 NLU 관련 worklog를 따른다.
- [x] **N-23** Size 음성 표현 NLU 연결 — NOT PLANNED: 최종 일정에서 Size 음성 주문·변경 지원 제외
  - 원래 완료 기준: `작은/스몰`, `보통/미디엄`, `큰/라지 사이즈` 표현을 `small`, `medium`, `large`로 변환하고 Size 생략 시 `null`을 유지하는 ADD_ITEM·UPDATE_OPTION AC를 통과한다.
  - 최종 결정: OrderCommand Schema와 일부 도메인 규칙에는 Size가 남아 있으나, 음성 NLU 연결과 최종 서비스 지원은 기능동결 범위에서 제외한다. 발표 및 최종 기능 목록에서 Size 지원을 주장하지 않는다.

## 5.4 Order Engine / Menu DB

**기본 담당:** B

- [x] **O-01** Menu DB Schema 구현
  - 완료 기준: 확정된 Menu Schema를 실제 코드/DB 형태로 구현한다.
- [x] **O-02** 가상 메뉴 데이터 입력
  - 완료 기준: MVP 메뉴와 가격, 옵션 데이터를 입력한다.
- [x] **O-03** 메뉴 검색 함수 구현
  - 완료 기준: ID/이름 기반 메뉴 조회 기능을 구현한다.
  - 결과: Menu DB의 ID·카테고리·태그·상세 필드와 승인된 이름 별칭을 이용한 `QUERY_MENU` 조회를 구현했다.
- [x] **O-04** Cart State Schema 구현
  - 완료 기준: 주문 항목, 수량, 옵션을 보관하는 상태 구조를 구현한다.
- [x] **O-05** Order Session 초기화 구현
  - 완료 기준: 신규 주문 시작 시 장바구니와 상태를 초기화한다.
  - 결과: `/api/reset`이 Cart, Undo 이력, TTS Level과 세션 상태를 초기화하도록 구현했다.
- [x] **O-06** add_item() 구현
  - 완료 기준: 정상 메뉴를 장바구니에 추가한다.
- [x] **O-07** remove_item() 구현
  - 완료 기준: 기존 주문 항목을 삭제한다.
  - 결과: 메뉴 ID와 온도 일치 항목을 장바구니에서 삭제하고 한국어 안내를 반환하도록 구현했다.
- [x] **O-08** change_quantity() 구현
  - 완료 기준: 주문 수량을 변경한다.
  - 결과: 대상 메뉴의 최종 수량을 갱신하고 장바구니 총액을 재계산하도록 구현했다.
- [x] **O-09** change_option() 구현
  - 완료 기준: 지원되는 메뉴 옵션을 변경한다.
  - 결과: 온도 옵션 유효성 검증 후 HOT/ICE 변경 및 동일 온도 항목 합산을 구현했다.
- [x] **O-10** show_order() 구현
  - 완료 기준: 현재 주문 내용을 응답 가능한 형태로 반환한다.
  - 결과: 장바구니 담긴 메뉴 목록과 총 결제 금액 안내를 구현했다.
- [x] **O-11** confirm_order() 구현
  - 완료 기준: 최종 주문 확정 상태 전환을 구현한다.
  - 결과: 빈 장바구니 거부 및 정상 주문 시 총액 안내와 확정 처리를 구현했다.

- [x] **O-12** 가상 결제 상태 처리 — NOT PLANNED: 기능동결 시 UI 완료 화면까지를 가상 결제 범위로 확정
  - 원래 완료 기준: 실제 PG 없이 백엔드 Order Session에 결제 완료 상태를 모사한다.
  - 최종 결정: 실제 PG와 별도 `payment_status` 상태 머신은 추가하지 않는다. 주문 확정 성공 후 GUI가 결제 완료 화면과 총액을 표시하는 현재 흐름을 최종 MVP의 가상 결제로 정의한다. 기능동결 이후 새 상태를 추가하지 않는다.
- [x] **O-13** 메뉴 존재 여부 Validation
  - 완료 기준: 존재하지 않는 메뉴가 장바구니에 반영되지 않게 한다.
- [x] **O-14** 옵션 유효성 Validation
  - 완료 기준: 메뉴별 미지원 옵션을 거부하거나 재질문한다.
- [x] **O-15** 수량 Validation
  - 완료 기준: 0 이하/비정상 수량을 안전하게 처리한다.
- [x] **O-16** 비정상 OrderCommand 처리
  - 완료 기준: Schema 오류나 처리 불가능한 Command에 대한 안전한 응답을 구현한다.
- [x] **O-17** 주문 변경 전 확인 정책 구현 — NOT PLANNED: 별도 Pending Confirmation 상태 머신 대신 최종 ORDER_REVIEW 확인 흐름 사용
  - 원래 완료 기준: 중요 상태 변경 전에 사용자 확인이 필요한 경우를 Pending Confirmation으로 저장하고 재확인 후 실행한다.
  - 최종 결정: 개별 주문 추가·삭제·수정은 결과를 Cart와 안내에 즉시 반영해 사용자가 확인·수정할 수 있게 하고, **주문 전체 확정은 ORDER_REVIEW의 명시적 확인 단계에서 수행**한다. 기존 확인 필요 판정 함수는 참고 정책으로 유지하되 새 Pending Confirmation 상태 머신은 기능동결 이후 구현하지 않는다.

## 5.5 STT / Audio

**기본 담당:** C

- [x] **S-01** Microphone Input 구현
  - 완료 기준: 마이크 입력을 애플리케이션에서 안정적으로 수집한다.
  - `src/adapters/audio/recorder.py` — `MicrophoneRecorder.stream_chunks()` (16kHz 모노 float32, 30ms 프레임, sounddevice lazy import)
- [x] **S-02** Tap-to-talk 구현
  - 완료 기준: 버튼을 한 번 누르면 녹음을 시작하고, 발화 종료를 자동 감지하여 녹음을 종료한다.
  - `src/adapters/audio/tap_to_talk.py` — 첫 발화부터 녹음, 무음 1.0초 연속 시 종료, 최대 10초 안전 종료
- [x] **S-03** Audio Buffer 관리
  - 완료 기준: 녹음 데이터를 파일 또는 메모리 Buffer로 안정적으로 전달한다.
  - `src/adapters/audio/buffer.py` + `wav.py` — 누적 후 `to_wav_bytes()`로 PCM16 WAV 반환(STT 계약 호환)
- [x] **S-04** VAD 후보 조사
  - 완료 기준: 로컬 실행 가능한 VAD 후보를 비교한다.
  - `EnergyVAD`(순수 numpy, 임계 -35dB, 발화 비율 50%) 선정 — sounddevice 없이 단위 테스트 가능, 로컬 실행 의존성 0
- [x] **S-05** VAD 적용
  - `src/adapters/audio/vad.py` — 프레임 단위 발화 판정을 TapToTalk에 적용, 발화 전 무음 버림
  - 스펙: `docs/specs/audio-input.md` + `docs/specs/audio-input-mic.md` · 테스트: `tests/unit/test_audio_input.py` (7건) + `tests/unit/test_mic_input.py` (14건)
- [x] **S-06** Noise Suppression 필요성 평가
  - 완료 기준: 카페 소음 조건에서 전처리 적용 필요성을 측정한다.
  - 결과: Kiosk J01 실카페 녹음 데이터 + domain_eval 50개 샘플로 SNR 5/10/15dB에서 4개 파이프라인 비교 완료
    - **Best Overall**: HPF 80Hz only (평균 CER 0.1126)
    - SNR 5dB: HPF only (0.1305) — noisereduce는 저SNR에서 음성 왜곡
    - SNR 10dB: HPF + noisereduce (0.0999) — 적절한 노이즈 제거 효과
    - SNR 15dB: HPF + noisereduce (0.0904) — 노이즈 제거 극대화
    - 현재 파이프라인(hpf_nr_norm) 대비 HPF only가 실카페 환경에서 6% CER 개선
  - 상세: `src/adapters/stt/stt_data/noise_suppression_eval/noise_suppression_eval_seed42.csv`
- [x] **S-07** Noise Gate / 전처리 적용
  - 완료 기준: 필요한 경우 선정한 오디오 전처리를 적용한다.
  - 결과: 전처리를 구현하고 적용했다. 설정과 결과는 `docs/worklogs/stt.md`를 따른다.
- [x] **S-08** STT 후보 조사
  - 완료 기준: 한국어 성능, 로컬 실행, 자원 요구량을 비교한다.
  - 결과: 후보 비교를 완료했다. 평가 계약은 `docs/specs/stt-model-size-comparison.md`, 수치와 선정 근거는 `docs/worklogs/stt.md`를 따른다.
- [x] **S-09** STT 후보 로컬 실행
  - 완료 기준: 후보 모델을 개발 환경에서 실제로 구동한다.
  - openai/whisper base·small·medium을 stt venv(GPU)에서 구동 확인, 평가 CSV 산출 (`models/model-size-compare/compare_validation_77_seed-42.csv`, `compare_test_73_seed-42.csv`)
- [x] **S-10** STT Benchmark Dataset 구성
  - 완료 기준: 메뉴명, 수량, 옵션을 포함한 평가 음성을 구성한다.
  - 결과: MeloTTS Friendly로 주문 도메인 문장 506개 합성 완료 (`stt_data/domain_eval/`, `domain_eval.csv`)
  - 메뉴 10종 × 수량/옵션 조합 × 템플릿으로 커버리지 확보
  - S-11~S-13 평가에 사용됨
- [x] **S-11** STT WER / CER 측정
  - 완료 기준: 일반적인 문자/단어 오류율을 측정한다.
  - 결과: Baseline/전처리/QLoRA CER·WER 측정 완료 (`docs/worklogs/stt.md` 참고)
- [x] **S-12** 메뉴명 인식률 측정
  - 완료 기준: 핵심 메뉴명 단위의 정확도를 별도로 측정한다.
  - 결과: 도메인 평가셋 506개에서 메뉴 Recall **89.5%** (453/506) 달성
- [x] **S-13** 숫자 / 수량 인식률 측정
  - 완료 기준: 한 잔, 두 잔 등 주문 핵심 수량 인식률을 측정한다.
  - 결과: 도메인 평가셋에서 수량 Recall **99.3%** (405/408) 달성
- [x] **S-14** 최종 STT 선정
  - 완료 기준: 정확도, 지연, 자원 사용량을 근거로 MVP STT를 선정한다.
  - 결과: **whisper-medium-qlora-domain/merged-bf16** 선정
    - CER 0.1131 (도메인 506개), WER 0.3352
    - 메뉴 Recall 89.5%, 수량 Recall 99.3%, 옵션 Recall 86.3%
    - Latency 0.505s/샘플 (RTX 4060 Ti 8GB, BF16)
    - Baseline 대비 CER -0.0161, WER -0.0159 개선
    - fast-exp(r1-lr5e-6) 대비 전 지표 우위
- [x] **S-15** 메뉴명 Candidate Matching 구현
  - 완료 기준: STT 오인식 결과를 Menu DB 후보와 비교한다.
  - `src/adapters/stt/postprocess.py` — `CandidateMatcher.correct()`, 정확 부분 문자열 + 토큰 그룹 기반 편집 거리 유사도 매칭, 메뉴 10종 로드
- [x] **S-16** STT 후보 보정 Threshold 정의
  - 완료 기준: 과도한 자동 보정을 막을 기준값을 정한다.
  - 결과: Threshold를 `docs/specs/stt-candidate-matching.md`에 확정했다.
- [x] **S-17** STT 보정 전/후 성능 비교
  - 완료 기준: 메뉴 기반 후처리 효과와 부작용을 측정한다.
  - 결과: 비교와 회귀 테스트를 완료했다. 평가 계약은 `docs/specs/stt-candidate-matching.md`, 수치는 `docs/worklogs/stt.md`를 따른다.

## 5.6 Minimal GUI / Service UI

**기본 담당:** C

- [x] **UI-01** Main Layout 구현
  - 완료 기준: Voice-first를 보조하는 최소 화면 골격을 구현한다.
  - 결과: 스타벅스 키오스크 스타일(Dark Green/Warm Cream)의 Semantic HTML5 및 CSS 레이아웃(`web/index.html`, `web/styles.css`)을 구축했다.
- [x] **UI-02** 현재 주문 목록 구현
  - 완료 기준: 장바구니의 현재 상태를 큰 글씨로 표시한다.
  - 결과: 메뉴명, HOT/ICE 뱃지, 수량, 가격 및 총액을 실시간으로 표시하는 카트 컴포넌트를 구현했다.
- [x] **UI-03** 시스템 응답 표시 구현
  - 완료 기준: 시스템이 말하는 핵심 문장을 화면에도 표시한다.
  - 결과: 시스템 안내 발화 자막 카드(`response-card`)를 구현했다.
- [x] **UI-04** Tap-to-talk 버튼 UI 구현
  - 완료 기준: 고령 사용자가 쉽게 찾을 수 있는 큰 음성 입력 버튼을 구현한다.
  - 결과: 대형 원형 음성 입력 버튼(Tap-to-talk) 및 키보드 입력창을 구현했다.
- [x] **UI-05** TTS 제어 버튼 UI 구현
  - 완료 기준: 다시 듣기/천천히/기본 속도 버튼을 구현한다.
  - 결과: 하단 `[다시 듣기]`, `[천천히 듣기]`, `[보통 속도]`, `[직원 호출]` 제어 바를 구현했다.
- [x] **UI-06** 시스템 상태 표시 구현
  - 완료 기준: 듣는 중/처리 중/말하는 중 상태를 표현한다.
  - 결과: 상단 `status-indicator` 및 `SessionState` 도메인 모델(`src/domain/session_state.py`)을 구현했다.

- [x] **UI-07** 주문 확인 화면 구현
  - 완료 기준: 주문 내역과 총액을 확인할 수 있는 화면을 만든다.
  - 결과: `web/index.html` 확인 모달(`#confirmModal`)에 장바구니 품목·온도·수량·금액과 총액을 표시하고, `web/app.js`가 `/api/state` 기준으로 렌더링한다.
- [x] **UI-08** 주문 수정 복귀 흐름 구현
  - 완료 기준: 확인 화면에서 주문 수정 단계로 돌아갈 수 있게 한다.
  - 결과: 확인 모달의 `수정하기` 버튼이 모달을 닫고 주문 편집 단계(ORDERING)로 복귀한다.
- [x] **UI-09** 주문 확정 처리 UI 구현
  - 완료 기준: 사용자의 명시적 확인 후 주문을 확정한다.
  - 결과: 모달의 `주문 확정` 버튼이 `/api/order {text:"주문 확정할게요"}`을 호출해 명시적 확정을 수행한다.
- [x] **UI-10** 가상 결제 완료 화면 구현
  - 완료 기준: 실제 PG 없이 주문 완료 상태를 보여준다.
  - 결과: 확정 성공 시 `#completeScreen` 결제 완료 화면을 표시하고 총액을 보여준다(실제 PG 없음).
- [x] **UI-11** 신규 주문 Session Reset UI 구현
  - 완료 기준: 완료 후 새 주문을 시작할 수 있도록 UI와 상태를 초기화한다.
  - 결과: 결제 완료 화면의 `새 주문 시작하기` 버튼이 `/api/reset`을 호출하고 cart·TTS 레벨·화면을 초기화한다.

## 5.7 Integration / Service

**기본 담당:** C 중심, 전원 협업

- [x] **I-01** STT → NLU 연결
  - 완료 기준: STT text를 NLU가 받을 수 있도록 실제 모듈을 연결한다.
  - 결과: `VoicePipeline.handle_audio()`에서 STT 음성 전사 결과를 NLU 파서로 자동 전달하도록 구현했다.
- [x] **I-02** NLU → Order Engine 연결
  - 완료 기준: OrderCommand를 Order Engine에 전달해 상태를 변경한다.
  - 결과: NLU 파싱 `OrderCommand[]`를 `ConversationAgent`로 전달하여 장바구니 변경 및 응답을 생성하도록 구현했다.
- [x] **I-03** Order Engine → TTS 연결
  - 완료 기준: response_text를 Adaptive TTS에 전달한다.
  - 결과: 응답 텍스트를 `AdaptiveTextTransformer`로 레벨별 변환 후 `MeloTTSAdapter`/`TTS` 어댑터로 전달하여 음성을 생성하도록 구현했다.
- [x] **I-04** GUI → TTS Controller 연결
  - 완료 기준: 버튼 입력으로 TTS Level 상태를 변경한다.
  - 결과: `web/app.js`의 다시 듣기/천천히/보통 속도 버튼이 `/api/tts-control`을 호출하고, 헤더의 `TTS Lv.0/1/2` 배지가 서버 상태(`/api/state`)와 동기화되도록 구현했다(I-10 서버 연동).
- [x] **I-05** 전체 Session State 관리
  - 완료 기준: Order State와 TTS Level을 하나의 주문 세션 기준으로 관리한다.
  - 결과: `VoicePipeline.reset_session()` 및 `VoiceInteractionResult`로 주문 상태와 TTS Level을 일관되게 관리하도록 구현했다.
- [x] **I-06** 통합 Error Handling 구현
  - 완료 기준: STT/NLU/Order/TTS 실패를 사용자에게 안전하게 안내한다.
  - 결과: STT 실패, 빈 입력, NLU 스키마 오류, TTS 합성 실패 시 `create_error_response`로 사용자 친화적 복구 안내 메시지를 반환하도록 구현했다.
- [x] **I-07** 통합 로그 저장 구현
  - 완료 기준: 입력, 모델 출력, 주문 상태, latency 등을 평가 가능한 형태로 기록한다.
  - 결과: `src/domain/session_log.py`, `src/interfaces/interaction_logger.py`, `src/adapters/logging/file_interaction_logger.py`에 `InteractionLogger` 계약과 `FileInteractionLogger`(JSONL)를 구현하고, `VoicePipeline`이 입력/모델 출력/주문 상태/latency를 `schemas/session-log.schema.json`(E-04) 형식으로 기록하도록 연결했다. ORDER_INTERACTION / TTS_SPEED_CONTROL / ERROR_RECOVERY / SESSION_RESET 이벤트를 단계별로 기록하며 단위 9건·통합 1건 통과.
- [x] **I-08** 전체 End-to-End Latency 측정
  - 완료 기준: `docs/specs/e2e-latency.md`에 따라 Real Warm 50 Turn과 Cold Start 3회를 측정하고 최종 판정을 기록한다.
  - 결과: Session 격리 Real Warm 50 Turn과 Cold Start 3회 측정을 완료하고 초기 Requirement 미달을 기록했다. 최종 반복 배분은 STT Showcase 5종 × 10회이며 10×5 초기 계약과의 차이는 Spec에 protocol deviation으로 명시했다. 상세 결과와 raw Turn evidence는 `docs/evidence/e2e/i08-final-real-e2e.md`를 따른다.
- [x] **I-09** End-to-End 시나리오 테스트
  - 완료 기준: 조회/추가/삭제/수정/확정 등 핵심 주문 흐름을 검증한다.
  - 결과: `tests/integration/test_e2e_order_flows.py`에 추가/조회/삭제/수량변경/옵션변경/확정·취소/UNDO/TTS 제어(느리게·기본)/전체 Happy Path 8건을 구현하고 통과했다.
- [x] **I-10** Web 백엔드 서버 브리지 구현 `[신규]`
  - 완료 기준: web/ GUI와 MalloService 백엔드를 연결한다.
  - 결과: `src/app/server.py`에 stdlib `ThreadingHTTPServer` 기반 서버(`/api/order`, `/api/audio`, `/api/tts-control`, `/api/reset`, `/api/state` + 정적 `web/` 제공, CORS)를 구현하고, `web/app.js`의 로컬 목업 파서를 제거해 백엔드 fetch 통신으로 재연결했다. 단일 세션 cart를 서버에서 유지한다. `tests/integration/test_web_server.py` 6건 통과. 의존성 추가 없음(requirements.txt 미변경).

## 5.8 평가 / 사용자 테스트 / 데모

**기본 담당:** 전원

- [x] **E-01** 사용자 테스트 과제 시나리오 작성
  - 완료 기준: 메뉴 탐색, 추가, 수정, 확인, 오류 복구 과제를 정의한다.
  - 결과: `docs/specs/user-test-protocol.md`에 TASK-1~5 표준 과제 시나리오를 정의했다.
- [x] **E-02** Baseline 비교 조건 확정
  - 완료 기준: 기존 GUI 또는 Fixed TTS 등 비교군과 실험 조건을 확정한다.
  - 결과: `docs/specs/user-test-protocol.md`에 Group A(Touch), Group B(Fixed Voice), Group C(Mallo Adaptive Voice) 3개 비교군 및 실험 조건을 확정했다.
- [x] **E-03** 평가 지표 확정
  - 완료 기준: 주문 성공률, 정확도, 이해도, 오류 복구 성공률, 도움 요청률, latency를 정의한다.
  - 결과: `docs/specs/user-test-protocol.md`에 TCR, TCT, ERR, E2E Latency, SUS, Voice MOS 산출 공식을 정의했다.
- [x] **E-04** 테스트 로그 수집 형식 확정
  - 완료 기준: 정량 평가에 필요한 이벤트와 필드를 정한다.
  - 결과: `schemas/session-log.schema.json`에 비식별 인터랙션 세션 로그 JSON Schema를 정의했다.
- [ ] **E-05** 파일럿 테스트 진행
  - 완료 기준: 본 평가 전에 소수 사용자/팀 내부 테스트로 문제를 찾는다.
- [ ] **E-06** 최종 사용자 평가 진행
  - 완료 기준: 확정된 프로토콜로 말로(Mallo) MVP를 평가한다.
- [ ] **E-07** 평가 결과 분석
  - 완료 기준: Baseline 대비 개선 여부와 실패 사례를 분석한다.
- [x] **E-08** 데모 시나리오 확정
  - 완료 기준: 발표에서 재현할 대표 주문/수정/Adaptive TTS 흐름을 확정한다.
  - 결과: `docs/specs/demo-scenarios.md`에 3분 5턴 라이브 시연 스크립트 및 Fallback 정책을 정의했다.
- [x] **E-09** 발표용 정량 결과 정리
  - 완료 기준: 핵심 지표와 그래프에 사용할 결과를 정리한다.
  - 결과: `docs/final-quantitative-results.md`에 STT/NLU/TTS 및 I-08 최종 Real E2E 결과와 발표용 그래프 데이터를 집계했다.
- [x] **E-10** 최종 데모 리허설
   - 완료 기준: 전체 환경에서 실제 발표 순서대로 End-to-End 리허설을 진행한다.
   - 결과: `tests/integration/test_demo_rehearsal.py`로 E-08 5-Turn Happy Path를 MalloService 파이프라인과 실제 ThreadingHTTPServer 양쪽에서 발표 순서대로 실행해 AC-01~AC-04 검증(3건 통과). 리허설 중 Order Engine이 턴당 단일 Intent만 허용함을 확인하여 E-08 Turn 4/AC-03을 "전체 아이스 변경(iced americano:2)"으로 정렬하고 명세 각주를 남겼다. MockNLU에 데모 전용 발화(복합주문/속도제어/온도변경/확정)를 추가했다.

---

# 6. Backlog 메타데이터

총 **138개 Ticket**을 관리한다.

- `C-*`: 19개 — 공통 / 설계
- `T-*`: 31개 — Adaptive TTS / Voice UX
- `N-*`: 23개 — Local LLM / NLU
- `O-*`: 17개 — Order Engine / Menu DB
- `S-*`: 17개 — STT / Audio
- `UI-*`: 11개 — Minimal GUI / Service UI
- `I-*`: 10개 — Integration / Service
- `E-*`: 10개 — 평가 / 사용자 테스트 / 데모

> 기능동결 기준으로 `[x] — NOT PLANNED`는 구현 완료가 아니라 범위 종료를 뜻한다. 실제 미완료 검증 과제(E-05~E-07, T-24, T-30)는 완료로 주장하지 않는다. 상세 정합화는 `docs/final-ticket-reconciliation.md`를 따른다.
> 계약·아키텍처·개발 원칙은 이 문서에서 정의하지 않는다. `docs/documentation-governance.md`의 Source of Truth를 따르며, GitHub Issues로 옮길 때 Ticket ID를 Issue 제목 앞에 그대로 유지한다.
