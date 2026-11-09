---
title: "C-07~C-11·C-13 — OrderCommand 계약"
tags: [spec]
---

# C-07~C-11·C-13 — OrderCommand 계약

> 이 문서는 NLU 출력과 Order Engine 입력 사이의 `OrderCommand` 기준 계약이다. 완료된 C-19 Mock Pipeline의 `ADD_ITEM` 전용 축소 계약보다 이 문서를 우선한다.

## Why

- **페르소나**: 한 문장으로 하나 이상의 메뉴를 주문하는 말로(Mallo)의 사용자와 NLU·Order Engine 담당자
- **상황**: 사용자는 `아이스 아메리카노 두 잔하고 따뜻한 카페라떼 한 잔 주세요`처럼 여러 메뉴를 한 번에 말할 수 있다.
- **문제**: 문서마다 Command 필드와 Intent 이름이 다르고, 단일·복수 메뉴 출력 및 Batch 실행 규칙이 완전히 고정되지 않았다.
- **측정 지표**: JSON Schema Valid Rate, 복수 메뉴 분해 정확도, Batch 원자성 테스트 통과율

## Goal

- **해결 목표**: 메뉴 하나를 표현하는 고정된 `OrderCommand`와 하나 이상의 Command를 전달하는 배열 계약을 확정한다.
- **성공 기준**:
  - NLU 정상 출력은 항상 길이 1 이상의 `OrderCommand[]`다.
- 모든 Command는 동일한 10개 필드를 가지며 사용하지 않는 값은 `null`이다.
  - 정의되지 않은 필드는 Schema Validation에서 거부한다.
  - 복수 메뉴의 순서·병합·실패 정책을 테스트로 재현할 수 있다.
- **Out of Scope**:
  - 하나의 `OrderCommand` 안에 `items[]`를 추가하는 구조
  - 결제·전체 취소·실행취소·메뉴 탐색·TTS 제어가 섞인 복합 명령
  - `menu_aliases`에 등록되지 않은 메뉴 별칭과 유사어 인식
  - 품절 메뉴 처리

## What

### Happy Path

1. 사용자가 `아이스 아메리카노 두 잔하고 따뜻한 카페라떼 한 잔 주세요`라고 말한다.
2. NLU는 발화 순서대로 메뉴별 `ADD_ITEM` Command를 만든다.
3. Schema Validator가 배열과 모든 Command의 구조를 검증한다.
4. Order Engine이 메뉴·수량·온도를 모두 검증한다.
5. 모든 Command가 유효하면 하나의 사용자 요청 단위로 Cart에 반영한다.

### Edge Cases

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 단일 메뉴 발화 | 길이 1의 `OrderCommand[]`를 반환한다. |
| EC-02 | 동일 메뉴·동일 온도 반복 | 실행 전에 하나의 Command로 합하고 수량을 더한다. |
| EC-03 | 동일 메뉴·다른 온도 | 서로 다른 Command로 유지한다. |
| EC-04 | 두 번째 Command가 유효하지 않음 | Batch 전체를 거부하고 기존 Cart를 유지한다. |
| EC-05 | 안전한 장바구니 변경 Intent가 한 발화에 섞임 | 최대 두 개를 발화 순서대로 원자 실행한다. |
| EC-06 | 지원 목록 밖의 Intent가 한 발화에 섞임 | 실행하지 않고 요청을 나누어 말하도록 안내한다. |
| EC-07 | 정의되지 않은 필드가 포함됨 | Schema Validation에서 전체 Batch를 거부한다. |

## How

### NLU 입력

현재 TRD 계약을 유지한다.

```text
STT text
Session context
Cart summary
Pending clarification
Allowed intent/schema
```

온도 선택이 필요한 신규 `ADD_ITEM`의 clarification은 session별 pending에
`target_item_id`·`quantity`·`temperature`·누락 필드를 보존한다. pending 중
`한 잔`~`다섯 잔`, `한 개`~`다섯 개`, 숫자 표기 및 존댓말 종결형과 `아이스로`·`따뜻하게`는 fallback NLU보다 먼저
해석하며, 기존 Cart 항목의 `UPDATE_OPTION`으로 전환하지 않는다. `UPDATE_OPTION`은
명시적인 변경 동사가 있는 발화만 허용한다.

### NLU 출력

단일 메뉴와 복수 메뉴 모두 배열로 반환한다.

```text
OrderCommand[]
```

Local LLM이 직접 생성하는 payload에는 의미 필드인 `intent`,
`target_item_id`, `category_id`, `quantity`, `temperature`, `query_tags`, `detail_fields`, `options`만 포함한다. NLU
어댑터가 payload를 검증한 뒤 `request_id`를 UUID v4로 주입하여 런타임
`OrderCommand[]`를 완성한다. 따라서 학습 라벨과 모델 출력에는 무작위
`request_id`를 넣지 않는다.

지원 Intent는 다음과 같다.

```text
ADD_ITEM
REMOVE_ITEM
UPDATE_QUANTITY
UPDATE_OPTION
QUERY_MENU
QUERY_CART
CONFIRM_ORDER
CANCEL
RESET_ORDER
UNDO
REQUEST_REPEAT
REQUEST_SLOWER
REQUEST_DEFAULT_SPEED
SELECT_PAYMENT_METHOD
```

주문이 확정된 상태에서는 지원 결제수단 이름이 명시된 발화(예: `카드`, `카드를`,
`카드로 결제할게요`, `카드를 결정할게요`, `삼성페이`, `카카오페이`, `현금으로`)를
`SELECT_PAYMENT_METHOD`로 우선 해석한다. 이 우선순위는 STT가 `결제`를 `결정`으로
오인식한 경우에도 유지한다. 결제수단이 없는 `결제할게요`는 기존 `CONFIRM_ORDER`
의미를 유지한다. 확정 후 결제수단 해석에 실패하면 결제수단을 다시 말해 달라고 안내한다.

### 공통 필드

모든 Command는 다음 9개 필드를 항상 포함한다.

| Field | Type | 의미 |
|---|---|---|
| `request_id` | string | NLU 어댑터가 런타임에 주입하는 UUID v4 |
| `intent` | enum | 수행할 명령 |
| `target_item_id` | string 또는 null | Menu DB의 메뉴 ID. `SELECT_PAYMENT_METHOD`에서는 `card`, `samsung`, `kakao`, `cash` 중 결제수단 ID |
| `category_id` | string 또는 null | Menu DB의 카테고리 ID |
| `quantity` | integer 또는 null | Command가 대상으로 하는 수량. 수량 변경에서는 변경 후 최종 수량 |
| `temperature` | `hot`, `iced` 또는 null | 메뉴 온도. 적용하지 않으면 `null` |
| `query_tags` | string[] 또는 null | `QUERY_MENU` 조건 검색용 표준 Menu Tag ID 배열 |
| `detail_fields` | string[] 또는 null | 단일 메뉴 상세 질문에서 요청한 정보 항목 배열 |
| `options` | object 또는 null | Size·샷·카페인·시럽·얼음 옵션의 변경 후 최종 값 |
| `fulfillment_type` | `dine_in`, `takeout` 또는 null | `SET_FULFILLMENT`의 주문 전체 이용 방식 |

규칙:

- 사용하지 않는 필드도 생략하지 않고 `null`을 사용한다.
- `quantity`가 값이면 1 이상의 정수여야 한다. 메뉴 ID·온도·옵션이 같은 Cart 행의 최대 수량은 5이며, `ADD_ITEM` 누적과 `UPDATE_QUANTITY` 모두 이 정책을 적용한다. 초과 요청은 명확한 수량 제한 응답으로 거부하고 Cart를 유지한다.
- `target_item_id`는 Menu DB의 공식 메뉴 ID만 허용하며 별칭 입력도 공식 ID로 정규화한다. 단, `SELECT_PAYMENT_METHOD`에서는 `card`, `samsung`, `kakao`, `cash`만 허용한다.
- `category_id`는 Menu DB의 공식 카테고리 ID만 허용한다.
- `query_tags`는 Menu DB의 공식 태그 ID만 허용하며 여러 태그는 AND로 적용한다.
- `detail_fields`는 `description`, `price`, `sweetness`, `caffeine`, `milk`, `temperature`만 허용한다.
- `options`는 기존 Schema 호환을 위해 `size`, `extra_shots`, `caffeine`, `syrup_pumps`, `ice_amount` 다섯 하위 필드를 유지한다. 단, 현재 제품 범위에서 NLU는 `caffeine` 값이 있는 `ADD_ITEM`·`UPDATE_OPTION`을 생성하지 않으며, 수신한 경우 실행하지 않는다.
- `size`는 `small`, `medium`, `large`, `null`을 사용한다. Size 지원 음료의 `null`은 Order Engine이 기본 MEDIUM으로 해석하되 이전 Cart 계약과의 호환을 위해 값은 `null`로 유지한다. 디저트는 `null`만 허용한다.
- `extra_shots`, `syrup_pumps`는 0 이상의 정수이며 서비스 정책상 최대값이 없다.
- `caffeine`은 `REGULAR`, `DECAF`, `ice_amount`는 `NONE`, `LESS`, `NORMAL`, `MORE` 중 메뉴가 지원하는 값만 허용한다.
- `options`는 `ADD_ITEM`, `UPDATE_OPTION`에서만 사용하며 하위 필드의 `null`은 해당 옵션을 지정하지 않았음을 뜻한다.
- 가격과 총액은 Command에 포함하지 않고 Menu DB와 Order Engine이 결정한다.
- 사용자 확인 필요 여부도 NLU가 결정하지 않고 Order Engine의 Confirmation Policy가 결정한다.
- Schema에 정의되지 않은 추가 필드는 허용하지 않는다.
- Intent별 필수 값과 `null` 허용 여부는 아래 표를 기준으로 한다.

### 출력 예시

```json
[
  {
    "request_id": "uuid-1",
    "intent": "ADD_ITEM",
    "target_item_id": "americano",
    "category_id": null,
    "quantity": 2,
    "temperature": "iced",
    "query_tags": null,
    "detail_fields": null,
    "options": {
      "size": null,
      "extra_shots": null,
      "caffeine": null,
      "syrup_pumps": null,
      "ice_amount": null
    }
  },
  {
    "request_id": "uuid-2",
    "intent": "ADD_ITEM",
    "target_item_id": "cafe_latte",
    "category_id": null,
    "quantity": 1,
    "temperature": "hot",
    "query_tags": null,
    "detail_fields": null,
    "options": {
      "size": null,
      "extra_shots": null,
      "caffeine": null,
      "syrup_pumps": null,
      "ice_amount": null
    }
  }
]
```

### Intent별 필드

`O`는 값 필수, `△`는 요청에 따라 값 또는 `null`, `-`는 `null`을 의미한다.

| Intent | target | category | quantity | temperature | query_tags | detail_fields | options |
|---|---:|---:|---:|---:|---:|---:|---:|
| `ADD_ITEM` | O | - | O | 메뉴 정책에 따름 | - | - | △ |
| `REMOVE_ITEM` | O | - | △ | △ | - | - | - |
| `UPDATE_QUANTITY` | O | - | O | △ | - | - | - |
| `UPDATE_OPTION` | O | - | 온도 부분 변경 시 O, 그 외 - | △ | - | - | △ |
| `QUERY_MENU` | △ | △ | - | - | △ | △ | - |
| `QUERY_CART` | - | - | - | - | - | - | - |
| `CONFIRM_ORDER` | - | - | - | - | - | - | - |
| `SELECT_PAYMENT_METHOD` | O | - | - | - | - | - | - |
| `CANCEL` | - | - | - | - | - | - | - |
| `RESET_ORDER` | - | - | - | - | - | - | - |
| `UNDO` | - | - | - | - | - | - | - |
| `REQUEST_REPEAT` | - | - | - | - | - | - | - |
| `REQUEST_SLOWER` | - | - | - | - | - | - | - |
| `REQUEST_DEFAULT_SPEED` | - | - | - | - | - | - | - |

`request_id`와 `intent`는 모든 Intent에서 값이 필수다. `UPDATE_OPTION`은 `temperature` 또는 하나 이상의 `options` 하위 필드를 가져야 한다. 온도와 `quantity`를 함께 지정하면 수량은 기존 Cart line에서 새 온도로 옮길 부분 수량이다. `QUERY_MENU`에서 `target_item_id`, `category_id`, `query_tags`, `detail_fields`가 모두 `null`이면 전체 메뉴 조회를 의미한다. `target_item_id`와 `query_tags`는 함께 사용하지 않으며 `detail_fields`는 `target_item_id`와 함께 사용한다.

`SELECT_PAYMENT_METHOD`는 이미 `confirmed=true`인 Cart에서만 성공하며, 결제수단의 실제 완료 화면 전환은 Web payment handler가 수행한다. NLU는 이 Intent를 `confirmed` Cart의 명확한 결제수단 발화에만 반환한다.

### Cart 대상 식별

- `REMOVE_ITEM`, `UPDATE_QUANTITY`, `UPDATE_OPTION`은 먼저 `target_item_id`로 Cart 후보를 찾는다.
- 후보가 하나이면 `temperature=null`이어도 해당 항목을 대상으로 한다.
- 같은 메뉴의 HOT과 ICED가 모두 있어 후보가 여러 개이면 `temperature`로 대상을 구분한다.
- 후보가 여러 개인데 `temperature=null`이면 Cart를 변경하지 않고 `AMBIGUOUS_TARGET`을 반환한다.
- P0에서는 원래 Command를 저장하지 않고 메뉴명과 온도를 포함해 다시 말하도록 안내한다.
- P1에서는 원래 Command를 보존하고 온도 후보를 제시하는 Clarification으로 해결할 수 있다.

### 온도 누락

- 고정 온도 메뉴는 Menu DB의 기본 온도를 적용한다.
- HOT과 ICED를 선택해야 하는 메뉴의 `ADD_ITEM`에서 `temperature=null`이면 Cart를 변경하지 않는다.
- P0에서는 `MISSING_FIELD`를 반환하고 HOT 또는 ICED를 포함해 다시 말하도록 안내한다.
- P1에서는 원래 Command를 보존한 뒤 온도 Clarification으로 해결할 수 있다.

### Confirmation Policy

- NLU는 사용자 확인 필요 여부를 출력하지 않는다.
- Order Engine이 Command 검증 후 Intent와 현재 Session 상태를 기준으로 확인 필요 여부를 결정한다.
- 확인이 필요하면 검증된 Command Batch를 `pending_command`로 저장하고 `CONFIRMING` 상태로 전환한다.
- `UNDO`는 복구 명령이므로 추가 확인 없이 즉시 실행한다.

### Batch 규칙

- NLU는 입력 발화에 등장한 순서로 Command를 반환한다.
- 같은 메뉴·온도·옵션 조합은 하나의 Command로 합치고 수량을 더한다.
- 같은 메뉴라도 온도 또는 옵션 조합이 다르면 별도 Command로 유지한다.
- Schema Validator와 Order Engine은 모든 Command를 실행 전에 검증한다.
- 하나라도 실패하면 어떤 Command도 실행하지 않고 기존 Cart를 유지한다.
- `ADD_ITEM`, `REMOVE_ITEM`, `UPDATE_QUANTITY`, `UPDATE_OPTION`은 최대 두 개까지 발화 순서대로 실행한다.
- `QUERY_CART`는 장바구니 변경 뒤 마지막 Command로만 허용한다.
- 순차 실행 중 하나라도 실패하면 전체 Batch를 취소하고 기존 Cart를 유지한다.
- 그 밖의 혼합 Intent 조합은 실행하지 않는다.

### 오류 출력

NLU 또는 검증 단계가 정상 Command 배열을 만들 수 없으면 빈 배열 대신 `OrderCommandError`를 반환한다.

```json
{
  "code": "MISSING_FIELD",
  "message": "아메리카노의 온도를 HOT 또는 ICED로 말씀해 주세요.",
  "command_index": 0,
  "field": "temperature",
  "candidates": ["hot", "iced"],
  "retryable": true
}
```

| Field | Type | 의미 |
|---|---|---|
| `code` | enum | 기계가 처리할 오류 코드 |
| `message` | string | 사용자에게 전달할 안전한 안내 문장 |
| `command_index` | integer 또는 null | 실패한 Command의 배열 위치 |
| `field` | string 또는 null | 실패하거나 누락된 필드 |
| `candidates` | string[] | 재입력 또는 P1 Clarification 후보 |
| `retryable` | boolean | 같은 세션에서 재시도 가능한지 여부 |

최소 오류 코드는 `INVALID_JSON`, `SCHEMA_ERROR`, `UNKNOWN_INTENT`, `MISSING_FIELD`, `MIXED_INTENT`, `AMBIGUOUS_TARGET`으로 한다. 정상 출력은 `OrderCommand[]`, 실패 출력은 `OrderCommandError`이며 빈 배열은 허용하지 않는다.

## AC (Given-When-Then)

### AC-01 · 단일 메뉴도 배열 반환

- GIVEN: 빈 Cart가 있다.
- WHEN: `아이스 아메리카노 두 잔 주세요`를 입력한다.
- THEN: 길이 1의 `OrderCommand[]`를 반환한다.

### AC-02 · 복수 메뉴 분해

- GIVEN: 빈 Cart가 있다.
- WHEN: `아이스 아메리카노 두 잔하고 따뜻한 카페라떼 한 잔 주세요`를 입력한다.
- THEN: 발화 순서대로 `americano`, `cafe_latte` Command를 반환한다.

### AC-03 · 사용하지 않는 필드

- GIVEN: 사용자가 현재 Cart 조회를 요청한다.
- WHEN: `QUERY_CART` Command를 생성한다.
- THEN: `target_item_id`, `category_id`, `quantity`, `temperature`, `query_tags`, `detail_fields`, `options`를 생략하지 않고 `null`로 반환한다.

### AC-04 · 동일 메뉴 병합

- GIVEN: 빈 Cart가 있다.
- WHEN: `아이스 아메리카노 한 잔하고 아이스 아메리카노 두 잔 주세요`를 입력한다.
- THEN: `americano`, `iced`, 수량 3인 Command 하나를 반환한다.

### AC-05 · 다른 온도 분리

- GIVEN: 빈 Cart가 있다.
- WHEN: `따뜻한 아메리카노 한 잔하고 아이스 아메리카노 한 잔 주세요`를 입력한다.
- THEN: 온도가 다른 Command 두 개를 반환한다.

### AC-06 · Batch 원자성

- GIVEN: 두 번째 Command가 존재하지 않는 메뉴를 참조한다.
- WHEN: Order Engine이 Batch를 검증한다.
- THEN: 첫 번째 Command도 실행하지 않고 기존 Cart를 유지한다.

### AC-07 · 안전한 혼합 Intent 순차 실행

- GIVEN: 한 발화에 추가와 삭제 요청이 함께 있다.
- WHEN: NLU가 발화를 처리한다.
- THEN: 최대 두 개의 장바구니 변경을 발화 순서대로 검증하고 모두 성공할 때만 Cart에 반영한다.
- AND: `QUERY_CART`가 있으면 마지막에 변경된 Cart를 안내한다.

### AC-08 · 추가 필드 거부

- GIVEN: Command에 정의되지 않은 `price` 필드가 있다.
- WHEN: Schema Validation을 수행한다.
- THEN: 전체 Batch를 거부하고 Cart를 변경하지 않는다.

### AC-09 · 카테고리 메뉴 조회

- GIVEN: `coffee` 카테고리가 있다.
- WHEN: `커피 종류가 뭐가 있어?`를 입력한다.
- THEN: `QUERY_MENU`, `category_id=coffee`인 Command를 반환한다.

### AC-10 · 수정 대상 모호성

- GIVEN: Cart에 HOT과 ICED 아메리카노가 모두 있다.
- WHEN: 온도 없이 아메리카노 수량 변경을 요청한다.
- THEN: `AMBIGUOUS_TARGET`을 반환하고 Cart를 변경하지 않는다.

### AC-11 · pending 수량·온도 보존

- GIVEN: `카페라떼`의 수량을 묻는 session pending이 있다.
- WHEN: `두 잔 주세요` 다음 `아이스로`를 입력한다.
- THEN: 기존 Cart 항목을 변경하지 않고 `cafe_latte`, `iced`, 수량 2를 `ADD_ITEM` 한다.

### AC-12 · 디카페인 범위 제외와 짧은 STT 안전성

- GIVEN: 디카페인 옵션은 현재 제품 범위 밖이다.
- WHEN: `디카페인` 또는 `디`·`디카` 같은 짧은 STT 결과를 입력한다.
- THEN: caffeine 옵션 명령이나 카드 결제 명령을 만들지 않고 Cart를 유지한다.

### AC-11 · P0 온도 누락

- GIVEN: HOT과 ICED를 선택해야 하는 아메리카노가 있다.
- WHEN: P0에서 `아메리카노 두 잔 주세요`를 입력한다.
- THEN: `MISSING_FIELD`를 반환하고 원래 Command를 저장하지 않은 채 온도를 포함한 재입력을 안내한다.

### AC-12 · Confirmation 책임

- GIVEN: Schema와 Business Validation을 통과한 Command Batch가 있다.
- WHEN: 확인 정책을 적용한다.
- THEN: NLU 출력이 아니라 Order Engine이 확인 필요 여부를 결정한다.
