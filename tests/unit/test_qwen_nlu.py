from adapters.nlu.qwen_nlu import QwenNLU
from domain.intents import Intent
from domain.models import BeverageOptions, Cart, CartItem, Temperature
from domain.order_command_error import OrderCommandErrorCode


def test_cart_payload_matches_training_contract() -> None:
    cart = Cart(
        items=[
            CartItem(
                menu_id="americano",
                quantity=2,
                temperature=Temperature.ICED,
                unit_price=2000,
                options=BeverageOptions(),
            )
        ]
    )

    assert QwenNLU.cart_payload(cart) == [
        {
            "menu_id": "americano",
            "quantity": 2,
            "temperature": "iced",
            "options": {
                "size": None,
                "extra_shots": None,
                "caffeine": None,
                "syrup_pumps": None,
                "ice_amount": None,
            },
        }
    ]


def test_parse_prediction_injects_runtime_request_id() -> None:
    result = QwenNLU.parse_prediction(
        '[{"intent":"ADD_ITEM","target_item_id":"americano","category_id":null,'
        '"quantity":2,"temperature":"iced","query_tags":null,'
        '"detail_fields":null,"options":null}]'
    )

    assert isinstance(result, list)
    assert result[0].intent is Intent.ADD_ITEM
    assert result[0].request_id


def test_parse_prediction_returns_invalid_json_error() -> None:
    result = QwenNLU.parse_prediction("not-json")

    assert not isinstance(result, list)
    assert result.code is OrderCommandErrorCode.INVALID_JSON
