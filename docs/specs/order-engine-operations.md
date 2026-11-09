---
title: "O-07~O-11 — Order Engine Intent Execution & Cart Operations"
tags: [spec]
---

# O-07~O-11 — Order Engine Intent Execution & Cart Operations

> 이 문서는 말로(Mallo)의 결정론적 Order Engine(`ConversationAgent`)이 NLU로부터 수신한 `OrderCommand[]`의 각 Intent(메뉴 삭제, 수량 변경, 옵션 변경, 장바구니 조회, 주문 확정, 전체 취소)를 검증하고 Cart 상태를 변경하는 기준 계약이다.

## Why

- **페르소나**: 메뉴를 추가한 뒤 잘못 담긴 메뉴를 빼거나 수량·옵션을 변경하고 주문 내역을 확인하려는 고령 사용자
- **상황**:
  - "아메리카노 빼줘"(`REMOVE_ITEM`), "두 잔으로 바꿔줘"(`UPDATE_QUANTITY`), "따뜻한 걸로 바꿔줘"(`UPDATE_OPTION`), "뭐 담겼어?"(`QUERY_CART`), "주문할게요"(`CONFIRM_ORDER`), "다 취소해줘"(`CANCEL`) 등 다양한 주문 관리 발화를 수행한다.
- **문제**:
  - `ADD_ITEM`만 지원되면 사용자가 주문을 수정할 수 없어 키오스크를 처음부터 다시 시작해야 하는 불편이 발생한다.
  - LLM에게 Cart 변경을 직접 맡기면 수량 누락이나 계산 착오 등의 환각이 발생하므로, 결정론적 Order Engine이 단일 진실 공급원(SSOT)으로서 상태를 안전하게 검증·변경해야 한다.
- **측정 지표**:
  - Intent별 Cart 상태 전이 정확도 100%
  - 금액 계산 오차 0%
  - 유효하지 않은 변경 시 기존 Cart 보호율 100%

## Goal

- **해결 목표**:
  - `ConversationAgent.execute()`에서 다음 6가지 Intent를 결정론적으로 지원한다:
    1. **`REMOVE_ITEM` (`O-07`)**: 장바구니 항목 삭제
    2. **`UPDATE_QUANTITY` (`O-08`)**: 수량 변경 (최종 수량 갱신)
    3. **`UPDATE_OPTION` (`O-09`)**: 온도와 Size·샷·카페인·시럽·얼음 옵션 변경
    4. **`QUERY_CART` (`O-10`)**: 현재 장바구니 내역 및 총액 조회
    5. **`CONFIRM_ORDER` (`O-11`)**: 최종 주문 확정
    6. **`CANCEL`**: 전체 주문 취소 (장바구니 비우기)
- **성공 기준**:
  - 각 Intent별 Happy Path 및 Edge Case 단위 테스트 100% 통과.
  - Cart 상태 보호 및 정확한 한국어 안내 문장 생성.
- **Out of Scope**:
  - 실제 PG 결제 단말 통신

## What

### Happy Path (Intent별 동작 및 응답)

1. **`REMOVE_ITEM` (메뉴 삭제)**:
   - 입력: `target_item_id="americano"`, `temperature="iced"`
   - 동작: Cart에서 일치하는 항목 삭제.
   - 응답: `아이스 아메리카노를 장바구니에서 삭제했습니다.` (남은 총액 갱신)
2. **`UPDATE_QUANTITY` (수량 변경)**:
   - 입력: `target_item_id="americano"`, `quantity=2`
   - 동작: Cart 내 아메리카노의 수량을 2로 변경.
   - 응답: `아이스 아메리카노를 두 잔으로 변경했습니다.`
3. **`UPDATE_OPTION` (옵션 변경)**:
   - 입력: `target_item_id="americano"`, `temperature="hot"`
   - 동작: 기존 아이스 아메리카노의 온도를 HOT으로 변경.
   - 응답: `아메리카노를 따뜻한 음료로 변경했습니다.`
   - 추가 입력: `options={size, extra_shots, caffeine, syrup_pumps, ice_amount}`
   - 동작: Menu DB의 `option_policy`를 검증한 뒤 기존 CartItem의 옵션을 변경한다.
   - `extra_shots`와 `syrup_pumps`는 0 이상의 정수이며 횟수 상한으로 거부하지 않는다.
   - Size는 `SMALL`, `MEDIUM`, `LARGE`를 검증하고 생략값 `null`은 기본 MEDIUM 가격으로 계산한다.
4. **`QUERY_CART` (장바구니 조회)**:
   - 동작: 현재 Cart의 항목과 총액을 포맷팅하여 응답.
   - 응답: `현재 아이스 아메리카노 두 잔이 담겨 있으며, 총 9,400원입니다.`
5. **`CONFIRM_ORDER` (주문 확정)**:
   - 동작: Cart가 비어있지 않으면 총 결제 금액 안내.
   - 응답: `총 결제 금액은 9,400원입니다. 결제를 진행해 주세요.`
6. **`CANCEL` (전체 취소)**:
   - 동작: Cart를 빈 상태로 초기화.
   - 응답: `주문이 모두 취소되었습니다.`

### Edge Cases (최소 5개 + 처리 방식)

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 삭제(`REMOVE_ITEM`) 대상이 장바구니에 없는 경우 | `ErrorCode.MENU_NOT_FOUND` 반환 및 기존 Cart 유지 |
| EC-02 | 수량 변경(`UPDATE_QUANTITY`) 시 수량이 0 이하인 경우 | `ErrorCode.INVALID_QUANTITY` 반환 및 기존 Cart 유지 |
| EC-03 | 옵션 변경(`UPDATE_OPTION`) 시 미지원 온도(예: 자몽에이드에 HOT) 요청 | `ErrorCode.INVALID_OPTION` 반환 및 기존 Cart 유지 |
| EC-04 | 장바구니가 비어있는데 `CONFIRM_ORDER` 요청 | `ErrorCode.INVALID_COMMAND` ("장바구니가 비어 있어 주문을 확정할 수 없습니다.") |
| EC-05 | 장바구니가 비어있는데 `QUERY_CART` 요청 | 성공 반환 ("장바구니가 비어 있습니다.") |
| EC-06 | 메뉴가 지원하지 않는 샷·디카페인·시럽 요청 | `ErrorCode.INVALID_OPTION` 반환 및 기존 Cart 유지 |
| EC-07 | HOT 음료의 얼음 양 변경 | `ErrorCode.INVALID_OPTION` 반환 및 기존 Cart 유지 |
| EC-08 | Size 미지원 메뉴에 SMALL/MEDIUM/LARGE 요청 | `INVALID_OPTION`, Cart 유지 |

## How

### `ConversationAgent` (`src/domain/conversation.py`) 확장

```python
class ConversationAgent:
    def execute(self, commands: list[OrderCommand], cart: Cart) -> OrderResult:
        # Batch 단일 Intent 검증 및 분기
        intent = commands[0].intent
        if intent == Intent.ADD_ITEM:
            return self._execute_add_item(commands, cart)
        elif intent == Intent.REMOVE_ITEM:
            return self._execute_remove_item(commands, cart)
        elif intent == Intent.UPDATE_QUANTITY:
            return self._execute_update_quantity(commands, cart)
        elif intent == Intent.UPDATE_OPTION:
            return self._execute_update_option(commands, cart)
        elif intent == Intent.QUERY_CART:
            return self._execute_query_cart(cart)
        elif intent == Intent.CONFIRM_ORDER:
            return self._execute_confirm_order(cart)
        elif intent == Intent.CANCEL:
            return self._execute_cancel()
        else:
            return self._failure(cart, ErrorCode.UNSUPPORTED_UTTERANCE, "지원되지 않는 요청입니다.")
```

## AC (Given-When-Then)

### AC-01 · REMOVE_ITEM 장바구니 항목 삭제
- **GIVEN**: 장바구니에 아이스 아메리카노 2잔이 있을 때
- **WHEN**: `REMOVE_ITEM` (target_item_id="americano", temperature=ICED)을 실행한다
- **THEN**: 장바구니가 비워지고 삭제 안내 문구가 반환된다.

### AC-02 · UPDATE_QUANTITY 수량 갱신
- **GIVEN**: 장바구니에 아이스 아메리카노 1잔이 있을 때
- **WHEN**: `UPDATE_QUANTITY` (target_item_id="americano", quantity=3)을 실행한다
- **THEN**: 수량이 3잔으로 갱신되고 총액이 14,100원으로 계산된다.

### AC-03 · UPDATE_OPTION 온도 변경
- **GIVEN**: 장바구니에 아이스 아메리카노 1잔이 있을 때
- **WHEN**: `UPDATE_OPTION` (target_item_id="americano", temperature=HOT)을 실행한다
- **THEN**: 항목 온도가 HOT으로 변경된다.

### AC-04 · QUERY_CART 장바구니 및 총액 안내
- **GIVEN**: 장바구니에 아이스 아메리카노 2잔(9,400원)이 있을 때
- **WHEN**: `QUERY_CART`를 실행한다
- **THEN**: `현재 아이스 아메리카노 두 잔이 담겨 있으며, 총 9,400원입니다.`가 반환된다.

### AC-05 · CANCEL 전체 취소
- **GIVEN**: 장바구니에 메뉴들이 담겨 있을 때
- **WHEN**: `CANCEL`을 실행한다
- **THEN**: 장바구니가 완전히 초기화되고 취소 안내가 반환된다.
