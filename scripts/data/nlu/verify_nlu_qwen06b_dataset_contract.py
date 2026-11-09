"""Verify the frozen train/validation contract for the Qwen3-0.6B NLU baseline.

This script never opens the test split. Paraphrase-group IDs are not preserved in the
Qwen conversational JSONL, so this verifier checks the frozen split counts/distribution,
sample-ID separation, canonical prompt/targets, and records that group leakage was already
an upstream dataset-build responsibility rather than pretending to re-check unavailable data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.data.nlu.dataset_tooling import TARGET_COUNTS

from adapters.nlu.qwen06b_config import reject_test_path
from adapters.nlu.qwen_training_data import DEFAULT_OUTPUT_DIR, build_system_prompt, canonical_json


EXPECTED_COUNTS = {"train": 2400, "validation": 300}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(path: Path, split: str) -> list[dict[str, Any]]:
    reject_test_path(path, label=split)
    if not path.is_file():
        raise RuntimeError(f"{split} 파일이 없습니다: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise RuntimeError(f"빈 JSONL 행: {path}:{line_number}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"JSONL 파싱 실패: {path}:{line_number}") from error
        if not isinstance(row, dict):
            raise RuntimeError(f"JSONL 행이 객체가 아닙니다: {path}:{line_number}")
        rows.append(row)
    if len(rows) != EXPECTED_COUNTS[split]:
        raise RuntimeError(f"{split} count 불일치: {len(rows)} != {EXPECTED_COUNTS[split]}")
    return rows


def validate_conversation(row: dict[str, Any], *, expected_system: str, split: str) -> None:
    sample_id = row.get("sample_id")
    messages = row.get("messages")
    metadata = row.get("metadata")
    if not isinstance(sample_id, str) or not sample_id:
        raise RuntimeError(f"{split}: sample_id가 없습니다")
    if not isinstance(messages, list) or len(messages) != 3:
        raise RuntimeError(f"{sample_id}: messages는 system/user/assistant 3개여야 합니다")
    if any(not isinstance(message, dict) for message in messages):
        raise RuntimeError(f"{sample_id}: message는 객체여야 합니다")
    if [message.get("role") for message in messages] != ["system", "user", "assistant"]:
        raise RuntimeError(f"{sample_id}: role 순서가 system/user/assistant가 아닙니다")
    if messages[0].get("content") != expected_system:
        raise RuntimeError(f"{sample_id}: canonical system prompt가 아닙니다")
    try:
        user_payload = json.loads(messages[1]["content"])
        assistant_payload = json.loads(messages[2]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{sample_id}: user/assistant JSON 계약 위반") from error
    if set(user_payload) != {"utterance", "cart_before"}:
        raise RuntimeError(f"{sample_id}: user payload key 계약 위반")
    if not isinstance(user_payload["utterance"], str) or not isinstance(user_payload["cart_before"], list):
        raise RuntimeError(f"{sample_id}: user payload type 계약 위반")
    if not isinstance(assistant_payload, (list, dict)):
        raise RuntimeError(f"{sample_id}: assistant target은 JSON array/object여야 합니다")
    if messages[2]["content"] != canonical_json(assistant_payload):
        raise RuntimeError(f"{sample_id}: assistant target이 canonical JSON이 아닙니다")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("label_group"), str):
        raise RuntimeError(f"{sample_id}: metadata.label_group이 없습니다")


def label_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        sorted(
            Counter(row["metadata"]["label_group"] for row in rows).items()
        )
    )


def expected_label_counts(split: str) -> dict[str, int]:
    index = 0 if split == "train" else 1
    return dict(sorted((group, counts[index]) for group, counts in TARGET_COUNTS.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=DEFAULT_OUTPUT_DIR / "train.jsonl")
    parser.add_argument("--validation", type=Path, default=DEFAULT_OUTPUT_DIR / "validation.jsonl")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    train_rows = load_rows(args.train, "train")
    validation_rows = load_rows(args.validation, "validation")
    expected_system = build_system_prompt()
    for row in train_rows:
        validate_conversation(row, expected_system=expected_system, split="train")
    for row in validation_rows:
        validate_conversation(row, expected_system=expected_system, split="validation")

    train_ids = {row["sample_id"] for row in train_rows}
    validation_ids = {row["sample_id"] for row in validation_rows}
    if len(train_ids) != len(train_rows) or len(validation_ids) != len(validation_rows):
        raise RuntimeError("split 내부 sample_id 중복이 있습니다")
    overlap = train_ids & validation_ids
    if overlap:
        raise RuntimeError(f"train/validation sample_id leakage: {sorted(overlap)[:10]}")

    actual_train_labels = label_counts(train_rows)
    actual_validation_labels = label_counts(validation_rows)
    expected_train_labels = expected_label_counts("train")
    expected_validation_labels = expected_label_counts("validation")
    if actual_train_labels != expected_train_labels:
        raise RuntimeError("train label-group 분포가 frozen 2400 계약과 다릅니다")
    if actual_validation_labels != expected_validation_labels:
        raise RuntimeError("validation label-group 분포가 frozen 300 계약과 다릅니다")

    converted_metadata_keys = sorted(
        set().union(
            *(set(row.get("metadata", {})) for row in train_rows + validation_rows)
        )
    )
    paraphrase_ids_available = "paraphrase_group_id" in converted_metadata_keys

    report = {
        "status": "PASS",
        "test_split_opened": False,
        "train": {
            "path": str(args.train),
            "count": len(train_rows),
            "sha256": sha256(args.train),
            "label_counts": actual_train_labels,
        },
        "validation": {
            "path": str(args.validation),
            "count": len(validation_rows),
            "sha256": sha256(args.validation),
            "label_counts": actual_validation_labels,
        },
        "sample_id_overlap": 0,
        "target_distribution_matches": True,
        "converted_metadata_keys": converted_metadata_keys,
        "paraphrase_group_leakage_recheck": (
            "AVAILABLE" if paraphrase_ids_available else "UNAVAILABLE_IN_QWEN_CONVERTED_METADATA"
        ),
        "paraphrase_group_contract_note": (
            "qwen_training_data preserves only label_group/menu_version/source; upstream final dataset build owns paraphrase split leakage validation"
        ),
        "canonical_system_prompt": True,
        "canonical_target_json": True,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        reject_test_path(args.report, label="report")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
