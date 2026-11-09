"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { route } = require("../../web/ui-command-router.js");

const cases = [
  // SERVICE_MODE
  ["SERVICE_MODE", "매장에서 먹을게요", "SELECT_DINE_IN"],
  ["SERVICE_MODE", "여기서 먹을게요", "SELECT_DINE_IN"],
  ["SERVICE_MODE", "매장", "SELECT_DINE_IN"],
  ["SERVICE_MODE", "포장할게요", "SELECT_TAKEOUT"],
  ["SERVICE_MODE", "가져갈게요", "SELECT_TAKEOUT"],
  ["SERVICE_MODE", "테이크아웃", "SELECT_TAKEOUT"],
  ["SERVICE_MODE", "포장", "SELECT_TAKEOUT"],

  // ORDER
  ["ORDER", "주문 확인할게요", "OPEN_REVIEW"],
  ["ORDER", "주문 확인", "OPEN_REVIEW"],
  ["ORDER", "이제 주문할게요", "OPEN_REVIEW"],
  ["ORDER", "장바구니 확인", "OPEN_REVIEW"],

  // ORDER_REVIEW
  ["ORDER_REVIEW", "수정할게요", "EDIT_ORDER"],
  ["ORDER_REVIEW", "주문 수정할게요", "EDIT_ORDER"],
  ["ORDER_REVIEW", "결제할게요", "OPEN_PAYMENT"],
  ["ORDER_REVIEW", "주문할게요", "OPEN_PAYMENT"],
  ["ORDER_REVIEW", "결제하러 갈게요", "OPEN_PAYMENT"],

  // PAYMENT
  ["PAYMENT", "카드로 할게요", "PAY_CARD"],
  ["PAYMENT", "카드 결제", "PAY_CARD"],
  ["PAYMENT", "신용카드로 할게요", "PAY_CARD"],
  ["PAYMENT", "삼성페이로 할게요", "PAY_SAMSUNG"],
  ["PAYMENT", "카카오페이로 할게요", "PAY_KAKAO"],
  ["PAYMENT", "현금으로 할게요", "PAY_CASH"],

  // Global accessibility
  ["ORDER", "처음으로", "GO_HOME", "GLOBAL"],
  ["ORDER", "처음 화면으로", "GO_HOME", "GLOBAL"],
  ["ORDER", "직원 불러줘", "CALL_STAFF", "GLOBAL"],
  ["ORDER", "직원 호출", "CALL_STAFF", "GLOBAL"],
  ["ORDER", "다시 들려줘", "REPEAT", "GLOBAL"],
  ["ORDER", "다시 말해줘", "REPEAT", "GLOBAL"],
  ["ORDER", "천천히 말해줘", "SPEED_SLOW", "GLOBAL"],
  ["ORDER", "더 천천히 말해줘", "SPEED_VERY_SLOW", "GLOBAL"],
  ["ORDER", "원래 속도로 말해줘", "SPEED_NORMAL", "GLOBAL"],
  ["ORDER", "말하기 속도 바꿔줘", "CYCLE_SPEED", "GLOBAL"],

  // Category filters in ORDER
  ["ORDER", "커피 보여줘", "FILTER_COFFEE", "ORDER"],
  ["ORDER", "디저트 보여줘", "FILTER_DESSERT", "ORDER"],
  ["ORDER", "차 보여줘", "FILTER_TEA", "ORDER"],
  ["ORDER", "전체 메뉴 보여줘", "FILTER_ALL", "ORDER"],

  // HOME_CONFIRM modal scope
  ["HOME_CONFIRM", "계속 주문할게요", "CANCEL_HOME", "HOME_CONFIRM"],
  ["HOME_CONFIRM", "취소 안 할게요", "CANCEL_HOME", "HOME_CONFIRM"],
  ["HOME_CONFIRM", "주문 취소할게요", "CONFIRM_HOME", "HOME_CONFIRM"],
  ["HOME_CONFIRM", "처음으로 갈게요", "CONFIRM_HOME", "HOME_CONFIRM"],
  ["HOME_CONFIRM", "네 취소할게요", "CONFIRM_HOME", "HOME_CONFIRM"],

  // OPTION_CHANGE
  ["OPTION_CHANGE", "변경하지 않고 돌아갈게요", "CANCEL_OPTION", "OPTION_CHANGE"],
  ["OPTION_CHANGE", "취소", "CANCEL_OPTION", "OPTION_CHANGE"],
];

for (const [screen, utterance, action, expectedScreen] of cases) {
  test(`${screen}: "${utterance}" routes to ${action}`, () => {
    const result = route(screen, utterance);
    assert.ok(result, `Expected route for "${utterance}" on ${screen}`);
    assert.equal(result.action, action);
    if (expectedScreen) assert.equal(result.screen, expectedScreen);
  });
}

test("screen allow-list prevents executing commands on wrong screens", () => {
  assert.equal(route("ORDER", "포장할게요"), null);
  assert.equal(route("PAYMENT", "주문 확인할게요"), null);
  assert.equal(route("SERVICE_MODE", "카드로 할게요"), null);
  assert.equal(route("WELCOME", "결제할게요"), null);
  assert.equal(route("HOME_CONFIRM", "아메리카노"), null);
  assert.equal(route("HOME_CONFIRM", "결제할게요"), null);
});

test("menu and option utterances fall through to the order NLU", () => {
  assert.equal(route("ORDER", "아이스 아메리카노 두 잔 주세요"), null);
  assert.equal(route("ORDER", "샷 하나 추가해 주세요"), null);
  assert.equal(route("SERVICE_MODE", "아메리카노"), null);
  assert.equal(route("ORDER", "바닐라라떼 시럽 덜 달게"), null);
});
