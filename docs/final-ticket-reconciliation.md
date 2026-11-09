---
title: "말로(Mallo) 기능 동결 기준 티켓 정합화"
tags: [doc, backlog, final]
---

# 말로(Mallo) 기능 동결 기준 티켓 정합화

## 목적

`docs/tasks.md`는 초기 MVP 백로그를 기준으로 작성되어 이후 병합된 NLU 학습·평가, 최종 UI/UX 기능 동결, 일정 축소 결정을 일부 반영하지 못하고 있었다. 이 문서는 2026-08-28 기능 동결 시점에서 **체크박스와 실제 구현 상태가 달랐던 항목과 최종 범위 결정을 기록**한다.

2026-08-28 최종 정합화에서 `docs/tasks.md`와 `docs/prd.md`를 본 결정에 맞게 직접 동기화했다. 기존 Ticket ID와 초기 Spec은 이력을 위해 유지하며, 기능동결 이후 최종 지원 범위는 `docs/prd.md`와 본 문서를 기준으로 해석한다.

## 1. 일정 축소로 제외된 항목

### N-23 Size 음성 표현 NLU 연결 — `NOT PLANNED`

초기 설계에서는 Size 음성 표현(`small`, `medium`, `large`)을 NLU에 연결하는 티켓이 있었으나, 최종 일정에서 **Size 음성 주문·변경 기능을 제외**하기로 결정했다.

따라서 N-23은 구현 미완료 버그가 아니라 기능 동결 시점의 일정 축소 항목이다.

- 상태: `NOT PLANNED`
- 사유: 최종 제출 일정 내 핵심 주문 흐름 안정화 우선
- 영향: 발표 및 최종 기능 목록에서 Size 지원을 주장하지 않는다.
- 문서 반영: `docs/tasks.md`, `docs/prd.md`에 최종 제외 범위를 동기화했다.

### STT 신규 재학습 체인 — `NOT PLANNED`

최종 단계에서 새로운 STT 재학습은 진행하지 않고, 이미 확보한 후보를 비교·선정하여 서비스에 반영하는 방향으로 범위를 확정했다.

GitHub의 S-18 이후 신규 재학습 관련 issue #168, #169, #170, #173, #174, #175, #176, #177, #178은 범위 변경 사유를 남기고 `not planned`로 종료했다. 기존 STT 실험·선정 결과는 유지하되 추가 데이터 감사, 새 Clean/Cafe 재학습 등은 수행하지 않는다.

## 2. TTS

### T-29 AI Hub 학습 산출물 공유 범위 문의 — `COMPLETED`

- 접수: 2026-08-27 20:21
- 답변: 2026-08-28 09:04:31
- 답변 기관: AI Hub 관리자
- 상세: `docs/aihub-tts-license-inquiry.md`

AI Hub 답변을 통해 다음을 확인했다.

- AI Hub 데이터로 학습해 도출한 AI 모델은 활용 가능하며 상업적 활용도 가능하다.
- 원천·라벨링 데이터 및 이를 편집·추출·변환한 재가공 데이터 자체는 외부 제공·공유·판매·재배포할 수 없다.
- GitHub/GitHub Pages에서도 원천·라벨링·재가공 데이터가 공개되지 않도록 해야 한다.
- TTS 생성 음성 결과물은 위 이용 원칙을 따라 활용할 수 있다.
- 결과물에는 사용 데이터명과 `AI 허브` 출처를 상시 확인 가능한 위치에 표시한다.
- AI Hub가 결과물 공개 샘플 수나 음성 길이를 별도로 일률 제한하지 않는다.

따라서 현재 TTS 쇼케이스의 **프로젝트 자체 작성 문장 합성 WAV 공개 + AI Hub 원본 데이터 비공개 + 출처 표기** 방식은 답변 원칙과 정합하다.

`docs/tasks.md`의 T-29도 완료 상태로 동기화했다.

### T-24 / T-30 — `OPEN`

- T-24: 실제 사용자 기반 Adaptive TTS Level별 이해도 비교 근거 없음
- T-30: 외부 참가자 기반 TTS 사용성 테스트 및 개선 전후 근거 없음

실제 참가자 데이터 없이 완료 처리하지 않는다.

## 3. NLU

초기 `docs/tasks.md`의 N-05~N-22 체크박스는 실제 구현 상태보다 뒤처져 있었다. 실제 저장소에는 다음 작업이 이미 반영돼 있다.

- NLU 데이터셋 3,000행 확정
- Train 2,400 / Validation 300 / Test 300
- 16개 Label Group 목표 분포 및 전 행 approved
- Qwen3 QLoRA 학습 파이프라인 통합
- Qwen NLU Web 런타임 연결
- 최종 평가 및 서비스 후보 비교

주요 병합 근거:

- PR #205: N-05~N-20 데이터셋 3천 행 및 Qwen3 QLoRA 파이프라인 통합
- PR #211: Qwen NLU 최종 제출 연결과 평가 결과 확정
- PR #214: production STT/NLU runtime hardening

따라서 N-05~N-22는 `docs/tasks.md`에서 완료 상태로 동기화했다.

### 최종 NLU 판단

- Qwen3-0.6B 서비스 후보: Intent 100%, Slot 96.78%, Error Code 96.67%, Schema Valid 100%, Warm p95 1.182s
- Qwen3-1.7B final test: 높은 Exact Match를 기록했으나 Error Code Accuracy 70%, Warm p95 8.40s로 production gate 실패

최종 발표에서는 0.6B 서비스 후보와 1.7B reference 결과를 구분한다.

## 4. Order Engine

### O-12 가상 결제 상태 처리 — `NOT PLANNED / FINAL SCOPE`

현재 GUI에는 주문 확정 이후 결제 완료 화면과 최종 총액 표시가 구현돼 있다. 반면 백엔드 Order Session에는 별도 `payment_status`를 저장하지 않는다.

기능동결 이후 새 상태 머신을 추가하지 않기로 결정하고, **최종 MVP의 가상 결제를 UI 완료 화면 시뮬레이션까지로 정의**한다.

- 실제 PG 연동 없음
- 백엔드 `payment_status` 추가 없음
- 승인번호·승인 실패·환불 등 결제 트랜잭션 생명주기 모사 없음
- 주문 확정 성공 후 결제 완료 화면과 총액을 표시하는 현재 흐름을 최종 데모 계약으로 사용
- `새 주문 시작하기`에서 Cart·세션·TTS Level을 초기화

따라서 O-12의 원래 백엔드 상태 보존 요구는 최종 범위에서 제외하고 `NOT PLANNED`로 닫는다. 이는 가상 결제 UI가 미완료라는 뜻이 아니다.

### O-17 주문 변경 전 확인 정책 — `NOT PLANNED / FINAL SCOPE`

확인 필요 여부를 판정하는 정책 함수는 있으나 Pending Confirmation 저장·재확인·실행 상태 머신은 완전 구현되지 않았다.

기능동결 이후에는 새 음성 상태 머신을 추가하지 않고, 현재 UI의 **ORDER_REVIEW 주문 확인/수정/확정 단계**를 최종 명시 확인 정책으로 사용한다.

- 개별 주문 추가·삭제·수정은 실행 결과를 Cart와 안내에 즉시 반영한다.
- 사용자는 Cart를 보고 잘못된 변경을 다시 수정할 수 있다.
- 주문 전체 확정은 ORDER_REVIEW에서 명시적으로 확인한다.
- 기존 확인 필요 판정 함수는 참고 정책으로 유지하지만, 별도 Pending Confirmation 상태 머신은 최종 MVP 요구사항이 아니다.

따라서 O-17의 원래 Pending Confirmation 구현 요구는 `NOT PLANNED`로 닫고, 현재 ORDER_REVIEW 흐름을 최종 제품 정책으로 문서화한다.

## 5. Integration / Evaluation

### I-08 전체 End-to-End Latency 측정 — `COMPLETED / REQUIREMENT MISSED`

2026-08-28 최종 Real E2E 측정을 완료했다. 첫 50 Turn diagnostic run에서 동일 Session Cart 누적 오염이 확인되어 최종 근거에서는 제외하고, 각 Turn을 독립 Session으로 격리한 재측정을 최종 evidence로 사용한다.

최종 측정 조건:

- 실제 Chromium Web Audio VAD / MediaRecorder / HTML5 `Audio.onplay`
- 실제 WhisperMediumSTT + RuleFirstNLU/Qwen06BNLU + ConversationAgent + MeloTTSAdapter
- 최초 3 Turn warm-up 제외
- STT Showcase 고정 음원 5종 × 10회 = Real Warm 50 Turn
- Cold Start 3회 별도 측정
- 각 Turn 고유 `X-Mallo-Session-ID`와 reset으로 Cart 상태 격리
- `stt-04`는 옵션 변경 대상 아메리카노 1잔을 비측정 precondition으로 준비

최종 결과:

- Warm 평균 1,915.6ms
- 일반 중앙값 2,166.5ms
- nearest-rank p95 3,338ms
- Warm 최대 3,448ms
- 1.5초 초과 30/50
- Playback Failure 0/50
- Rule-First 20 Turn p95 967ms
- Qwen-0.6B fallback 30 Turn p95 3,386ms
- Cold Start Raw startup-to-first-response 평균 7,704.3ms

초기 Target 1.2초 / Requirement 1.5초는 변경하지 않았으며 **최종 Requirement는 미달**이다. 지연 분해에서 Interpret 구간이 가장 크게 나타났고, Rule-First와 Qwen fallback 경로가 명확히 분리됐다.

초기 Spec의 문장 반복 배분은 10문장 × 5회였으나 최종 제출 측정은 공개 고정 입력 재현성을 위해 5종 × 10회를 사용했다. 총 50 Turn, warm-up, 실제 Provider/브라우저 경계, p95, Cold Start 및 성능 임계값은 유지했으며 이 차이는 `docs/specs/e2e-latency.md`에 protocol deviation으로 명시한다.

상세 evidence:

- `docs/evidence/e2e/i08-final-real-e2e.md`
- `docs/evidence/e2e/i08-real-e2e-warm-50-turns-isolated.csv`
- `docs/evidence/e2e/i08-real-e2e-cold-start-3-runs.csv`

I-08은 성능 달성을 의미하는 티켓이 아니라 **최종 실측과 판정을 기록하는 티켓**이므로 완료 처리한다. Requirement 미달 사실은 숨기거나 기준을 사후 변경하지 않는다.

### E-09 발표용 정량 결과 정리 — `COMPLETED`

`docs/final-quantitative-results.md`에 STT/NLU/TTS/통합 결과와 발표용 그래프 데이터를 집계했고 `docs/tasks.md`도 완료 상태로 동기화했다. I-08 최종 측정 결과도 같은 문서에 반영한다.

### E-05 / E-06 / E-07 — `OPEN`

- E-05 파일럿 사용자 테스트
- E-06 최종 사용자 평가
- E-07 평가 결과 분석

실제 참가자 기반 결과가 없으므로 완료 처리하지 않는다.

## 6. 현재 최종 마감 관점의 남은 일

기능동결 이후 새 기능을 추가하지 않는다는 전제에서 남은 검증 과제는 **실제 참가자 기반 사용자 평가**다.

1. 외부 사용자 테스트를 실제로 수행할 경우 E-05~E-07, T-24, T-30 결과 기록
2. 제출 시점까지 수행하지 않는 경우 해당 항목을 향후 검증 과제로 명확히 유지

I-08은 최종 실측 및 판정까지 완료했다. O-12, O-17, N-23 및 신규 STT 재학습 체인도 더 이상 구현 대기 항목으로 보지 않는다.

## 7. 기능 동결 원칙

최종 제출 단계에서는 새로운 기능을 추가해 안정성을 흔드는 것보다 다음을 우선한다.

- 실제 구현 상태와 문서 일치
- 발표 수치의 출처와 조건 명시
- 수행하지 않은 사용자 평가를 수행한 것처럼 주장하지 않기
- 일정상 제외한 기능을 미완료 버그와 구분하기
- 공개 산출물의 데이터·라이선스 조건 준수
