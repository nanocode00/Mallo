(function (root, factory) {
  const exported = factory();
  if (typeof module === "object" && module.exports) module.exports = exported;
  else root.MalloMenuMetadata = exported;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const items = Object.freeze({
    americano: Object.freeze({ imagePath: "assets/menu/americano.png", accent: "coffee", name: "아메리카노", price: 4700, category: "coffee", temperature: "iced", temperatureOptions: Object.freeze(["hot", "iced"]) }),
    cafe_latte: Object.freeze({ imagePath: "assets/menu/cafe-latte.png", accent: "latte", name: "카페라떼", price: 5200, category: "coffee", temperature: "iced", temperatureOptions: Object.freeze(["hot", "iced"]) }),
    vanilla_latte: Object.freeze({ imagePath: "assets/menu/vanilla-latte.png", accent: "latte", name: "바닐라라떼", price: 3400, category: "coffee", temperature: "iced", temperatureOptions: Object.freeze(["hot", "iced"]) }),
    grapefruit_ade: Object.freeze({ imagePath: "assets/menu/grapefruit-ade.png", accent: "fruit", name: "자몽에이드", price: 3500, category: "non_coffee", temperature: "iced", temperatureOptions: Object.freeze(["iced"]) }),
    matcha_latte: Object.freeze({ imagePath: "assets/menu/matcha-latte.png", accent: "tea", name: "말차라떼", price: 3500, category: "non_coffee", temperature: "iced", temperatureOptions: Object.freeze(["hot", "iced"]) }),
    milk_tea: Object.freeze({ imagePath: "assets/menu/milk-tea.png", accent: "tea", name: "밀크티", price: 3500, category: "tea", temperature: "iced", temperatureOptions: Object.freeze(["hot", "iced"]) }),
    chamomile_tea: Object.freeze({ imagePath: "assets/menu/chamomile-tea.png", accent: "tea", name: "캐모마일티", price: 3700, category: "tea", temperature: "hot", temperatureOptions: Object.freeze(["hot", "iced"]) }),
    iced_tea: Object.freeze({ imagePath: "assets/menu/iced-tea.png", accent: "fruit", name: "아이스티", price: 4700, category: "tea", temperature: "iced", temperatureOptions: Object.freeze(["iced"]) }),
    croffle_icecream: Object.freeze({ imagePath: "assets/menu/croffle-icecream.png", accent: "dessert", name: "크로플 아이스크림", price: 5500, orderText: "크로플 아이스크림 한 개 주세요", category: "dessert" }),
    basque_cheesecake: Object.freeze({ imagePath: "assets/menu/basque-cheesecake.png", accent: "dessert", name: "바스크 치즈 케이크", price: 6500, orderText: "바스크 치즈 케이크 한 개 주세요", category: "dessert" }),
  });

  const categories = Object.freeze([
    Object.freeze({ id: "all", name: "전체" }),
    Object.freeze({ id: "coffee", name: "커피" }),
    Object.freeze({ id: "non_coffee", name: "논커피" }),
    Object.freeze({ id: "tea", name: "차" }),
    Object.freeze({ id: "dessert", name: "디저트" }),
  ]);

  function get(menuId) {
    return items[menuId] || Object.freeze({ imagePath: null, accent: "default" });
  }

  return { items, categories, get };
});
