# 음성 원샷 주문 결제 진입

## Why

- **페르소나**: 화면 전환과 추가 질문이 부담스러운 고령 음성 주문 사용자
- **상황**: 빈 장바구니에서 메뉴·수량·온도·이용 방식을 한 발화로 모두 말한다.
- **문제**: 이미 충분한 정보를 제공해도 메뉴 추가 뒤 별도 확정 단계를 거쳐야 한다.
- **측정 지표**: 완결 원샷 발화의 PAYMENT 화면 진입률 100% (명시한 제한 내).

## Goal

- 빈 Cart의 완결 음성 주문은 기존 `SET_FULFILLMENT`, `ADD_ITEM`, `CONFIRM_ORDER` 조합으로 원자 실행하고 PAYMENT 화면까지 이동한다.
- **Out of Scope**: 실제 결제 완료, 결제수단 선택 변경, 새 intent/schema, 기존 Cart 자동 결제 진입, 누락값 추론.

## What

**Happy Path**

1. 빈 Cart에서 메뉴·수량·필수 온도·매장/포장이 모두 있는 음성 발화를 해석한다.
2. 서버가 fulfillment 설정, 메뉴 추가, 주문 확정을 순서대로 성공시킨다.
3. 브라우저는 확정된 응답만 PAYMENT로 이동하고 기존 결제수단 선택을 유지한다.

**Edge Cases**

| 상황 | 처리 방식 |
|---|---|
| 수량 또는 2온도 메뉴의 온도 누락 | 기존 pending clarification, PAYMENT 이동 없음 |
| 기존 Cart 존재 | 메뉴만 추가, 이용 방식 변경·자동 확정·PAYMENT 이동 없음 |
| 수량 validator 실패 | 기존 Cart를 유지하고 PAYMENT 이동 없음 |
| 배치 중 하나 실패 | 원자적으로 실패하고 PAYMENT 이동 없음 |

## How

- Rule-first NLU는 빈 Cart의 완결 발화에만 `[SET_FULFILLMENT, ADD_ITEM, CONFIRM_ORDER]`를 생성한다.
- Order Engine은 위 정확한 3-command 순서만 순차 원자 배치로 허용한다.
- 프런트는 서버 `order_commands`와 `cart.confirmed`만으로 PAYMENT 이동을 결정하며 원문/STT 문자열을 해석하지 않는다.

## AC

- GIVEN 빈 Cart, WHEN `아이스 아메리카노 하나 포장하고 싶어`를 음성 해석하면, THEN takeout·iced americano 1잔·confirmed=true이며 PAYMENT로 이동한다.
- GIVEN 빈 Cart, WHEN `따뜻한 카페라떼 두 잔 매장에서 먹을게요`를 음성 해석하면, THEN dine_in·hot cafe_latte 2잔·confirmed=true이며 PAYMENT로 이동한다.
- GIVEN 온도 또는 수량이 누락된 발화, WHEN 음성 해석하면, THEN 기존 pending clarification을 유지하고 PAYMENT로 이동하지 않는다.
- GIVEN 기존 Cart, WHEN 완결 발화를 음성 해석하면, THEN 기존 항목을 보존하고 메뉴만 추가하며 PAYMENT로 이동하지 않는다.
- GIVEN 원샷 배치의 command 하나가 실패하면, WHEN 응답을 처리하면, THEN PAYMENT로 이동하지 않는다.
