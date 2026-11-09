---
title: "T-21 — TTS 평가 문장 세트"
tags: [spec]
---

# T-21 — TTS 평가 문장 세트

## Why

- **페르소나**: 말로(Mallo)의 주문 안내를 듣고 메뉴·수량·금액을 확인해야 하는 고령 사용자
- **상황**: MeloTTS Baseline과 Fine-tuned MeloTTS·Qwen3-TTS를 동일한 주문 문장으로 비교해야 한다.
- **문제**:
  1. 임의 문장을 모델마다 다르게 사용하면 명료도와 성능을 공정하게 비교할 수 없다.
  2. 학습 문장과 같은 문장을 평가하면 Fine-tuning 효과를 과대평가할 수 있다.
  3. 자연스러움만 평가하면 메뉴명·수량·단위·가격 같은 주문 핵심 정보의 오독을 놓칠 수 있다.
- **측정 지표**: 문장 20개 구성률, 범주별 4개 충족률, 데이터 중복 0건, 핵심 정보 태그 누락 0건

## Goal

- **해결 목표**: 실제 TTS 시스템 응답 형태의 한국어 문장 20개를 고정하여 모든 TTS 후보의 합성·성능·청취 평가에 공통 사용한다.
- **성공 기준**:
  - `menu_temperature`, `quantity_unit`, `price_total`, `modify_delete`, `summary_payment`를 각각 4개 포함한다.
  - 문장 ID와 문장 text는 중복되지 않는다.
  - 모든 문장에 청취자가 식별해야 할 `critical_terms`가 1개 이상 있다.
  - 메뉴를 언급한 문장은 현재 Menu Catalog의 공식 이름만 사용한다.
  - NFKC, 소문자화, 문장부호 제거, 공백 정규화 후 AI Hub train/validation/test 문장과 완전히 일치하는 문장이 0개다.
- **Out of Scope**:
  - 음성 합성, latency·RTF 측정
  - MOS 평가 양식과 블라인드 샘플 배치
  - 학습용 문장 추가 또는 AI Hub 원문 수정
  - 영어·다국어 문장과 복수 발화 성격 평가
  - TTS 모델별 발음 사전 또는 숫자 전처리 보정

## What

### Happy Path

1. 평가 도구가 JSON 문장 세트를 읽는다.
2. Schema, 20개 개수, 범주별 4개, ID·text 고유성 및 `critical_terms` 포함 여부를 검사한다.
3. 메뉴 관련 `critical_terms`가 Menu Catalog의 공식 이름과 일치하는지 검사한다.
4. 로컬 T-25 manifest가 있으면 train/validation/test 전체와 정규화 완전 일치 여부를 검사한다.
5. 검증된 20개 text를 모든 TTS 후보에 같은 순서로 전달한다.

### Edge Cases

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 문장이 20개가 아니거나 범주별 4개가 아님 | 검증 실패, 합성 시작 금지 |
| EC-02 | ID 또는 정규화 text가 중복됨 | 검증 실패, 중복 문장 수정 |
| EC-03 | 학습·검증·test manifest와 정규화 완전 일치 | 해당 평가 문장을 교체하고 다시 검사 |
| EC-04 | T-25 manifest가 로컬에 없음 | 정적 문장 검사는 수행하되 누수 검사는 `NOT_RUN`으로 기록하고 최종 완료 처리하지 않음 |
| EC-05 | 비공식 메뉴명·약칭이 포함됨 | 검증 실패, Menu Catalog 공식 이름으로 교체 |
| EC-06 | `critical_terms`가 text에 그대로 존재하지 않음 | 검증 실패, text 또는 태그 수정 |
| EC-07 | 가격·수량의 발음이 모델별로 다름 | 원문은 바꾸지 않고 T-23 평가에서 오독으로 기록 |

## How

평가 데이터는 `data/tts/evaluation/sentences.json`에 저장한다.

```json
{
  "version": "1.0",
  "language": "KR",
  "sentences": [
    {
      "id": "tts_eval_01",
      "category": "menu_temperature",
      "text": "아이스 아메리카노 한 잔을 주문에 담았습니다.",
      "critical_terms": ["아이스", "아메리카노", "한 잔"],
      "menu_ids": ["americano"]
    }
  ]
}
```

- JSON에는 직접 작성한 평가 문장만 저장하며 AI Hub 원문을 복사하지 않는다.
- `id`는 `tts_eval_01`부터 `tts_eval_20`까지 연속이어야 한다.
- `language`는 `KR`로 고정한다.
- `category`는 성공 기준의 다섯 값 중 하나다.
- `critical_terms`는 청취 평가에서 의미 보존 여부를 확인할 최소 단위이며 모두 text의 부분 문자열이어야 한다.
- `menu_ids`는 text에 등장하는 Menu Catalog ID 목록이며 각 ID의 공식 메뉴명이 text에 포함되어야 한다. 메뉴가 없는 문장은 빈 배열을 사용한다.
- 숫자는 실제 TTS frontend의 숫자·금액 처리 능력을 확인하도록 아라비아 숫자와 한글 표현을 함께 포함할 수 있다. 모델별 결과에 맞춰 원문을 변경하지 않는다.
- 누수 정규화는 Unicode NFKC → 소문자화 → Unicode 문장부호·기호 제거 → 공백 하나로 축약 순서로 수행한다.

## AC (Given-When-Then)

### AC-01 · 문장 세트 구조

- GIVEN: 평가 문장 JSON이 있다.
- WHEN: 정적 검증을 실행한다.
- THEN: 연속 ID 20개, `KR`, 고유 text와 유효한 `critical_terms`만 존재한다.

### AC-02 · 범주 균형

- GIVEN: 평가 문장 20개가 있다.
- WHEN: category별 문장 수를 집계한다.
- THEN: 다섯 범주가 각각 정확히 4개다.

### AC-03 · 공식 메뉴명

- GIVEN: 평가 문장과 현재 Menu Catalog가 있다.
- WHEN: 메뉴명 critical term을 검사한다.
- THEN: 공식 메뉴명만 사용되고 비공식 alias는 존재하지 않는다.

### AC-04 · 학습 데이터 누수 방지

- GIVEN: T-25의 train/validation/test manifest와 평가 문장 20개가 있다.
- WHEN: 동일한 정규화 함수로 text를 비교한다.
- THEN: 완전히 일치하는 문장이 0개이고 검사한 manifest·레코드 수가 기록된다.

### AC-05 · 모델 공통 입력

- GIVEN: 검증을 통과한 평가 JSON이 있다.
- WHEN: 모델별 평가 코드가 문장을 읽는다.
- THEN: 모든 모델에 ID·text·순서가 동일한 20개 문장이 전달된다.
