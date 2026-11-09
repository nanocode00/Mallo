---
title: "Qwen3 NLU 로컬 런타임 연결"
tags: [spec, nlu]
---

# Qwen3 NLU 로컬 런타임 연결

## Why

- **페르소나**: Talkiosk 음성 주문 시연을 준비하는 프로젝트 팀원
- **상황**: Qwen3-1.7B QLoRA 어댑터의 Validation은 완료했지만 Web 서버는
  여전히 `MockNLU`만 사용한다.
- **문제**: 학습 산출물이 있어도 UI의 음성·텍스트 입력이 실제 모델을 거쳐
  주문엔진으로 전달되지 않는다.
- **측정 지표**: 실제 어댑터 로딩 성공 여부, NLU 출력 계약 준수율, 기존 Mock
  회귀 테스트 통과 여부

## Goal

- 서버 시작 옵션으로 Mock 또는 Qwen NLU를 명시적으로 선택한다.
- Qwen 출력은 반드시 기존 `NLUResult` 계약으로 변환하고 JSON Schema 검증 후에만
  주문엔진에 전달한다.
- 같은 서버 프로세스에서는 모델을 한 번만 로딩하고 각 요청에서 재사용한다.
- 잘못된 JSON·Schema·어댑터 경로는 주문 상태를 변경하지 않는 복구 가능한 오류로
  처리한다.
- **Out of Scope**: 추가 파인튜닝, Test Split 평가, 모델 파일의 Git 커밋, 실제 결제
  단말 연동, 다중 키오스크 세션 운영

## What

**Happy Path**

1. 운영자가 Qwen NLU와 로컬 adapter 경로로 서버를 시작한다.
2. 서버가 고정된 base model revision과 adapter를 한 번 로딩한다.
3. UI의 텍스트 또는 STT 결과와 현재 장바구니를 학습 당시 형식으로 직렬화한다.
4. 모델이 JSON 하나를 생성한다.
5. 정상 배열은 `OrderCommand[]`, 오류 객체는 `OrderCommandError`로 변환한다.
6. 기존 Voice Pipeline과 결정론적 Order Engine이 결과를 실행한다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | adapter 경로가 없거나 파일이 누락됨 | 서버 시작을 즉시 중단하고 경로 오류 표시 |
| EC-02 | CUDA를 사용할 수 없음 | CPU로 로딩하되 시작 로그에 느린 실행임을 표시 |
| EC-03 | 모델 출력이 JSON이 아님 | `INVALID_JSON` 반환, 장바구니 유지 |
| EC-04 | JSON 필드·enum이 Schema와 다름 | `SCHEMA_ERROR` 반환, 장바구니 유지 |
| EC-05 | 여러 HTTP 요청이 동시에 추론함 | 단일 모델 생성 Lock으로 순차 처리 |
| EC-06 | 2차 보정 adapter로 교체함 | 코드 수정 없이 시작 인자의 경로만 변경 |

## How

- Base model: 학습 manifest와 같은 `Qwen/Qwen3-1.7B` 및 고정 revision
- Adapter: PEFT `final-adapter` 디렉터리
- CUDA: bitsandbytes 4-bit NF4, deterministic greedy generation
- CPU: 비양자화 로딩, 시연 전 별도 지연 검증 필요
- 입력: `{"utterance": string, "cart_before": array}`
- 출력: `schemas/order-command.schema.json` 또는
  `schemas/order-command-error.schema.json`
- UI 장바구니 응답은 다음 NLU 요청의 상태와 화면 표시가 일치하도록 음료 `options`를
  포함한다.
- 서버 옵션:
  - `--nlu mock|qwen`
  - `--nlu-adapter PATH`
  - `--nlu-device auto|cpu|cuda[:N]`
  - `--nlu-local-files-only` (선택)
- 주문 계약의 Source of Truth는 기존 OrderCommand 및 Order Engine Spec을 따른다.

## AC (Given-When-Then)

**AC-01 · 정상 Command 변환**

- GIVEN: Qwen backend가 유효한 Command 배열 JSON을 반환한다.
- WHEN: `parse()`를 호출한다.
- THEN: runtime request ID가 주입된 `OrderCommand[]`가 반환되고 Schema를 통과한다.

**AC-02 · 오류 객체 변환**

- GIVEN: Qwen backend가 유효한 `OrderCommandError` JSON을 반환한다.
- WHEN: `parse()`를 호출한다.
- THEN: 동일한 error code와 복구 정보의 도메인 객체가 반환된다.

**AC-03 · Fail-closed 출력 처리**

- GIVEN: Qwen backend가 잘못된 JSON 또는 Schema를 반환한다.
- WHEN: Voice Pipeline이 요청을 처리한다.
- THEN: 실패 응답을 반환하고 기존 장바구니는 변경되지 않는다.

**AC-04 · 서버 선택 연결**

- GIVEN: 유효한 adapter 경로와 `--nlu qwen` 옵션이 있다.
- WHEN: 서버를 시작한다.
- THEN: `MockNLU` 대신 Qwen NLU 인스턴스가 Pipeline에 한 번 주입된다.

**AC-05 · 기존 기능 회귀 없음**

- GIVEN: `--nlu mock` 기본값을 사용한다.
- WHEN: 기존 주문엔진·Web 통합 테스트를 실행한다.
- THEN: 기존 테스트가 모두 통과한다.
