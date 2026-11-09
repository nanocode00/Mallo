from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read_all_lines(file_path: Path) -> list[str]:
    lines = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            ref = file_path.parent / line[3:].strip()
            lines.extend(_read_all_lines(ref))
        else:
            lines.append(line)
    return lines


def test_production_requirements_keep_transformers_runtimes_separate() -> None:
    runtime_lines = _read_all_lines(ROOT / "requirements/runtime.txt")
    nlu_lines = _read_all_lines(ROOT / "requirements/nlu.txt")

    assert any(line.startswith("torch==") and "cu128" in line for line in runtime_lines)
    assert any(line.startswith("transformers==4.27.4") for line in runtime_lines)
    assert any(line.startswith("torch==") and "cu128" in line for line in nlu_lines)
    assert any(line.startswith("transformers==5.15.0") for line in nlu_lines)

    assert not any(line.startswith("peft") for line in nlu_lines)
    assert not any(line.startswith("bitsandbytes") for line in nlu_lines)


def test_runtime_requirements_declare_gateway_stt_and_melo_imports() -> None:
    runtime_lines = _read_all_lines(ROOT / "requirements/runtime.txt")
    for dependency in ("jsonschema>=4.20,<5.0", "av==18.1.0", "soundfile==0.14.0"):
        assert dependency in runtime_lines
    assert any("melotts" in line for line in runtime_lines)
