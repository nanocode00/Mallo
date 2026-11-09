---
title: "NLU 메뉴 상세 질문"
tags: [spec]
---

# NLU 메뉴 상세 질문

## Why

- **페르소나**: 메뉴 이름은 확인했지만 작은 글씨나 복잡한 설명을 읽기 어려운 고령 사용자
- **상황**: 사용자가 `아메리카노는 어떤 음료야?`, `카페라떼에 카페인하고 우유가 있어?`처럼 메뉴별 정보를 음성으로 묻는다.
- **문제**: 기존 단일 메뉴 조회는 가격과 지원 온도를 항상 함께 안내해 사용자가 실제로 궁금한 설명·단맛·카페인·우유 여부를 구분해 답하지 못한다.
- **측정 지표**: 지원 상세 항목 응답 정확도 100%, 복수 항목 응답 순서 보존율 100%, 조회 중 Cart 비변경률 100%

## Goal

- **해결 목표**: `QUERY_MENU.detail_fields`로 사용자가 요청한 메뉴 상세 항목만 결정론적으로 안내한다.
- **성공 기준**: 가격·설명·단맛·카페인·우유·지원 온도 6개 항목과 복수 항목 질문 테스트가 모두 통과한다.
- **Out of Scope**: NLU 모델 방식 확정, 영양 수치·알레르기 보증, 재고, 개인화 추천, 기존 전체·카테고리·태그 검색 변경, TTS 변경

## What

### Happy Path

1. NLU가 공식 메뉴명을 `target_item_id`로, 질문 항목을 `detail_fields` 배열로 변환한다.
2. Order Engine은 Menu DB의 가격·설명·온도·표준 태그만 사용해 답한다.
3. 여러 항목을 물으면 `detail_fields` 순서대로 문장을 조합한다.
4. 조회 전후 Cart는 동일하게 유지한다.

### Edge Cases

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 상세 항목이 있는데 대상 메뉴 없음 | `INVALID_COMMAND`, 메뉴명을 다시 요청 |
| EC-02 | 존재하지 않는 상세 항목 | Schema Validation에서 거부 |
| EC-03 | 상세 항목 중복 | Schema Validation에서 거부 |
| EC-04 | 태그 조건 검색과 상세 질문 동시 사용 | `INVALID_COMMAND`, 요청을 분리 |
| EC-05 | 존재하지 않는 메뉴 | `MENU_NOT_FOUND`, Cart 유지 |

## How

- 런타임 `OrderCommand`와 Local LLM 의미 Payload에 `detail_fields: string[] | null`을 추가한다.
- 지원 값은 `description`, `price`, `sweetness`, `caffeine`, `milk`, `temperature`다.
- `detail_fields`는 `QUERY_MENU`와 단일 `target_item_id`가 있을 때만 사용한다.
- `detail_fields=null`인 기존 단일 메뉴 조회는 가격과 온도를 안내하는 현재 동작을 유지한다.
- 단맛·카페인·우유 답변은 Menu DB의 표준 태그를 사용하며 영양·알레르기 보증으로 표현하지 않는다.
- 자연어 질문 항목 정규화는 특정 NLU 구현과 독립된 함수로 제공한다.

```json
[
  {
    "intent": "QUERY_MENU",
    "target_item_id": "cafe_latte",
    "category_id": null,
    "quantity": null,
    "temperature": null,
    "query_tags": null,
    "detail_fields": ["caffeine", "milk"],
    "options": null
  }
]
```

## AC (Given-When-Then)

### AC-01 · 메뉴 설명 질문

- **GIVEN**: 아메리카노의 설명이 Menu DB에 있다.
- **WHEN**: `target_item_id=americano`, `detail_fields=[description]`을 실행한다.
- **THEN**: 아메리카노 설명만 안내하고 Cart를 유지한다.

### AC-02 · 속성 상세 질문

- **GIVEN**: 카페라떼에 단맛·카페인·우유 태그가 있다.
- **WHEN**: 해당 상세 항목을 질문한다.
- **THEN**: 태그에 대응하는 정성 정보를 정확하게 안내한다.

### AC-03 · 복수 항목 질문

- **GIVEN**: `detail_fields=[caffeine, milk]`인 Command가 있다.
- **WHEN**: 단일 메뉴 상세 조회를 실행한다.
- **THEN**: 카페인과 우유 정보를 배열 순서대로 모두 안내한다.

### AC-04 · 기존 메뉴 조회 회귀 방지

- **GIVEN**: `detail_fields=null`인 전체·카테고리·단일·태그 메뉴 조회가 있다.
- **WHEN**: 기존 조회를 실행한다.
- **THEN**: 기존 응답과 검색 결과가 변경되지 않는다.

### AC-05 · 계약 및 데이터셋 검증

- **GIVEN**: 모든 Intent의 OrderCommand와 NLU CSV Label이 있다.
- **WHEN**: Schema 및 데이터셋 검증을 실행한다.
- **THEN**: `detail_fields`는 항상 존재하며 대상 메뉴 상세 질문 외에는 `null`이다.
