---
title: "T-12 — Adaptive TTS Level 0/1 Latency 비교"
tags: [spec]
---

# T-12 — Adaptive TTS Level 0/1 Latency 비교

## Why

- **페르소나**: 느린 음성 안내를 요청하는 고령 사용자와 TTS 운영 담당자
- **상황**: Level 1은 Level 0보다 느린 발화 속도와 Pause가 적용되지만, 그 변화가 합성 대기시간에 주는 영향은 같은 모델·문장·장치에서 측정되지 않았다.
- **문제**: 서로 다른 문장이나 모델의 기존 Benchmark 수치를 비교하면 Adaptive TTS 자체의 추가 지연을 분리할 수 없다.
- **측정 지표**: Level별 합성 지연·RTF의 평균, 중앙값, nearest-rank p95, Level 1의 Level 0 대비 차이와 비율

## Goal

- **해결 목표**: 최종 TTS 후보에서 Level 0/1을 동일한 20개 T-21 문장과 반복 조건으로 교차 측정하여 Adaptive TTS 적용 전후 지연을 기록한다.
- **성공 기준**:
  - 모델을 한 번 로드하고 Level별 warm-up 1회를 제외한 총 200개 성공 측정을 확보한다.
  - 20개 문장을 Level별 5회 합성하고 실행 순서를 번갈아 순서 편향을 줄인다.
  - Level별 합성 지연·RTF의 평균·중앙값·nearest-rank p95와 Level 1의 차이·비율을 기록한다.
  - Git SHA, 실행 시각, OS, Python, 모델·checkpoint, device와 반복 정책을 결과에 남긴다.
- **Out of Scope**: Level 2·T-24 이해도 평가, 모델 재선정, 실제 재생 장치의 playback 지연

## What

### Happy Path

1. 최종 후보를 로드하고 Level별 warm-up 1회를 수행한다.
2. T-21 원문을 Level별 변환하고 각 5회씩 순서를 교차해 합성한다.
3. 합성 지연·음성 길이로 RTF를 계산하고 비교 통계를 JSON과 worklog에 기록한다.

### Edge Cases

| 상황 | 처리 방식 |
|---|---|
| 합성 실패·빈 오디오·0ms 음성 | 실패 run으로 보존하고 완료 판정 차단 |
| Level별 성공 수 불일치 또는 Level 0 평균 0 | 비교 판정을 중단하고 재측정 |
| 모델·checkpoint·장치 변경 | 결과를 폐기하고 동일 조건으로 재실행 |

## How

- 입력·변환: T-21 문장 20개와 `AdaptiveTextTransformer.transform(text, level)`
- 측정: `TTSResult.latency_ms`, RTF=`latency_ms / duration_ms`
- 반복·통계: Level별 warm-up 1회 제외, 문장별 각 5회, nearest-rank p95
- 원시 WAV와 checkpoint는 커밋하지 않고 결과 JSON도 로컬 증빙으로 보관한다. 저장소에는 재현 명령과 집계값만 기록한다.

## AC (Given-When-Then)

### AC-01 · 동일 입력과 반복 수

- GIVEN T-21 문장 20개와 하나의 backend가 있고, WHEN Level 0/1 비교를 실행하면, THEN 같은 원문 ID별로 각 5회씩 총 200개 run이 기록된다.

### AC-02 · 실제 Adaptive 변환과 합성

- GIVEN 원문과 Level이 있고, WHEN 각 run을 합성하면, THEN 변환된 text와 Level이 같은 `TTS.synthesize()` 호출에 전달된다.

### AC-03 · 통계와 차이

- GIVEN 모든 run이 성공했고, WHEN 결과를 집계하면, THEN Level별 latency·RTF 통계와 Level 1의 차이·비율이 계산된다.

### AC-04 · 재현 정보

- GIVEN 결과 JSON이 있고, WHEN metadata를 확인하면, THEN Git SHA·환경·모델·device·반복 정책이 존재한다.

### AC-05 · 실패 차단

- GIVEN 합성 실패나 유효하지 않은 길이가 있고, WHEN 결과를 생성하면, THEN 실패 run을 보존하고 성공 run 200개가 아니면 완료로 판정하지 않는다.
