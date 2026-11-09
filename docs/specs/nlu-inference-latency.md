---
title: "Qwen3-1.7B NLU Reference Latency 최적화"
tags: [spec, nlu, latency, reference]
---

# Qwen3-1.7B NLU Reference Latency 최적화

> **Reference only.** 이 문서는 기존 Qwen3-1.7B QLoRA 추론 최적화 실험을 보존하기 위한 reference spec이다. PR #209의 실제 서비스 통합 대상은 **Qwen3-0.6B**이며, 0.6B 서비스 후보 성능은 `docs/specs/nlu-qwen06b-service-candidate.md`를 기준으로 한다. 이 문서와 1.7B reference benchmark 결과를 0.6B 실서비스 검증 결과로 해석하지 않는다.

## Why

- **페르소나**: 음성 주문 뒤 긴 침묵 없이 응답을 받아야 하는 말로 사용자와 NLU 운영자
- **상황**: Qwen3-1.7B QLoRA v1은 warm validation 추론에서 수 초의 지연이 측정됐다.
- **문제**: 출력 길이, Prompt, 생성 설정, 양자화, PEFT Adapter 결합 및 모델 수명주기의
  비용이 분리되지 않아 정확도를 보존하는 최적 경로를 선택할 근거가 없다.
- **측정 지표**: input/output token, EOS 도달률, median/p95 latency, peak VRAM,
  Exact Match, Intent/Slot Accuracy, JSON/Schema Valid Rate

## Goal

- 고정 validation 300건과 동일 warm-up 조건에서 한 번에 하나의 추론 요소만 바꿔 비교한다.
- 서비스 후보는 v1 대비 Exact Match, Intent/Slot Accuracy 또는 Schema Valid Rate가
  의미 있게 하락하지 않는 변경만 채택한다.
- 모델/tokenizer가 상주하는 warm persistent 경로와 cold start를 분리해 기록한다.
- 최종 후보를 실제 Mallo Pipeline에 연결해 STT, NLU, Order Engine, TTS 및 전체 구간을 측정한다.
- **Out of Scope**: 동결된 test 결과를 이용한 Prompt·설정·모델 선택, test 재실행,
  새로운 학습 데이터나 Fine-tuning hyperparameter 선택

## What

1. v1 test 300건을 한 번만 실행하고 prediction, summary, hash와 실행 ledger를 동결한다.
2. 기존 4-bit PEFT 경로의 Prompt 구성별 token, 실제 생성 token, EOS와 latency를 기록한다.
3. Prompt 축소, greedy 설정 정리, BF16, merged BF16을 순서대로 한 요소씩 비교한다.
4. 각 후보는 같은 validation 순서, warm-up 횟수와 평가기로 품질 및 latency를 측정한다.
5. 채택 후보는 프로세스 안에서 모델/tokenizer를 재사용하며 cold와 warm을 분리한다.
6. 마지막에만 실제 Pipeline의 구간별 및 Real E2E latency를 측정한다.

### Edge Cases

- EOS 없이 `max_new_tokens`에 도달하면 truncation으로 기록하고 품질 후보에서 제외한다.
- JSON 뒤 설명이나 두 번째 JSON이 있으면 출력 계약 실패로 집계한다.
- BF16 또는 merge가 16GB VRAM에서 실패하면 오류와 peak VRAM을 기록하고 채택하지 않는다.
- test ledger가 이미 완료된 experiment는 어떠한 최적화 variant로도 다시 실행하지 않는다.
- Real STT/TTS가 준비되지 않았거나 실제 재생 시각이 없으면 Mock/Component 결과를
  Real E2E로 표현하지 않는다.

## How

- 기준 모델: `Qwen/Qwen3-1.7B` revision
  `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`와 v1 final adapter
- 기준 입력: `data/nlu/processed/validation.jsonl` 300건, 파일 순서 고정
- warm-up: 같은 모델 instance에서 최초 5회, 통계 제외
- latency: tokenization을 별도 측정하고 CUDA synchronize 사이의 generation을 warm latency로 기록
- p95: `docs/specs/e2e-latency.md`와 같은 nearest-rank 방식
- VRAM: 측정 시작 전 CUDA peak stats를 초기화하고 allocated/reserved peak를 함께 기록
- 품질: `model_evaluator.py`의 동일 계약 지표 사용
- 결과에는 모델 revision, adapter/hash, dtype/quantization, Prompt profile,
  generation options, 환경과 원시 sample별 값을 보존한다.

변경 순서는 `token 계측 -> compact Prompt -> greedy 설정 정리 -> 4-bit/BF16 ->
PEFT/merged BF16 -> persistent warm 경로 -> Real E2E`로 고정한다. 앞 단계 결과를 기준으로
다음 단계의 단일 변수를 정의하되 test 결과는 판단 입력에서 제외한다.

품질 채택 기준은 기준 validation 대비 다음을 모두 만족하는 것이다.

- Exact Match 하락 `<= 0.5%p`
- Intent Accuracy 하락 `<= 0.5%p`
- Slot Accuracy 하락 `<= 0.5%p`
- JSON/Schema Valid Rate 하락 `<= 0.5%p`
- invalid menu output 증가 없음

## AC

### AC-01 · Test 단회 동결

- GIVEN: v1 experiment의 test ledger가 비어 있다.
- WHEN: `--final-test`와 experiment ID로 test 300건을 완료한다.
- THEN: prediction·summary·hash·ledger가 남고 같은 experiment/variant 재실행은 거부된다.

### AC-02 · Token과 EOS 계측

- GIVEN: 고정 validation 입력과 기존 v1 추론 경로가 있다.
- WHEN: warm inference를 수행한다.
- THEN: 각 행의 input/output token, EOS 도달 여부와 집계치 및 `max_new_tokens`가 기록된다.

### AC-03 · 단일 변수 비교

- GIVEN: 직전 단계의 채택 기준 결과가 있다.
- WHEN: 다음 최적화 후보를 측정한다.
- THEN: 나머지 모델·입력·warm 조건은 동일하고 변경 요소가 manifest에 하나로 식별된다.

### AC-04 · 품질 방어

- GIVEN: 후보의 latency와 품질 결과가 있다.
- WHEN: 기준 결과와 비교한다.
- THEN: 품질 채택 기준을 하나라도 위반한 후보는 최종 경로로 채택되지 않는다.

### AC-05 · Cold/Warm 분리

- GIVEN: 모델을 새로 시작한 실행과 상주 instance가 있다.
- WHEN: latency를 측정한다.
- THEN: load/cold-first-generation과 warm median/p95가 분리돼 기록된다.

### AC-06 · 실제 E2E 경계

- GIVEN: 최적 NLU가 실제 STT·Order Engine·TTS 경로에 연결돼 있다.
- WHEN: 대표 문장 조건으로 측정한다.
- THEN: 구간별 latency와 전체 latency가 `docs/specs/e2e-latency.md` 계약대로 기록된다.
