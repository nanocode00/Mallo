"""MeloTTS Fine-tuning 실행 전 입력과 설정을 검증한다.

Python 환경 확정 전에도 실행 계획을 만들 수 있지만 설치, 전처리, 학습 자체는
수행하지 않는다. 원본 데이터와 checkpoint는 읽기만 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
from pathlib import Path


REQUIRED_REPOSITORY_FILES = (
    "melo/preprocess_text.py",
    "melo/train.py",
    "melo/infer.py",
    "melo/configs/config.json",
)
PRETRAIN_FILES = ("G.pth", "D.pth", "DUR.pth")


def _require_absolute_directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f"{label}는 존재하는 절대 디렉터리여야 함: {path}")
    return path.resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(path: Path) -> dict[str, object]:
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"manifest는 존재하는 절대 파일이어야 함: {path}")
    audio_paths: set[str] = set()
    speakers: set[str] = set()
    languages: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = line.split("|", 3)
        if len(fields) != 4:
            raise ValueError(f"manifest {line_number}행 형식 오류: {path}")
        audio, speaker, language, text = fields
        if not Path(audio).is_absolute() or not Path(audio).is_file():
            raise ValueError(f"manifest {line_number}행 WAV 경로 오류: {audio}")
        if not speaker or language != "KR" or not text.strip():
            raise ValueError(f"manifest {line_number}행 필드 오류: {path}")
        if audio in audio_paths:
            raise ValueError(f"manifest 내 WAV 중복: {audio}")
        audio_paths.add(audio)
        speakers.add(speaker)
        languages.add(language)
    if not audio_paths:
        raise ValueError(f"빈 manifest: {path}")
    return {
        "path": str(path.resolve()),
        "records": len(audio_paths),
        "speakers": sorted(speakers),
        "languages": sorted(languages),
        "audio_paths": audio_paths,
    }


def _git_revision(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def prepare_run_plan(
    melotts_repository: Path,
    derived_root: Path,
    pretrain_root: Path,
    baseline_checkpoint: Path,
    run_root: Path,
) -> dict[str, object]:
    repository = _require_absolute_directory(melotts_repository, "MeloTTS 저장소")
    derived = _require_absolute_directory(derived_root, "T-25 파생 데이터 경로")
    pretrain = _require_absolute_directory(pretrain_root, "사전학습 가중치 경로")
    if not run_root.is_absolute():
        raise ValueError("run 경로는 절대 경로여야 함")
    for relative in REQUIRED_REPOSITORY_FILES:
        if not (repository / relative).is_file():
            raise ValueError(f"MeloTTS 공식 파일 누락: {relative}")
    if not baseline_checkpoint.is_absolute() or not baseline_checkpoint.is_file():
        raise ValueError("한국어 Baseline checkpoint가 필요함")

    train = validate_manifest((derived / "melotts_train.txt").resolve())
    validation = validate_manifest((derived / "melotts_validation.txt").resolve())
    if train["speakers"] != validation["speakers"] or train["speakers"] != ["10"]:
        raise ValueError("train/validation은 목표 화자 10번 한 명만 포함해야 함")
    if train["audio_paths"] & validation["audio_paths"]:
        raise ValueError("train/validation WAV가 중복됨")

    weights: dict[str, dict[str, object]] = {}
    for filename in PRETRAIN_FILES:
        path = (pretrain / filename).resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"사전학습 가중치 누락 또는 빈 파일: {filename}")
        weights[filename] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    run_root.mkdir(parents=True, exist_ok=True)
    melo_dir = repository / "melo"
    q = shlex.quote
    train_cleaned = run_root / "train.cleaned.list"
    validation_cleaned = run_root / "validation.cleaned.list"
    config_path = run_root / "config.json"
    commands = {
        "preprocess_train": (
            f"cd {q(str(melo_dir))} && python preprocess_text.py "
            f"--metadata {q(str(train['path']))} --cleaned-path {q(str(train_cleaned))} "
            f"--train-path {q(str(run_root / 'train.preprocessed.list'))} "
            f"--val-path {q(str(run_root / 'unused-train-val.list'))} "
            "--val-per-spk 0 --max-val-total 0"
        ),
        "preprocess_validation": (
            f"cd {q(str(melo_dir))} && python preprocess_text.py "
            f"--metadata {q(str(validation['path']))} --cleaned-path {q(str(validation_cleaned))} "
            f"--train-path {q(str(run_root / 'unused-validation-train.list'))} "
            f"--val-path {q(str(run_root / 'validation.preprocessed.list'))} "
            "--val-per-spk 100000 --max-val-total 100000"
        ),
        "finalize_config": (
            "PYTHONPATH=src python -m adapters.tts.prepare_melotts_training finalize-config "
            f"--base-config {q(str(melo_dir / 'configs/config.json'))} "
            f"--train-list {q(str(run_root / 'train.preprocessed.list'))} "
            f"--validation-list {q(str(run_root / 'validation.preprocessed.list'))} "
            f"--output {q(str(config_path))}"
        ),
        "train": (
            f"cd {q(str(melo_dir))} && torchrun --nproc_per_node=1 --master_port=10902 "
            f"train.py --c {q(str(config_path))} --model mallo-friendly "
            f"--pretrain_G {q(weights['G.pth']['path'])} "
            f"--pretrain_D {q(weights['D.pth']['path'])} "
            f"--pretrain_dur {q(weights['DUR.pth']['path'])}"
        ),
    }
    plan = {
        "status": "PREPARED_NOT_EXECUTED",
        "melotts_revision": _git_revision(repository),
        "repository": str(repository),
        "baseline_checkpoint": {
            "path": str(baseline_checkpoint.resolve()),
            "sha256": _sha256(baseline_checkpoint),
        },
        "pretrained_weights": weights,
        "manifests": {
            "train": {key: value for key, value in train.items() if key != "audio_paths"},
            "validation": {key: value for key, value in validation.items() if key != "audio_paths"},
        },
        "training_contract": {
            "seed": 42,
            "learning_rate": 0.0001,
            "batch_size": 4,
            "eval_interval": 500,
            "skip_optimizer": True,
            "decision_step": 2000,
            "maximum_step": 5000,
        },
        "commands": commands,
        "notes": [
            "Python 환경 확정 전에는 명령을 실행하지 않음",
            "공식 preprocess_text.py의 재분할을 피하려고 고정 split을 각각 전처리함",
            "공식 train.sh는 무한 auto-resume이므로 step 제한 실험에 사용하지 않음",
            "학습 시작 전 G/D/DUR 로딩 로그 세 줄과 shape mismatch를 보존함",
        ],
    }
    (run_root / "run-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return plan


def finalize_config(base_config: Path, train_list: Path, validation_list: Path, output: Path) -> None:
    for path in (base_config, train_list, validation_list):
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"설정 입력은 존재하는 절대 파일이어야 함: {path}")
    config = json.loads(base_config.read_text(encoding="utf-8"))
    config["train"].update(
        seed=42,
        learning_rate=0.0001,
        batch_size=4,
        eval_interval=500,
        skip_optimizer=True,
    )
    config["data"].update(
        training_files=str(train_list.resolve()),
        validation_files=str(validation_list.resolve()),
        sampling_rate=44_100,
        n_speakers=1,
        spk2id={"10": 0},
        cleaned_text=True,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="MeloTTS T-26 실행 준비")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--melotts-repository", type=Path, required=True)
    plan.add_argument("--derived-root", type=Path, required=True)
    plan.add_argument("--pretrain-root", type=Path, required=True)
    plan.add_argument("--baseline-checkpoint", type=Path, required=True)
    plan.add_argument("--run-root", type=Path, required=True)
    finalize = subparsers.add_parser("finalize-config")
    finalize.add_argument("--base-config", type=Path, required=True)
    finalize.add_argument("--train-list", type=Path, required=True)
    finalize.add_argument("--validation-list", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        result = prepare_run_plan(
            args.melotts_repository,
            args.derived_root,
            args.pretrain_root,
            args.baseline_checkpoint,
            args.run_root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        finalize_config(args.base_config, args.train_list, args.validation_list, args.output)


if __name__ == "__main__":
    main()
