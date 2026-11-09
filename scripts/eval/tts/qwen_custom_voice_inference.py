"""Fine-tuned Qwen3-TTS checkpoint를 재로딩해 smoke WAV를 생성한다."""

from __future__ import annotations

import argparse
from pathlib import Path


def synthesize(model: Path, text_file: Path, output: Path, speaker: str) -> None:
    if not model.is_absolute() or not model.is_dir():
        raise ValueError("Fine-tuned model은 존재하는 절대 디렉터리여야 함")
    if not text_file.is_absolute() or not text_file.is_file():
        raise ValueError("추론 text 파일은 존재하는 절대 파일이어야 함")
    text = text_file.read_text(encoding="utf-8").strip()
    if not text or not speaker.strip():
        raise ValueError("추론 text와 speaker는 비어 있을 수 없음")

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    tts = Qwen3TTSModel.from_pretrained(
        str(model.resolve()),
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="flash_attention_2",
    )
    wavs, sample_rate = tts.generate_custom_voice(text=text, speaker=speaker)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output.resolve()), wavs[0], sample_rate)


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen3-TTS custom voice smoke 추론")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--text-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--speaker", required=True)
    args = parser.parse_args()
    synthesize(args.model, args.text_file, args.output, args.speaker)


if __name__ == "__main__":
    main()
