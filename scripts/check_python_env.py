"""Validate the repository Python environment without importing GPU libraries."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VENVS = {
    "core": (PROJECT_ROOT / ".venvs" / "dev",),
    "stt": (PROJECT_ROOT / ".venvs" / "runtime",),
    "training": (PROJECT_ROOT / ".venvs" / "dev",),
    "tts-melo": (PROJECT_ROOT / ".venvs" / "runtime",),
    "tts-qwen": (PROJECT_ROOT / ".venvs" / "dev",),
}
CORE_MODULES = ("jsonschema", "pytest")
STT_MODULES = (
    "accelerate",
    "bitsandbytes",
    "datasets",
    "evaluate",
    "faster_whisper",
    "jiwer",
    "noisereduce",
    "numpy",
    "pandas",
    "peft",
    "scipy",
    "soundfile",
    "torch",
    "transformers",
)
TTS_COMMON_MODULES = (
    "accelerate",
    "librosa",
    "scipy",
    "soundfile",
    "torch",
    "transformers",
)


def activation_scripts(venv: Path) -> tuple[Path, ...]:
    if os.name == "nt":
        return (
            venv / "Scripts" / "Activate.ps1",
            venv / "Scripts" / "activate.bat",
        )
    return (venv / "bin" / "activate",)


def validate(scope: str) -> list[str]:
    errors: list[str] = []
    version = sys.version_info[:3]
    resolved_prefix = Path(sys.prefix).resolve()

    expected_venvs = EXPECTED_VENVS[scope]
    if resolved_prefix not in {venv.resolve() for venv in expected_venvs}:
        errors.append(f"저장소 가상환경이 아닙니다: {resolved_prefix}")

    if version[:2] not in {(3, 11), (3, 12)}:
        errors.append(f"지원하지 않는 Python 버전입니다: {version[0]}.{version[1]}.{version[2]}")

    if scope != "core" and version != (3, 11, 9):
        errors.append(
            "프로젝트 학습/실험 기준 환경은 Python 3.11.9입니다: "
            f"현재 {version[0]}.{version[1]}.{version[2]}"
        )

    scripts = activation_scripts(Path(sys.prefix))
    missing_scripts = [str(script) for script in scripts if not script.is_file()]
    if missing_scripts:
        errors.append(f"활성화 스크립트가 없습니다: {', '.join(missing_scripts)}")

    if scope == "stt":
        scope_modules = STT_MODULES
    elif scope == "tts-melo":
        scope_modules = TTS_COMMON_MODULES + ("melo",)
    elif scope == "tts-qwen":
        scope_modules = TTS_COMMON_MODULES + ("qwen_tts",)
    elif scope == "training":
        scope_modules = STT_MODULES
    else:
        scope_modules = ()

    modules = CORE_MODULES + scope_modules
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if missing:
        errors.append(f"설치되지 않은 {scope} 의존성: {', '.join(missing)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scope",
        choices=("core", "stt", "training", "tts-melo", "tts-qwen"),
        nargs="?",
        default="core",
    )
    args = parser.parse_args()

    print(f"Python: {sys.version.split()[0]}")
    print(f"Environment: {Path(sys.prefix).resolve()}")
    print(f"Scope: {args.scope}")

    errors = validate(args.scope)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print("환경을 지운 뒤 문서의 생성 명령으로 다시 만드는 것이 가장 안전합니다.", file=sys.stderr)
        return 1

    print("Environment check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
