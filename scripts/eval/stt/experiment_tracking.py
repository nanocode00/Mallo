"""실험 재현성 유틸리티.

체크포인트 재개 경로 해석과 split CSV 해시 계산을 제공한다.
torch 등 무거운 의존성 없이 단위 테스트 가능하도록 순수 Python으로 유지한다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def resolve_resume_checkpoint(resume_arg: str | None, output_dir: Path) -> str | None:
    """--resume-from-checkpoint 값을 존재가 확인된 절대 경로 문자열로 해석한다.

    상대 경로는 output_dir 기준으로 해석한다. 경로가 존재하지 않으면 None을
    반환해 학습을 처음부터 시작한다. Trainer에는 반드시 이 함수의 반환값을
    전달해야 실행 cwd와 무관하게 올바른 체크포인트에서 재개한다.
    """
    if not resume_arg:
        return None
    path = Path(resume_arg)
    if not path.is_absolute():
        path = output_dir / path
    if not path.exists():
        return None
    return str(path)


def compute_split_hash(csv_path: Path) -> str:
    """split CSV 파일 내용의 MD5 해시를 계산한다.

    학습과 평가가 동일한 split을 사용했는지 추적하기 위한 값이다.
    """
    return hashlib.md5(csv_path.read_bytes()).hexdigest()
