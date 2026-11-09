"""STT 학습 스크립트 진입점 회귀 테스트.

finetune_whisper_qlora.py와 finetune_kiosk.py는 PYTHONPATH=src 없이
파일 경로로 직접 실행하는 것을 공식 진입점으로 지원한다.
직접 실행 시 sys.path[0]은 스크립트 디렉터리이므로, 패키지 경로 import가
유입되면 인자 처리 전에 ModuleNotFoundError로 종료된다.
이 테스트는 PYTHONPATH를 제거한 환경에서 --help 실행이 성공하는지 확인해
그 회귀를 막는다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

STT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "train" / "stt"


def _run_help_without_pythonpath(script: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, str(STT_DIR / script), "--help"],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        cwd=str(STT_DIR),
    )


def test_finetune_whisper_qlora_help_runs_without_pythonpath() -> None:
    result = _run_help_without_pythonpath("finetune_whisper_qlora.py")

    assert result.returncode == 0, result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_finetune_kiosk_help_runs_without_pythonpath() -> None:
    result = _run_help_without_pythonpath("finetune_kiosk.py")

    assert result.returncode == 0, result.stderr
    assert "ModuleNotFoundError" not in result.stderr
