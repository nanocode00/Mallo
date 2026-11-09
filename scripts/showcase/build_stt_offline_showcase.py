#!/usr/bin/env python3
"""Build a self-contained, offline STT submission showcase from WAV files."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import tempfile
import time
import re
from datetime import datetime, timezone
from pathlib import Path


def _input_wavs(values: list[Path]) -> list[Path]:
    files: list[Path] = []
    for value in values:
        if value.is_dir():
            files.extend(sorted(value.glob("*.wav")))
        elif value.suffix.lower() == ".wav" and value.is_file():
            files.append(value)
        else:
            raise FileNotFoundError(f"WAV 파일 또는 디렉터리가 아닙니다: {value}")
    unique = list(dict.fromkeys(path.resolve() for path in files))
    if not unique:
        raise ValueError("처리할 WAV 파일이 없습니다.")
    return unique


def _load_references(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    references = {
        item["filename"]: {
            "reference": item["reference"],
            "audio_name": item.get("audio_name", item["filename"]),
            "display_name": item.get("display_name", item["filename"]),
        }
        for item in items
    }
    if not references:
        raise ValueError(f"reference 항목이 없습니다: {path}")
    return references


def _canonical_text(text: str) -> str:
    normalized = re.sub(r"[.?!,\s]+", "", text)
    normalized = normalized.removeprefix("어")
    return normalized.translate(str.maketrans({"1": "한", "2": "두", "3": "세", "4": "네"}))


def _comparison(reference: str | None, transcript: str) -> str:
    if reference is None:
        return "reference 미제공"
    return "일치" if _canonical_text(reference) == _canonical_text(transcript) else "오류"


def _build_html(results: list[dict[str, object]], model: str) -> str:
    cards = "\n".join(
        "<article><h2>{name}</h2><audio controls preload=\"metadata\" src=\"{audio}\"></audio>"
        "<dl><dt>실제 발화</dt><dd>{reference}</dd><dt>STT 전사</dt><dd>{text}</dd>"
        "<dt>판정</dt><dd class=\"{status_class}\">{status}</dd></dl></article>".format(
            name=html.escape(str(item.get("display_name", item["filename"]))),
            audio=html.escape(str(item["audio_file"])),
            reference=html.escape(str(item.get("reference", "reference 미제공"))),
            text=html.escape(str(item["transcript"])),
            status=html.escape(str(item["comparison"])),
            status_class="pass" if item["comparison"] == "일치" else "fail",
        )
        for item in results
    )
    return f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>말로 STT 최종 쇼케이스</title><style>body{{max-width:900px;margin:32px auto;padding:0 16px;font:16px system-ui;background:#0b1120;color:#e2e8f0}}article{{margin:16px 0;padding:20px;background:#1e293b;border-radius:12px}}h1{{color:#38bdf8}}h2{{font-size:18px}}audio{{width:100%}}dl{{display:grid;grid-template-columns:120px 1fr;gap:8px}}dt{{color:#94a3b8}}dd{{margin:0;white-space:pre-wrap}}.pass{{color:#86efac;font-weight:700}}.fail{{color:#fca5a5;font-weight:700}}</style><body><h1>말로 STT 최종 쇼케이스</h1><p>모델: <code>{html.escape(model)}</code></p><p>직접 녹음한 WAV의 실제 발화와 전사를 비교한 독립 정적 산출물입니다.</p>{cards}</body></html>"""


def build_showcase(
    input_paths: list[Path], output_dir: Path, model_dir: Path,
    references: dict[str, dict[str, str]] | None = None,
) -> dict[str, object]:
    import soundfile as sf
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, torch_dtype=dtype
    ).to(device).eval()
    prompt_ids = processor.get_decoder_prompt_ids(language="ko", task="transcribe")

    output_parent = output_dir.parent
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}-", dir=output_parent) as temp:
        stage = Path(temp)
        audio_dir = stage / "audio"
        audio_dir.mkdir()
        results: list[dict[str, object]] = []
        for index, wav_path in enumerate(input_paths, 1):
            reference_entry = (references or {}).get(wav_path.name, {})
            info = sf.info(wav_path)
            if info.samplerate != 16000 or info.channels != 1:
                raise ValueError(f"16kHz mono WAV가 아닙니다: {wav_path} ({info.samplerate}Hz, {info.channels}ch)")
            samples, sample_rate = sf.read(wav_path, dtype="float32", always_2d=False)
            if getattr(samples, "ndim", 1) > 1:
                samples = samples.mean(axis=1)
            inputs = processor(samples, sampling_rate=sample_rate, return_tensors="pt")
            start = time.perf_counter()
            with torch.inference_mode():
                generated = model.generate(
                    inputs.input_features.to(device, dtype=dtype),
                    forced_decoder_ids=prompt_ids,
                )
            elapsed_ms = (time.perf_counter() - start) * 1000
            audio_name = reference_entry.get("audio_name", f"{index:02d}-{wav_path.name}")
            shutil.copy2(wav_path, audio_dir / audio_name)
            transcript = processor.batch_decode(generated, skip_special_tokens=True)[0].strip()
            reference = reference_entry.get("reference")
            results.append({
                "filename": audio_name,
                "source_filename": wav_path.name,
                "display_name": reference_entry.get("display_name", audio_name),
                "audio_file": f"audio/{audio_name}",
                "reference": reference,
                "transcript": transcript,
                "comparison": _comparison(reference, transcript),
                "inference_ms": round(elapsed_ms, 3),
                "audio_duration_s": round(len(samples) / sample_rate, 3),
                "audio_format": {"sample_rate_hz": info.samplerate, "channels": info.channels, "subtype": info.subtype},
            })
        metadata: dict[str, object] = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": str(model_dir), "device": device, "items": results,
        }
        (stage / "results.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (stage / "index.html").write_text(_build_html(results, str(model_dir)), encoding="utf-8")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.move(str(stage), str(output_dir))
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="WAV 배치 추론 기반 오프라인 STT 쇼케이스 생성")
    parser.add_argument("--input-wav", nargs="+", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path("models/stt/final-train65-merged-bf16"))
    parser.add_argument("--references-json", type=Path, help="filename/reference/audio_name 항목의 JSON")
    args = parser.parse_args()
    metadata = build_showcase(
        _input_wavs(args.input_wav), args.output_dir, args.model_dir,
        _load_references(args.references_json),
    )
    print(f"STT 쇼케이스 생성 완료: {args.output_dir} ({len(metadata['items'])}개, {metadata['device']})")


if __name__ == "__main__":
    main()
