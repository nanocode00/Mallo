"""마이크 입력 → 실제 Whisper STT 시연 (사용자 STT 작업 검증용).

사용법:
    .venvs\\runtime\\Scripts\\Activate.ps1
    $env:PYTHONPATH = "src"
    python scripts/demo_voice.py --variant train65 --seconds 6
    python scripts/demo_voice.py --list-devices        # 입력 장치 번호 확인
    python scripts/demo_voice.py --variant baseline --device 1
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, "src")

import numpy as np

from adapters.audio.recorder import MicrophoneRecorder
from adapters.audio.wav import to_wav_bytes
from adapters.stt.whisper_medium import WhisperMediumSTT


def list_devices() -> None:
    import sounddevice as sd

    print("입력 장치 목록:")
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            print(f"  [{i}] {d['name']}")


def record_wav(seconds: float, device: int | None) -> bytes:
    recorder = MicrophoneRecorder(sample_rate=16000, device=device)
    print(f"[MIC] {seconds:g}초 녹음 시작 - 지금 말씀하세요!", flush=True)
    chunks: list[np.ndarray] = []
    start = time.perf_counter()
    for chunk in recorder.stream_chunks():
        chunks.append(np.asarray(chunk, dtype=np.float32))
        if time.perf_counter() - start >= seconds:
            break
    audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    return to_wav_bytes(audio, sample_rate=16000)


def main() -> None:
    ap = argparse.ArgumentParser(description="마이크 STT 시연")
    ap.add_argument(
        "--variant",
        choices=["baseline", "qlora", "train65", "peft"],
        default="train65",
        help="train65=기본 merged BF16, qlora/baseline=rollback, peft=deprecated alias",
    )
    ap.add_argument("--alts", type=int, default=3, help="대체 후보 수 (alternatives)")
    ap.add_argument("--seconds", type=float, default=6.0, help="녹음 길이(초)")
    ap.add_argument("--device", type=int, default=None, help="마이크 장치 번호 (--list-devices)")
    ap.add_argument("--list-devices", action="store_true", help="입력 장치 목록 출력")
    args = ap.parse_args()

    if args.list_devices:
        list_devices()
        return

    wav_bytes = record_wav(seconds=args.seconds, device=args.device)

    print("[STT] 추론 중...", flush=True)
    stt = WhisperMediumSTT(variant=args.variant, num_return_sequences=args.alts)
    result = stt.transcribe(wav_bytes)

    lines = [
        "=== STT 결과 ===",
        f"인식 텍스트 : {result.text}",
        f"confidence  : {result.confidence}",
        f"alternatives: {result.alternatives}",
        f"duration_ms : {result.duration_ms}",
    ]

    text = "\n".join(lines)
    print(text)
    with open("demo_out.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
