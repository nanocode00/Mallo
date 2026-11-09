---
title: "NLU 메뉴 태그 조건 검색"
tags: [spec]
---

# NLU 메뉴 태그 조건 검색

## Why

- **페르소나**: 메뉴 이름을 모르지만 원하는 맛이나 재료 조건은 말할 수 있는 고령 사용자
- **상황**: 사용자가 `안 단 거 있어요?`, `카페인 없고 우유 안 들어간 음료 알려줘`처럼 조건으로 메뉴를 찾는다.
- **문제**: 기존 `QUERY_MENU`는 전체·카테고리·단일 메뉴 조회만 지원해 조건 발화를 Menu DB 검색으로 연결할 수 없다.
- **측정 지표**: 표준 태그 변환 정확도 100%, 복수 조건 AND 검색 정확도 100%, 조회 중 Cart 비변경률 100%

## Goal

- **해결 목표**: 자연어 별칭을 표준 태그로 정규화하고 `QUERY_MENU.query_tags`로 Menu DB를 검색한다.
- **성공 기준**: 등록된 모든 별칭이 표준 태그로 변환되고, 단일·복수·카테고리 결합 검색 테스트가 모두 통과한다.
- **Out of Scope**: NLU 모델·규칙 기반 방식 확정, 기존 메뉴 탐색 변경, 개인화 추천, 영양·알레르기 보증, TTS 변경

## What

### Happy Path

1. `안 단 거`와 `당도 낮은 거`를 모두 `sweetness_low`로 정규화한다.
2. NLU는 `QUERY_MENU`와 하나 이상의 `query_tags`를 출력한다.
3. Order Engine은 모든 태그를 가진 메뉴만 카탈로그 순서로 안내한다.
4. `category_id`가 함께 있으면 카테고리와 태그를 모두 만족하는 메뉴만 안내한다.
5. 조건 검색 전후 Cart는 동일하게 유지한다.

### Edge Cases

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 등록되지 않은 태그 | `INVALID_OPTION`, Cart 유지 |
| EC-02 | 조건을 만족하는 메뉴 없음 | `MENU_NOT_FOUND`, Cart 유지 |
| EC-03 | 같은 태그 중복 출력 | Schema Validation에서 거부 |
| EC-04 | `target_item_id`와 태그 동시 사용 | `INVALID_COMMAND`, 단일 메뉴 조회와 조건 검색을 분리 |
| EC-05 | 조건 검색에 수량 포함 | `INVALID_COMMAND`, Cart 유지 |

## How

- Menu DB의 `tag_definitions`는 표준 태그 ID, 표시명, 한국어 별칭을 정의한다.
- 각 메뉴의 `tags`에는 표준 태그 ID만 저장한다.
- 기본 태그 축은 단맛·카페인·우유·온도이며, 맛·질감 탐색을 위해 과일·허브·상큼함·부드러움을 추가한다.
- 별칭 정규화기는 특정 NLU 구현과 독립된 함수로 제공한다.
- 런타임 `OrderCommand`와 Local LLM 의미 Payload에 `query_tags: string[] | null`을 추가한다.
- 여러 태그는 OR가 아니라 AND로 검색한다.
- 태그는 매장 운영자가 관리하는 탐색용 메타데이터이며 의학적·영양학적 보증으로 사용하지 않는다.

```json
[
  {
    "intent": "QUERY_MENU",
    "target_item_id": null,
    "category_id": null,
    "quantity": null,
    "temperature": null,
    "query_tags": ["sweetness_low"],
    "detail_fields": null,
    "options": null
  }
]
```

## AC (Given-When-Then)

### AC-01 · 동의 표현 정규화

- **GIVEN**: `안 단`, `당도 낮음`, `달지 않은`이 `sweetness_low` 별칭으로 등록돼 있다.
- **WHEN**: 각 표현이 포함된 메뉴 조건 질문을 정규화한다.
- **THEN**: 모두 `sweetness_low` 하나로 변환된다.

### AC-02 · 단일 조건 검색

- **GIVEN**: 여러 메뉴에 `sweetness_low` 태그가 있다.
- **WHEN**: `QUERY_MENU`, `query_tags=["sweetness_low"]`를 실행한다.
- **THEN**: 해당 태그 메뉴들을 카탈로그 순서로 안내하고 Cart를 유지한다.

### AC-03 · 복수 조건 AND 검색

- **GIVEN**: 메뉴마다 카페인·우유·온도 태그가 다르다.
- **WHEN**: `caffeine_free`, `milk_free`, `iced`를 함께 검색한다.
- **THEN**: 세 태그를 모두 가진 메뉴만 안내한다.

### AC-04 · 기존 탐색 회귀 방지

- **GIVEN**: 기존 전체·카테고리·단일 메뉴 조회 요청이 있다.
- **WHEN**: `query_tags=null`로 실행한다.
- **THEN**: 기존 응답과 동작이 변경되지 않는다.

### AC-05 · 계약 및 데이터셋 검증

- **GIVEN**: 모든 Intent의 `OrderCommand`와 NLU CSV Label이 있다.
- **WHEN**: Schema 및 데이터셋 검증을 실행한다.
- **THEN**: `query_tags`는 항상 존재하고 `QUERY_MENU` 외 Intent에서는 `null`이다.
