from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from domain.models import Cart, OrderCommand
from domain.order_command_error import OrderCommandError, OrderCommandErrorCode
from interfaces.nlu import NLUFailure


logger = logging.getLogger(__name__)
_USER_SERVICE_ERROR = "음성 주문 서비스를 잠시 사용할 수 없습니다. 다시 시도해 주세요."


class HTTPClientNLU:
    """별도 Qwen NLU 프로세스를 호출하는 stdlib-only NLU 어댑터."""

    def __init__(
        self,
        url: str = "http://127.0.0.1:8002/parse",
        timeout: int = 120,
    ) -> None:
        self.url = url
        self.timeout = timeout

    @staticmethod
    def _cart_payload(cart: Cart) -> dict[str, Any]:
        return {
            "fulfillment_type": (
                cart.fulfillment_type.value
                if cart.fulfillment_type is not None
                else None
            ),
            "items": [
                {
                    "menu_id": item.menu_id,
                    "quantity": item.quantity,
                    "temperature": (
                        item.temperature.value
                        if item.temperature is not None
                        else None
                    ),
                    "options": item.options.to_dict(),
                }
                for item in cart.items
            ],
        }

    @staticmethod
    def _schema_failure(message: str) -> NLUFailure:
        return NLUFailure(
            OrderCommandError(
                code=OrderCommandErrorCode.SCHEMA_ERROR,
                message=message,
            )
        )

    @staticmethod
    def _error_from_payload(payload: Any) -> OrderCommandError:
        if not isinstance(payload, dict):
            raise HTTPClientNLU._schema_failure("NLU sidecar 오류 응답 형식이 올바르지 않습니다.")
        try:
            candidates = payload.get("candidates")
            return OrderCommandError(
                code=OrderCommandErrorCode(payload["code"]),
                message=str(payload["message"]),
                retryable=bool(payload.get("retryable", True)),
                command_index=payload.get("command_index"),
                field=payload.get("field"),
                candidates=(
                    tuple(str(value) for value in candidates)
                    if candidates is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPClientNLU._schema_failure(
                "NLU sidecar 오류 응답을 해석할 수 없습니다."
            ) from error

    def parse(
        self,
        text: str,
        current_order_state: Cart,
    ) -> list[OrderCommand] | OrderCommandError:
        body = json.dumps(
            {
                "text": text,
                "cart": self._cart_payload(current_order_state),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST")
        request.add_header("Content-Type", "application/json; charset=utf-8")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except Exception as error:  # noqa: BLE001
            logger.exception("NLU sidecar 호출 실패: %s", self.url)
            raise self._schema_failure(_USER_SERVICE_ERROR) from error

        if not isinstance(data, dict) or not data.get("ok", False):
            detail = (
                str(data.get("error", "NLU sidecar 오류"))
                if isinstance(data, dict)
                else "NLU sidecar 응답 형식 오류"
            )
            logger.error("NLU sidecar 비정상 응답: %s", detail)
            raise self._schema_failure(_USER_SERVICE_ERROR)

        semantic_error = data.get("error")
        if semantic_error is not None:
            return self._error_from_payload(semantic_error)

        payloads = data.get("commands")
        if not isinstance(payloads, list) or not payloads:
            logger.error("NLU sidecar가 주문 명령을 반환하지 않았습니다")
            raise self._schema_failure(_USER_SERVICE_ERROR)

        commands: list[OrderCommand] = []
        try:
            for payload in payloads:
                if not isinstance(payload, dict):
                    raise TypeError("command payload must be an object")
                semantic = dict(payload)
                semantic.pop("request_id", None)
                commands.append(OrderCommand.from_nlu_payload(semantic))
        except (KeyError, TypeError, ValueError) as error:
            logger.exception("NLU sidecar 주문 명령 형식 오류")
            raise self._schema_failure(_USER_SERVICE_ERROR) from error
        return commands
