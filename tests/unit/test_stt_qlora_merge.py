import sys
import types
from pathlib import Path

import pytest


class _FakeTensor:
    dtype = "bfloat16"


_FROM_PRETRAINED_CALLS = []


class _FakeModule:
    def __init__(self, name="model"):
        self.name = name
        self._params = [_FakeTensor()]
        self.eval_called = False
        self.saved_to = None
        self.to_device = None
        self.pretrained_args = None

    def parameters(self):
        return iter(self._params)

    def eval(self):
        self.eval_called = True
        return self

    def to(self, device=None, **kwargs):
        if device is not None:
            self.to_device = device
        return self

    def save_pretrained(self, path):
        self.saved_to = str(path)

    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        _FROM_PRETRAINED_CALLS.append(args)
        instance = cls()
        instance.pretrained_args = (args, kwargs)
        return instance


class _FakePeftModel(_FakeModule):
    def merge_and_unload(self):
        self.merge_called = True
        return _FakeModule(name="merged")


class _FakeWhisperProcessor:
    def __init__(self):
        self.pretrained_path = None
        self.saved_to = None

    def save_pretrained(self, path):
        self.saved_to = str(path)

    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        instance = cls()
        instance.pretrained_path = (args, kwargs)
        return instance


class _FakeBitsAndBytesConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeTorch:
    bfloat16 = "bfloat16"
    float16 = "float16"
    float32 = "float32"

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
        def manual_seed_all(seed):
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
    for name in ("torch", "transformers", "peft", "bitsandbytes"):
        if name in sys.modules:
            _ORIGINAL_DEPS[name] = sys.modules[name]

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.WhisperForConditionalGeneration = _FakeModule
    fake_transformers.WhisperProcessor = _FakeWhisperProcessor
    fake_transformers.BitsAndBytesConfig = _FakeBitsAndBytesConfig
    sys.modules["transformers"] = fake_transformers

    fake_peft = types.ModuleType("peft")
    fake_peft.PeftModel = _FakePeftModel
    sys.modules["peft"] = fake_peft

    fake_bnb = types.ModuleType("bitsandbytes")
    sys.modules["bitsandbytes"] = fake_bnb

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
    for name in ("torch", "transformers", "peft", "bitsandbytes"):
        if name in _ORIGINAL_DEPS:
            sys.modules[name] = _ORIGINAL_DEPS[name]
        elif name in sys.modules:
            del sys.modules[name]


_install_fake_deps()

import adapters.stt.common as common  # noqa: E402

# 모듈 import 시점에 require_cuda()/setup_cuda_dll_paths()가 실행되므로
# GPU 없는 CI에서도 통과하도록 미리 패치한다.
common.require_cuda = lambda: "cuda"  # type: ignore[method-assign]
common.setup_cuda_dll_paths = lambda: None  # type: ignore[method-assign]

import scripts.eval.stt.baseline_qlora_compare as baseline_qlora_compare  # noqa: E402
import scripts.models.stt.merge_qlora_adapter as merge_qlora_adapter  # noqa: E402

from scripts.eval.stt.baseline_qlora_compare import (  # noqa: E402
    load_qlora_model,
    load_processor,
)
from scripts.models.stt.merge_qlora_adapter import (  # noqa: E402
    DEFAULT_ADAPTER_PATH,
    OUTPUT_DIR_NAME,
    main,
)

import torch  # noqa: E402

_restore_real_deps()


# ------------------------------------------------------------
# merge_qlora_adapter.py
# ------------------------------------------------------------


def test_default_adapter_path_points_to_speaker_split() -> None:
    assert "whisper-medium-qlora-speaker-split" in str(
        DEFAULT_ADAPTER_PATH
    )


def test_merge_main_saves_model_and_processor(
    monkeypatch, tmp_path
) -> None:
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "merge_qlora_adapter.py",
            "--checkpoint",
            str(adapter_dir),
        ],
    )

    _FROM_PRETRAINED_CALLS.clear()

    main()

    expected_output = adapter_dir.parent / OUTPUT_DIR_NAME
    assert expected_output.is_dir()
    assert _FROM_PRETRAINED_CALLS[0][0] == merge_qlora_adapter.MODEL_ID
    assert _FROM_PRETRAINED_CALLS[1][1] == str(adapter_dir)
    assert len(_FROM_PRETRAINED_CALLS) == 2


# ------------------------------------------------------------
# baseline_qlora_compare.py
# ------------------------------------------------------------


def test_merged_model_loads_bf16_from_bundle() -> None:
    bundle = Path(".") / "merged-bf16"
    model = load_qlora_model(
        bundle,
        merged=True,
        device="cuda",
        eval_dtype=torch.bfloat16,
    )

    assert model.eval_called is True
    assert model.to_device == "cuda"
    assert model.pretrained_args[0][0] == bundle
    actual_dtype = (
        model.pretrained_args[1].get("dtype")
        or model.pretrained_args[1].get("torch_dtype")
    )
    assert (
        actual_dtype
        == torch.bfloat16
    )


def test_nonmerged_model_requires_adapter_files(tmp_path) -> None:
    empty = tmp_path / "adapter"
    empty.mkdir()

    with pytest.raises(FileNotFoundError):
        load_qlora_model(empty, merged=False, device="cuda")


def test_processor_loads_from_bundle_when_merged(tmp_path) -> None:
    bundle = tmp_path / "merged-bf16"
    bundle.mkdir()
    (bundle / "preprocessor_config.json").write_text("{}")

    processor = load_processor(bundle, merged=True)

    assert processor.pretrained_path[0][0] == str(bundle)


def test_processor_falls_back_to_model_id(tmp_path) -> None:
    from scripts.eval.stt.baseline_qlora_compare import MODEL_ID

    bundle = tmp_path / "merged-bf16"
    bundle.mkdir()

    processor = load_processor(bundle, merged=True)

    assert processor.pretrained_path[0][0] == MODEL_ID


def test_processor_nonmerged_uses_model_id(tmp_path) -> None:
    from scripts.eval.stt.baseline_qlora_compare import MODEL_ID

    processor = load_processor(tmp_path / "adapter", merged=False)

    assert processor.pretrained_path[0][0] == MODEL_ID
