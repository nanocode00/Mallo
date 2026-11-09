from __future__ import annotations

from app.service import build_mock_service
from domain.models import FulfillmentType


def select_fulfillment() -> FulfillmentType:
    choices = {
        "1": FulfillmentType.DINE_IN,
        "매장": FulfillmentType.DINE_IN,
        "매장에서 먹기": FulfillmentType.DINE_IN,
        "2": FulfillmentType.TAKEOUT,
        "포장": FulfillmentType.TAKEOUT,
        "포장하기": FulfillmentType.TAKEOUT,
    }
    while True:
        answer = input(
            "매장에서 드시나요, 포장하시나요? [1: 매장 / 2: 포장]: "
        ).strip()
        if answer in choices:
            return choices[answer]
        print("1번 매장 또는 2번 포장을 선택해 주세요.")


def main() -> None:
    service = build_mock_service()
    cart = service.start_order(select_fulfillment())
    text = input("주문을 입력하세요: ").strip()
    result = service.handle_text(text, cart)

    fulfillment_label = {
        FulfillmentType.DINE_IN: "매장",
        FulfillmentType.TAKEOUT: "포장",
        None: "미선택",
    }[result.cart.fulfillment_type]
    print(f"이용 방식: {fulfillment_label}")
    print(result.response_text)
    if result.cart.items:
        for item in result.cart.items:
            temperature = item.temperature.value if item.temperature is not None else "없음"
            print(
                f"- {item.menu_id}: {item.quantity} / 온도: {temperature} "
                f"/ 금액: {item.total_price:,}원"
            )
        print(f"총액: {result.cart.total_price:,}원")
    else:
        print("- 장바구니가 비어 있습니다.")

    if result.error_code is not None:
        print(f"오류: {result.error_code.value}")


if __name__ == "__main__":
    main()
