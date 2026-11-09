#!/usr/bin/env python3
"""Qwen3-0.6B NLU resident HTTP sidecar for the Mallo desktop runtime."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = str(ROOT / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from adapters.nlu.qwen06b_nlu import Qwen06BNLU  # noqa: E402
from domain.models import (  # noqa: E402
    BeverageOptions,
    Cart,
    CartItem,
    FulfillmentType,
    Temperature,
)
from domain.order_command_error import OrderCommandError  # noqa: E402

logger = logging.getLogger("mallo.nlu")


def _cart_from_payload(payload: Any) -> Cart:
    if payload is None:
        return Cart()
    if not isinstance(payload, dict):
        raise ValueError("cart는 JSON object여야 합니다.")

    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        raise ValueError("cart.items는 JSON array여야 합니다.")

    items: list[CartItem] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ValueError("cart item은 JSON object여야 합니다.")
        raw_options = raw_item.get("options")
        options = (
            BeverageOptions()
            if raw_options is None
            else BeverageOptions.from_mapping(raw_options)
        )
        raw_temperature = raw_item.get("temperature")
        items.append(
            CartItem(
                menu_id=str(raw_item["menu_id"]),
                quantity=int(raw_item["quantity"]),
                temperature=(
                    Temperature(raw_temperature)
                    if raw_temperature is not None
                    else None
                ),
                unit_price=0,
                options=options,
            )
        )

    raw_fulfillment = payload.get("fulfillment_type")
    fulfillment = (
        FulfillmentType(raw_fulfillment)
        if raw_fulfillment is not None
        else None
    )
    return Cart(items=items, fulfillment_type=fulfillment)


def _semantic_command_payload(command) -> dict[str, Any]:
    payload = command.to_dict()
    payload.pop("request_id", None)
    return payload


def _command_log_payload(command) -> dict[str, Any]:
    """Return useful semantic output without request IDs or model internals."""
    return _semantic_command_payload(command)


class NLUSidecarApp:
    def __init__(self, nlu: Qwen06BNLU) -> None:
        self.nlu = nlu
        self.warmed = False
        self._inference_lock = threading.Lock()

    def parse(self, body: dict[str, Any]) -> dict[str, Any]:
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return {"ok": False, "error": "text는 비어 있지 않은 문자열이어야 합니다."}

        cart = _cart_from_payload(body.get("cart"))
        t0 = time.perf_counter()
        with self._inference_lock:
            result = self.nlu.parse(text, cart)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # RuleFirstNLU runs per browser session in the gateway; this resident
        # sidecar records only the Qwen portion of a request.
        source = "qwen"
        if isinstance(result, OrderCommandError):
            logger.info(
                "[NLU] input=%r source=%s error_code=%s latency_ms=%.1f",
                text, source, result.code.value, elapsed_ms,
            )
            return {"ok": True, "commands": None, "error": result.to_dict()}
        commands = [_command_log_payload(cmd) for cmd in result]
        logger.info(
            "[NLU] input=%r source=%s commands=%s latency_ms=%.1f",
            text, source, commands, elapsed_ms,
        )
        return {
            "ok": True,
            "commands": commands,
            "error": None,
        }

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "warmed": self.warmed,
            "model_path": str(self.nlu.merged_model_path),
            "load_latency_ms": round(self.nlu.load_latency_ms, 1),
        }

    def warmup(self) -> dict[str, Any]:
        started = time.perf_counter()
        self.parse({"text": "아메리카노 한 잔 주세요", "cart": {"items": []}})
        self.warmed = True
        return {"ok": True, "warmed": True, "warmup_ms": round((time.perf_counter() - started) * 1000, 1)}


class NLUHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "MalloNLUSidecar/0.1"

    @property
    def app(self) -> NLUSidecarApp:
        return self.server.nlu_app  # type: ignore[attr-defined]

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(self.app.health())
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/parse", "/warmup"}:
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("JSON object가 필요합니다.")
            payload = self.app.warmup() if self.path == "/warmup" else self.app.parse(body)
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError) as error:
            self._send_json({"ok": False, "error": str(error)}, status=400)
            return
        except Exception as error:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"NLU 추론 실패: {error}"}, status=500)
            return

        self._send_json(payload, status=200 if payload.get("ok") else 400)

    def log_message(self, *args) -> None:
        return None


def build_server(
    *,
    host: str,
    port: int,
    model_path: Path | str,
    prompt_lookup_num_tokens: int = 8,
    allow_download: bool = False,
) -> ThreadingHTTPServer:
    nlu = Qwen06BNLU(
        merged_model_path=model_path,
        prompt_lookup_num_tokens=prompt_lookup_num_tokens,
        allow_download=allow_download,
    )
    server = ThreadingHTTPServer((host, port), NLUHTTPRequestHandler)
    server.nlu_app = NLUSidecarApp(nlu)  # type: ignore[attr-defined]
    return server


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Mallo Qwen3-0.6B NLU sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--model", required=True, help="merged-bf16 model directory")
    parser.add_argument("--prompt-lookup-num-tokens", type=int, default=8)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()

    server = build_server(
        host=args.host,
        port=args.port,
        model_path=args.model,
        prompt_lookup_num_tokens=args.prompt_lookup_num_tokens,
        allow_download=args.allow_download,
    )
    print(
        f"Mallo NLU sidecar running at http://{args.host}:{args.port} "
        f"[model={args.model}]"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
