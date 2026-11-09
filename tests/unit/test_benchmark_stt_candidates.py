import hashlib
import importlib.util
import json
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/eval/stt/benchmark_stt_candidates.py"
SPEC = importlib.util.spec_from_file_location("benchmark_stt_candidates", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def _adapter(directory: Path, contents: bytes = b"adapter") -> Path:
    directory.mkdir(parents=True)
    (directory / "adapter_model.safetensors").write_bytes(contents)
    (directory / "adapter_config.json").write_text(json.dumps({"base_model_name_or_path": "openai/whisper-medium"}))
    return directory


def test_discovery_prefers_top_level_adapter_over_qlora_checkpoints(tmp_path: Path) -> None:
    models = tmp_path / "models"
    _adapter(models / "whisper-medium-qlora-kiosk-test", b"top")
    _adapter(models / "whisper-medium-qlora-kiosk-test/checkpoint-200", b"old")
    _adapter(models / "whisper-medium-qlora-kiosk-test/checkpoint-600", b"new")
    _adapter(models / "experiment-smoke", b"smoke")
    _adapter(models / "checkpoint_backups/checkpoint-900", b"backup")

    candidates = benchmark.discover_peft_candidates(models)

    assert [Path(c.path) for c in candidates] == [models / "whisper-medium-qlora-kiosk-test"]
    assert candidates[0].selection_reason == "top-level adapter"


def test_discovery_uses_largest_checkpoint_only_without_top_level_adapter(tmp_path: Path) -> None:
    models = tmp_path / "models"
    _adapter(models / "whisper-medium-qlora/lr-2e-05/checkpoint-200", b"old")
    final = _adapter(models / "whisper-medium-qlora/lr-2e-05/checkpoint-600", b"new")

    candidates = benchmark.discover_peft_candidates(models)

    assert [Path(c.path) for c in candidates] == [final]
    assert candidates[0].selection_reason == "largest checkpoint"


def test_discovery_records_duplicate_adapter_without_dropping_audit_entry(tmp_path: Path) -> None:
    models = tmp_path / "models"
    first = _adapter(models / "first", b"same")
    second = _adapter(models / "second", b"same")

    candidates = benchmark.discover_peft_candidates(models)

    assert len(candidates) == 2
    assert candidates[0].adapter_sha256 == hashlib.sha256(b"same").hexdigest()
    assert candidates[1].duplicate_of == candidates[0].name
    assert {Path(c.path) for c in candidates} == {first, second}


def test_non_qlora_experiment_keeps_top_level_adapter(tmp_path: Path) -> None:
    models = tmp_path / "models"
    top = _adapter(models / "whisper-medium-train65-golden-v1", b"final")
    _adapter(models / "whisper-medium-train65-golden-v1/checkpoint-44", b"older")

    candidates = benchmark.discover_peft_candidates(models)

    assert [Path(c.path) for c in candidates] == [top]
    assert candidates[0].selection_reason == "top-level adapter"


def test_filter_supports_include_and_exclude() -> None:
    candidates = [
        benchmark.Candidate("baseline-openai-whisper-medium", "baseline"),
        benchmark.Candidate("peft-kiosk", "peft", path="/models/kiosk"),
    ]

    assert [c.name for c in benchmark.filter_candidates(candidates, ["kiosk"], [])] == ["peft-kiosk"]
    assert benchmark.filter_candidates(candidates, [], ["baseline", "kiosk"]) == []


def test_latency_rank_is_partitioned_by_runtime_and_device() -> None:
    rows = [
        {"name": "pytorch", "latency_comparison_group": "pytorch-cuda", "inference_p95_ms": 100.0, "corpus_cer": 0.1, "corpus_wer": 0.2, "menu_recall": 0.8},
        {"name": "onnx-cpu", "latency_comparison_group": "onnx-cpu", "inference_p95_ms": 80.0, "corpus_cer": 0.1, "corpus_wer": 0.2, "menu_recall": 0.8},
        {"name": "onnx-cuda", "latency_comparison_group": "onnx-cuda", "inference_p95_ms": 90.0, "corpus_cer": 0.1, "corpus_wer": 0.2, "menu_recall": 0.8},
    ]

    benchmark.set_latency_ranks(rows)

    assert [row["latency_rank"] for row in rows] == [1, 1, 1]
    assert benchmark.leaderboard_sort_key(rows[0]) < benchmark.leaderboard_sort_key(rows[1])


def test_generic_manifest_uses_required_columns_and_ignores_prior_results(tmp_path: Path) -> None:
    csv_path = tmp_path / "golden.csv"
    csv_path.write_text(
        "sample_id,audio_path,reference,hypothesis,latency_sec\n"
        "sample-1,/tmp/audio.wav,정답,이전 결과,0.12\n",
        encoding="utf-8",
    )

    manifest, data = benchmark.load_generic_eval_csv(csv_path, "clean-kiosk")

    assert manifest.name == "clean-kiosk"
    assert manifest.semantic_metrics is False
    assert data.to_dict("records") == [{"id": "sample-1", "audio_path": "/tmp/audio.wav", "text": "정답"}]


def test_generic_metrics_keep_semantic_recalls_as_na() -> None:
    record = benchmark.metric_row(
        {"id": "sample-1", "text": "정답"}, "정답", 10.0, None, semantic_metrics=False
    )
    manifest = benchmark.EvalManifest("clean-kiosk", Path("golden.csv"), False, "generic-csv")
    summary = benchmark.summarize(benchmark.Candidate("baseline", "baseline"), manifest, [record], 1.0, 2.0)

    assert record["menu_recall"] is None
    assert record["quantity_recall"] is None
    assert record["option_recall"] is None
    assert summary["menu_recall"] is None
    assert summary["semantic_metrics_available"] is False


def test_noise_degradation_uses_overlapping_ids_and_corpus_cer(tmp_path: Path) -> None:
    per_model = tmp_path / "per_model"
    per_model.mkdir()
    pd = benchmark.pd
    pd.DataFrame([
        {"evaluation_name": "clean-kiosk", "id": "shared", "reference": "가나다", "hypothesis": "가나다"},
        {"evaluation_name": "clean-kiosk", "id": "clean-only", "reference": "라마바사", "hypothesis": "라마바사"},
        {"evaluation_name": "cafe15", "id": "shared", "reference": "가나다", "hypothesis": "가나"},
        {"evaluation_name": "cafe15", "id": "noise-only", "reference": "라마바사", "hypothesis": "오류"},
    ]).to_csv(per_model / "candidate.csv", index=False)

    rows = benchmark.build_noise_degradation(per_model, ["candidate"])

    assert rows[0]["clean_overlap_samples"] == 2
    assert rows[0]["cafe15_overlap_samples"] == 1
    assert rows[0]["clean_cer"] == 0.0
    assert rows[0]["cafe15_cer"] > 0.0
    assert rows[0]["cafe15_vs_clean_cer_increase"] > 0.0


def test_benchmark_generation_config_is_deepcopied_and_common() -> None:
    class Config:
        language = "en"
        task = "translate"
        max_new_tokens = 10
        do_sample = True
        num_beams = 4
        num_return_sequences = 3
        return_timestamps = True
        forced_decoder_ids = [[1, 999]]
        suppress_tokens = [1, 2, 3]
        begin_suppress_tokens = [220, 50257]

    original = Config()
    config = benchmark.build_benchmark_generation_config(original)

    assert config is not original
    assert (config.language, config.task, config.max_new_tokens) == ("ko", "transcribe", benchmark.MAX_NEW_TOKENS)
    assert (config.do_sample, config.num_beams, config.num_return_sequences) == (False, 1, 1)
    assert config.return_timestamps is False
    assert config.forced_decoder_ids is None
    assert config.suppress_tokens == [1, 2, 3]
    assert config.begin_suppress_tokens == [220, 50257]
    assert original.language == "en"
    assert original.forced_decoder_ids == [[1, 999]]


def test_generate_kwargs_put_suppress_tokens_only_in_generation_config() -> None:
    config = object()
    kwargs = benchmark.build_generate_kwargs("features", "mask", config)

    assert kwargs == {"input_features": "features", "attention_mask": "mask", "generation_config": config}
    assert "suppress_tokens" not in kwargs
    assert "begin_suppress_tokens" not in kwargs


def test_inner_default_fallback_context_restores_original_generation_config() -> None:
    class Config:
        transformers_version = "5.15.0"
        suppress_tokens = [1, 2]

    class Model:
        def __init__(self) -> None:
            self.generation_config = Config()

    model = Model()
    original = model.generation_config

    with benchmark.disable_inner_model_default_fallback(model):
        assert model.generation_config is not original
        assert model.generation_config.transformers_version == "4.49.0"
        assert model.generation_config.suppress_tokens == [1, 2]

    assert model.generation_config is original
    assert original.transformers_version == "5.15.0"


def test_peft_diagnostics_capture_active_adapter_lora_size_and_zero_effect_warning() -> None:
    class Parameter:
        def __init__(self, count: int, value: float) -> None:
            self.count = count
            self.value = value

        def numel(self) -> int:
            return self.count

        def detach(self):
            return self

        def abs(self):
            return self

        def sum(self):
            return self

        def item(self) -> float:
            return self.count * self.value

    class Module:
        lora_A = object()

    class Config:
        peft_type = "LORA"
        base_model_name_or_path = "openai/whisper-medium"

    class Model:
        active_adapters = ["default"]
        peft_config = {"default": Config()}

        def named_modules(self):
            return [("encoder.layers.0.self_attn.q_proj", Module())]

        def named_parameters(self):
            return [
                ("encoder.layers.0.self_attn.q_proj.lora_A.default.weight", Parameter(4, 2.0)),
                ("encoder.layers.0.self_attn.q_proj.lora_B.default.weight", Parameter(3, 1.0)),
                ("encoder.layers.0.self_attn.q_proj.weight", Parameter(99, 9.0)),
            ]

    diagnostics = benchmark.collect_peft_diagnostics(Model())

    assert diagnostics["active_adapters"] == ["default"]
    assert diagnostics["peft_type"] == "LORA"
    assert diagnostics["base_model_name_or_path"] == "openai/whisper-medium"
    assert diagnostics["lora_module_count"] == 1
    assert diagnostics["adapter_parameter_count"] == 7
    assert diagnostics["adapter_parameter_abs_sum"] == 11.0
    assert diagnostics["diagnostic_error"] is None
    assert benchmark.adapter_effect_verdict(0.0, 0.0) == (False, ["adapter effect logits are exactly zero; verify adapter activation and checkpoint compatibility"])
    assert benchmark.adapter_effect_verdict(0.1, 0.01) == (True, [])


def test_adapter_logit_effect_records_verification_and_zero_warning() -> None:
    import torch

    same, warnings = benchmark.summarize_adapter_logit_effect(torch.tensor([[1.0, 2.0]]), torch.tensor([[1.0, 2.0]]))
    changed, no_warnings = benchmark.summarize_adapter_logit_effect(torch.tensor([[1.0, 2.0]]), torch.tensor([[1.0, 1.5]]))

    assert same["adapter_effect_verified"] is False
    assert same["adapter_effect_max_abs_logit_diff"] == 0.0
    assert warnings
    assert changed["adapter_effect_verified"] is True
    assert changed["adapter_effect_max_abs_logit_diff"] == 0.5
    assert no_warnings == []


def test_teacher_forced_whisper_forward_never_passes_input_ids() -> None:
    kwargs = benchmark.build_teacher_forced_whisper_kwargs("features", "mask", "decoder-prefix")

    assert kwargs == {
        "input_features": "features",
        "attention_mask": "mask",
        "decoder_input_ids": "decoder-prefix",
        "use_cache": False,
        "return_dict": True,
    }
    assert "input_ids" not in kwargs


def test_metadata_keeps_peft_diagnostic_schema(tmp_path: Path) -> None:
    candidate = benchmark.Candidate(
        "peft-kiosk", "peft", peft_diagnostics={"active_adapters": ["default"], "adapter_effect_verified": True},
        diagnostic_warnings=[], decoding_config_applied={"forced_decoder_ids_actual": None, "attention_mask_passed_to_generate": True},
    )
    manifest = benchmark.EvalManifest("clean-kiosk", Path("golden.csv"), False, "generic-csv")

    benchmark.write_metadata(tmp_path, [candidate], [manifest])
    metadata = json.loads((tmp_path / "metadata.json").read_text())

    model = metadata["models"][0]
    assert model["peft_diagnostics"]["adapter_effect_verified"] is True
    assert model["decoding_config_applied"]["forced_decoder_ids_actual"] is None
