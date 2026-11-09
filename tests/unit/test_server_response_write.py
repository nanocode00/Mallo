from __future__ import annotations

import logging

from app.server import MalloHTTPRequestHandler


class _DisconnectedWriter:
    def write(self, body: bytes) -> int:
        raise BrokenPipeError("client closed")


def test_gateway_suppresses_client_disconnect_during_response_write(caplog) -> None:
    handler = object.__new__(MalloHTTPRequestHandler)
    handler.wfile = _DisconnectedWriter()
    handler.path = "/health"

    with caplog.at_level(logging.DEBUG, logger="app.server"):
        handler._write_body(b"{}")

    assert "client disconnected before response write" in caplog.text
