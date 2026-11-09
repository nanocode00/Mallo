# -*- coding: utf-8 -*-
"""merged-bf16(HF) 모델을 CTranslate2 fp16 포맷으로 변환한다.

ctranslate2 4.8 변환기가 transformers 5.x 방식의 ``dtype`` kwarg를 전달하기 때문에
transformers 4.27 환경(.venv-melo)에서는 그대로 실행되지 않는다. 이 스크립트는
WhisperForConditionalGeneration.__init__ 에서 dtype kwarg를 제거하는 호환 패치를
적용한 뒤 변환기 main()을 호출한다.

사용법 (.venv-melo):
    python scripts/convert_stt_ct2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import torch  # noqa: E402
import transformers  # noqa: E402
from transformers.models.whisper.modeling_whisper import (  # noqa: E402
    WhisperForConditionalGeneration,
)

_orig_init = WhisperForConditionalGeneration.__init__


def _compat_init(self, config, *args, **kwargs):
    # transformers 4.x 는 dtype kwarg 미지원( torch_dtype 사용). 변환 목적상
    # 기본 정밀도(float32)로 로드해도 출력 quantization에는 영향이 없다.
    kwargs.pop("dtype", None)
    _orig_init(self, config, *args, **kwargs)


WhisperForConditionalGeneration.__init__ = _compat_init

# ---------------------------------------------------------------------------
# tokenizer 호환: transformers 5.x 포맷의 tokenizer.json 은 구형 tokenizers 가
# 파싱하지 못하므로, hub의 whisper-medium 구형 tokenizer.json 으로 교체해 둔다
# (특수토큰 <|startoftranscript|> 등 전체 어휘가 포함된 fast tokenizer 사용).
# vocab.json / merges.txt 는 slow 폴백용으로 함께 보완한다.
# ---------------------------------------------------------------------------
import urllib.request  # noqa: E402

from transformers import AutoTokenizer  # noqa: E402


def _ensure_slow_tokenizer_files(model_dir: Path) -> None:
    """slow WhisperTokenizer 폴백용 vocab.json/merges.txt 보완."""
    url_tpl = "https://huggingface.co/openai/whisper-medium/resolve/main/{name}?download=true"
    for name in ("vocab.json", "merges.txt"):
        dst = model_dir / name
        if dst.exists() and dst.stat().st_size > 0:
            continue
        print(f"[tokenizer] {name} 다운로드 중: openai/whisper-medium")
        urllib.request.urlretrieve(url_tpl.format(name=name), dst)


from ctranslate2.converters.transformers import main  # noqa: E402

_canonical_model = ROOT / "models" / "stt" / "final-train65-merged-bf16"
_legacy_model = ROOT / "src" / "adapters" / "stt" / "models" / "whisper-medium-qlora-domain" / "merged-bf16"
_target_model = _canonical_model if _canonical_model.exists() else _legacy_model

sys.argv = [
    "ct2-transformers-converter",
    "--model",
    str(_target_model),
    "--output_dir",
    str(_target_model.parent / f"{_target_model.name}-ct2"),
    "--quantization",
    "float16",
]

if __name__ == "__main__":
    model_dir = _target_model
    _ensure_slow_tokenizer_files(model_dir)

    print(f"transformers {transformers.__version__} / torch {torch.__version__}")
    main()
