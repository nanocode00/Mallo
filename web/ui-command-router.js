(function (root, factory) {
  const exported = factory();
  if (typeof module === "object" && module.exports) module.exports = exported;
  else root.MalloUICommandRouter = exported;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const exact = (values) => new Set(values.map(normalize));

  function normalize(text) {
    return String(text || "").trim().replace(/[.!?]/g, "").replace(/\s+/g, " ");
  }

  const globalCommands = [
    ["GO_HOME", exact(["처음으로", "처음으로 가줘", "처음 화면으로", "처음으로 돌아갈게요", "처음으로 가자", "처음", "주문 취소할게요"])],
    ["CALL_STAFF", exact(["직원 불러줘", "직원 호출", "직원 호출해줘", "직원 불러주세요", "직원", "도와주세요", "직원분"])],
    ["REPEAT", exact(["다시 들려줘", "다시 말해줘", "다시 듣기", "다시 한번 말해줘", "다시", "한 번 더 말해줘", "뭐라고 했어"])],
    ["SPEED_NORMAL", exact(["원래 속도로 말해줘", "기본 속도로 말해줘", "보통으로 말해줘", "기본으로 말해줘", "원래 속도", "기본 속도"])],
    ["SPEED_SLOW", exact(["천천히 말해줘", "천천히 해줘", "천천히", "조금 천천히 말해줘"])],
    ["SPEED_VERY_SLOW", exact(["더 천천히 말해줘", "더 천천히", "제일 천천히 말해줘", "아주 천천히 말해줘"])],
    ["CYCLE_SPEED", exact(["말하기 속도 바꿔줘", "속도 바꿔줘", "말하기 속도", "속도 변경"])],
  ];
  const screenCommands = {
    SERVICE_MODE: [
      ["SELECT_DINE_IN", exact(["매장에서", "매장에서 먹을게요", "여기서 먹을게요", "매장", "매장 이용", "먹고 갈게요", "먹고 갈래"])],
      ["SELECT_TAKEOUT", exact(["포장", "포장할게요", "포장해줘", "가져갈게요", "테이크아웃", "싸갈게요", "포장이요"])],
    ],
    ORDER: [
      ["OPEN_REVIEW", exact(["주문 확인할게요", "주문 확인", "이제 주문할게요", "메뉴 확인할게요", "주문 확인하기", "장바구니 확인", "장바구니 볼래요", "장바구니 보여줘", "장바구니 보기", "장바구니 볼게", "담은 거 확인할게요", "장바구니"])],
      ["FILTER_COFFEE", exact(["커피 보여줘", "커피 메뉴 보여줘", "커피 카테고리 보여줘"])],
      ["FILTER_NON_COFFEE", exact(["논커피 보여줘", "논커피 메뉴 보여줘", "논커피 카테고리 보여줘"])],
      ["FILTER_TEA", exact(["차 보여줘", "티 보여줘", "차 메뉴 보여줘", "티 메뉴 보여줘", "차 카테고리 보여줘"])],
      ["FILTER_DESSERT", exact(["디저트 보여줘", "디저트 메뉴 보여줘", "디저트 카테고리 보여줘"])],
      ["FILTER_ALL", exact(["전체 메뉴 보여줘", "전체 보여줘", "모든 메뉴 보여줘", "전체 메뉴"])],
    ],
    ORDER_REVIEW: [
      ["OPEN_PAYMENT", exact(["주문할게요", "결제할게요", "결제하러 갈게요", "결제", "결제하기", "돈 낼게요", "계산할게요", "이대로 할게요", "이대로 주문할게요"])],
      ["EDIT_ORDER", exact(["수정할게요", "주문 수정할게요", "수정", "메뉴 바꿀게요", "다시 고를게요", "메뉴 더 담을게요", "더 담을게요", "더 주문할게요"])],
    ],
    PAYMENT: [
      ["PAY_CARD", exact(["카드로 할게요", "카드 결제", "카드", "신용카드로 할게요", "체크카드로 할게요", "신용카드", "체크카드", "카드요"])],
      ["PAY_SAMSUNG", exact(["삼성페이로 할게요", "삼성페이", "삼성페이 결제", "삼성 페이"])],
      ["PAY_KAKAO", exact(["카카오페이로 할게요", "카카오페이", "카카오페이 결제", "카카오 페이"])],
      ["PAY_CASH", exact(["현금으로 할게요", "현금", "현금 결제", "현금이요"])],
    ],
    HOME_CONFIRM: [
      ["CANCEL_HOME", exact(["계속 주문할게요", "취소 안 할게요", "계속할게요", "아니오", "아니요", "계속 주문하기", "주문 계속할게요", "계속"])],
      ["CONFIRM_HOME", exact(["주문 취소할게요", "처음으로 갈게요", "네 취소할게요", "취소", "네", "주문 취소", "처음으로", "취소할게요", "처음으로 가줘", "예"])],
    ],
    OPTION_CHANGE: [
      ["CANCEL_OPTION", exact(["변경하지 않고 돌아갈게요", "돌아가기", "취소", "취소할게요", "변경 취소"])],
    ],
  };

  function route(screen, text) {
    const normalized = normalize(text);
    if (!normalized) return null;

    if (screen === "HOME_CONFIRM") {
      for (const [action, phrases] of screenCommands.HOME_CONFIRM || []) {
        if (phrases.has(normalized)) return { action, screen: "HOME_CONFIRM" };
      }
      return null;
    }

    for (const [action, phrases] of screenCommands[screen] || []) {
      if (phrases.has(normalized)) return { action, screen };
    }
    for (const [action, phrases] of globalCommands) {
      if (phrases.has(normalized)) return { action, screen: "GLOBAL" };
    }
    return null;
  }

  return { normalize, route, screenCommands, globalCommands };
});
