---
title: "문서 책임과 변경 규칙"
tags: [doc]
---

# 문서 책임과 변경 규칙

이 문서는 같은 결정을 여러 Markdown에 복사하면서 발생하는 불일치를 줄이기 위한 문서 관리 기준이다.

> **단일 소유권 원칙:** 하나의 결정·계약·수치는 정확히 하나의 기준 문서만 책임진다. 다른 문서는 해당 값을 다시 선언하지 않고 기준 문서로 링크한다. 소유 문서가 불명확하거나 둘 이상의 기준 문서가 필요해 보이면 내용을 복제하지 말고, 먼저 이 문서의 Source of Truth 표에서 소유권을 하나로 확정한다.

문서는 다음 두 종류로 구분한다.

- **기준 문서(Normative)**: 현재 계약과 판정값을 소유한다. 같은 값을 소유하는 기준 문서는 하나만 둔다.
- **참조 문서(Informative)**: 배경, 실행 절차, 예시, 상태 또는 결과를 설명한다. 기준값이 필요하면 링크하고 값을 다시 선언하지 않는다.

## 문서별 책임

| 문서 | 책임 | 포함하지 않는 내용 |
|---|---|---|
| `docs/proposal.md` | 문제·해결 방향·발표용 서사 | 최신 요구사항의 최종 판정, 상세 수치와 AC |
| `docs/prd.md` | 제품 범위, 사용자 경험, P0/P1/P2 우선순위 | 모델·데이터 포맷·학습 설정 |
| `docs/trd.md` | 시스템 구조, 모듈 책임, 인터페이스, 상태·오류·안전 경계 | 기능 Spec의 실험 수치와 상세 평가표 |
| `docs/inference-deployment.md` | TRD를 보조하는 배포·자원·환경 검증 계획 | TRD와 다른 배포 기본안, 제품 성능 요구사항의 재정의 |
| `docs/specs/*.md` | 기능별 데이터·모델·설정·수치·Edge Case·AC | 프로젝트 전체 우선순위의 재정의 |
| `docs/specs/demo-scenarios.md`, `docs/specs/user-test-protocol.md` | 기준 문서를 검증하는 시나리오·측정 절차 | 독자적인 제품 범위·enum·성능 요구사항의 재정의 |
| `docs/tasks.md` | Ticket ID, 담당, 상태, 의존성과 짧은 완료 기준 | 상세 설계와 평가 계약의 복사본 |
| `docs/worklogs/*.md` | 결정 배경, 수행 결과, 변경 이력 | 현재 요구사항의 최종 기준 |
| `docs/worklog.md` | 기존 공통 기록의 요약·진입점 | 신규 기능별 결정의 중복 기록 |
| `docs/notion-reconciliation-report.md` | 2026-08-19 문서 정합화의 변경·검증 기록 | 새로운 제품·기술 요구사항의 정의 |

## 주제별 Source of Truth

문서 종류만으로 소유권이 충분히 명확하지 않은 공통 계약은 아래 표를 따른다.

| 주제 | 기준 문서 | 다른 문서에 허용되는 내용 |
|---|---|---|
| 메뉴 목록·기본 가격·메뉴별 옵션 지원 여부 | `docs/specs/menu-catalog.md` | 메뉴 ID 또는 시나리오 예시와 기준 문서 링크 |
| Size·샷·시럽·카페인·얼음의 값 의미와 가격 계산 | `docs/specs/beverage-option-adjustments.md` | 필드명과 기능 지원 여부 요약, 기준 문서 링크 |
| `OrderCommand` wire format·Intent·필드 null 규칙 | `docs/specs/order-command.md` | 모듈 경계를 설명하기 위한 `OrderCommand[]` 명칭과 링크 |
| Intent별 Order Engine 실행·원자성·오류 | `docs/specs/order-engine-operations.md` 및 Intent별 기능 Spec | 제품 수준 동작 요약과 링크 |
| Adaptive TTS Level·전이·속도 | `docs/specs/adaptive-tts-controller.md` | 사용자 시나리오의 Level 이름과 링크 |
| Adaptive TTS Level 0/1 추가 지연 | `docs/specs/adaptive-tts-latency.md` | 측정 결과와 Spec 링크 |
| Adaptive TTS Intent 실행 연결 | `docs/specs/adaptive-tts-intent-execution.md` | 지원 여부와 링크 |
| Python·CUDA·가상환경·의존성 설치 정책 | `docs/specs/python-environment.md` | 모델별 추가 의존성 및 실행 절차와 환경 Spec 링크 |
| Real E2E 측정 구간·반복·통계·판정 | `docs/specs/e2e-latency.md` | 배포 검증 단계와 측정 결과 링크 |
| 배포 Plan·네트워크 경계·Fallback 구조 | `docs/inference-deployment.md` | TRD의 구조 요약과 배포 문서 링크 |
| 사용자 평가 과제·지표·수집 절차 | `docs/specs/user-test-protocol.md` | PRD의 제품 성공 기준과 결과 링크 |

JSON Schema와 런타임 모델은 문서와 함께 구현되는 계약 산출물이다. 서로 다를 경우 임의로 한쪽을 우선하지 않고 해당 기준 Spec의 AC에 따라 함께 수정한다.

## 충돌 시 우선순위

1. 제품 범위와 P0/P1/P2 충돌은 `docs/prd.md`를 따른다.
2. 시스템 구조와 공통 인터페이스 충돌은 `docs/trd.md`를 따른다.
3. 기능별 수치·데이터·모델·평가·AC 충돌은 해당 `docs/specs/*.md`를 따른다.
4. `docs/tasks.md`는 위 기준 문서의 실행 상태만 나타내며 요구사항을 바꾸지 않는다.
5. worklog와 proposal은 결정 당시의 맥락을 설명하는 기록이다. 현재 기준과 충돌하면 기준 문서를 따르고 새 worklog에 변경 이유를 남긴다.
6. 데모·사용자 테스트 문서는 PRD/TRD/기능 Spec을 검증한다. 시나리오의 예시 값이 기준 문서와 다르면 기준 문서를 따른다.

## 변경 규칙

- 우선순위를 바꾸면 PRD 한 곳을 수정하고 TRD·tasks에는 의미를 복사하지 않고 링크만 갱신한다.
- 기능의 수치나 AC를 바꾸면 해당 Spec 한 곳을 수정한다.
- TRD에는 구현 경계에 필요한 최소 요약과 Spec 링크만 둔다.
- 다른 기준 문서의 enum, 임계값, 가격표, JSON 예시를 복사하지 않는다. 검증 시나리오상 값이 꼭 필요하면 "예시"로 표시하고 기준 문서를 링크한다.
- 배포 Fallback(`Deployment Plan B`)과 모델 지연 대응(`Latency Provider Fallback`)은 이름과 전환 조건을 구분한다.
- tasks의 완료 기준은 한두 문장과 관련 Spec/AC 링크로 유지한다. 완료 결과에는 산출물 경로와 검증 여부만 남기고 계약값·측정값·구현 상세를 복사하지 않는다.
- worklog의 과거 기록은 소급 수정하지 않는다. 정책이 바뀌면 새 항목으로 이전 결정과 변경 이유를 남긴다.
- 아직 합의되지 않은 값은 `TBD`와 결정 주체·시점을 함께 기록한다.

## 현재 TTS 기준 문서

- 제품 우선순위: `docs/prd.md`
- TTS 기술 경계: `docs/trd.md`
- 친절체 학습·비교·최종 선택: `docs/specs/melotts-friendly-finetuning-poc.md`
- 실행 상태: `docs/tasks.md`의 `T-*`
- 결정 이력: `docs/worklogs/tts.md`

## 현재 Evaluation / 사용자 조사 기준 문서

- 제품 요구사항 근거: `docs/prd.md` (Section 3.3)
- 설문 분석 및 파이프라인 변경안: `docs/survey-pipeline-update.md`
- 사용자 평가 및 테스트 프로토콜: `docs/specs/user-test-protocol.md`
- 실행 상태: `docs/tasks.md`의 `E-*`
- 결정 이력: `docs/worklogs/evaluation.md`
