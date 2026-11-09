"""Qwen3-TTS Fine-tuning 실행 전 데이터와 smoke test 계획을 준비한다."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path


PRIMARY_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
FALLBACK_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
TOKENIZER_MODEL = "Qwen/Qwen3-TTS-Tokenizer-12Hz"
SPEAKER_NAME = "mallo_friendly"
SMOKE_TEXT = "주문하신 음료를 차분하게 안내해 드리겠습니다."
REQUIRED_REPOSITORY_FILES = (
    "finetuning/prepare_data.py",
    "finetuning/sft_12hz.py",
    "finetuning/dataset.py",
)


def _require_absolute_directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f"{label}는 존재하는 절대 디렉터리여야 함: {path}")
    return path.resolve()


def _git_revision(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def validate_qwen_manifest(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"Qwen manifest는 존재하는 절대 파일이어야 함: {path}")
    rows: list[dict[str, str]] = []
    audio_paths: set[str] = set()
    reference_paths: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Qwen manifest {line_number}행 JSON 오류") from error
        if set(row) != {"audio", "text", "ref_audio"}:
            raise ValueError(f"Qwen manifest {line_number}행 필드 오류")
        if not all(isinstance(row[key], str) for key in ("audio", "text", "ref_audio")):
            raise ValueError(f"Qwen manifest {line_number}행 값 타입 오류")
        audio = Path(row["audio"])
        reference = Path(row["ref_audio"])
        if not audio.is_absolute() or not audio.is_file():
            raise ValueError(f"Qwen manifest {line_number}행 audio 경로 오류")
        if not reference.is_absolute() or not reference.is_file():
            raise ValueError(f"Qwen manifest {line_number}행 ref_audio 경로 오류")
        if audio.resolve() == reference.resolve():
            raise ValueError("ref_audio는 일반 학습 audio에서 제외되어야 함")
        if not isinstance(row["text"], str) or not row["text"].strip():
            raise ValueError(f"Qwen manifest {line_number}행 text 오류")
        resolved_audio = str(audio.resolve())
        if resolved_audio in audio_paths:
            raise ValueError(f"Qwen manifest audio 중복: {resolved_audio}")
        audio_paths.add(resolved_audio)
        reference_paths.add(str(reference.resolve()))
        rows.append({"audio": resolved_audio, "text": row["text"], "ref_audio": str(reference.resolve())})
    if len(rows) < 2:
        raise ValueError("Qwen smoke test에는 최소 2개 레코드가 필요함")
    if len(reference_paths) != 1:
        raise ValueError("모든 Qwen 학습 행은 동일한 ref_audio를 사용해야 함")
    return rows, reference_paths.pop()


def validate_paired_records(melotts_manifest: Path, qwen_rows: list[dict[str, str]]) -> None:
    if not melotts_manifest.is_absolute() or not melotts_manifest.is_file():
        raise ValueError("MeloTTS train manifest는 존재하는 절대 파일이어야 함")
    melo_pairs: list[tuple[str, str]] = []
    for line_number, line in enumerate(
        melotts_manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        fields = line.split("|", 3)
        if len(fields) != 4:
            raise ValueError(f"MeloTTS manifest {line_number}행 형식 오류")
        audio, speaker, language, text = fields
        if speaker != "10" or language != "KR":
            raise ValueError("MeloTTS manifest의 화자·언어 계약 오류")
        melo_pairs.append((str(Path(audio).resolve()), text))
    qwen_pairs = [(row["audio"], row["text"]) for row in qwen_rows]
    if melo_pairs != qwen_pairs:
        raise ValueError("MeloTTS와 Qwen3-TTS paired training records가 일치하지 않음")


def prepare_run_plan(qwen_repository: Path, derived_root: Path, run_root: Path) -> dict[str, object]:
    repository = _require_absolute_directory(qwen_repository, "Qwen3-TTS 저장소")
    derived = _require_absolute_directory(derived_root, "T-25 파생 데이터 경로")
    if not run_root.is_absolute():
        raise ValueError("run 경로는 절대 경로여야 함")
    for relative in REQUIRED_REPOSITORY_FILES:
        if not (repository / relative).is_file():
            raise ValueError(f"Qwen3-TTS 공식 파일 누락: {relative}")

    qwen_manifest = (derived / "qwen_train.jsonl").resolve()
    rows, reference_audio = validate_qwen_manifest(qwen_manifest)
    validate_paired_records((derived / "melotts_train.txt").resolve(), rows)
    normalized_training_texts = {" ".join(row["text"].split()) for row in rows}
    if " ".join(SMOKE_TEXT.split()) in normalized_training_texts:
        raise ValueError("smoke 추론 문장이 학습 데이터와 중복됨")

    run_root.mkdir(parents=True, exist_ok=True)
    smoke_raw = run_root / "smoke-raw.jsonl"
    smoke_raw.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows[:2]),
        encoding="utf-8",
    )
    smoke_text = run_root / "smoke-text.txt"
    smoke_text.write_text(SMOKE_TEXT + "\n", encoding="utf-8")

    finetuning = repository / "finetuning"
    smoke_codes = run_root / "smoke-with-codes.jsonl"
    smoke_output = run_root / "smoke-output"
    full_codes = run_root / "train-with-codes.jsonl"
    primary_model_path = run_root / "models" / "Qwen3-TTS-12Hz-0.6B-Base"
    q = shlex.quote
    commands = {
        "prepare_smoke": (
            f"cd {q(str(finetuning))} && python prepare_data.py --device cuda:0 "
            f"--tokenizer_model_path {q(TOKENIZER_MODEL)} --input_jsonl {q(str(smoke_raw))} "
            f"--output_jsonl {q(str(smoke_codes))}"
        ),
        "train_smoke": (
            f"cd {q(str(finetuning))} && python sft_12hz.py "
            f"--init_model_path {q(str(primary_model_path))} "
            f"--output_model_path {q(str(smoke_output))} --train_jsonl {q(str(smoke_codes))} "
            f"--batch_size 2 --lr 2e-5 --num_epochs 1 --speaker_name {q(SPEAKER_NAME)}"
        ),
        "infer_smoke": (
            "PYTHONPATH=src python -m adapters.tts.qwen_custom_voice_inference "
            f"--model {q(str(smoke_output / 'checkpoint-epoch-0'))} "
            f"--text-file {q(str(smoke_text))} --output {q(str(run_root / 'smoke-output.wav'))} "
            f"--speaker {q(SPEAKER_NAME)}"
        ),
        "prepare_full_data": (
            f"cd {q(str(finetuning))} && python prepare_data.py --device cuda:0 "
            f"--tokenizer_model_path {q(TOKENIZER_MODEL)} --input_jsonl {q(str(qwen_manifest))} "
            f"--output_jsonl {q(str(full_codes))}"
        ),
    }
    plan = {
        "status": "SMOKE_PREPARED_NOT_EXECUTED",
        "qwen3_tts_revision": _git_revision(repository),
        "repository": str(repository),
        "models": {
            "primary": {"id": PRIMARY_MODEL, "required_local_path": str(primary_model_path)},
            "fallback": FALLBACK_MODEL,
            "tokenizer": TOKENIZER_MODEL,
        },
        "manifest": {
            "path": str(qwen_manifest),
            "records": len(rows),
            "reference_audio": reference_audio,
            "paired_with_melotts": True,
        },
        "smoke_test": {
            "records": 2,
            "batch_size": 2,
            "epochs": 1,
            "speaker_name": SPEAKER_NAME,
            "inference_uses_reference_audio": False,
        },
        "full_training": {
            "status": "BLOCKED_UNTIL_MAX_STEP_CONTROL_IS_IMPLEMENTED",
            "decision_step": 2000,
            "maximum_step": 5000,
            "reason": "공식 sft_12hz.py는 num_epochs만 받고 optimizer max_steps를 지원하지 않음",
        },
        "commands": commands,
        "notes": [
            "Python 환경 확정 전에는 명령을 실행하지 않음",
            "공식 SFT checkpoint 저장은 초기 모델 디렉터리를 복사하므로 primary를 required_local_path에 먼저 다운로드",
            "0.6B smoke 실패 시 원인과 revision 기록 후 자원 한도 안에서만 1.7B 시도",
            "zero-shot 결과는 Fine-tuned 비교 결과로 사용하지 않음",
            "smoke checkpoint 재로딩 후 generate_custom_voice로 참조 음성 없이 합성",
        ],
    }
    (run_root / "run-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen3-TTS T-27 실행 준비")
    parser.add_argument("--qwen-repository", type=Path, required=True)
    parser.add_argument("--derived-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    result = prepare_run_plan(args.qwen_repository, args.derived_root, args.run_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
