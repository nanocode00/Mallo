---
title: "Order Engine / Menu DB 작업 로그 (`O-*`)"
tags: [worklog]
---

# Order Engine / Menu DB 작업 로그 (`O-*`)

Order Engine과 Menu DB 영역에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다.

## 2026-08-18

### O-03 QUERY_MENU 실제 실행

- `QUERY_MENU`를 단일 메뉴, 카테고리, 전체 메뉴 조회로 분기했다.
- Menu Catalog 순서를 유지하며 공식 메뉴명·가격을 안내하고 단일 메뉴 조회에는 지원 온도를 포함했다.
- 조회 실패와 잘못된 target/category 조합은 Cart를 변경하지 않고 거부하도록 했다.

## 2026-08-17

### O-07~O-11 Order Engine 주문 관리 Intent 확장 구현

- 결정론적 Order Engine(`ConversationAgent`)에 메뉴 삭제, 수량 변경, 옵션 변경, 장바구니 조회, 주문 확정, 전체 취소 기능을 확장 구현했다.
- **`REMOVE_ITEM` (O-07)**: 메뉴 ID 및 온도 기준으로 Cart 항목 삭제 및 총액 갱신
- **`UPDATE_QUANTITY` (O-08)**: 대상 항목 최종 수량 갱신 및 총액 재계산
- **`UPDATE_OPTION` (O-09)**: 메뉴 온도 유효성 검증 후 HOT ↔ ICE 변경 및 동일 온도 항목 합산
- **`QUERY_CART` (O-10)**: 현재 장바구니 품목 및 총 결제 금액 조회 문장 반환
- **`CONFIRM_ORDER` (O-11)**: 빈 카트 검증 및 최종 결제 안내
- **`CANCEL`**: 장바구니 전체 초기화
- 한글 종성(받침)에 따른 올바른 조사(`을/를`, `이/가`, `으로/로`) 자동 선택 로직 추가
- 스펙 문서 `docs/specs/order-engine-operations.md` 작성 및 단위 테스트 70개 통과를 확인했다.

## 2026-08-14

### ICE 전용 메뉴 정책 적용

- 자몽에이드와 아이스티의 온도 옵션을 `iced` 하나로 제한했다.
- 두 메뉴에 HOT이 입력되면 Order Engine이 `INVALID_OPTION`을 반환하고 Cart를 변경하지 않도록 검증했다.

