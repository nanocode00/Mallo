"""Whisper STT 후보를 같은 domain_eval 셋으로 비교한다.

기존 모델 파일은 전혀 변경하지 않는다. 기본 CUDA BF16 경로가 불가능한 환경에서는
명확한 오류를 남기고 다음 후보로 진행한다. ONNX는 onnxruntime으로 별도 실행한다.
"""
from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import re
import statistics
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import soundfile as sf

from adapters.stt.common import resample_to_16k_mono, setup_cuda_dll_paths
from scripts.eval.stt.evaluate_domain_eval import load_eval_data
from scripts.eval.stt.metrics import (
    DEFAULT_KEYWORDS, _normalize_quantity, compute_cer, compute_wer,
    corpus_cer, corpus_wer, keyword_recall,
)

MODEL_ID = "openai/whisper-medium"
MAX_NEW_TOKENS = 440
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODELS_ROOT = ROOT / "models/stt"
DEFAULT_EVAL_DIR = ROOT / "data/stt/domain_eval"
ARTIFACT_ROOT = ROOT / "artifacts/stt-benchmark"
EVAL_PRESETS = {
    "clean-kiosk": ROOT / "data/stt/heldout/results_v1/full-v1/golden_kiosk.csv",
    "clean-general": ROOT / "data/stt/heldout/results_v1/full-v1/golden_clean.csv",
    "cafe15": ROOT / "data/stt/heldout/results_v1/cafe-full-v1/golden_cafe15.csv",
    "cafe10": ROOT / "data/stt/heldout/results_v1/cafe-full-v1/golden_cafe10.csv",
    "cafe5": ROOT / "data/stt/heldout/results_v1/cafe-full-v1/golden_cafe5.csv",
}
CHECKPOINT_RE = re.compile(r"^checkpoint-(\d+)$")
EXCLUDED_PARTS = {"checkpoint_backups"}


@dataclass
class Candidate:
    name: str
    model_type: str
    path: str | None = None
    adapter_sha256: str | None = None
    base_model_name_or_path: str | None = None
    duplicate_of: str | None = None
    selection_reason: str | None = None
    execution_providers: list[str] | None = None
    execution_provider: str | None = None
    execution_device: str | None = None
    latency_comparison_group: str | None = None
    latency_rank: int | None = None
    generation_config_observed: dict[str, Any] | None = None
    decoding_config_applied: dict[str, Any] | None = None
    peft_diagnostics: dict[str, Any] | None = None
    diagnostic_warnings: list[str] | None = None


@dataclass(frozen=True)
class EvalManifest:
    name: str
    path: Path | None
    semantic_metrics: bool
    source: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS or "smoke" in part.lower() for part in path.parts)


def largest_checkpoint(directory: Path) -> Path | None:
    choices: list[tuple[int, Path]] = []
    for child in directory.iterdir() if directory.exists() else ():
        match = CHECKPOINT_RE.match(child.name)
        # directory 자체는 호출자가 이미 제외 검사했다. 여기서는 절대경로의
        # 임시 상위 디렉터리 이름이 "smoke"인 경우까지 제외하지 않는다.
        if match and (child / "adapter_model.safetensors").is_file():
            choices.append((int(match.group(1)), child))
    return max(choices, default=(0, None), key=lambda item: item[0])[1]


def discover_peft_candidates(models_root: Path) -> list[Candidate]:
    """실험별 final adapter를 고르고 SHA 중복은 기록만 하고 실행에서 제외한다."""
    roots: set[Path] = set()
    adapters = [p.parent for p in models_root.rglob("adapter_model.safetensors") if not is_excluded(p.relative_to(models_root))]
    for adapter_dir in adapters:
        if CHECKPOINT_RE.match(adapter_dir.name):
            roots.add(adapter_dir.parent)
        else:
            roots.add(adapter_dir)

    selected: list[Path] = []
    for root in sorted(roots):
        if is_excluded(root.relative_to(models_root)):
            continue
        # 실험 디렉터리의 adapter는 trainer가 저장한 최종 모델이다. checkpoint는
        # top-level final adapter가 없는 실험에만 적용하는 fallback이다.
        final_checkpoint = None if (root / "adapter_model.safetensors").is_file() else largest_checkpoint(root)
        selected_path = final_checkpoint or root
        adapter = selected_path / "adapter_model.safetensors"
        config = selected_path / "adapter_config.json"
        if not adapter.is_file() or not config.is_file():
            continue
        # A parent with checkpoints represents one experiment; don't also pick children.
        if any(selected_path.is_relative_to(parent) and selected_path != parent for parent in selected):
            continue
        selected = [p for p in selected if not p.is_relative_to(selected_path)]
        selected.append(selected_path)

    seen: dict[str, str] = {}
    candidates: list[Candidate] = []
    for path in sorted(selected):
        adapter = path / "adapter_model.safetensors"
        config = json.loads((path / "adapter_config.json").read_text(encoding="utf-8"))
        digest = sha256_file(adapter)
        name = "peft-" + str(path.relative_to(models_root)).replace("/", "--")
        duplicate_of = seen.get(digest)
        if duplicate_of is None:
            seen[digest] = name
        candidates.append(Candidate(
            name=name, model_type="peft", path=str(path), adapter_sha256=digest,
            base_model_name_or_path=config.get("base_model_name_or_path"),
            duplicate_of=duplicate_of,
            selection_reason=("largest checkpoint" if CHECKPOINT_RE.match(path.name) else "top-level adapter"),
        ))
    return candidates


def discover_candidates(models_root: Path, skip_onnx: bool = False) -> list[Candidate]:
    candidates = [
        Candidate("baseline-openai-whisper-medium", "baseline", base_model_name_or_path=MODEL_ID),
        Candidate("merged-team-handoff-domain", "merged", path=str(models_root / "team_handoff/domain/merged-bf16"), base_model_name_or_path=MODEL_ID),
    ]
    candidates.extend(discover_peft_candidates(models_root))
    onnx_dir = models_root / "whisper-onnx"
    if not skip_onnx and (onnx_dir / "encoder_model_int8.onnx").is_file():
        candidates.append(Candidate("onnx-whisper-int8", "onnx", path=str(onnx_dir), base_model_name_or_path=MODEL_ID))
    return candidates


def filter_candidates(candidates: Iterable[Candidate], includes: list[str], excludes: list[str]) -> list[Candidate]:
    def matches(candidate: Candidate, patterns: list[str]) -> bool:
        haystack = f"{candidate.name} {candidate.path or ''}".lower()
        return any(pattern.lower() in haystack for pattern in patterns)
    return [c for c in candidates if (not includes or matches(c, includes)) and not matches(c, excludes)]


def print_candidate_list(candidates: Iterable[Candidate], manifests: Iterable[EvalManifest] = ()) -> None:
    """모델이나 평가 데이터를 열지 않는 후보 탐색 결과 출력."""
    rows = [
        {
            "name": candidate.name,
            "model_type": candidate.model_type,
            "selection_reason": candidate.selection_reason,
            "path": candidate.path,
            "duplicate_of": candidate.duplicate_of,
            "adapter_sha256": candidate.adapter_sha256,
        }
        for candidate in candidates
    ]
    print(json.dumps({"manifests": [asdict(manifest) | {"path": str(manifest.path) if manifest.path else None} for manifest in manifests], "candidates": rows}, ensure_ascii=False, indent=2))


def load_generic_eval_csv(path: Path, name: str | None = None) -> tuple[EvalManifest, pd.DataFrame]:
    """heldout golden CSV의 최소 schema를 내부 평가 schema로 변환한다."""
    if not path.is_file():
        raise FileNotFoundError(f"평가 CSV를 찾을 수 없습니다: {path}")
    df = pd.read_csv(path)
    required = {"sample_id", "audio_path", "reference"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"generic 평가 CSV 필수 컬럼 누락 ({path}): {', '.join(sorted(missing))}")
    # hypothesis/latency_sec 등 기존 결과 컬럼은 입력 평가에 영향을 주지 않는다.
    normalized = df.loc[:, ["sample_id", "audio_path", "reference"]].rename(columns={"sample_id": "id", "reference": "text"})
    return EvalManifest(name or path.stem, path, False, "generic-csv"), normalized


def resolve_eval_manifests(eval_dir: Path, eval_csvs: list[Path], presets: list[str]) -> list[tuple[EvalManifest, pd.DataFrame]]:
    """명시 CSV/preset이 없을 때만 기존 domain_eval 동작을 보존한다."""
    if eval_csvs and presets:
        raise ValueError("--eval-csv와 --eval-preset은 함께 사용할 수 없습니다")
    if eval_csvs:
        return [load_generic_eval_csv(path) for path in eval_csvs]
    if presets:
        return [load_generic_eval_csv(EVAL_PRESETS[name], name) for name in presets]
    return [(EvalManifest("domain-eval", eval_dir, True, "domain-eval"), load_eval_data(eval_dir))]


def load_audio_rows(eval_df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for _, row in eval_df.iterrows():
        audio, sr = sf.read(str(row["audio_path"]))
        audio, _ = resample_to_16k_mono(audio, sr)
        rows.append({**row.to_dict(), "audio": np.asarray(audio, dtype=np.float32)})
    return rows


GENERATION_CONFIG_FIELDS = (
    "language", "task", "max_new_tokens", "do_sample", "num_beams", "num_return_sequences",
    "suppress_tokens", "begin_suppress_tokens", "forced_decoder_ids", "return_timestamps",
    "decoder_start_token_id", "no_timestamps_token_id",
)


def generation_config_snapshot(config: Any) -> dict[str, Any]:
    """모델 설정을 읽기만 하여 fairness audit metadata에 보관한다."""
    return {field: getattr(config, field, None) for field in GENERATION_CONFIG_FIELDS}


def build_benchmark_generation_config(canonical_config: Any) -> Any:
    """Official baseline config의 깊은 복사본에만 공통 benchmark 조건을 적용한다."""
    benchmark_config = copy.deepcopy(canonical_config)
    benchmark_config.language = "ko"
    benchmark_config.task = "transcribe"
    benchmark_config.max_new_tokens = MAX_NEW_TOKENS
    benchmark_config.do_sample = False
    benchmark_config.num_beams = 1
    benchmark_config.num_return_sequences = 1
    benchmark_config.return_timestamps = False
    # language/task prompt가 결정하도록 legacy 값은 benchmark copy에서만 해제한다.
    benchmark_config.forced_decoder_ids = None
    # suppress 목록은 deepcopy된 official baseline config에 유지한다. generate kwargs로 중복 전달하지 않는다.
    benchmark_config.suppress_tokens = list(getattr(canonical_config, "suppress_tokens", None) or [])
    benchmark_config.begin_suppress_tokens = list(getattr(canonical_config, "begin_suppress_tokens", None) or [])
    return benchmark_config


@lru_cache(maxsize=1)
def load_canonical_decoding_config() -> Any:
    """모델 bundle의 generation_config를 바꾸지 않는 official baseline 설정 source."""
    from transformers import GenerationConfig
    return GenerationConfig.from_pretrained(MODEL_ID)


def _active_adapter_names(model: Any) -> list[str]:
    active = getattr(model, "active_adapters", None)
    if active is None:
        active = getattr(model, "active_adapter", None)
    if isinstance(active, str):
        return [active]
    try:
        return [str(name) for name in active]
    except TypeError:
        return []


def collect_peft_diagnostics(model: Any) -> dict[str, Any]:
    """PEFT model 상태를 읽기만 하며 LoRA module/parameter 규모를 집계한다."""
    active_adapters = _active_adapter_names(model)
    peft_config = getattr(model, "peft_config", {})
    active_config = peft_config.get(active_adapters[0]) if active_adapters else None
    lora_modules = [name for name, module in model.named_modules() if hasattr(module, "lora_A") or hasattr(module, "lora_B")]
    adapter_parameters = [
        parameter for name, parameter in model.named_parameters()
        if ".lora_" in name or ".lora" in name
    ]
    return {
        "active_adapters": active_adapters,
        "peft_type": getattr(getattr(active_config, "peft_type", None), "value", getattr(active_config, "peft_type", None)),
        "base_model_name_or_path": getattr(active_config, "base_model_name_or_path", None),
        "lora_module_count": len(lora_modules),
        "adapter_parameter_count": sum(parameter.numel() for parameter in adapter_parameters),
        "adapter_parameter_abs_sum": float(sum(parameter.detach().abs().sum().item() for parameter in adapter_parameters)),
        "diagnostic_error": None,
    }


def adapter_effect_verdict(max_abs_logit_diff: float, mean_abs_logit_diff: float) -> tuple[bool, list[str]]:
    verified = max_abs_logit_diff != 0.0 and mean_abs_logit_diff != 0.0
    if not verified:
        return False, ["adapter effect logits are exactly zero; verify adapter activation and checkpoint compatibility"]
    return verified, []


def summarize_adapter_logit_effect(active_logits: Any, base_logits: Any) -> tuple[dict[str, Any], list[str]]:
    difference = (active_logits.float() - base_logits.float()).abs()
    max_diff = float(difference.max().item())
    mean_diff = float(difference.mean().item())
    verified, warnings = adapter_effect_verdict(max_diff, mean_diff)
    return {
        "adapter_effect_max_abs_logit_diff": max_diff,
        "adapter_effect_mean_abs_logit_diff": mean_diff,
        "adapter_effect_verified": verified,
    }, warnings


def build_generate_kwargs(input_features: Any, attention_mask: Any, generation_config: Any) -> dict[str, Any]:
    """Suppress 관련 값은 generation_config에만 존재하도록 generate 입력을 한정한다."""
    return {
        "input_features": input_features,
        "attention_mask": attention_mask,
        "generation_config": generation_config,
    }


def build_teacher_forced_whisper_kwargs(input_features: Any, attention_mask: Any, decoder_input_ids: Any) -> dict[str, Any]:
    """Whisper forward의 실제 audio interface만 사용한다; input_ids는 절대 전달하지 않는다."""
    return {
        "input_features": input_features,
        "attention_mask": attention_mask,
        "decoder_input_ids": decoder_input_ids,
        "use_cache": False,
        "return_dict": True,
    }


def generation_config_owner(model: Any) -> Any:
    """PEFT wrapper가 아닌 실제 Whisper generate 구현체를 반환한다."""
    return model.get_base_model() if hasattr(model, "get_base_model") else model


@contextmanager
def disable_inner_model_default_fallback(model: Any):
    """Whisper가 suppress processor를 만든 뒤 inner GenerationMixin이 재삽입하지 않게 한다.

    Transformers 4.57.3 Whisper는 자체 processor 생성 후 suppress fields를 None으로
    비운 config를 inner ``GenerationMixin.generate``에 넘긴다. inner call은 4.50+
    model defaults를 다시 채워 중복 processor를 만든다. 이 context는 원본 객체를
    수정하지 않고, compatibility gate만 바꾼 복사본을 호출 동안 교체한다.
    """
    owner = generation_config_owner(model)
    original = owner.generation_config
    isolated = copy.deepcopy(original)
    isolated.transformers_version = "4.49.0"
    owner.generation_config = isolated
    try:
        yield
    finally:
        owner.generation_config = original


class TransformersRunner:
    def __init__(self, candidate: Candidate) -> None:
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor
        self.torch = torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA BF16 추론이 필요하지만 CUDA를 사용할 수 없습니다")
        started = time.perf_counter()
        dtype = torch.bfloat16
        source = candidate.path if candidate.model_type == "merged" else (candidate.base_model_name_or_path or MODEL_ID)
        processor_source = candidate.path if candidate.model_type == "merged" else source
        self.processor = WhisperProcessor.from_pretrained(str(processor_source), language="ko", task="transcribe")
        model = WhisperForConditionalGeneration.from_pretrained(str(source), torch_dtype=dtype).to("cuda")
        if candidate.model_type == "peft":
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, str(candidate.path))
        self.model = model.eval()
        self.generation_config_observed = generation_config_snapshot(self.model.generation_config)
        self.benchmark_generation_config = build_benchmark_generation_config(load_canonical_decoding_config())
        self.decoding_config_applied = generation_config_snapshot(self.benchmark_generation_config) | {
            "forced_decoder_ids_actual": self.benchmark_generation_config.forced_decoder_ids,
            "attention_mask_passed_to_generate": True,
            "outer_use_model_defaults": False,
            "inner_model_default_fallback": "disabled with temporary generation_config copy",
        }
        torch.cuda.synchronize()
        self.load_ms = (time.perf_counter() - started) * 1000
        torch.cuda.reset_peak_memory_stats()

    def _prepare_forward_inputs(self, audio: np.ndarray) -> tuple[Any, Any, Any]:
        features = self.processor.feature_extractor(
            audio, sampling_rate=16000, return_attention_mask=True, return_tensors="pt"
        )
        input_features = features.input_features.to("cuda", dtype=self.torch.bfloat16)
        attention_mask = features.attention_mask.to("cuda")
        start_token_id = int(self.model.config.decoder_start_token_id)
        prompt = [start_token_id] + [
            token for _, token in self.processor.get_decoder_prompt_ids(
                language="ko", task="transcribe", no_timestamps=True
            )
        ]
        decoder_input_ids = self.torch.tensor([prompt], device="cuda", dtype=self.torch.long)
        return input_features, attention_mask, decoder_input_ids

    def diagnose_peft_effect(self, audio: np.ndarray) -> tuple[dict[str, Any], list[str]]:
        """공식 disable_adapter context로 활성/비활성 forward logits를 비교한다."""
        if not hasattr(self.model, "disable_adapter"):
            raise TypeError("PEFT model에 disable_adapter()가 없습니다")
        diagnostics = collect_peft_diagnostics(self.model)
        input_features, attention_mask, decoder_input_ids = self._prepare_forward_inputs(audio)
        # PeftModelForSeq2SeqLM.forward()는 input_ids=None도 base Whisper로 전달한다.
        # LoRA hooks를 보유한 base_model을 직접 호출하면 Whisper audio interface를 보존한다.
        adapter_forward_model = self.model.base_model
        forward_kwargs = build_teacher_forced_whisper_kwargs(input_features, attention_mask, decoder_input_ids)
        with self.torch.inference_mode():
            active_logits = adapter_forward_model(**forward_kwargs).logits
            with self.model.disable_adapter():
                base_logits = adapter_forward_model(**forward_kwargs).logits
        effect, warnings = summarize_adapter_logit_effect(active_logits, base_logits)
        diagnostics.update({
            "adapter_effect_forward": "active adapter vs PeftModel.disable_adapter()",
            **effect,
        })
        return diagnostics, warnings

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        inputs, attention_mask, _ = self._prepare_forward_inputs(audio)
        self.torch.cuda.synchronize()
        started = time.perf_counter()
        with self.torch.inference_mode():
            with disable_inner_model_default_fallback(self.model):
                ids = self.model.generate(
                    **build_generate_kwargs(inputs, attention_mask, self.benchmark_generation_config),
                    use_model_defaults=False,
                )
        self.torch.cuda.synchronize()
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip(), (time.perf_counter() - started) * 1000

    def peak_memory_mb(self) -> float:
        return self.torch.cuda.max_memory_allocated() / (1024 * 1024)

    def unload(self) -> None:
        del self.model, self.processor
        gc.collect()
        self.torch.cuda.empty_cache()


class OnnxRunner:
    """Optimum wrapper가 아닌 onnxruntime encoder/decoder greedy loader."""
    def __init__(self, candidate: Candidate) -> None:
        import onnxruntime as ort
        from transformers import WhisperProcessor
        started = time.perf_counter()
        self.ort = ort
        self.dir = Path(candidate.path or "")
        available = ort.get_available_providers()
        self.providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in available]
        self.encoder = ort.InferenceSession(str(self.dir / "encoder_model_int8.onnx"), providers=self.providers)
        self.decoder = ort.InferenceSession(str(self.dir / "decoder_model_int8.onnx"), providers=self.providers)
        self.execution_providers = self.encoder.get_providers()
        self.execution_provider = self.execution_providers[0] if self.execution_providers else None
        if self.execution_provider == "CUDAExecutionProvider" and "CPUExecutionProvider" in self.execution_providers:
            # ORT는 CUDA 뒤에 CPU fallback을 나열한다. 노드별 실행을 가정하지 않고
            # 보수적으로 mixed group으로 분리해 CUDA PyTorch와 혼합 순위화하지 않는다.
            self.execution_device = "cuda+cpu"
        elif self.execution_provider == "CUDAExecutionProvider":
            self.execution_device = "cuda"
        else:
            self.execution_device = "cpu"
        self.processor = WhisperProcessor.from_pretrained(str(self.dir), language="ko", task="transcribe")
        self.config = json.loads((self.dir / "generation_config.json").read_text(encoding="utf-8"))
        self.load_ms = (time.perf_counter() - started) * 1000

    @staticmethod
    def _input_name(session: Any, fragment: str) -> str | None:
        return next((i.name for i in session.get_inputs() if fragment in i.name), None)

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        features = self.processor.feature_extractor(audio, sampling_rate=16000).input_features.astype(np.float32)
        encoder_name = self.encoder.get_inputs()[0].name
        hidden = self.encoder.run(None, {encoder_name: features})[0]
        start_id = int(self.config.get("decoder_start_token_id", 50258))
        prompt = [start_id] + [token for _, token in self.processor.get_decoder_prompt_ids(language="ko", task="transcribe", no_timestamps=True)]
        eos = self.config.get("eos_token_id", 50257)
        eos_ids = set(eos if isinstance(eos, list) else [eos])
        ids = np.asarray([prompt], dtype=np.int64)
        started = time.perf_counter()
        for _ in range(MAX_NEW_TOKENS):
            feeds: dict[str, np.ndarray] = {}
            for inp in self.decoder.get_inputs():
                if "input_ids" in inp.name:
                    feeds[inp.name] = ids
                elif "encoder_hidden_states" in inp.name:
                    feeds[inp.name] = hidden
                elif "attention_mask" in inp.name:
                    feeds[inp.name] = np.ones((1, hidden.shape[1]), dtype=np.int64)
                elif "cache_position" in inp.name:
                    feeds[inp.name] = np.arange(ids.shape[1], dtype=np.int64)
            logits = self.decoder.run(None, feeds)[0]
            token = int(np.argmax(logits[0, -1]))
            ids = np.concatenate((ids, [[token]]), axis=1)
            if token in eos_ids:
                break
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip(), (time.perf_counter() - started) * 1000

    def peak_memory_mb(self) -> float | None:
        return None

    def unload(self) -> None:
        del self.encoder, self.decoder, self.processor
        gc.collect()


def metric_row(row: dict[str, Any], hypothesis: str, latency_ms: float | None, error: str | None, semantic_metrics: bool) -> dict[str, Any]:
    reference = str(row["text"])
    values = {"id": row["id"], "reference": reference, "hypothesis": hypothesis, "latency_ms": latency_ms, "error": error,
              "menu_gt": row.get("menu"), "quantity_gt": row.get("quantity"), "option_gt": row.get("option")}
    values["cer"] = compute_cer(reference, hypothesis)
    values["wer"] = compute_wer(reference, hypothesis)
    for label, normalizer in (("menu", None), ("quantity", _normalize_quantity), ("option", None)):
        if not semantic_metrics:
            values.update({f"{label}_recall": None, f"{label}_matched": None, f"{label}_total": None})
            continue
        result = keyword_recall(reference, hypothesis, DEFAULT_KEYWORDS[label], normalize_fn=normalizer)
        values.update({f"{label}_recall": result["recall"], f"{label}_matched": result["matched"], f"{label}_total": result["total"]})
    return values


PER_SAMPLE_COLUMNS = [
    "id", "reference", "hypothesis", "latency_ms", "error", "menu_gt", "quantity_gt", "option_gt",
    "cer", "wer", "menu_recall", "menu_matched", "menu_total", "quantity_recall", "quantity_matched",
    "quantity_total", "option_recall", "option_matched", "option_total",
]


def summarize(candidate: Candidate, manifest: EvalManifest, records: list[dict[str, Any]], load_ms: float | None, peak_mb: float | None) -> dict[str, Any]:
    refs, hyps = [r["reference"] for r in records], [r["hypothesis"] for r in records]
    latencies = [float(r["latency_ms"]) for r in records if r["latency_ms"] is not None]
    result = asdict(candidate) | {
        "evaluation_name": manifest.name, "evaluation_source": manifest.source, "semantic_metrics_available": manifest.semantic_metrics,
        "sample_count": len(records), "failed_samples": sum(r["error"] is not None for r in records),
        "corpus_cer": corpus_cer(refs, hyps), "corpus_wer": corpus_wer(refs, hyps), "model_load_time_ms": load_ms,
        "inference_mean_ms": statistics.fmean(latencies) if latencies else None,
        "inference_median_ms": statistics.median(latencies) if latencies else None,
        "inference_p95_ms": float(np.percentile(latencies, 95)) if latencies else None,
        "peak_cuda_memory_mb": peak_mb,
    }
    for label in ("menu", "quantity", "option"):
        if not manifest.semantic_metrics:
            result[f"{label}_recall"] = None
            continue
        total, matched = sum(r[f"{label}_total"] for r in records), sum(r[f"{label}_matched"] for r in records)
        result[f"{label}_recall"] = matched / total if total else 0.0
    return result


def set_latency_ranks(rows: list[dict[str, Any]]) -> None:
    """서로 다른 runtime/device의 latency는 그룹 내부에서만 순위를 매긴다."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group = row.get("latency_comparison_group")
        if group and row.get("inference_p95_ms") is not None:
            groups.setdefault(group, []).append(row)
    for group_rows in groups.values():
        for rank, row in enumerate(sorted(group_rows, key=lambda row: row["inference_p95_ms"]), 1):
            row["latency_rank"] = rank


def leaderboard_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """N/A semantic metric은 0점으로 바꾸지 않고 같은 평가셋 안에서만 정렬한다."""
    is_pytorch_cuda = row.get("latency_comparison_group") == "pytorch-cuda"
    menu_recall = row.get("menu_recall")
    return (
        row.get("evaluation_name", ""),
        row["corpus_cer"] is None,
        row["corpus_cer"] if row["corpus_cer"] is not None else float("inf"),
        row["corpus_wer"] if row["corpus_wer"] is not None else float("inf"),
        menu_recall is None,
        -menu_recall if menu_recall is not None else 0.0,
        row["inference_p95_ms"] if is_pytorch_cuda and row["inference_p95_ms"] is not None else float("inf"),
        row["name"],
    )


def build_noise_degradation(per_model_dir: Path, candidate_names: Iterable[str]) -> list[dict[str, Any]]:
    """같은 sample_id의 clean-kiosk 및 SNR 평가 결과를 corpus CER로 비교한다."""
    rows: list[dict[str, Any]] = []
    for name in candidate_names:
        csv_path = per_model_dir / f"{name}.csv"
        if not csv_path.is_file():
            continue
        data = pd.read_csv(csv_path, keep_default_na=False)
        if not {"evaluation_name", "id", "reference", "hypothesis"}.issubset(data.columns):
            continue
        clean = data[data["evaluation_name"] == "clean-kiosk"]
        if clean.empty:
            continue
        summary: dict[str, Any] = {"name": name}
        for label in ("clean", "cafe15", "cafe10", "cafe5"):
            evaluation = "clean-kiosk" if label == "clean" else label
            noisy = data[data["evaluation_name"] == evaluation]
            joined = clean.merge(noisy, on="id", suffixes=("_clean", "_noisy")) if label != "clean" else clean
            if joined.empty:
                summary[f"{label}_cer"] = None
                summary[f"{label}_vs_clean_cer_increase"] = None
                summary[f"{label}_overlap_samples"] = 0
                continue
            if label == "clean":
                score = corpus_cer(joined["reference"].tolist(), joined["hypothesis"].tolist())
                summary["clean_cer"] = score
                summary["clean_overlap_samples"] = len(joined)
                continue
            score = corpus_cer(joined["reference_noisy"].tolist(), joined["hypothesis_noisy"].tolist())
            clean_score = corpus_cer(joined["reference_clean"].tolist(), joined["hypothesis_clean"].tolist())
            summary[f"{label}_cer"] = score
            summary[f"{label}_vs_clean_cer_increase"] = score - clean_score
            summary[f"{label}_overlap_samples"] = len(joined)
        if any(summary.get(f"cafe{snr}_overlap_samples", 0) for snr in (15, 10, 5)):
            rows.append(summary)
    return rows


def artifact_dir(resume: bool) -> Path:
    if resume and ARTIFACT_ROOT.exists():
        previous = sorted(path for path in ARTIFACT_ROOT.iterdir() if path.is_dir())
        if previous:
            return previous[-1]
    return ARTIFACT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")


def write_metadata(output_dir: Path, candidates: Iterable[Candidate], manifests: Iterable[EvalManifest]) -> None:
    """재현에 필요한 적용 decoding config와 모델별 원본 config 관측값을 기록한다."""
    metadata = {
        "decoding_config_source": MODEL_ID,
        "attention_mask_passed_to_generate": True,
        "models": [
            {
                "name": candidate.name,
                "model_type": candidate.model_type,
                "generation_config_observed": candidate.generation_config_observed,
                "decoding_config_applied": candidate.decoding_config_applied,
                "peft_diagnostics": candidate.peft_diagnostics,
                "diagnostic_warnings": candidate.diagnostic_warnings,
            }
            for candidate in candidates
        ],
        "evaluations": [
            {"name": manifest.name, "source": manifest.source, "path": str(manifest.path) if manifest.path else None}
            for manifest in manifests
        ],
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="STT 후보 전체 비교 벤치마크")
    parser.add_argument("--models-root", type=Path, default=DEFAULT_MODELS_ROOT)
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--eval-csv", type=Path, action="append", default=[], help="generic CSV (sample_id,audio_path,reference); 반복 지정 가능")
    parser.add_argument("--eval-preset", choices=sorted(EVAL_PRESETS), action="append", default=[], help="heldout golden 평가셋 preset; 반복 지정 가능")
    parser.add_argument("--include", action="append", default=[], help="이름/경로 부분문자열 (반복 또는 쉼표 구분)")
    parser.add_argument("--exclude", action="append", default=[], help="제외 이름/경로 부분문자열")
    parser.add_argument("--limit", type=int, default=None, help="평가할 샘플 수")
    parser.add_argument("--skip-onnx", action="store_true")
    parser.add_argument("--resume", action="store_true", help="가장 최근 artifact에서 완료 후보를 건너뜀")
    parser.add_argument("--dry-run", action="store_true", help="후보 목록만 JSON으로 출력하고 모델/평가셋을 열지 않음")
    args = parser.parse_args()
    setup_cuda_dll_paths()
    patterns = lambda xs: [p.strip() for x in xs for p in x.split(",") if p.strip()]
    candidates = filter_candidates(discover_candidates(args.models_root, args.skip_onnx), patterns(args.include), patterns(args.exclude))
    manifests = resolve_eval_manifests(args.eval_dir, args.eval_csv, args.eval_preset)
    if args.dry_run:
        print_candidate_list(candidates, (manifest for manifest, _ in manifests))
        return
    out = artifact_dir(args.resume)
    per_model = out / "per_model"
    per_model.mkdir(parents=True, exist_ok=True)
    (out / "candidates.json").write_text(json.dumps([asdict(c) for c in candidates], ensure_ascii=False, indent=2), encoding="utf-8")
    write_metadata(out, candidates, (manifest for manifest, _ in manifests))
    manifest_rows: list[tuple[EvalManifest, list[dict[str, Any]]]] = []
    for manifest, eval_df in manifests:
        if args.limit:
            eval_df = eval_df.head(args.limit)
        manifest_rows.append((manifest, load_audio_rows(eval_df)))
    completed: list[dict[str, Any]] = []
    old = out / "leaderboard.json"
    if args.resume and old.exists():
        completed = json.loads(old.read_text(encoding="utf-8"))
    done_keys = {(r["name"], r.get("evaluation_name")) for r in completed}
    error_log = (out / "errors.log").open("a", encoding="utf-8")
    for candidate in candidates:
        if candidate.duplicate_of or all((candidate.name, manifest.name) in done_keys for manifest, _ in manifest_rows):
            continue
        runner = None
        candidate_records: list[dict[str, Any]] = []
        try:
            runner = OnnxRunner(candidate) if candidate.model_type == "onnx" else TransformersRunner(candidate)
            if candidate.model_type == "onnx":
                candidate.execution_providers = runner.execution_providers
                candidate.execution_provider = runner.execution_provider
                candidate.execution_device = runner.execution_device
                candidate.latency_comparison_group = f"onnx-{runner.execution_device}"
            else:
                candidate.execution_device = "cuda"
                candidate.latency_comparison_group = "pytorch-cuda"
                candidate.generation_config_observed = runner.generation_config_observed
                candidate.decoding_config_applied = runner.decoding_config_applied | {"attention_mask": "processor output"}
                if candidate.model_type == "peft":
                    first_manifest, first_rows = manifest_rows[0]
                    if first_rows:
                        try:
                            candidate.peft_diagnostics, candidate.diagnostic_warnings = runner.diagnose_peft_effect(first_rows[0]["audio"])
                            for warning in candidate.diagnostic_warnings:
                                error_log.write(f"WARNING {candidate.name} eval={first_manifest.name}: {warning}\n")
                        except Exception as exc:
                            candidate.peft_diagnostics = collect_peft_diagnostics(runner.model) | {
                                "diagnostic_error": str(exc),
                                "adapter_effect_max_abs_logit_diff": None,
                                "adapter_effect_mean_abs_logit_diff": None,
                                "adapter_effect_verified": False,
                            }
                            candidate.diagnostic_warnings = ["PEFT adapter effect diagnostic failed"]
                            error_log.write(f"WARNING {candidate.name} eval={first_manifest.name}: PEFT adapter effect diagnostic failed: {exc}\n")
            for manifest, rows in manifest_rows:
                if (candidate.name, manifest.name) in done_keys:
                    continue
                records: list[dict[str, Any]] = []
                for index, row in enumerate(rows, 1):
                    try:
                        text, latency_ms = runner.transcribe(row["audio"])
                        records.append(metric_row(row, text, latency_ms, None, manifest.semantic_metrics))
                    except Exception as exc:
                        message = f"{candidate.name} eval={manifest.name} sample={row['id']}: {exc}"
                        error_log.write(message + "\n")
                        records.append(metric_row(row, "", None, str(exc), manifest.semantic_metrics))
                    print(f"{candidate.name} [{manifest.name}]: {index}/{len(rows)}", flush=True)
                for record in records:
                    record["evaluation_name"] = manifest.name
                candidate_records.extend(records)
                completed.append(summarize(candidate, manifest, records, runner.load_ms, runner.peak_memory_mb()))
        except Exception as exc:
            error_log.write(f"{candidate.name} load: {exc}\n{traceback.format_exc()}\n")
            for manifest, rows in manifest_rows:
                if (candidate.name, manifest.name) in done_keys:
                    continue
                records = [metric_row(row, "", None, f"model load failed: {exc}", manifest.semantic_metrics) for row in rows]
                for record in records:
                    record["evaluation_name"] = manifest.name
                candidate_records.extend(records)
                completed.append(asdict(candidate) | {"evaluation_name": manifest.name, "evaluation_source": manifest.source, "semantic_metrics_available": manifest.semantic_metrics,
                    "sample_count": len(records), "failed_samples": len(records), "error": str(exc), "corpus_cer": None, "corpus_wer": None,
                    "model_load_time_ms": None, "inference_mean_ms": None, "inference_median_ms": None, "inference_p95_ms": None,
                    "menu_recall": None, "quantity_recall": None, "option_recall": None, "peak_cuda_memory_mb": None})
        finally:
            if runner is not None:
                runner.unload()
        existing_path = per_model / f"{candidate.name}.csv"
        existing_records = pd.read_csv(existing_path).to_dict("records") if args.resume and existing_path.exists() else []
        pd.DataFrame(existing_records + candidate_records, columns=["evaluation_name", *PER_SAMPLE_COLUMNS]).to_csv(existing_path, index=False, encoding="utf-8-sig")
        (out / "leaderboard.json").write_text(json.dumps(completed, ensure_ascii=False, indent=2), encoding="utf-8")
    error_log.close()
    set_latency_ranks(completed)
    leaderboard = sorted(completed, key=leaderboard_sort_key)
    pd.DataFrame(leaderboard).to_csv(out / "leaderboard.csv", index=False, encoding="utf-8-sig")
    (out / "leaderboard.json").write_text(json.dumps(leaderboard, ensure_ascii=False, indent=2), encoding="utf-8")
    noise_rows = build_noise_degradation(per_model, {row["name"] for row in completed})
    if noise_rows:
        pd.DataFrame(noise_rows).to_csv(out / "noise_degradation.csv", index=False, encoding="utf-8-sig")
        (out / "noise_degradation.json").write_text(json.dumps(noise_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "candidates.json").write_text(json.dumps([asdict(c) for c in candidates], ensure_ascii=False, indent=2), encoding="utf-8")
    write_metadata(out, candidates, (manifest for manifest, _ in manifests))
    print(f"결과: {out}")


if __name__ == "__main__":
    main()
