import sys
import types
from pathlib import Path

import pandas as pd
import pytest


class _FakeTorch:
    bfloat16 = "bfloat16"
    float16 = "float16"

    @staticmethod
    def inference_mode(func=None):
        if func is not None:
            return func

        def decorator(fn):
            return fn

        return decorator

    class cuda:
        @staticmethod
        def is_available():
            return False

        @staticmethod
        def empty_cache():
            return None

        @staticmethod
        def memory_allocated():
            return 0

        @staticmethod
        def max_memory_allocated():
            return 0

        @staticmethod
        def reset_peak_memory_stats():
            return None

    @staticmethod
    def manual_seed(seed):
        return None

    class backends:
        class cudnn:
            deterministic = False
            benchmark = False


_ORIGINAL_DEPS: dict[str, object] = {}


def _install_fake_deps() -> None:
    for name in ("torch", "transformers"):
        if name in sys.modules:
            _ORIGINAL_DEPS[name] = sys.modules[name]

    fake = types.ModuleType("transformers")
    fake.WhisperForConditionalGeneration = object
    fake.WhisperProcessor = object
    sys.modules["transformers"] = fake

    # CI(ubuntu)에는 torch가 설치되어 있지 않아 mock으로 주입한다.
    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = _FakeTorch.bfloat16
    fake_torch.float16 = _FakeTorch.float16
    fake_torch.inference_mode = _FakeTorch.inference_mode
    fake_torch.cuda = _FakeTorch.cuda
    fake_torch.backends = _FakeTorch.backends
    fake_torch.manual_seed = _FakeTorch.manual_seed
    fake_torch.Tensor = type("Tensor", (), {})  # scipy array API 호환용
    sys.modules["torch"] = fake_torch


def _restore_real_deps() -> None:
    for name in ("torch", "transformers"):
        if name in _ORIGINAL_DEPS:
            sys.modules[name] = _ORIGINAL_DEPS[name]
        elif name in sys.modules:
            del sys.modules[name]


_install_fake_deps()

from scripts.eval.stt.compare_model_sizes import (  # noqa: E402
    build_dataset,
    summarize_corpus,
    transcribe,
)

_restore_real_deps()


class _Args:
    def __init__(self, split, samples=150, seed=42, val_csv=None, test_csv=None):
        self.split = split
        self.samples = samples
        self.seed = seed
        self.val_csv = val_csv
        self.test_csv = test_csv


def _make_split_csv(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    csv_path = tmp_path / f"{name}.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture(autouse=True)
def _patch_split_paths(tmp_path, monkeypatch):
    validation_rows = [
        {"audio_path": "v1.wav", "reference": "안녕하세요"},
        {"audio_path": "v2.wav", "reference": "카페라떼 한 잔"},
    ]
    test_rows = [
        {"audio_path": "t1.wav", "reference": "아메리카노"},
        {"audio_path": "t2.wav", "reference": "자몽에이드"},
    ]
    import scripts.eval.stt.compare_model_sizes as module

    monkeypatch.setattr(
        module, "VALIDATION_CSV", _make_split_csv(tmp_path, "validation", validation_rows)
    )
    monkeypatch.setattr(
        module, "TEST_CSV", _make_split_csv(tmp_path, "test", test_rows)
    )


def test_build_dataset_validation_only(_patch_split_paths) -> None:
    df = build_dataset(_Args("validation", samples=None))

    assert set(df["split"]) == {"validation"}
    assert len(df) == 2


def test_build_dataset_test_only(_patch_split_paths) -> None:
    df = build_dataset(_Args("test", samples=None))

    assert set(df["split"]) == {"test"}
    assert len(df) == 2


def test_build_dataset_both(_patch_split_paths) -> None:
    df = build_dataset(_Args("both", samples=None))

    assert set(df["split"]) == {"validation", "test"}
    assert len(df) == 4


def test_build_dataset_samples_respects_seed(_patch_split_paths) -> None:
    df = build_dataset(_Args("both", samples=2, seed=42))

    assert len(df) == 2


def test_build_dataset_missing_csv_raises(tmp_path, monkeypatch) -> None:
    import scripts.eval.stt.compare_model_sizes as module

    missing = tmp_path / "missing.csv"
    monkeypatch.setattr(module, "VALIDATION_CSV", missing)
    monkeypatch.setattr(module, "TEST_CSV", missing)

    with pytest.raises(FileNotFoundError):
        build_dataset(_Args("validation", samples=None))


def test_summarize_corpus_reports_per_split() -> None:
    rows = pd.DataFrame(
        [
            {"split": "validation"},
            {"split": "validation"},
            {"split": "test"},
        ]
    )
    references = ["안녕하세요", "카페라떼", "아메리카노"]
    results = {
        "medium": {
            "texts": ["안녕하세요", "카페라떼", "아메리카노"],
            "latencies": [0.1, 0.2, 0.3],
            "params_m": 763.9,
            "vram_gb": 1.58,
        }
    }

    summary = summarize_corpus(
        results, ["medium"], references, rows
    )

    assert len(summary) == 2
    validation = next(row for row in summary if row["split"] == "validation")
    test = next(row for row in summary if row["split"] == "test")
    assert validation["n"] == 2
    assert validation["cer"] == 0.0
    assert validation["wer"] == 0.0
    assert validation["latency"] == pytest.approx(0.15)
    assert test["n"] == 1
    assert test["params_m"] == 763.9
    assert test["vram_gb"] == 1.58


def test_summarize_corpus_skips_missing_audio_latency() -> None:
    rows = pd.DataFrame(
        [{"split": "validation"}, {"split": "validation"}]
    )
    references = ["안녕하세요", "카페라떼"]
    results = {
        "medium": {
            "texts": ["안녕하세요", ""],
            "latencies": [0.1, float("nan")],
            "params_m": 763.9,
            "vram_gb": 1.58,
        }
    }

    summary = summarize_corpus(
        results, ["medium"], references, rows
    )

    row = summary[0]
    assert row["cer"] > 0.0  # 누락(빈) 예측은 오류로 집계됨
    assert row["latency"] == pytest.approx(0.1)  # NaN 제외 평균


def test_resolve_audio_path_legacy500_windows_path() -> None:
    from adapters.stt.common import resolve_audio_path

    win_path = r"C:\Users\PC\Downloads\proj1-d\src\adapters\stt\stt_data\preprocessed\st_set1_collectorgs510_speakergs4802_19_12.wav"
    resolved = resolve_audio_path(win_path)
    assert resolved.is_file()
    assert resolved.name == "st_set1_collectorgs510_speakergs4802_19_12.wav"
    assert "legacy500" in resolved.parts


def test_resolve_audio_path_train65() -> None:
    from adapters.stt.common import resolve_audio_path

    legacy_train65 = "/home/honorbear/AI_Human_7th/proj1-d/src/adapters/stt/stt_data/train65_v1/audio/validation/0002e8ace467c0d04408.wav"
    resolved = resolve_audio_path(legacy_train65)
    assert resolved.is_file()
    assert resolved.name == "0002e8ace467c0d04408.wav"
    assert "train65_v1" in resolved.parts


def test_resolve_audio_path_graceful_missing() -> None:
    from adapters.stt.common import resolve_audio_path

    non_existent = r"C:\Some\Fake\Path\non_existent_file_12345.wav"
    resolved = resolve_audio_path(non_existent)
    # FileNotFoundError를 던지지 않고 graceful하게 Path 반환
    assert isinstance(resolved, Path)
    assert not resolved.is_file()


def test_build_dataset_with_custom_csv(tmp_path) -> None:
    custom_val = _make_split_csv(
        tmp_path,
        "custom_val",
        [{"audio_path": "c1.wav", "reference": "커스텀 주문"}],
    )
    df = build_dataset(_Args("validation", samples=None, val_csv=custom_val))
    assert len(df) == 1
    assert df.iloc[0]["reference"] == "커스텀 주문"


def test_actual_validation_csv_resolves_all_audio_files() -> None:
    from adapters.stt.common import VALIDATION_CSV

    if not VALIDATION_CSV.exists():
        pytest.skip("validation.csv가 로컬에 존재하지 않습니다.")

    df = build_dataset(_Args("validation", samples=None, val_csv=VALIDATION_CSV))
    assert len(df) == 77
    for path_str in df["audio_path"]:
        path = Path(path_str)
        assert path.is_file(), f"오디오 파일 누락: {path_str}"


def test_transcribe_passes_attention_mask(monkeypatch) -> None:
    import numpy as np
    import scripts.eval.stt.compare_model_sizes as module

    monkeypatch.setattr(
        module,
        "load_audio",
        lambda p: (np.zeros(16000, dtype=np.float32), 16000),
    )

    captured_kwargs = {}

    class _FakeTensor:
        def __init__(self, name):
            self.name = name

        def to(self, *args, **kwargs):
            return self

    class _FakeInputs:
        def __init__(self):
            self.input_features = _FakeTensor("input_features")
            self.attention_mask = _FakeTensor("attention_mask")

    class _FakeProcessor:
        def __call__(self, audio, sampling_rate, return_attention_mask=False, return_tensors=None):
            assert return_attention_mask is True
            assert return_tensors == "pt"
            return _FakeInputs()

        def batch_decode(self, generated_ids, **kwargs):
            return ["테스트 텍스트"]

    class _FakeParam:
        dtype = "bfloat16"

    class _FakeModel:
        def parameters(self):
            yield _FakeParam()

        def generate(self, **kwargs):
            captured_kwargs.update(kwargs)
            return [[1, 2, 3]]

    model = _FakeModel()
    processor = _FakeProcessor()

    result = transcribe(model, processor, "dummy.wav")
    assert result == "테스트 텍스트"
    assert "attention_mask" in captured_kwargs
    assert captured_kwargs["attention_mask"].name == "attention_mask"
    assert captured_kwargs["language"] == "ko"
    assert captured_kwargs["task"] == "transcribe"
    assert captured_kwargs["max_new_tokens"] == module.MAX_NEW_TOKENS


def test_run_model_uses_dtype_instead_of_torch_dtype(monkeypatch) -> None:
    import scripts.eval.stt.compare_model_sizes as module

    called_kwargs = {}

    class _FakeModelClass:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            called_kwargs.update(kwargs)
            fake_inst = types.SimpleNamespace(
                eval=lambda: None,
                to=lambda device: fake_inst,
                parameters=lambda: iter([types.SimpleNamespace(dtype="bfloat16", numel=lambda: 1000)]),
            )
            return fake_inst

    class _FakeProcessorClass:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            return object()

    monkeypatch.setattr(module, "WhisperForConditionalGeneration", _FakeModelClass)
    monkeypatch.setattr(module, "WhisperProcessor", _FakeProcessorClass)
    monkeypatch.setattr(module, "count_parameters", lambda m: 1000)

    empty_df = pd.DataFrame(columns=["audio_path", "reference", "split"])
    module.run_model("base", empty_df)

    assert "dtype" in called_kwargs
    assert "torch_dtype" not in called_kwargs

