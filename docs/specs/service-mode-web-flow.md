# Web 매장·포장 선택 Flow
>
> **SSOT 안내**: 초기 Web Flow PoC 스펙이며, 실제 음성 선택 및 화면 레이아웃(세로 가운데 정렬 대형 카드)은 [`docs/specs/order-fulfillment-selection.md`](order-fulfillment-selection.md) 및 [`docs/specs/senior-first-web-ui.md`](senior-first-web-ui.md)를 최종 기준으로 한다.

## Why

현재 Web은 `주문하기`를 누르면 매장·포장 선택 없이 바로 마이크를 시작한다. Domain에는 `FulfillmentType`과 `Cart.fulfillment_type`이 있지만 Web session과 주문 확인 화면에 연결되지 않아 결정된 시작 Flow와 불일치한다.

## Goal

- `WELCOME → SERVICE_MODE → LISTENING` 순서를 구현한다.
- 매장/포장 터치 선택을 server-side session Cart에 저장한다.
- `/api/state`, `/api/order`, `/api/audio`에서 선택값을 확인할 수 있게 한다.
- ORDER_CONFIRM에 사용자 언어의 이용 방식과 각 메뉴 수량을 표시한다.
- reset 시 선택값을 초기화하고 주문 실패·수정 중에는 유지한다.

Out of Scope: 음성 SERVICE_MODE 선택, VAD, 4초 timer 변경, TTS 종료 후 자동 Listening, clarification, 실제 payment, 옵션 전체 표시, production NLU.

## What

Happy Path:

1. 사용자가 WELCOME에서 `주문하기`를 누른다.
2. SERVICE_MODE에서 `[매장에서]` 또는 `[포장]`을 누른다. 실제 음성 선택을 지원하기 전에는 음성 affordance를 표시하지 않는다.
3. backend 저장 성공 후 LISTENING으로 이동한다.
4. 주문 결과에서 `매장에서` 또는 `포장 주문`과 메뉴별 `× 수량`을 확인한다.

Edge Case:

- 저장 실패 시 SERVICE_MODE에 머물고 이해 가능한 오류를 표시한다.
- WELCOME에는 메뉴 텍스트 입력을 두지 않고, fulfillment 저장 후 진입하는 LISTENING에서 텍스트 fallback을 제공한다.
- 실패 요청은 기존 session cart를 변경하지 않는다.
- OPTION_CHANGE와 주문 오류는 선택값을 유지한다.
- reset은 items와 fulfillment를 모두 초기화한다.

## How

- 기존 `MalloService.start_order()`로 선택된 빈 Cart를 생성한다.
- `POST /api/fulfillment`은 `{ "fulfillment_type": "dine_in" | "takeout" }`을 받는다.
- 모든 cart payload에 nullable `fulfillment_type`을 additive로 추가한다.
- Frontend `orderState`에 `fulfillmentType`을 두고 API cart와 동기화한다.
- 별도 `ServiceModeFlow`는 성공 응답에 저장된 fulfillment가 있을 때만 LISTENING을 허용한다.

## AC

- GIVEN WELCOME, WHEN 주문하기를 누르면, THEN SERVICE_MODE가 표시된다.
- GIVEN SERVICE_MODE, WHEN 매장을 선택하고 API 저장이 성공하면, THEN session cart는 `dine_in`이고 LISTENING으로 이동한다.
- GIVEN SERVICE_MODE, WHEN 포장을 선택하고 API 저장이 성공하면, THEN session cart는 `takeout`이고 LISTENING으로 이동한다.
- GIVEN API 저장 실패, WHEN 응답을 처리하면, THEN SERVICE_MODE와 기존 session cart가 유지된다.
- GIVEN fulfillment가 선택된 cart, WHEN 주문·수정·실패를 처리하면, THEN 선택값이 유지된다.
- GIVEN reset, WHEN state를 조회하면, THEN items는 비고 fulfillment_type은 null이다.
- GIVEN quantity=2 주문, WHEN ORDER_CONFIRM을 렌더링하면, THEN `× 2`를 표시한다.
- GIVEN 새 Web session, WHEN WELCOME을 표시하면, THEN SERVICE_MODE를 거치지 않는 메뉴 입력 control이 존재하지 않는다.
