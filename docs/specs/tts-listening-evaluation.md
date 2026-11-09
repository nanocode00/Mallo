---
title: "T-23 — TTS 블라인드 청취 평가 양식"
tags: [spec]
---

# T-23 — TTS 블라인드 청취 평가 양식

## Why

- **페르소나**: 모델 정보를 모른 채 말로(Mallo)의 주문 안내 음성을 평가하는 팀원
- **상황**: Baseline과 Fine-tuned 후보를 최소 3명이 동일한 문장과 척도로 비교해야 한다.
- **문제**:
  1. 파일명에 모델명이 보이면 기대 편향이 생긴다.
  2. 평가자마다 다른 항목과 기준을 사용하면 MOS와 모델 선택 점수를 합칠 수 없다.
  3. 단순 자연스러움 점수만으로는 메뉴명·수량·가격 오독과 음성 깨짐을 판정할 수 없다.
- **측정 지표**: 모델명 노출 0건, 후보별 문장 누락 0건, 필수 응답 열 누락 0건, 재현 가능한 무작위 배치율 100%

## Goal

- **해결 목표**: T-21의 동일 문장과 후보별 WAV를 익명화하여 최소 3명이 7개 청취 항목과 안전·명료도 판정을 기록할 수 있는 패키지를 만든다.
- **성공 기준**:
  - 후보가 2개 이상이고 각 후보에 T-21 문장 20개가 정확히 한 번씩 있다.
  - 공개 평가표와 WAV 파일명에 모델 ID·checkpoint·원본 경로가 노출되지 않는다.
  - 동일 seed와 participant ID는 같은 순서를, 다른 participant ID는 독립적인 순서를 만든다.
  - 7개 점수는 정수 1~5 또는 항목 비적용 시 `NA`만 허용한다.
  - 자연스러움·전체 명료도·친절함·매장 안내 적합성은 모든 행에서 필수다.
  - 메뉴명·수량·단위·가격 명료도는 해당 정보가 `critical_terms`에 존재하는 문장에서만 필수이며 나머지는 `NA`다.
  - 핵심 정보 전달 성공과 심각한 오독·음성 깨짐은 `yes` 또는 `no`로 기록한다.
- **Out of Scope**:
  - 실제 평가자 모집과 평가 수행
  - MOS·SIM 집계와 최종 모델 선택
  - 음성 생성, 보정, 정규화 또는 loudness 변경
  - 웹 기반 평가 UI와 외부 설문 서비스 업로드
  - AI Hub 원본 음성의 평가 패키지 포함

## What

### Happy Path

1. 작업자가 후보별 T-21 WAV 20개의 로컬 입력 manifest를 만든다.
2. 생성기가 후보·문장 누락과 WAV decode 여부를 검사한다.
3. participant ID와 seed로 40개 이상의 샘플 순서를 섞는다.
4. WAV를 `sample_001.wav` 형식으로 복사하고 공개 `evaluation.tsv`를 생성한다.
5. 모델 대응 관계는 별도 비공개 `answer-key.tsv`에만 저장한다.
6. 평가자는 원문과 핵심 정보를 보며 점수·오류 여부·메모를 기록한다.

### Edge Cases

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 후보가 2개 미만 | 생성 실패 |
| EC-02 | 후보에 문장 누락·중복·추가 ID가 있음 | 생성 실패 |
| EC-03 | WAV 누락·decode 실패·0초 | 생성 실패 |
| EC-04 | 후보 ID가 공개 파일명이나 평가표에 포함됨 | 생성 실패 |
| EC-05 | 동일 출력 디렉터리가 이미 존재함 | 기존 결과를 덮어쓰지 않고 생성 실패 |
| EC-06 | 1~5·NA 이외의 점수 또는 yes/no 이외의 판정 | 응답 검증 실패 |
| EC-07 | 작성자가 최종 평가자에 포함됨 | 최종 평가 인원 조건 미충족으로 기록 |

## How

입력 manifest는 Git에 포함하지 않는 로컬 JSON이다.

```json
{
  "experiment_id": "tts-final-001",
  "candidates": [
    {
      "candidate_id": "model-internal-name",
      "samples": [
        {"sentence_id": "tts_eval_01", "audio_path": "/absolute/path.wav"}
      ]
    }
  ]
}
```

공개 `evaluation.tsv`에는 다음 열을 둔다.

```text
participant_id, presentation_order, sample_id, sentence_id, text,
critical_terms, naturalness, overall_clarity, friendliness,
menu_name_clarity, quantity_unit_clarity, price_clarity,
store_guidance_suitability, critical_information_success,
serious_misread_or_corruption, calm_friendly_notes, comments
```

- 점수 기준: 1 매우 나쁨, 2 나쁨, 3 보통, 4 좋음, 5 매우 좋음
- `naturalness`, `overall_clarity`, `friendliness`, `store_guidance_suitability`는 항상 1~5다.
- 정보별 명료도는 해당 핵심 정보가 있는 행에서 1~5, 없는 행에서 `NA`다.
- `critical_information_success=yes`는 메뉴명·온도·수량·단위·가격·수정·결제 의도 중 해당 문장의 모든 핵심 정보를 올바르게 이해한 경우다.
- `serious_misread_or_corruption=yes`는 의미가 달라지는 오독, 무음, 잘림, 반복 또는 비정상 잡음이 있는 경우다.
- 공개 패키지는 생성 WAV를 변환하지 않고 byte-for-byte 복사한다.
- `answer-key.tsv`와 응답 완료 파일은 결과 공개 전까지 로컬 비공개로 유지한다.

## AC (Given-When-Then)

### AC-01 · 후보별 완전한 문장 세트

- GIVEN: 후보별 WAV manifest와 T-21 문장 세트가 있다.
- WHEN: 패키지를 생성한다.
- THEN: 각 후보에 20개 ID가 정확히 한 번씩 있고 총 행 수는 `후보 수 × 20`이다.

### AC-02 · 블라인드 익명화

- GIVEN: 내부 후보 ID와 checkpoint 경로가 있다.
- WHEN: 공개 패키지를 검사한다.
- THEN: WAV 파일명과 `evaluation.tsv`에 내부 식별자가 없고 대응 관계는 `answer-key.tsv`에만 있다.

### AC-03 · 재현 가능한 무작위화

- GIVEN: 같은 입력, seed와 participant ID가 있다.
- WHEN: 서로 다른 빈 출력 경로에 두 번 생성한다.
- THEN: sample ID·문장·후보 순서가 같고 participant ID가 달라지면 순서가 달라진다.

### AC-04 · 평가 응답 계약

- GIVEN: 작성 완료한 `evaluation.tsv`가 있다.
- WHEN: 응답 검증기를 실행한다.
- THEN: 필수 점수·NA·yes/no·participant ID 규칙을 모두 통과하거나 오류 행과 사유를 반환한다.

### AC-05 · 원본 보존

- GIVEN: 입력 WAV와 익명화 WAV가 있다.
- WHEN: SHA-256을 비교한다.
- THEN: 모든 쌍이 byte-for-byte 동일하고 입력 WAV는 변경되지 않는다.
