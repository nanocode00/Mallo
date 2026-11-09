# -*- coding: utf-8 -*-
"""STT 사이드카 서버 — production STT runtime 전용 프로세스.

WhisperMediumSTT(Train65 merged BF16, GPU BF16)를 로드하고 HTTP로 전사만 제공한다.
Gateway/TTS와 같은 canonical runtime 환경에서 별도 프로세스로 실행한다.

실행:
    .venvs/runtime/bin/python -m sidecars.stt_server
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = str(ROOT / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

logger = logging.getLogger("mallo.stt")

from adapters.stt.whisper_medium import WhisperMediumSTT  # noqa: E402

_stt: WhisperMediumSTT | None = None
_configured_model_path: Path | None = None


def get_stt() -> WhisperMediumSTT:
    global _stt
    if _stt is None:
        t0 = time.perf_counter()
        _stt = WhisperMediumSTT(model_path=_configured_model_path)
        print(f"[sidecar] STT 모델 로딩 완료 {time.perf_counter() - t0:.1f}s", flush=True)
    return _stt



def _warmup_audio() -> bytes:
    """Return one second of in-memory, valid 16 kHz mono silence."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\0\0" * 16_000)
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            body = json.dumps({"ok": True, "warmed": self.server.warmed}).encode("utf-8")  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/warmup":
            started = time.perf_counter()
            try:
                with self.server.inference_lock:  # type: ignore[attr-defined]
                    get_stt().transcribe(_warmup_audio(), language="ko")
                self.server.warmed = True  # type: ignore[attr-defined]
                body = json.dumps(
                    {"ok": True, "warmed": True, "warmup_ms": round((time.perf_counter() - started) * 1000, 1)}
                ).encode("utf-8")
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/transcribe":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        audio = self.rfile.read(length) if length else b""
        language = self.headers.get("X-Language", "ko")
        t0 = time.perf_counter()
        try:
            with self.server.inference_lock:  # type: ignore[attr-defined]
                result = get_stt().transcribe(audio, language=language)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "[STT] success transcript=%r latency_ms=%.1f",
                result.text, elapsed_ms,
            )
            body = json.dumps(
                {"ok": True, "text": result.text, "duration_ms": result.duration_ms},
                ensure_ascii=False,
            ).encode("utf-8")
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.warning(
                "[STT] failure latency_ms=%.1f error_type=%s",
                elapsed_ms, type(exc).__name__,
            )
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode(
                "utf-8"
            )
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence default logging
        return None


def main(argv: list[str] | None = None) -> None:
    global _configured_model_path
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Mallo Train65 STT sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help="Custom Whisper merged model path (default: models/stt/final-train65-merged-bf16)",
    )
    args = parser.parse_args(argv)
    if args.model is not None:
        _configured_model_path = args.model
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    server.inference_lock = threading.Lock()  # type: ignore[attr-defined]
    server.warmed = False  # type: ignore[attr-defined]
    print(f"[sidecar] listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
