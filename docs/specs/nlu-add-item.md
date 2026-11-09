---
title: "N-01~N-06 — NLU OrderCommand Batch Contract"
tags: [spec]
---

# N-01~N-06 — NLU OrderCommand Batch Contract

> 현재 공통 계약은 `docs/specs/order-command.md`, 실제 실행 범위는
> `docs/specs/order-engine-operations.md`를 우선한다.

## Why

- **페르소나**: 공식 메뉴명을 사용해 음성으로 여러 카페 메뉴를 주문하는 고령 사용자
- **상황**: 한 발화에 여러 메뉴가 들어오고 수정·삭제 대상이 현재 Cart 문맥에 의존할 수 있다.
- **문제**:
  1. Command 하나가 여러 메뉴를 가지면 오류 위치와 실행 단위가 불명확해진다.
  2. 사용자 문장만으로는 `한 잔 더`, 수정·삭제 대상을 해석할 수 없다.
  3. 자유 형식 JSON과 임의 필드는 Order Engine이 안전하게 실행할 수 없다.
  4. NLU가 확인 정책을 결정하면 모델 출력에 따라 주문 안전 정책이 달라질 수 있다.
- **측정 지표**: Intent Accuracy, Slot Accuracy, Schema Valid Rate, Batch Accuracy

## Goal

- NLU 출력은 항상 `OrderCommand[]`다.
- Command 하나는 메뉴 하나만 대상으로 한다.
- `UNDO`를 포함한 Intent 12개를 동일한 공통 필드 구조로 표현한다.
- NLU 입력은 사용자 문장과 원본에서 분리한 현재 Cart 복사본이다.
- `quantity`는 증가량이 아니라 실행 후의 최종 수량이다.
- 여러 Command는 발화 순서를 유지하고 Batch 전체를 먼저 검증한다.
- Confirmation Policy는 NLU가 아니라 Order Engine이 결정한다.

## Decision Table

| 항목 | 결정할 내용 | 추천안 | 결론 |
|---|---|---|---|
| 출력 형태 | 단일·복수 메뉴 표현 | 항상 `OrderCommand[]` | 채택: 단일 메뉴도 길이 1 배열 사용 |
| Command 단위 | Command 하나의 대상 | 메뉴 하나 | 채택: Command당 `target_item_id` 하나 |
| Intent | 지원 명령 이름 | TRD 목록 유지 | 채택: 12개 Intent를 Enum·Schema에 등록 |
| 공통 필드 | 필드명 | 공통 필드 유지 | 채택: `request_id`, `intent`, `target_item_id`, `category_id`, `quantity`, `temperature`, `query_tags`, `detail_fields`, `options` |
| 필드 생략 | 사용하지 않는 값 | 필드는 유지하고 `null` 사용 | 채택: 정의된 9개 필드는 항상 존재 |
| 메뉴 대상 | `target_item_id` 의미 | Menu DB의 메뉴 ID | 채택 |
| 카테고리 대상 | `category_id` 의미 | Menu DB의 Category ID | 채택: 카테고리 조회에 사용 |
| 수량 | `quantity` 의미 | 최종 수량 | 채택: 기존 2잔에 1잔 추가 요청이면 `3` |
| 온도 | `temperature` 값 | `hot`, `iced`, `null` | 채택 |
| 복수 메뉴 | 배열 순서 | 발화 순서 유지 | 채택 |
| 중복 메뉴 | 같은 메뉴·온도 반복 | 수량 합산 | 채택: 첫 등장 위치 유지 |
| 다른 온도 | 같은 메뉴의 HOT·ICED | 별도 Command 유지 | 채택 |
| Batch 실패 | 일부 Command 오류 | 전체 실행 취소 | 채택: Cart 원자성 보장 |
| 혼합 Intent | 추가와 삭제 등이 섞인 발화 | 안전한 조합만 순차 실행 | 채택: Cart 변경 최대 2개, 마지막 `QUERY_CART` 허용, 전체 성공 시에만 반영 |
| 추가 필드 | 정의되지 않은 JSON 필드 | 허용하지 않음 | 채택: `additionalProperties=false` |
| 요청 ID | 중복 요청 식별 | 자동 생성 | 채택: Command마다 UUID v4 생성 |
| 확인 정책 | 사용자 확인 필요 여부 | Order Engine에서 결정 | 채택: Command 필드로 출력하지 않음 |
| 수정·삭제 대상 | 동일 메뉴의 온도별 항목 식별 | 메뉴 ID와 온도 사용 | 채택: 온도 생략으로 후보가 2개 이상이면 `AMBIGUOUS_TARGET` |
| 필수 온도 누락 | P0/P1 처리 경계 | P0 재입력, P1 Clarification | 채택 |

## Supported Intent

| Intent | 목적 | NLU Contract | 현재 실행 범위 |
|---|---|---|---|
| `ADD_ITEM` | 메뉴 추가·최종 수량 지정 | 지원 | 구현됨 |
| `REMOVE_ITEM` | 메뉴 삭제 요청 | 지원 | 메뉴 ID·온도로 대상을 식별해 삭제함 |
| `UPDATE_QUANTITY` | 최종 수량 변경 | 지원 | Cart Context를 기준으로 최종 수량을 변경함 |
| `UPDATE_OPTION` | 온도·샷·카페인·시럽·얼음 옵션 변경 | 지원 | 메뉴별 옵션 정책을 검증한 뒤 변경함 |
| `QUERY_MENU` | 메뉴·카테고리·조건·상세 조회 | 지원 | Menu DB의 ID·태그·상세 필드를 기준으로 조회함 |
| `QUERY_CART` | 현재 주문 조회 | 지원 | 품목·옵션·수량·총액을 안내함 |
| `CONFIRM_ORDER` | 최종 주문 확정 | 지원 | 빈 Cart를 거부하고 주문 요약·결제 금액을 안내함 |
| `CANCEL` | 전체 주문 취소 | 지원 | Cart와 주문 수령 방식을 초기화함 |
| `UNDO` | 마지막 장바구니 변경 취소 | 지원 | 구현됨 |
| `REQUEST_REPEAT` | 안내 반복 | 지원 | Orchestrator에서 직전 응답을 반복함 |
| `REQUEST_SLOWER` | 느린 TTS 요청 | 지원 | Orchestrator에서 Adaptive TTS Level을 올림 |
| `REQUEST_DEFAULT_SPEED` | 기본 TTS 속도 복원 | 지원 | Orchestrator에서 TTS Level 0으로 복원함 |

초기 범위는 **NLU 계약 완성(A안)**이었으며, 후속 작업에서 `UNDO`를 포함한 12개 Intent 실행으로 확장했다.

## What

### 복수 메뉴 예시

입력:

```text
아이스 아메리카노 두 잔이랑 따뜻한 카페라떼 한 잔 주세요
```

출력:

```json
[
  {
    "request_id": "자동 생성 UUID",
    "intent": "ADD_ITEM",
    "target_item_id": "americano",
    "category_id": null,
    "quantity": 2,
    "temperature": "iced",
    "query_tags": null,
    "detail_fields": null,
    "options": null
  },
  {
    "request_id": "자동 생성 UUID",
    "intent": "ADD_ITEM",
    "target_item_id": "cafe_latte",
    "category_id": null,
    "quantity": 1,
    "temperature": "hot",
    "query_tags": null,
    "detail_fields": null,
    "options": null
  }
]
```

### 현재 주문 상태와 최종 수량

- 현재 Cart: 아이스 아메리카노 2잔
- 사용자: `아이스 아메리카노 한 잔 더 주세요`
- NLU 출력: `quantity: 3`
- Order Engine: 기존 수량에 3을 더하지 않고 최종 수량을 3으로 교체

### 공통 필드

| Field | Type | 규칙 |
|---|---|---|
| `request_id` | UUID v4 string | NLU 어댑터가 Command마다 런타임에 자동 생성 |
| `intent` | enum | 지원 Intent 12개 중 하나 |
| `target_item_id` | string / `null` | Menu DB의 메뉴 ID |
| `category_id` | string / `null` | Menu DB의 Category ID, 카테고리 조회에 사용 |
| `quantity` | integer / `null` | 1 이상 최종 수량 |
| `temperature` | `hot` / `iced` / `null` | 디저트·미사용 Intent는 `null` 가능 |
| `query_tags` | string[] / `null` | 메뉴 조건 검색의 표준 태그 |
| `detail_fields` | string[] / `null` | 메뉴 상세 질문 항목 |
| `options` | object / `null` | Size·샷·카페인·시럽·얼음 옵션. 하위 값과 제약은 `docs/specs/order-command.md`를 따름 |

정의된 필드를 생략하지 않는다. 해당 Intent에서 사용하지 않는 필드는 `null`로 유지한다.

### Confirmation Policy

| 정책 결과 | Intent |
|---|---|
| 확인 필요 | `REMOVE_ITEM`, `CONFIRM_ORDER`, `CANCEL` |
| 즉시 처리 | 나머지 8개 Intent |

NLU는 확인 필요 여부를 판단하거나 Command에 출력하지 않는다. Order Engine이 Intent 기반 고정 정책을 별도로 적용한다. `REMOVE_ITEM`은 확인 요청을 Pending 상태로 보관하고 사용자가 확인한 뒤 실제 삭제하는 것으로 정의하며, Pending/Confirmation 실행 흐름은 별도 작업이다.

### 수정·삭제 대상 식별

- `target_item_id`와 `temperature`를 함께 사용한다.
- Cart에 같은 메뉴의 HOT과 ICE가 모두 있을 때 온도가 생략되면 임의 선택하지 않는다.
- 이 경우 `AMBIGUOUS_TARGET`을 반환한다.
- P0는 전체 문장을 다시 입력하도록 안내한다.
- P1에서만 후보를 제시하고 `CLARIFYING` 상태로 이동한다.

### 필수 온도 누락

- ADD_ITEM 음료에 온도가 없으면 `temperature=null`으로 즉시 추가한다.
- `null`은 온도를 임의로 HOT/ICE로 보정하지 않은 미지정 상태이며, 재질문을 만들지 않는다.
- Menu DB에 명시 default가 추가되기 전까지 runtime은 새 온도 default를 정의하지 않는다. 입력 정규화의 범위와 진단은 `docs/specs/nlu-runtime-normalization.md`를 따른다.

## How

### Python Contract

```python
@dataclass(frozen=True)
class OrderCommand:
    request_id: str
    intent: Intent
    target_item_id: str | None
    category_id: str | None
    quantity: int | None
    temperature: Temperature | None
    query_tags: tuple[str, ...] | None
    detail_fields: tuple[MenuDetailField, ...] | None
    options: BeverageOptions | None

class NLU(Protocol):
    def parse(self, text: str, current_order_state: Cart) -> list[OrderCommand]: ...
```

### Validation Pipeline

```text
text + Cart copy
  → NLU
  → OrderCommand[] Schema Validation
  → Mixed Intent Validation
  → Order Engine Confirmation Policy
  → Intent별 실행
```

- Schema: `schemas/order-command.schema.json`
- 모든 공통 필드는 required다.
- 배열은 1개 이상 10개 이하로 제한한다.
- 추가 JSON 필드는 허용하지 않는다.
- 일부 Command가 실패하면 ADD_ITEM Batch 전체를 실행하지 않는다.

## AC

### AC-01 · 항상 배열 출력

- GIVEN: 단일 또는 복수 메뉴 발화가 있다.
- WHEN: NLU가 분석한다.
- THEN: 항상 길이 1 이상의 `OrderCommand[]`를 반환한다.

### AC-02 · 12개 Intent

- GIVEN: TRD Intent 목록이 있다.
- WHEN: Enum과 Schema를 검사한다.
- THEN: 12개 Intent가 모두 유효하다.

### AC-03 · 최종 수량

- GIVEN: Cart에 아이스 아메리카노 2잔이 있다.
- WHEN: 사용자가 한 잔 더 요청한다.
- THEN: NLU는 `quantity: 3`을 반환하고 최종 Cart 수량은 3이다.

### AC-04 · 복수·중복·순서

- GIVEN: 한 발화에 여러 메뉴 또는 같은 메뉴·온도가 반복된다.
- WHEN: NLU가 Command 배열을 만든다.
- THEN: 발화 순서를 유지하고 같은 메뉴·온도는 수량을 합산한다.

### AC-05 · 다른 온도 분리

- GIVEN: 같은 메뉴의 HOT과 ICE가 함께 있다.
- WHEN: NLU가 분석한다.
- THEN: 서로 다른 Command로 유지한다.

### AC-06 · Batch 원자성

- GIVEN: 여러 ADD_ITEM Command 중 하나가 유효하지 않다.
- WHEN: Order Engine이 검증한다.
- THEN: 전체 Batch를 취소하고 기존 Cart를 유지한다.

### AC-07 · 안전한 혼합 Intent만 허용·추가 필드 거부

- GIVEN: 한 배열에 서로 다른 Intent가 있거나 정의되지 않은 필드가 있다.
- WHEN: 계약 검증을 실행한다.
- THEN: Cart 변경 Intent 최대 2개와 마지막 `QUERY_CART`로 구성된 안전한 조합만 허용하고, 나머지 혼합 조합과 추가 필드는 거부한다.

### AC-08 · Confirmation Policy

- GIVEN: 12개 Intent Command가 있다.
- WHEN: Order Engine 정책을 적용한다.
- THEN: 삭제·최종 확정·전체 취소에만 확인 필요 정책 결과가 `true`이며 `OrderCommand` 구조는 바뀌지 않는다.

### AC-09 · 카테고리 조회

- GIVEN: 사용자가 커피 카테고리를 조회한다.
- WHEN: NLU가 분석한다.
- THEN: `intent=QUERY_MENU`, `category_id=coffee`를 반환한다.

### AC-10 · 모호한 수정·삭제 대상

- GIVEN: 같은 메뉴의 HOT과 ICE가 Cart에 있고 온도가 생략됐다.
- WHEN: 수정·삭제 대상 해석을 시도한다.
- THEN: P0는 `AMBIGUOUS_TARGET`과 재입력을 반환하고 P1만 Clarification을 사용한다.
