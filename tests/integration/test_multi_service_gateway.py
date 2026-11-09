from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.server import SidecarGatewayConfig, build_server


class _SidecarHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._send({"ok": True, "warmed": True}) if self.path == "/health" else self._send({"ok": False}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self._send({"path": self.path, "body": self.rfile.read(length).decode("utf-8")})

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        return None


def _start(server: ThreadingHTTPServer) -> int:
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def _request(port: int, path: str, body: bytes | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method="POST" if body is not None else "GET")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request) as response:
        return response.status, json.loads(response.read())


def test_gateway_exposes_health_and_only_proxies_public_sidecar_paths() -> None:
    sidecar = ThreadingHTTPServer(("127.0.0.1", 0), _SidecarHandler)
    sidecar_port = _start(sidecar)
    base = f"http://127.0.0.1:{sidecar_port}"
    gateway = build_server(
        "127.0.0.1",
        0,
        sidecar_gateway=SidecarGatewayConfig(stt_url=f"{base}/transcribe", nlu_url=f"{base}/parse", tts_url=f"{base}/synthesize"),
    )
    gateway_port = _start(gateway)
    try:
        status, health = _request(gateway_port, "/health")
        assert status == 200
        assert health == {"status": "ready", "stt": "ready", "nlu": "ready", "tts": "ready", "warmed": True}

        for path, target, body in (
            ("/stt", "/transcribe", b"audio"),
            ("/nlu", "/parse", '{"text":"주문"}'.encode()),
            ("/tts", "/synthesize", '{"text":"안내"}'.encode()),
        ):
            status, payload = _request(gateway_port, path, body)
            assert status == 200
            assert payload == {"path": target, "body": body.decode()}
    finally:
        gateway.shutdown()
        sidecar.shutdown()
