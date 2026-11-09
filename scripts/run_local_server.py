# -*- coding: utf-8 -*-
"""Mallo 로컬 실모델 통합 테스트 서버 런처.

- STT: Faster-Whisper(CTranslate2, merged-bf16-ct2)
- TTS: MeloTTS 친절체(G_2800.pth, speaker 10)
- NLU: MockNLU(규칙 기반)

.venvs/runtime 단일 환경에서 실행한다. ctranslate2 GPU 추론에 필요한 cuDNN/cuBLAS는
torch가 번들한 DLL을 PATH로 제공한다. MeloTTS 한국어 경로의 Windows 의존성
(japanese cleaner의 MeCab, g2pkk의 eunjeon)은 python-mecab-ko 기반 스텁으로 우회한다.

사용법:
    .venvs\\runtime\\Scripts\\python.exe scripts/run_local_server.py ^
        --stt fastwhisper --stt-model <ct2 디렉터> --tts melo ...
"""
from __future__ import annotations

import importlib.machinery
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# ---------------------------------------------------------------------------
# GPU DLL 경로
# 1) nvidia-cudnn-cu12 휠의 cuDNN 9.x (ctranslate2 가 요구하는 cudnnGetLibConfig
#    등 심볼 보유) 를 최우선 배치
# 2) torch 번들 cuBLAS 12 는 폴백으로 제공
# 순서가 바뀌면 torch 번들 구버전 cuDNN 이 로드되어 ctranslate2 가 크래시한다.
# ---------------------------------------------------------------------------
_sp = ROOT / ".venvs" / "runtime" / "Lib" / "site-packages"
_cudnn_bin = _sp / "nvidia" / "cudnn" / "bin"
_torch_lib = _sp / "torch" / "lib"
prepend = []
if _cudnn_bin.is_dir():
    prepend.append(str(_cudnn_bin))
if _torch_lib.is_dir():
    prepend.append(str(_torch_lib))
if prepend:
    os.environ["PATH"] = os.pathsep.join(prepend) + os.pathsep + os.environ.get("PATH", "")

# ---------------------------------------------------------------------------
# MeCab 계열 우회 (한국어 합성 경로에는 미사용)
# 1) melo.text.japanese 가 모듈 레벨에서 MeCab.Tagger()를 요구 -> 더미 스텁
# 2) g2pkk 가 Windows에서 요구하는 eunjeon -> python-mecab-ko로 대체
# ---------------------------------------------------------------------------
_mecab_stub = types.ModuleType("MeCab")


class _DummyTagger:
    def parse(self, text):
        raise RuntimeError("MeCab stub: Japanese pipeline is not used")


_mecab_stub.Tagger = lambda *args, **kwargs: _DummyTagger()
_mecab_stub.__spec__ = importlib.machinery.ModuleSpec("MeCab", None)
sys.modules["MeCab"] = _mecab_stub

from mecab import MeCab as _KoMeCab  # noqa: E402

_eunjeon_stub = types.ModuleType("eunjeon")
_eunjeon_stub.Mecab = _KoMeCab
_eunjeon_stub.__spec__ = importlib.machinery.ModuleSpec("eunjeon", None)
sys.modules["eunjeon"] = _eunjeon_stub

from app.server import main  # noqa: E402

if __name__ == "__main__":
    # 환경 통일 가드: Windows venv는 런처가 베이스 인터프리터를 자식 실행하므로
    # exe 경로가 아니라 sys.prefix(실제 사용 중인 site-packages 위치)로 판별한다.
    expected_prefix = str((ROOT / ".venvs" / "runtime").resolve())
    if not str(Path(sys.prefix).resolve()).startswith(expected_prefix):
        print(
            "[run_local_server] 잘못된 인터프리터입니다:\n"
            f"  현재 prefix: {sys.prefix}\n"
            f"  기대 prefix: {expected_prefix}\n"
            "scripts/run_local_real.bat 를 사용해 주세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    main()
