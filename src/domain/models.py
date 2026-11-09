from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Iterable
from typing import Any, Mapping
from uuid import uuid4

from domain.intents import Intent
from domain.order_command_error import (
    OrderCommandError,
    OrderCommandErrorCode,
)
from domain.stt_result import STTResult
from domain.korean_normalizer import (
    native_number_to_korean,
    normalize_korean_text_for_tts,
    sino_number_to_korean,
)
from domain.text_transformer import (
    AdaptiveTextTransformer,
    transform_text_by_level,
)
from domain.tts_controller import AdaptiveTTSController
from domain.tts_result import TTSLevel, TTSResult



from domain.errors import (
    ErrorCode,
    ErrorModule,
    ErrorResponse,
    create_error_response,
    get_default_error_response,
)


class Temperature(str, Enum):
    HOT = "hot"
    ICED = "iced"


class FulfillmentType(str, Enum):
    DINE_IN = "dine_in"
    TAKEOUT = "takeout"


class CaffeineOption(str, Enum):
    REGULAR = "regular"
    DECAF = "decaf"


class IceAmount(str, Enum):
    NONE = "none"
    LESS = "less"
    NORMAL = "normal"
    MORE = "more"


class BeverageSize(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass(frozen=True)
class BeverageOptions:
    size: BeverageSize | None = None
    extra_shots: int | None = None
    caffeine: CaffeineOption | None = None
    syrup_pumps: int | None = None
    ice_amount: IceAmount | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("extra_shots", self.extra_shots),
            ("syrup_pumps", self.syrup_pumps),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or null")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> BeverageOptions:
        expected_fields = {
            "size",
            "extra_shots",
            "caffeine",
            "syrup_pumps",
            "ice_amount",
        }
        if set(payload) != expected_fields:
            raise ValueError("options must contain exactly the five option fields")
        return cls(
            size=(BeverageSize(payload["size"]) if payload["size"] is not None else None),
            extra_shots=payload["extra_shots"],
            caffeine=(
                CaffeineOption(payload["caffeine"])
                if payload["caffeine"] is not None
                else None
            ),
            syrup_pumps=payload["syrup_pumps"],
            ice_amount=(
                IceAmount(payload["ice_amount"])
                if payload["ice_amount"] is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size.value if self.size is not None else None,
            "extra_shots": self.extra_shots,
            "caffeine": self.caffeine.value if self.caffeine is not None else None,
            "syrup_pumps": self.syrup_pumps,
            "ice_amount": self.ice_amount.value if self.ice_amount is not None else None,
        }

    @property
    def is_empty(self) -> bool:
        return all(value is None for value in self.to_dict().values())

    def normalized(self) -> BeverageOptions:
        return BeverageOptions(
            size=self.size,
            extra_shots=self.extra_shots or None,
            caffeine=(
                None if self.caffeine is CaffeineOption.REGULAR else self.caffeine
            ),
            syrup_pumps=self.syrup_pumps or None,
            ice_amount=(
                None if self.ice_amount is IceAmount.NORMAL else self.ice_amount
            ),
        )


class MenuDetailField(str, Enum):
    DESCRIPTION = "description"
    PRICE = "price"
    SWEETNESS = "sweetness"
    CAFFEINE = "caffeine"
    MILK = "milk"
    TEMPERATURE = "temperature"


@dataclass(frozen=True)
class OrderCommand:
    request_id: str
    intent: Intent
    target_item_id: str | None
    category_id: str | None
    quantity: int | None
    temperature: Temperature | None
    query_tags: tuple[str, ...] | None
    detail_fields: tuple[MenuDetailField, ...] | None
    options: BeverageOptions | None = None
    fulfillment_type: FulfillmentType | None = None

    @classmethod
    def create(
        cls,
        intent: Intent,
        target_item_id: str | None = None,
        category_id: str | None = None,
        quantity: int | None = None,
        temperature: Temperature | None = None,
        query_tags: Iterable[str] | None = None,
        detail_fields: Iterable[MenuDetailField | str] | None = None,
        options: BeverageOptions | Mapping[str, Any] | None = None,
        fulfillment_type: FulfillmentType | str | None = None,
    ) -> OrderCommand:
        return cls(
            request_id=str(uuid4()),
            intent=intent,
            target_item_id=target_item_id,
            category_id=category_id,
            quantity=quantity,
            temperature=temperature,
            query_tags=tuple(query_tags) if query_tags is not None else None,
            detail_fields=(
                tuple(MenuDetailField(field) for field in detail_fields)
                if detail_fields is not None
                else None
            ),
            options=(
                options
                if isinstance(options, BeverageOptions) or options is None
                else BeverageOptions.from_mapping(options)
            ),
            fulfillment_type=(FulfillmentType(fulfillment_type) if fulfillment_type is not None else None),
        )

    @classmethod
    def from_nlu_payload(cls, payload: Mapping[str, Any]) -> OrderCommand:
        """LLM 의미 필드에 런타임 ``request_id``를 주입합니다."""
        expected_fields = {
            "intent",
            "target_item_id",
            "category_id",
            "quantity",
            "temperature",
            "query_tags",
            "detail_fields",
            "options",
        }
        # Existing trained labels omit the additive fulfillment field.
        if set(payload) not in (expected_fields, expected_fields | {"fulfillment_type"}):
            raise ValueError("NLU payload fields are invalid")

        intent = Intent(payload["intent"])
        raw_temperature = payload["temperature"]
        temperature = (
            Temperature(raw_temperature) if raw_temperature is not None else None
        )
        return cls.create(
            intent=intent,
            target_item_id=payload["target_item_id"],
            category_id=payload["category_id"],
            quantity=payload["quantity"],
            temperature=temperature,
            query_tags=payload["query_tags"],
            detail_fields=payload["detail_fields"],
            options=payload["options"],
            fulfillment_type=payload.get("fulfillment_type"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "intent": self.intent.value,
            "target_item_id": self.target_item_id,
            "category_id": self.category_id,
            "quantity": self.quantity,
            "temperature": self.temperature.value if self.temperature is not None else None,
            "query_tags": list(self.query_tags) if self.query_tags is not None else None,
            "detail_fields": (
                [field.value for field in self.detail_fields]
                if self.detail_fields is not None
                else None
            ),
            "options": self.options.to_dict() if self.options is not None else None,
            "fulfillment_type": self.fulfillment_type.value if self.fulfillment_type is not None else None,
        }


@dataclass(frozen=True)
class CartItem:
    menu_id: str
    quantity: int
    temperature: Temperature | None
    unit_price: int
    options: BeverageOptions = field(default_factory=BeverageOptions)

    @property
    def total_price(self) -> int:
        return self.quantity * self.unit_price


@dataclass
class Cart:
    items: list[CartItem] = field(default_factory=list)
    fulfillment_type: FulfillmentType | None = None
    confirmed: bool = False

    def copy(self) -> Cart:
        return Cart(
            items=list(self.items),
            fulfillment_type=self.fulfillment_type,
            confirmed=self.confirmed,
        )

    @property
    def total_price(self) -> int:
        return sum(item.total_price for item in self.items)


@dataclass(frozen=True)
class MenuOptionPolicy:
    size_supported: bool = False
    shot_supported: bool = False
    decaf_available: bool = False
    syrup_supported: bool = False
    ice_amount_available: bool = False


@dataclass(frozen=True)
class MenuItem:
    id: str
    category_id: str
    name: str
    description: str
    base_price: int
    unit: str
    temperature_options: tuple[Temperature, ...]
    price_source_brand: str
    price_source_menu_name: str
    price_source_url: str
    price_checked_at: str
    tags: tuple[str, ...] = ()
    option_policy: MenuOptionPolicy = field(default_factory=MenuOptionPolicy)


@dataclass(frozen=True)
class MenuTagDefinition:
    id: str
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class MenuAliasDefinition:
    alias: str
    target_item_id: str
    temperature: Temperature | None


@dataclass(frozen=True)
class OrderResult:
    success: bool
    cart: Cart
    response_text: str
    error_code: ErrorCode | None = None
    error_response: ErrorResponse | None = None
    # Internal execution trace for debug JSONL. The UI/API uses response_text.
    debug_response_text: str | None = None

    @classmethod
    def failure(
        cls,
        error_response: ErrorResponse,
        cart: Cart | None = None,
        response_text: str | None = None,
    ) -> OrderResult:
        """ErrorResponse로부터 실패 OrderResult를 생성합니다."""
        return cls(
            success=False,
            cart=cart if cart is not None else Cart(),
            response_text=response_text if response_text is not None else error_response.user_message,
            error_code=error_response.error_code,
            error_response=error_response,
        )


from domain.session_state import SessionState, SessionStatus
