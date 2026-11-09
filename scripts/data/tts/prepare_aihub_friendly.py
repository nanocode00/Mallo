"""AI Hub 71349 친절체 데이터를 TTS 학습 형식으로 준비한다.

원본 ZIP은 수정하지 않으며, 선택된 WAV와 원문 포함 manifest는 로컬 전용
``data/tts/derived/aihub-71349`` 아래에 생성한다.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import shutil
import wave
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from statistics import median
from typing import Iterable


DATASET_DIRNAME = "133.감성 및 발화 스타일 동시 고려 음성합성 데이터"
TARGET_STYLE = "친절체"
TARGET_SOURCE_TYPE = "매장응대"
TARGET_EMOTION = "기쁨"
LANGUAGE_CODE = "KR"


@dataclass(frozen=True)
class Record:
    sentence_id: str
    speaker_id: int
    recording_group_id: str
    text: str
    duration_seconds: float
    sample_rate: int
    channels: int
    source_zip: str
    source_member: str


def _zip_index(path: Path, suffix: str) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(suffix)]
    index: dict[str, str] = {}
    for member in members:
        basename = Path(member).name
        if basename in index:
            raise ValueError(f"ZIP 내부 파일명 중복: {path.name}:{basename}")
        index[basename] = member
    return index


def discover_zip_pairs(dataset_root: Path) -> list[tuple[Path, Path]]:
    """TL/VL 라벨 ZIP과 같은 번호의 TS/VS 원천 ZIP을 찾는다."""
    labels = sorted(dataset_root.rglob("[TV]L_친절체_*.zip"))
    pairs: list[tuple[Path, Path]] = []
    for label_zip in labels:
        source_name = ("TS" if label_zip.name.startswith("TL") else "VS") + label_zip.name[2:]
        matches = list(dataset_root.rglob(source_name))
        if len(matches) != 1:
            raise FileNotFoundError(f"원천 ZIP 쌍을 하나로 결정할 수 없음: {source_name}")
        pairs.append((label_zip, matches[0]))
    if not pairs:
        raise FileNotFoundError(f"친절체 라벨 ZIP을 찾지 못함: {dataset_root}")
    return pairs


def _wav_metadata(payload: bytes) -> tuple[float, int, int]:
    with wave.open(io.BytesIO(payload), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        duration = wav.getnframes() / sample_rate
    return duration, sample_rate, channels


def collect_records(
    pairs: Iterable[tuple[Path, Path]], target_speaker_id: int
) -> tuple[list[Record], Counter[str]]:
    """조건에 맞는 레코드를 수집하고 제외 사유를 집계한다."""
    records: list[Record] = []
    excluded: Counter[str] = Counter()
    seen_text: set[tuple[int, str]] = set()
    seen_sentence_ids: set[str] = set()

    for label_zip, source_zip in pairs:
        wav_index = _zip_index(source_zip, ".wav")
        with zipfile.ZipFile(label_zip) as labels, zipfile.ZipFile(source_zip) as sources:
            for json_member in sorted(name for name in labels.namelist() if name.endswith(".json")):
                groups = json.loads(labels.read(json_member))
                if not isinstance(groups, list):
                    raise ValueError(f"JSON 최상위가 배열이 아님: {label_zip.name}:{json_member}")
                for group in groups:
                    speaker_id = group.get("reciter", {}).get("id")
                    if speaker_id != target_speaker_id:
                        excluded["speaker"] += len(group.get("sentences", []))
                        continue
                    if group.get("src_type") != TARGET_SOURCE_TYPE:
                        excluded["src_type"] += len(group.get("sentences", []))
                        continue
                    group_id = str(group.get("id", "")).strip()
                    if not group_id:
                        excluded["recording_group_id"] += len(group.get("sentences", []))
                        continue
                    for sentence in group.get("sentences", []):
                        style = sentence.get("style", {})
                        if style.get("style") != TARGET_STYLE:
                            excluded["style"] += 1
                            continue
                        if style.get("emotion") != TARGET_EMOTION:
                            excluded["emotion"] += 1
                            continue
                        text = str(sentence.get("origin_text", "")).strip()
                        if not text or "|" in text or "\n" in text or "\r" in text:
                            excluded["text"] += 1
                            continue
                        sentence_id = str(sentence.get("id", "")).strip()
                        if not sentence_id:
                            excluded["sentence_id"] += 1
                            continue
                        if sentence_id in seen_sentence_ids:
                            excluded["duplicate_sentence_id"] += 1
                            continue
                        dedupe_key = (target_speaker_id, " ".join(text.split()))
                        if dedupe_key in seen_text:
                            excluded["duplicate"] += 1
                            continue
                        filename = Path(sentence.get("voice_piece", {}).get("filename", "")).name
                        member = wav_index.get(filename)
                        if not member:
                            excluded["missing_wav"] += 1
                            continue
                        try:
                            duration, sample_rate, channels = _wav_metadata(sources.read(member))
                        except (EOFError, ValueError, ZeroDivisionError, wave.Error):
                            excluded["broken_wav"] += 1
                            continue
                        if channels != 1:
                            excluded["channels"] += 1
                            continue
                        if sample_rate != 44_100:
                            excluded["sample_rate"] += 1
                            continue
                        seen_text.add(dedupe_key)
                        seen_sentence_ids.add(sentence_id)
                        records.append(
                            Record(
                                sentence_id=sentence_id,
                                speaker_id=target_speaker_id,
                                recording_group_id=group_id,
                                text=text,
                                duration_seconds=duration,
                                sample_rate=sample_rate,
                                channels=channels,
                                source_zip=str(source_zip.resolve()),
                                source_member=member,
                            )
                        )
    return records, excluded


def split_by_group(records: list[Record], seed: int = 42) -> dict[str, list[Record]]:
    """한 녹음 그룹이 둘 이상의 split에 들어가지 않게 시간 기준 분할한다."""
    grouped: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        grouped[record.recording_group_id].append(record)
    if len(grouped) < 3:
        raise ValueError("train/validation/test 분할에는 녹음 그룹이 최소 3개 필요함")

    groups = sorted(grouped.items())
    random.Random(seed).shuffle(groups)
    if len(groups) > 16:
        raise ValueError("최적 그룹 분할 탐색은 녹음 그룹 16개 이하만 지원함")

    group_durations = [sum(r.duration_seconds for r in items) for _, items in groups]
    total = sum(r.duration_seconds for r in records)
    targets = {"train": total * 0.90, "validation": total * 0.05, "test": total * 0.05}
    names = ("train", "validation", "test")
    target_vals = [targets[name] for name in names]
    n = len(groups)

    best_assignment: list[int] | None = None
    best_score: tuple[float, float] = (float("inf"), float("inf"))

    suffix_sum = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix_sum[i] = suffix_sum[i + 1] + group_durations[i]

    current_assignment = [0] * n
    current_durations = [0.0, 0.0, 0.0]

    def search(idx: int, used_mask: int) -> None:
        nonlocal best_assignment, best_score

        if idx == n:
            if used_mask != 7:
                return
            errors = [abs(current_durations[i] - target_vals[i]) for i in range(3)]
            score = (sum(errors), max(errors))
            if score < best_score:
                best_score = score
                best_assignment = list(current_assignment)
            return

        unused_count = 3 - bin(used_mask).count("1")
        if n - idx < unused_count:
            return

        current_min_err = 0.0
        for i in range(3):
            if current_durations[i] > target_vals[i]:
                current_min_err += current_durations[i] - target_vals[i]
            elif current_durations[i] + suffix_sum[idx] < target_vals[i]:
                current_min_err += target_vals[i] - (current_durations[i] + suffix_sum[idx])

        if current_min_err > best_score[0]:
            return

        for split_idx in (0, 1, 2):
            current_assignment[idx] = split_idx
            current_durations[split_idx] += group_durations[idx]
            search(idx + 1, used_mask | (1 << split_idx))
            current_durations[split_idx] -= group_durations[idx]

    search(0, 0)
    assert best_assignment is not None
    assigned: dict[str, list[Record]] = {name: [] for name in names}
    for split_index, (_, group_records) in zip(best_assignment, groups):
        assigned[names[split_index]].extend(group_records)
    return assigned


def select_adaptation_package(train: list[Record], target_seconds: float, seed: int = 42) -> list[Record]:
    grouped: dict[str, list[Record]] = defaultdict(list)
    for record in train:
        grouped[record.recording_group_id].append(record)
    groups = [items for _, items in sorted(grouped.items())]
    random.Random(seed).shuffle(groups)
    if len(groups) > 20:
        raise ValueError("최적 adaptation package 탐색은 녹음 그룹 20개 이하만 지원함")

    durations = [sum(r.duration_seconds for r in group) for group in groups]
    candidates: list[tuple[float, tuple[int, ...]]] = []
    for included in product(range(2), repeat=len(groups)):
        if not any(included):
            continue
        duration = sum(value for selected, value in zip(included, durations) if selected)
        candidates.append((abs(target_seconds - duration), included))
    _, selected_groups = min(candidates)
    selected = [record for included, group in zip(selected_groups, groups) if included for record in group]
    if sum(r.duration_seconds for r in selected) < target_seconds * 0.90:
        raise ValueError("목표 길이의 90% 이상인 adaptation package를 구성할 수 없음")
    return selected


def _extract(record: Record, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(record.source_zip) as archive, archive.open(record.source_member) as source:
        with destination.open("wb") as output:
            shutil.copyfileobj(source, output)
    return destination.resolve()


def prepare_dataset(
    data_root: Path,
    output_root: Path,
    target_speaker_id: int,
    target_seconds: float = 1_800.0,
    seed: int = 42,
) -> dict[str, object]:
    dataset_root = data_root / "aihub" / DATASET_DIRNAME
    if not data_root.is_absolute() or not dataset_root.is_dir():
        raise ValueError("MALLO_TTS_DATA_ROOT는 데이터셋을 포함한 절대 data/tts 경로여야 함")
    if output_root == dataset_root or dataset_root in output_root.parents:
        raise ValueError("출력 경로는 AI Hub 원본 데이터 디렉터리 밖이어야 함")

    pairs = discover_zip_pairs(dataset_root)
    records, excluded = collect_records(pairs, target_speaker_id)
    splits = split_by_group(records, seed)
    package = select_adaptation_package(splits["train"], target_seconds, seed)
    ref_candidates = [record for record in package if 3.0 <= record.duration_seconds <= 10.0]
    ref_selection_method = "standard_range_3_to_10_sec"
    if not ref_candidates:
        if not package:
            raise ValueError("adaptation package가 비어 있어 참조 오디오(ref_audio)를 선택할 수 없음")
        ref_candidates = list(package)
        ref_selection_method = "relaxed_all_durations"

    ref_audio = min(
        ref_candidates,
        key=lambda record: (abs(record.duration_seconds - 6.5), record.sentence_id),
    )
    paired_ids = {record.sentence_id for record in package if record != ref_audio}

    extracted: dict[str, Path] = {}
    for split_name, split_records in splits.items():
        for record in split_records:
            path = output_root / "audio" / split_name / f"{record.sentence_id}.wav"
            extracted[record.sentence_id] = _extract(record, path)

    output_root.mkdir(parents=True, exist_ok=True)
    for split_name, split_records in splits.items():
        usable = [record for record in split_records if split_name != "train" or record.sentence_id in paired_ids]
        with (output_root / f"melotts_{split_name}.txt").open("w", encoding="utf-8") as manifest:
            for record in usable:
                manifest.write(f"{extracted[record.sentence_id]}|{record.speaker_id}|{LANGUAGE_CODE}|{record.text}\n")
        with (output_root / f"qwen_{split_name}.jsonl").open("w", encoding="utf-8") as manifest:
            for record in usable:
                row = {"audio": str(extracted[record.sentence_id]), "text": record.text}
                if split_name == "train":
                    row["ref_audio"] = str(extracted[ref_audio.sentence_id])
                manifest.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "seed": seed,
        "target_speaker_id": target_speaker_id,
        "zip_pairs": len(pairs),
        "scanned_records": len(records) + sum(excluded.values()),
        "valid_records": len(records),
        "valid_duration_seconds": sum(r.duration_seconds for r in records),
        "speakers": len({r.speaker_id for r in records}),
        "text_length_characters": {
            "min": min(len(r.text) for r in records),
            "max": max(len(r.text) for r in records),
            "median": median(len(r.text) for r in records),
            "average": sum(len(r.text) for r in records) / len(records),
        },
        "excluded": dict(sorted(excluded.items())),
        "splits": {
            name: {
                "records": len(items),
                "duration_seconds": sum(r.duration_seconds for r in items),
                "groups": len({r.recording_group_id for r in items}),
            }
            for name, items in splits.items()
        },
        "adaptation_package": {
            "records": len(package),
            "paired_training_records": len(paired_ids),
            "duration_seconds": sum(r.duration_seconds for r in package),
            "ref_audio_id": ref_audio.sentence_id,
            "ref_audio_duration_seconds": ref_audio.duration_seconds,
            "ref_audio_selection": ref_selection_method,
        },
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Hub 71349 친절체 TTS 데이터 준비")
    parser.add_argument("--output", type=Path, default=Path("data/tts/derived/aihub-71349"))
    parser.add_argument("--target-seconds", type=float, default=1_800.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    data_root_value = os.environ.get("MALLO_TTS_DATA_ROOT")
    speaker_value = os.environ.get("MALLO_TTS_TARGET_SPEAKER_ID")
    if not data_root_value or not speaker_value:
        parser.error("MALLO_TTS_DATA_ROOT와 MALLO_TTS_TARGET_SPEAKER_ID가 필요함")
    summary = prepare_dataset(
        Path(data_root_value), args.output.resolve(), int(speaker_value), args.target_seconds, args.seed
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
