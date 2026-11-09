---
title: "T-28 — TTS 다중 모델 비교 및 선택"
tags: [spec]
---

# T-28 — TTS 다중 모델 비교 및 선택

## Why

- **페르소나**: 말로(Mallo)의 기본 TTS 후보를 기술 지표와 블라인드 청취 결과로 결정해야 하는 팀
- **상황**: MeloTTS와 Qwen3-TTS의 Fine-tuned 결과를 동일한 T-21 문장·T-22 Benchmark·T-23 평가 양식으로 비교해야 한다.
- **문제**:
  1. 평균 점수만 높고 주문 핵심 정보를 오독하는 모델이 선택될 수 있다.
  2. 낮을수록 좋은 지표와 높을수록 좋은 지표를 같은 방향으로 환산해야 한다.
  3. 평가자·Benchmark·SIM 파일이 후보별로 어긋나면 비교 결과를 재현할 수 없다.
- **측정 지표**: 필수 조건 자동 판정률, 100점 계산 오차 0건, 평가자·문장 누락 검출률, 동일 입력 재현률

## Goal

- **해결 목표**: 후보별 T-22 결과, 최소 3명의 T-23 응답, SIM 결과와 운영 체크리스트를 검증하고 필수 조건을 통과한 후보 중 최종 모델을 선택한다.
- **성공 기준**:
  - 후보별 평가자가 3명 이상이고 작성자는 최종 평가자에서 제외된다.
  - 각 평가자에게 후보별 T-21 문장 20개가 정확히 한 번씩 있다.
  - 문장별 평가자 과반수로 심각한 오독·깨짐 0건과 핵심 정보 전달 18/20 이상을 판정한다.
  - 전체 명료도·친절함·매장 안내 적합성 평균이 각각 4.0 이상이고 친절함이 대응 Baseline보다 0.5 이상 향상됐는지 판정한다.
  - 필수 조건 통과 후보만 주문 정보 명료도 40, 친절체 품질 30, 응답 성능 20, 운영 적합성 10의 총 100점으로 계산한다.
  - 2점 이내 동점은 warm TTFB p95, Peak VRAM, 통합 단순성 순으로 결정한다.
  - 모든 후보가 탈락하거나 필수 입력이 없으면 최종 선택을 `WITHHELD`로 기록한다.
- **Out of Scope**:
  - 모델 학습·합성·Benchmark·청취 평가·SIM 자체의 실행
  - 누락된 평가값의 보간 또는 임의 점수 부여
  - 실패 후보를 zero-shot·다른 데이터 결과로 대체
  - 모델 checkpoint와 생성 WAV 공개

## What

### Happy Path

1. 비교 manifest가 후보와 각 결과 파일을 연결한다.
2. 도구가 T-22 Benchmark Schema와 T-23 평가·정답표, SIM 및 운영 체크리스트를 검증한다.
3. 후보별 청취 평균과 문장별 과반수 판정을 계산한다.
4. 필수 조건을 하나라도 충족하지 못한 후보를 탈락시킨다.
5. 통과 후보의 100점 영역 점수를 계산하고 동점 규칙을 적용한다.
6. 결과 JSON에 원시 입력 경로·집계값·탈락 사유·최종 선택 근거를 저장한다.

### Edge Cases

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 최종 평가자 3명 미만 또는 작성자 포함 | 입력 검증 실패 |
| EC-02 | 평가자별 후보·문장 누락·중복 | 입력 검증 실패 |
| EC-03 | Benchmark 성공 run 부족 | 후보 필수 조건 탈락 |
| EC-04 | RAM·VRAM·TTFB·RTF 값이 0·음수·null | 100점 계산 불가로 후보 탈락 |
| EC-05 | SIM 입력 누락 | 보고서 생성 실패. SIM은 점수에 넣지 않지만 비교 결과 필수 산출물임 |
| EC-06 | 모든 후보가 필수 조건 탈락 | `WITHHELD`, 탈락 사유 전체 기록 |
| EC-07 | 총점 차이 2점 이내 | warm TTFB p95 → Peak VRAM → 통합 단순성 순 비교 |
| EC-08 | 끝까지 동률 | candidate ID 오름차순으로 결정하지 않고 `WITHHELD_TIE` 기록 |

## How

비교 입력은 후보 ID, Baseline 대응 관계, T-22 결과, T-23 응답·정답표, SIM 결과와 운영 조건을 연결하는 로컬 JSON이다. 원본 음성이나 AI Hub 문장을 포함하지 않는다.

```json
{
  "experiment_id": "tts-final-001",
  "author_participant_id": "tts-author",
  "candidates": [
    {
      "candidate_id": "melotts-finetuned",
      "candidate_role": "finetuned",
      "baseline_candidate_id": "melotts-baseline",
      "benchmark_path": "/absolute/benchmark.json",
      "sim_path": "/absolute/sim.json",
      "evaluations": [
        {"evaluation_path": "/absolute/evaluation.tsv", "answer_key_path": "/absolute/answer-key.tsv"}
      ],
      "benchmark_rerun_success": true,
      "resource_limits_met": true,
      "operational_checklist": [true, true, true, true, true]
    }
  ]
}
```

- `candidate_role`은 `baseline` 또는 `finetuned`다. Baseline도 같은 평가·Benchmark 입력을 제공하지만 친절함 향상 기준으로만 사용하며 최종 100점 선택 대상에서 제외한다.
- `finetuned` 후보는 반드시 manifest 안의 `baseline` 후보 ID를 `baseline_candidate_id`로 가리킨다. Baseline의 `baseline_candidate_id`는 `null`이다.

### 집계 및 점수

- MOS는 모든 최종 평가자의 `naturalness` 유효 점수 평균이다.
- 정보별 명료도는 `NA`를 제외한 1~5점 평균이다.
- 문장별 안전·전달 판정은 해당 후보를 들은 평가자의 과반수다.
- 주문 정보 명료도: 메뉴명 평균/5×10 + 수량·단위 평균/5×15 + 가격 평균/5×15
- 친절체 품질: 자연스러움 평균/5×10 + 친절함 평균/5×10 + 매장 안내 적합성 평균/5×10
- 응답 성능: 후보 중 최소 warm TTFB p95/해당 후보 값×10 + 후보 중 최소 warm RTF p95/해당 후보 값×10
- 자원 점수: 후보 중 최소 Peak RAM p95/해당 후보 값×2.5 + 후보 중 최소 Peak VRAM p95/해당 후보 값×2.5
- 재현성·통합 난이도: 운영 체크리스트 true 개수, 최대 5점
- SIM은 후보별 평균·revision·참조 수를 보고하지만 총점에는 포함하지 않는다.
- 상대 점수의 최솟값은 필수 조건을 통과하고 유효 기술 지표를 가진 후보 집합에서 계산한다.

## AC (Given-When-Then)

### AC-01 · 입력 완전성

- GIVEN: 후보별 Benchmark·평가·정답표·SIM·운영 입력이 있다.
- WHEN: 비교 도구를 실행한다.
- THEN: 최소 3명의 비작성자 평가와 후보별 20문장, 유효 기술 지표가 모두 연결된다.

### AC-02 · 필수 조건

- GIVEN: 후보별 청취·성능 집계가 있다.
- WHEN: 필수 조건을 적용한다.
- THEN: 심각한 오독·깨짐, 핵심 전달, 3개 평균, Baseline 친절함 향상, Benchmark 재실행과 자원 한도를 후보별 통과·탈락 사유로 기록한다.

### AC-03 · 100점 산식

- GIVEN: 필수 조건 통과 후보가 2개 이상 있다.
- WHEN: 가중치와 낮을수록 좋은 지표의 비율식을 적용한다.
- THEN: 영역별 점수 합이 100점 이하이고 계산 근거가 후보별로 기록된다.

### AC-04 · 선택 및 보류

- GIVEN: 후보별 총점과 tie-break 지표가 있다.
- WHEN: 최종 선택 규칙을 적용한다.
- THEN: 단일 후보와 근거를 선택하거나 `WITHHELD`·`WITHHELD_TIE`와 사유를 기록한다.

### AC-05 · 재현 가능 결과

- GIVEN: 동일한 입력 파일과 코드 revision이 있다.
- WHEN: 두 번 집계한다.
- THEN: 실행 시각을 제외한 후보 집계·점수·선택 결과가 동일하다.
