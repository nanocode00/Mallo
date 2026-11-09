"""MeloTTS 및 Qwen3-TTS Baseline을 사용하여 20개 도메인 평가 문장을 합성하고 벤치마크 지표를 측정한다."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class SentenceEvalResult:
    id: str
    category: str
    text: str
    wav_path: str
    latency_seconds: float
    audio_duration_seconds: float
    rtf: float
    sample_rate: int
    num_samples: int
    file_size_bytes: int


@dataclass(frozen=True)
class EvalSummary:
    model_name: str
    device: str
    total_sentences: int
    total_latency_seconds: float
    total_audio_duration_seconds: float
    mean_latency_seconds: float
    median_latency_seconds: float
    mean_rtf: float
    median_rtf: float
    min_rtf: float
    max_rtf: float
    sample_rate: int
    results: list[SentenceEvalResult]


class TTSEvalBackend(Protocol):
    def synthesize(self, text: str, output_path: Path) -> tuple[int, int]:
        """텍스트를 합성하여 output_path에 저장하고 (sample_rate, num_samples)를 반환한다."""
        ...


class MeloTTSBackend:
    """MeloTTS 한국어 사전학습 모델 백엔드."""

    def __init__(self, device: str = "cpu", speed: float = 1.0) -> None:
        from melo.api import TTS

        self.model = TTS(language="KR", device=device)
        self.speaker_id = self.model.hps.data.spk2id["KR"]
        self.speed = speed
        self.device = device

    def synthesize(self, text: str, output_path: Path) -> tuple[int, int]:
        import soundfile as sf

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.model.tts_to_file(
            text, self.speaker_id, str(output_path), speed=self.speed
        )
        data, sr = sf.read(str(output_path))
        return sr, len(data)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_speaker_id(spk2id: Any, speaker: str = "10") -> int:
    """spk2id 매핑(dict 또는 namespace)에서 speaker_id를 추출한다."""
    if isinstance(spk2id, dict):
        if speaker in spk2id:
            return int(spk2id[speaker])
        if "10" in spk2id:
            return int(spk2id["10"])
        if "KR" in spk2id:
            return int(spk2id["KR"])
        return 0
    if hasattr(spk2id, speaker):
        return int(getattr(spk2id, speaker))
    if hasattr(spk2id, "10"):
        return int(getattr(spk2id, "10"))
    if hasattr(spk2id, "KR"):
        return int(getattr(spk2id, "KR"))
    return 0


class MeloTTSFineTunedBackend:
    """MeloTTS 친절체 파인튜닝 모델 백엔드."""

    def __init__(
        self,
        config_path: Path,
        ckpt_path: Path,
        device: str = "cpu",
        speaker: str = "10",
        speed: float = 1.0,
    ) -> None:
        from melo.api import TTS

        self.model = TTS(
            language="KR",
            device=device,
            use_hf=False,
            config_path=str(config_path),
            ckpt_path=str(ckpt_path),
        )
        self.speaker = speaker
        self.speaker_id = _resolve_speaker_id(self.model.hps.data.spk2id, speaker=speaker)
        self.speed = speed
        self.device = device

    def synthesize(self, text: str, output_path: Path) -> tuple[int, int]:
        import soundfile as sf

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.model.tts_to_file(
            text, self.speaker_id, str(output_path), speed=self.speed
        )
        data, sr = sf.read(str(output_path))
        return sr, len(data)


class Qwen3TTSBackend:
    """Qwen3-TTS 0.6B 사전학습/파인튜닝 모델 백엔드."""

    def __init__(
        self,
        model_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        device: str = "cpu",
        speaker: str = "Ryan",
        max_new_tokens: int = 512,
    ) -> None:
        import torch
        from qwen_tts import Qwen3TTSModel

        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        self.tts = Qwen3TTSModel.from_pretrained(
            model_id, device_map=device, dtype=dtype
        )
        self.speaker = speaker
        self.device = device
        self.max_new_tokens = max_new_tokens

    def synthesize(self, text: str, output_path: Path) -> tuple[int, int]:
        import soundfile as sf

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wavs, sr = self.tts.generate_custom_voice(
            text=text, speaker=self.speaker, max_new_tokens=self.max_new_tokens
        )
        sf.write(str(output_path), wavs[0], sr)
        return sr, len(wavs[0])


def load_evaluation_sentences(sentences_path: Path) -> list[dict[str, Any]]:
    """sentences.json 파일을 로드하고 유효성을 검증한다."""
    if not sentences_path.is_file():
        raise FileNotFoundError(f"평가 문장 파일이 존재하지 않음: {sentences_path}")
    data = json.loads(sentences_path.read_text(encoding="utf-8"))
    sentences = data.get("sentences", [])
    if not sentences or len(sentences) < 20:
        raise ValueError(f"평가 문장은 최소 20개여야 함 (현재: {len(sentences)})")
    return sentences


def run_evaluation_synthesis(
    backend: TTSEvalBackend,
    sentences: list[dict[str, Any]],
    output_dir: Path,
    model_name: str,
    device: str = "cpu",
    clock: Callable[[], float] = time.perf_counter,
) -> EvalSummary:
    """주어진 백엔드로 20개 문장을 합성하고 지표를 계산한다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[SentenceEvalResult] = []

    # Warm-up (1회 가벼운 발화로 모델 워밍업)
    try:
        warmup_path = output_dir / "_warmup.wav"
        backend.synthesize("워밍업", warmup_path)
        if warmup_path.exists():
            warmup_path.unlink()
    except Exception:
        pass

    for s in sentences:
        s_id = str(s["id"])
        category = str(s.get("category", "general"))
        text = str(s["text"])
        wav_path = output_dir / f"{s_id}.wav"

        t_start = clock()
        sr, num_samples = backend.synthesize(text, wav_path)
        latency = clock() - t_start

        duration = num_samples / sr if sr > 0 else 0.0
        rtf = latency / duration if duration > 0 else 0.0
        file_size = wav_path.stat().st_size if wav_path.is_file() else 0

        results.append(
            SentenceEvalResult(
                id=s_id,
                category=category,
                text=text,
                wav_path=str(wav_path.resolve()),
                latency_seconds=latency,
                audio_duration_seconds=duration,
                rtf=rtf,
                sample_rate=sr,
                num_samples=num_samples,
                file_size_bytes=file_size,
            )
        )

    latencies = [r.latency_seconds for r in results]
    durations = [r.audio_duration_seconds for r in results]
    rtfs = [r.rtf for r in results]
    sample_rate = results[0].sample_rate if results else 0

    return EvalSummary(
        model_name=model_name,
        device=device,
        total_sentences=len(results),
        total_latency_seconds=sum(latencies),
        total_audio_duration_seconds=sum(durations),
        mean_latency_seconds=statistics.mean(latencies) if latencies else 0.0,
        median_latency_seconds=statistics.median(latencies) if latencies else 0.0,
        mean_rtf=statistics.mean(rtfs) if rtfs else 0.0,
        median_rtf=statistics.median(rtfs) if rtfs else 0.0,
        min_rtf=min(rtfs) if rtfs else 0.0,
        max_rtf=max(rtfs) if rtfs else 0.0,
        sample_rate=sample_rate,
        results=results,
    )


def save_summary_report(summary: EvalSummary, report_path: Path) -> None:
    """평가 요약 결과를 JSON 파일로 저장한다."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_data = {
        "model_name": summary.model_name,
        "device": summary.device,
        "total_sentences": summary.total_sentences,
        "total_latency_seconds": round(summary.total_latency_seconds, 4),
        "total_audio_duration_seconds": round(summary.total_audio_duration_seconds, 4),
        "mean_latency_seconds": round(summary.mean_latency_seconds, 4),
        "median_latency_seconds": round(summary.median_latency_seconds, 4),
        "mean_rtf": round(summary.mean_rtf, 4),
        "median_rtf": round(summary.median_rtf, 4),
        "min_rtf": round(summary.min_rtf, 4),
        "max_rtf": round(summary.max_rtf, 4),
        "sample_rate": summary.sample_rate,
        "results": [
            {
                "id": r.id,
                "category": r.category,
                "text": r.text,
                "wav_path": r.wav_path,
                "latency_seconds": round(r.latency_seconds, 4),
                "audio_duration_seconds": round(r.audio_duration_seconds, 4),
                "rtf": round(r.rtf, 4),
                "sample_rate": r.sample_rate,
                "file_size_bytes": r.file_size_bytes,
            }
            for r in summary.results
        ],
    }
    report_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="TTS 20개 도메인 평가 문장 합성 및 벤치마크")
    parser.add_argument(
        "--sentences",
        type=Path,
        default=Path("data/tts/evaluation/sentences.json"),
        help="20개 평가 문장 JSON 경로",
    )
    parser.add_argument(
        "--model",
        choices=["melotts", "qwen3", "melotts_friendly", "qwen3_friendly", "both", "all"],
        default="both",
        help="평가할 TTS 모델 (melotts, qwen3, melotts_friendly, qwen3_friendly, both, all)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/tts/runs/benchmarks"),
        help="WAV 및 결과 저장 루트 경로",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="추론 디바이스 (cpu, cuda:0)",
    )
    parser.add_argument(
        "--qwen-friendly-model",
        type=Path,
        default=Path("data/tts/runs/qwen3/checkpoints-lr1e5/checkpoint-epoch-4"),
        help="Qwen3-TTS 친절체 파인튜닝 체크포인트 경로",
    )
    parser.add_argument(
        "--melotts-config",
        type=Path,
        default=Path("data/tts/runs/melotts/config.json"),
        help="MeloTTS 설정 파일 경로",
    )
    parser.add_argument(
        "--melotts-checkpoint",
        type=Path,
        default=None,
        help="MeloTTS 파인튜닝 체크포인트 경로 (기본값: models/tts/mallo-friendly/G_2800.pth)",
    )
    args = parser.parse_args()

    sentences = load_evaluation_sentences(args.sentences.resolve())
    output_root = args.output_root.resolve()

    if args.model in ("melotts", "both", "all"):
        print("\n==========================================")
        print("▶ [1] MeloTTS Baseline 평가 합성 시작...")
        print("==========================================")
        melotts_dir = output_root / "melotts_baseline"
        melotts_backend = MeloTTSBackend(device=args.device)
        melo_summary = run_evaluation_synthesis(
            melotts_backend, sentences, melotts_dir, "MeloTTS-Korean-Baseline", device=args.device
        )
        save_summary_report(melo_summary, melotts_dir / "summary.json")
        print(f"✓ MeloTTS Baseline 완료: 총 {melo_summary.total_sentences}개 문장 합성")
        print(f"  • 평균 지연시간: {melo_summary.mean_latency_seconds:.4f}s")
        print(f"  • 평균 RTF: {melo_summary.mean_rtf:.4f}")
        print(f"  • 저장 위치: {melotts_dir}")

    if args.model in ("melotts_friendly", "all"):
        print("\n==========================================")
        print("▶ [2] MeloTTS 친절체 Fine-tuned 평가 합성 시작...")
        print("==========================================")
        ckpt_path = args.melotts_checkpoint
        if ckpt_path is None:
            canonical_ckpt = PROJECT_ROOT / "models" / "tts" / "mallo-friendly" / "G_2800.pth"
            if canonical_ckpt.exists():
                ckpt_path = canonical_ckpt
            else:
                logs_dir = PROJECT_ROOT / "logs" / "mallo-friendly"
                ckpts = sorted(logs_dir.glob("G_*.pth"), key=lambda p: p.stat().st_mtime) if logs_dir.is_dir() else []
                if not ckpts:
                    raise FileNotFoundError(f"MeloTTS 체크포인트가 {canonical_ckpt}에 존재하지 않습니다.")
                ckpt_path = ckpts[-1]
        print(f"  • 사용 체크포인트: {ckpt_path}")
        melotts_ft_dir = output_root / "melotts_friendly"
        melotts_ft_backend = MeloTTSFineTunedBackend(
            config_path=args.melotts_config,
            ckpt_path=ckpt_path,
            device=args.device,
        )
        melo_ft_summary = run_evaluation_synthesis(
            melotts_ft_backend, sentences, melotts_ft_dir, "MeloTTS-Korean-Friendly", device=args.device
        )
        save_summary_report(melo_ft_summary, melotts_ft_dir / "summary.json")
        print(f"✓ MeloTTS Friendly 완료: 총 {melo_ft_summary.total_sentences}개 문장 합성")
        print(f"  • 평균 지연시간: {melo_ft_summary.mean_latency_seconds:.4f}s")
        print(f"  • 평균 RTF: {melo_ft_summary.mean_rtf:.4f}")
        print(f"  • 저장 위치: {melotts_ft_dir}")

    if args.model in ("qwen3", "both", "all"):
        print("\n==========================================")
        print("▶ [3] Qwen3-TTS Baseline 평가 합성 시작...")
        print("==========================================")
        qwen_dir = output_root / "qwen3_baseline"
        qwen_backend = Qwen3TTSBackend(device=args.device, speaker="Ryan")
        qwen_summary = run_evaluation_synthesis(
            qwen_backend, sentences, qwen_dir, "Qwen3-TTS-0.6B-Baseline", device=args.device
        )
        save_summary_report(qwen_summary, qwen_dir / "summary.json")
        print(f"✓ Qwen3-TTS Baseline 완료: 총 {qwen_summary.total_sentences}개 문장 합성")
        print(f"  • 평균 지연시간: {qwen_summary.mean_latency_seconds:.4f}s")
        print(f"  • 평균 RTF: {qwen_summary.mean_rtf:.4f}")
        print(f"  • 저장 위치: {qwen_dir}")

    if args.model in ("qwen3_friendly", "all"):
        print("\n==========================================")
        print("▶ [4] Qwen3-TTS 친절체 Fine-tuned 평가 합성 시작...")
        print("==========================================")
        qwen_ft_dir = output_root / "qwen3_friendly"
        qwen_ft_backend = Qwen3TTSBackend(
            model_id=str(args.qwen_friendly_model),
            device=args.device,
            speaker="calm_friendly",
            max_new_tokens=300,
        )
        qwen_ft_summary = run_evaluation_synthesis(
            qwen_ft_backend, sentences, qwen_ft_dir, "Qwen3-TTS-0.6B-Friendly", device=args.device
        )
        save_summary_report(qwen_ft_summary, qwen_ft_dir / "summary.json")
        print(f"✓ Qwen3-TTS Friendly 완료: 총 {qwen_ft_summary.total_sentences}개 문장 합성")
        print(f"  • 평균 지연시간: {qwen_ft_summary.mean_latency_seconds:.4f}s")
        print(f"  • 평균 RTF: {qwen_ft_summary.mean_rtf:.4f}")
        print(f"  • 저장 위치: {qwen_ft_dir}")


if __name__ == "__main__":
    main()
