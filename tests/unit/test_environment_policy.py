from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_python_env import activation_scripts  # noqa: E402


def test_stt_reproduction_python_version_is_recorded() -> None:
    assert (PROJECT_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.11.9"


def test_stt_direct_dependencies_are_declared() -> None:
    requirements = "\n".join(
        (PROJECT_ROOT / "requirements" / name).read_text(encoding="utf-8")
        for name in ("base.txt", "runtime.txt")
    )
    expected = {
        "accelerate",
        "numpy",
        "transformers",
        "av",
    }
    declared = {
        line.strip().split(" @ ")[0].split("==")[0].split(">=")[0].split("<=")[0].lower()
        for line in requirements.splitlines()
        if line.strip() and not line.startswith(("#", "-r"))
    }
    assert expected <= declared


def test_tts_direct_dependencies_are_declared() -> None:
    runtime = "\n".join(
        (PROJECT_ROOT / "requirements" / name).read_text(encoding="utf-8")
        for name in ("base.txt", "runtime.txt")
    )
    expected_common = {
        "librosa",
        "safetensors",
        "scipy",
        "soundfile",
    }
    expected_melo = {
        "accelerate",
        "mecab-python3",
        "melotts",
        "python-mecab-ko",
        "python-mecab-ko-dic",
        "transformers",
    }
    def declared(requirements: str) -> set[str]:
        return {
        line.strip().split(" @ ")[0].split("==")[0].lower()
        for line in requirements.splitlines()
        if line.strip() and not line.startswith(("#", "-r"))
        }

    assert expected_common <= declared(runtime)
    assert expected_melo <= declared(runtime)
    assert "transformers==4.27.4" in runtime


def test_torch_installation_is_documented_as_platform_specific() -> None:
    requirements = (PROJECT_ROOT / "requirements" / "cuda" / "cu128-torch.txt").read_text(encoding="utf-8")
    assert "torch==2.11.0+cu128" in requirements
    assert "cu128" in requirements


def test_activation_script_policy_uses_platform_layout() -> None:
    scripts = activation_scripts(Path(".venvs/dev"))
    assert scripts
    assert all(script.parts[:2] == (".venvs", "dev") for script in scripts)


def test_environment_policy_spec_exists() -> None:
    spec_path = PROJECT_ROOT / "docs" / "specs" / "python-environment.md"
    assert spec_path.is_file()
    content = spec_path.read_text(encoding="utf-8")
    assert "3.11.9" in content
    assert "2.11.0+cu128" in content
    assert "transformers" in content
    assert "팀 논의" in content
