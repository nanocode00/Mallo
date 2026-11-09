#!/usr/bin/env python3
"""MeloTTS production sidecar. It binds only to the loopback interface."""

from __future__ import annotations

import argparse
import json
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

from adapters.tts.melotts_adapter import MeloTTSAdapter  # noqa: E402


class TTSSidecarApp:
    def __init__(self, tts: MeloTTSAdapter) -> None:
        self.tts = tts
        self.warmed = False
        self._inference_lock = threading.Lock()

    def warmup(self) -> dict[str, Any]:
        started = time.perf_counter()
        with self._inference_lock:
            self.tts.synthesize("준비되었습니다.", 0)
        self.warmed = True
        return {"ok": True, "warmed": True, "warmup_ms": round((time.perf_counter() - started) * 1000, 1)}

    def synthesize(self, body: dict[str, Any]) -> dict[str, Any]:
        text = body.get("text")
        level = body.get("level", 0)
        if not isinstance(text, str):
            return {"ok": False, "error": "text는 문자열이어야 합니다."}
        if not isinstance(level, int):
            return {"ok": False, "error": "level은 정수여야 합니다."}
        with self._inference_lock:
            result = self.tts.synthesize(text, level)
        return {"ok": True, **result.to_dict()}


class TTSHTTPRequestHandler(BaseHTTPRequestHandler):
    @property
    def app(self) -> TTSSidecarApp:
        return self.server.tts_app  # type: ignore[attr-defined]

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json({"ok": True, "status": "ready", "warmed": self.app.warmed})
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/synthesize", "/warmup"}:
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(length) if length else b"{}")
            if not isinstance(body, dict):
                raise ValueError("JSON object가 필요합니다.")
            payload = self.app.warmup() if self.path == "/warmup" else self.app.synthesize(body)
            self._send_json(payload, status=200 if payload["ok"] else 400)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            self._send_json({"ok": False, "error": str(error)}, status=400)
        except Exception as error:  # noqa: BLE001
            self._send_json({"ok": False, "error": f"TTS 합성 실패: {error}"}, status=500)

    def log_message(self, *args) -> None:
        return None


def build_server(*, host: str, port: int, checkpoint: Path | str, config: Path | str, speaker: str, device: str) -> ThreadingHTTPServer:
    app = TTSSidecarApp(MeloTTSAdapter(device=device, ckpt_path=checkpoint, config_path=config, speaker=speaker))
    server = ThreadingHTTPServer((host, port), TTSHTTPRequestHandler)
    server.tts_app = app  # type: ignore[attr-defined]
    return server


def main() -> None:
    default_ckpt = str(ROOT / "models" / "tts" / "mallo-friendly" / "G_2800.pth")
    default_config = str(ROOT / "models" / "tts" / "mallo-friendly" / "config.json")

    parser = argparse.ArgumentParser(description="Mallo MeloTTS sidecar")

    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--checkpoint", default=default_ckpt, help="Path to fine-tuned TTS checkpoint (default: models/tts/mallo-friendly/G_2800.pth)")
    parser.add_argument("--config", default=default_config, help="Path to TTS config.json (default: models/tts/mallo-friendly/config.json)")
    parser.add_argument("--speaker", default="10")
    parser.add_argument("--device", default="cuda")

    args = parser.parse_args()
    server = build_server(host=args.host, port=args.port, checkpoint=args.checkpoint, config=args.config, speaker=args.speaker, device=args.device)
    print(f"Mallo TTS sidecar running at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
