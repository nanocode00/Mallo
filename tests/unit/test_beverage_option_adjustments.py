import pytest

from config.settings import load_menu
from adapters.nlu.mock_nlu import MockNLU
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.models import (
    BeverageSize,
    BeverageOptions,
    CaffeineOption,
    Cart,
    CartItem,
    ErrorCode,
    FulfillmentType,
    IceAmount,
    OrderCommand,
    Temperature,
)


@pytest.fixture
def agent() -> ConversationAgent:
    return ConversationAgent(load_menu())


def option_command(
    menu_id: str,
    options: BeverageOptions,
    *,
    temperature: Temperature | None = None,
) -> OrderCommand:
    return OrderCommand.create(
        Intent.UPDATE_OPTION,
        target_item_id=menu_id,
        temperature=temperature,
        options=options,
    )


def test_add_decaf_keeps_base_price(agent: ConversationAgent) -> None:
    command = OrderCommand.create(
        Intent.ADD_ITEM,
        target_item_id="americano",
        quantity=1,
        temperature=Temperature.ICED,
        options=BeverageOptions(caffeine=CaffeineOption.DECAF),
    )

    result = agent.execute([command], Cart())

    assert result.success is True
    assert result.cart.total_price == 4700
    assert result.cart.items[0].options == BeverageOptions(
        caffeine=CaffeineOption.DECAF
    )
    assert "디카페인" in result.response_text


def test_same_menu_and_temperature_with_different_options_stay_separate(
    agent: ConversationAgent,
) -> None:
    commands = [
        OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id="americano",
            quantity=1,
            temperature=Temperature.ICED,
        ),
        OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id="americano",
            quantity=1,
            temperature=Temperature.ICED,
            options=BeverageOptions(caffeine=CaffeineOption.DECAF),
        ),
    ]

    result = agent.execute(commands, Cart())

    assert len(result.cart.items) == 2
    assert result.cart.total_price == 9400
    assert result.cart.items[0].options == BeverageOptions()
    assert result.cart.items[1].options == BeverageOptions(
        caffeine=CaffeineOption.DECAF,
    )


def test_duplicate_option_combination_merges_quantity(agent: ConversationAgent) -> None:
    options = BeverageOptions(extra_shots=1)
    commands = [
        OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id="cafe_latte",
            quantity=1,
            temperature=Temperature.ICED,
            options=options,
        ),
        OrderCommand.create(
            Intent.ADD_ITEM,
            target_item_id="cafe_latte",
            quantity=2,
            temperature=Temperature.ICED,
            options=options,
        ),
    ]

    result = agent.execute(commands, Cart())

    assert result.cart.items == [
        CartItem(
            "cafe_latte",
                3,
                Temperature.ICED,
                5200,
                BeverageOptions(extra_shots=1),
        )
    ]


def test_update_shot_syrup_and_ice_accumulates_options(
    agent: ConversationAgent,
) -> None:
    cart = Cart([CartItem("cafe_latte", 1, Temperature.ICED, 5200)])

    shot = agent.execute(
        [option_command("cafe_latte", BeverageOptions(extra_shots=1))],
        cart,
    )
    syrup = agent.execute(
        [option_command("cafe_latte", BeverageOptions(syrup_pumps=1))],
        shot.cart,
    )
    ice = agent.execute(
        [option_command("cafe_latte", BeverageOptions(ice_amount=IceAmount.LESS))],
        syrup.cart,
    )

    assert ice.cart.items[0].options == BeverageOptions(
        extra_shots=1,
        syrup_pumps=1,
        ice_amount=IceAmount.LESS,
    )
    query = agent.execute([OrderCommand.create(Intent.QUERY_CART)], ice.cart)
    assert "추가 샷 1회" in query.response_text
    assert "시럽 1회" in query.response_text
    assert "얼음 적게" in query.response_text


@pytest.mark.parametrize(
    ("size", "expected_price"),
    [
        (BeverageSize.SMALL, 4200),
        (BeverageSize.MEDIUM, 4700),
        (BeverageSize.LARGE, 5200),
    ],
)
def test_size_price_uses_medium_base(
    agent: ConversationAgent,
    size: BeverageSize,
    expected_price: int,
) -> None:
    result = agent.execute(
        [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="americano",
                quantity=1,
                temperature=Temperature.ICED,
                options=BeverageOptions(size=size),
            )
        ],
        Cart(),
    )

    assert result.success is True
    assert result.cart.items[0].unit_price == expected_price


def test_omitted_size_defaults_to_medium(agent: ConversationAgent) -> None:
    result = agent.execute(
        [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="americano",
                quantity=1,
                temperature=Temperature.HOT,
            )
        ],
        Cart(),
    )

    # null은 계약상 기본 MEDIUM을 뜻하며 명시 Size와 중복 CartItem을 만들지 않는다.
    assert result.cart.items[0].options.size is None
    assert result.cart.items[0].unit_price == 4700


def test_dessert_rejects_size(agent: ConversationAgent) -> None:
    result = agent.execute(
        [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="basque_cheesecake",
                quantity=1,
                options=BeverageOptions(size=BeverageSize.LARGE),
            )
        ],
        Cart(),
    )

    assert result.error_code is ErrorCode.INVALID_OPTION
    assert result.cart.items == []


def test_hot_drink_rejects_ice_amount_and_keeps_cart(
    agent: ConversationAgent,
) -> None:
    cart = Cart([CartItem("americano", 1, Temperature.HOT, 4700)])

    result = agent.execute(
        [option_command("americano", BeverageOptions(ice_amount=IceAmount.LESS))],
        cart,
    )

    assert result.error_code is ErrorCode.INVALID_OPTION
    assert result.cart == cart


@pytest.mark.parametrize("menu_id", ["matcha_latte", "iced_tea", "grapefruit_ade"])
def test_non_espresso_menu_rejects_decaf(
    agent: ConversationAgent,
    menu_id: str,
) -> None:
    cart = Cart([CartItem(menu_id, 1, Temperature.ICED, 3500)])

    result = agent.execute(
        [
            option_command(
                menu_id,
                BeverageOptions(caffeine=CaffeineOption.DECAF),
            )
        ],
        cart,
    )

    assert result.error_code is ErrorCode.INVALID_OPTION
    assert result.cart == cart


def test_dessert_rejects_beverage_option(agent: ConversationAgent) -> None:
    cart = Cart([CartItem("basque_cheesecake", 1, None, 6500)])

    result = agent.execute(
        [option_command("basque_cheesecake", BeverageOptions(syrup_pumps=1))],
        cart,
    )

    assert result.error_code is ErrorCode.INVALID_OPTION
    assert result.cart == cart


def test_unspecified_drink_size_keeps_null_as_medium(agent: ConversationAgent) -> None:
    command = OrderCommand.create(
        Intent.ADD_ITEM,
        target_item_id="americano",
        quantity=1,
        temperature=Temperature.ICED,
    )

    result = agent.execute([command], Cart())

    assert result.cart.items[0].options.size is None
    assert result.cart.items[0].unit_price == 4700


@pytest.mark.parametrize(
    ("size", "expected_price"),
    [(BeverageSize.MEDIUM, 4700), (BeverageSize.LARGE, 5200)],
)
def test_size_increases_unit_price_by_five_hundred_per_step(
    agent: ConversationAgent,
    size: BeverageSize,
    expected_price: int,
) -> None:
    command = OrderCommand.create(
        Intent.ADD_ITEM,
        target_item_id="americano",
        quantity=1,
        temperature=Temperature.ICED,
        options=BeverageOptions(size=size),
    )

    result = agent.execute([command], Cart())

    assert result.cart.items[0].unit_price == expected_price
    assert result.cart.total_price == expected_price


def test_update_size_recalculates_price(agent: ConversationAgent) -> None:
    cart = Cart(
        [
            CartItem(
                "americano",
                2,
                Temperature.ICED,
                4700,
                BeverageOptions(size=BeverageSize.SMALL),
            )
        ]
    )

    result = agent.execute(
        [option_command("americano", BeverageOptions(size=BeverageSize.LARGE))],
        cart,
    )

    assert result.cart.items[0].options.size is BeverageSize.LARGE
    assert result.cart.items[0].unit_price == 5200
    assert result.cart.total_price == 10400


def test_dessert_rejects_size_and_keeps_cart(agent: ConversationAgent) -> None:
    cart = Cart([CartItem("basque_cheesecake", 1, None, 6500)])

    result = agent.execute(
        [option_command("basque_cheesecake", BeverageOptions(size=BeverageSize.LARGE))],
        cart,
    )

    assert result.error_code is ErrorCode.INVALID_OPTION
    assert result.cart == cart


def test_mock_nlu_outputs_default_and_requested_size() -> None:
    nlu = MockNLU()

    default = nlu.parse("아아 한 잔 주세요", Cart())
    medium = nlu.parse("아이스 아메리카노 미디엄 한 잔 주세요", Cart())
    changed = nlu.parse(
        "아메리카노를 라지로 바꿔줘",
        Cart(
            [
                CartItem(
                    "americano",
                    1,
                    Temperature.ICED,
                    4700,
                    BeverageOptions(size=BeverageSize.SMALL),
                )
            ]
        ),
    )

    assert isinstance(default, list)
    assert isinstance(medium, list)
    assert isinstance(changed, list)
    assert default[0].options is None
    assert medium[0].options == BeverageOptions(size=BeverageSize.MEDIUM)
    assert changed[0].options == BeverageOptions(size=BeverageSize.LARGE)


def test_option_update_rejects_ambiguous_same_menu_variants(
    agent: ConversationAgent,
) -> None:
    cart = Cart(
        [
            CartItem("americano", 1, Temperature.ICED, 4700),
            CartItem(
                "americano",
                1,
                Temperature.ICED,
                4700,
                BeverageOptions(caffeine=CaffeineOption.DECAF),
            ),
        ]
    )

    result = agent.execute(
        [option_command("americano", BeverageOptions(syrup_pumps=1))],
        cart,
    )

    assert result.error_code is ErrorCode.AMBIGUOUS_TARGET
    assert result.cart == cart


def test_confirm_and_undo_preserve_option_state(agent: ConversationAgent) -> None:
    original = Cart([CartItem("americano", 1, Temperature.ICED, 4700)], fulfillment_type=FulfillmentType.DINE_IN)
    changed = agent.execute(
        [
            option_command(
                "americano",
                BeverageOptions(caffeine=CaffeineOption.DECAF),
            )
        ],
        original,
    )

    confirmation = agent.execute(
        [OrderCommand.create(Intent.CONFIRM_ORDER)],
        changed.cart,
    )
    undone = agent.execute([OrderCommand.create(Intent.UNDO)], changed.cart)

    assert "디카페인" in confirmation.response_text
    assert confirmation.response_text.endswith("결제를 진행해 주세요.")
    assert undone.success is True
    assert undone.cart == original


def test_supported_shot_and_syrup_have_no_upper_limit(agent: ConversationAgent) -> None:
    assert BeverageOptions(extra_shots=4).extra_shots == 4
    assert BeverageOptions(syrup_pumps=12).syrup_pumps == 12
    result = agent.execute(
        [
            OrderCommand.create(
                Intent.ADD_ITEM,
                target_item_id="americano",
                quantity=1,
                temperature=Temperature.ICED,
                options=BeverageOptions(extra_shots=4, syrup_pumps=12),
            )
        ],
        Cart(),
    )
    assert result.success is True
    assert result.cart.items[0].options.extra_shots == 4
    assert result.cart.items[0].options.syrup_pumps == 12


def test_option_counts_reject_negative_values() -> None:
    with pytest.raises(ValueError):
        BeverageOptions(syrup_pumps=-1)
