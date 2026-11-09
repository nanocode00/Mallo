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
            return True

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


class _FakeWhisperProcessor:
    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        return cls()

    def __call__(self, *args, **kwargs):
        return types.SimpleNamespace(
            input_features=types.SimpleNamespace(to=lambda *a, **k: None),
            attention_mask=types.SimpleNamespace(to=lambda *a, **k: None),
        )

    def batch_decode(self, *args, **kwargs):
        return [""]


class _FakeWhisperModel:
    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        inst = cls()
        inst.eval = lambda: None
        inst.to = lambda device: inst
        return inst

    def parameters(self):
        yield types.SimpleNamespace(dtype="bfloat16")


_ORIGINAL_DEPS: dict[str, object] = {}


def _install_fake_deps() -> None:
    for name in ("torch", "transformers", "peft", "bitsandbytes"):
        if name in sys.modules:
            _ORIGINAL_DEPS[name] = sys.modules[name]

    fake_trans = types.ModuleType("transformers")
    fake_trans.WhisperForConditionalGeneration = _FakeWhisperModel
    fake_trans.WhisperProcessor = _FakeWhisperProcessor
    fake_trans.BitsAndBytesConfig = object
    sys.modules["transformers"] = fake_trans

    fake_peft = types.ModuleType("peft")
    fake_peft.PeftModel = object
    sys.modules["peft"] = fake_peft

    fake_bnb = types.ModuleType("bitsandbytes")
    sys.modules["bitsandbytes"] = fake_bnb

    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = _FakeTorch.bfloat16
    fake_torch.float16 = _FakeTorch.float16
    fake_torch.inference_mode = _FakeTorch.inference_mode
    fake_torch.cuda = _FakeTorch.cuda
    fake_torch.backends = _FakeTorch.backends
    fake_torch.manual_seed = _FakeTorch.manual_seed
    fake_torch.Tensor = type("Tensor", (), {})
    sys.modules["torch"] = fake_torch


def _restore_real_deps() -> None:
    for name in ("torch", "transformers", "peft", "bitsandbytes"):
        if name in _ORIGINAL_DEPS:
            sys.modules[name] = _ORIGINAL_DEPS[name]
        elif name in sys.modules:
            del sys.modules[name]
    sys.modules.pop("scripts.eval.stt.baseline_qlora_compare", None)


_install_fake_deps()

from scripts.eval.stt.baseline_qlora_compare import (  # noqa: E402
    build_dataset,
    transcribe,
    load_qlora_model,
    FINAL_MERGED_PATH,
    MAX_NEW_TOKENS,
)

_restore_real_deps()


class _Args:
    def __init__(self, split="validation", samples=None, seed=42, val_csv=None, test_csv=None):
        self.split = split
        self.samples = samples
        self.seed = seed
        self.val_csv = val_csv
        self.test_csv = test_csv


def _make_split_csv(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    csv_path = tmp_path / f"{name}.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path


def test_final_merged_path_exists() -> None:
    assert FINAL_MERGED_PATH.exists(), f"FINAL_MERGED_PATH does not exist: {FINAL_MERGED_PATH}"
    assert (FINAL_MERGED_PATH / "model.safetensors").exists()


def test_build_dataset_with_mock_csv(tmp_path) -> None:
    val_csv = _make_split_csv(
        tmp_path,
        "mock_val",
        [
            {"audio_path": "a1.wav", "reference": "카페라떼"},
            {"audio_path": "a2.wav", "reference": "아메리카노"},
        ],
    )
    df = build_dataset(_Args("validation", samples=None, val_csv=val_csv))
    assert len(df) == 2
    assert set(df["split"]) == {"validation"}


def test_actual_validation_resolves_all_audio_files() -> None:
    from adapters.stt.common import VALIDATION_CSV

    if not VALIDATION_CSV.exists():
        pytest.skip("validation.csv가 존재하지 않습니다.")

    df = build_dataset(_Args("validation", samples=None, val_csv=VALIDATION_CSV))
    assert len(df) == 77
    for path_str in df["audio_path"]:
        assert Path(path_str).is_file(), f"오디오 파일 누락: {path_str}"


def test_transcribe_passes_attention_mask(monkeypatch) -> None:
    import numpy as np
    import scripts.eval.stt.baseline_qlora_compare as module

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

    result = module.transcribe(model, processor, "dummy.wav")
    assert result == "테스트 텍스트"
    assert "attention_mask" in captured_kwargs
    assert captured_kwargs["attention_mask"].name == "attention_mask"
    assert captured_kwargs["language"] == "ko"
    assert captured_kwargs["task"] == "transcribe"
    assert captured_kwargs["max_new_tokens"] == MAX_NEW_TOKENS


def test_load_qlora_model_uses_dtype_for_merged(monkeypatch, tmp_path) -> None:
    import scripts.eval.stt.baseline_qlora_compare as module

    called_kwargs = {}

    class _FakeModelClass:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            called_kwargs.update(kwargs)
            fake_inst = types.SimpleNamespace(
                eval=lambda: None,
                to=lambda device: fake_inst,
            )
            return fake_inst

    monkeypatch.setattr(module, "WhisperForConditionalGeneration", _FakeModelClass)

    res = module.load_qlora_model(tmp_path, merged=True, device="cpu", eval_dtype="bfloat16")
    assert "dtype" in called_kwargs
    assert "torch_dtype" not in called_kwargs
    assert called_kwargs["dtype"] == "bfloat16"
