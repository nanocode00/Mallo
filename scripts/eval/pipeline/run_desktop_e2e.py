#!/usr/bin/env python3
"""WSL2/CUDA 12.8 desktop launcher for the Mallo integrated web runtime."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = str(ROOT / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from app.server import build_server  # noqa: E402
from app.service import build_service  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Mallo desktop E2E runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)

    parser.add_argument("--tts", choices=["mock", "melo", "qwen3"], default="mock")
    parser.add_argument("--tts-ckpt", default=None)
    parser.add_argument("--tts-config", default=None)
    parser.add_argument("--tts-device", default="auto")
    parser.add_argument("--tts-speaker", default="KR")

    parser.add_argument(
        "--stt",
        choices=["mock", "whisper", "fastwhisper", "http"],
        default="mock",
    )
    parser.add_argument(
        "--stt-variant",
        choices=["baseline", "qlora", "train65", "peft"],
        default="train65",
    )
    parser.add_argument("--stt-device", default="auto")
    parser.add_argument(
        "--stt-model",
        default=None,
        help="Whisper train65/qlora merged path, Faster-Whisper model path, or HTTP STT sidecar URL",
    )

    parser.add_argument(
        "--nlu",
        choices=["mock", "qwen06b", "http"],
        default="mock",
    )
    parser.add_argument(
        "--nlu-model",
        default=None,
        help="Qwen merged-bf16 directory for direct qwen06b mode",
    )
    parser.add_argument(
        "--nlu-url",
        default="http://127.0.0.1:8002/parse",
        help="Qwen NLU sidecar URL for http mode",
    )
    parser.add_argument("--nlu-prompt-lookup-num-tokens", type=int, default=8)

    args = parser.parse_args()

    service = build_service(
        tts_backend=args.tts,
        tts_ckpt_path=args.tts_ckpt,
        tts_config_path=args.tts_config,
        tts_device=args.tts_device,
        tts_speaker=args.tts_speaker,
        stt_backend=args.stt,
        stt_variant=args.stt_variant,
        stt_device=args.stt_device,
        stt_model_path=args.stt_model,
        nlu_backend=args.nlu,
        nlu_model_path=args.nlu_model,
        nlu_prompt_lookup_num_tokens=args.nlu_prompt_lookup_num_tokens,
        nlu_url=args.nlu_url,
    )
    print("Warming TTS…", flush=True)
    service.warmup_tts()
    print("Mallo readiness: TTS warm-up complete", flush=True)

    server = build_server(args.host, args.port, service=service)
    print(
        f"Mallo desktop server running at http://{args.host}:{args.port} "
        f"[TTS={args.tts}, STT={args.stt}, NLU={args.nlu}]"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
