import io
import json
import wave
import zipfile
from pathlib import Path

import pytest

from scripts.data.tts.prepare_aihub_friendly import (
    DATASET_DIRNAME,
    collect_records,
    discover_zip_pairs,
    prepare_dataset,
    select_adaptation_package,
    split_by_group,
)


def wav_bytes(seconds: float = 3.5, sample_rate: int = 44_100, channels: int = 1) -> bytes:
    payload = io.BytesIO()
    with wave.open(payload, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * int(seconds * sample_rate) * channels)
    return payload.getvalue()


def write_pair(root: Path, prefix: str, groups: list[dict], wavs: dict[str, bytes]) -> None:
    split = "Training" if prefix == "T" else "Validation"
    label_dir = root / split / "02.라벨링데이터"
    source_dir = root / split / "01.원천데이터"
    label_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(label_dir / f"{prefix}L_친절체_001.zip", "w") as archive:
        archive.writestr("labels.json", json.dumps(groups, ensure_ascii=False))
    with zipfile.ZipFile(source_dir / f"{prefix}S_친절체_001.zip", "w") as archive:
        for name, payload in wavs.items():
            archive.writestr(name, payload)


def group(group_id: str, sentence_id: str, text: str, **overrides: object) -> dict:
    style = {
        "style": overrides.get("style", "친절체"),
        "emotion": overrides.get("emotion", "기쁨"),
    }
    return {
        "id": group_id,
        "reciter": {"id": overrides.get("speaker_id", 10)},
        "src_type": overrides.get("src_type", "매장응대"),
        "sentences": [
            {
                "id": sentence_id,
                "origin_text": text,
                "style": style,
                "voice_piece": {"filename": f"{sentence_id}.wav"},
            }
        ],
    }


@pytest.fixture
def dataset(tmp_path: Path) -> tuple[Path, Path]:
    data_root = (tmp_path / "data" / "tts").resolve()
    dataset_root = data_root / "aihub" / DATASET_DIRNAME
    groups = [
        group("g1", "s1", "첫 번째 안내입니다."),
        group("g2", "s2", "두 번째 안내입니다."),
        group("g3", "s3", "세 번째 안내입니다."),
        group("g4", "s4", "네 번째 안내입니다."),
        group("bad-speaker", "s5", "제외 화자", speaker_id=5),
        group("bad-source", "s6", "제외 유형", src_type="전화상담"),
        group("bad-emotion", "s7", "제외 감정", emotion="분노"),
    ]
    write_pair(dataset_root, "T", groups, {f"s{i}.wav": wav_bytes() for i in range(1, 8)})
    return data_root, dataset_root


def test_discovers_label_source_pairs(dataset: tuple[Path, Path]) -> None:
    _, dataset_root = dataset
    pairs = discover_zip_pairs(dataset_root)
    assert [(label.name[:2], source.name[:2]) for label, source in pairs] == [("TL", "TS")]


def test_filters_and_validates_records(dataset: tuple[Path, Path]) -> None:
    _, dataset_root = dataset
    records, excluded = collect_records(discover_zip_pairs(dataset_root), 10)
    assert [record.sentence_id for record in records] == ["s1", "s2", "s3", "s4"]
    assert excluded == {"speaker": 1, "src_type": 1, "emotion": 1}
    assert all(record.sample_rate == 44_100 and record.channels == 1 for record in records)


def test_split_keeps_recording_groups_disjoint(dataset: tuple[Path, Path]) -> None:
    _, dataset_root = dataset
    records, _ = collect_records(discover_zip_pairs(dataset_root), 10)
    splits = split_by_group(records)
    group_sets = [set(record.recording_group_id for record in values) for values in splits.values()]
    assert all(group_sets[index].isdisjoint(other) for index, group_set in enumerate(group_sets) for other in group_sets[index + 1 :])
    assert all(splits.values())


def test_adaptation_package_uses_closest_group_combination() -> None:
    from scripts.data.tts.prepare_aihub_friendly import Record

    records = [
        Record(f"s{i}", 10, f"g{i}", "안내", duration, 44_100, 1, "source.zip", f"s{i}.wav")
        for i, duration in enumerate((4.0, 6.0, 9.0), start=1)
    ]
    selected = select_adaptation_package(records, target_seconds=10.0)
    assert sum(record.duration_seconds for record in selected) == 10.0


def test_prepare_writes_leakage_safe_manifests(dataset: tuple[Path, Path], tmp_path: Path) -> None:
    data_root, _ = dataset
    output = tmp_path / "derived"
    summary = prepare_dataset(data_root, output, 10, target_seconds=7.0)
    ref_id = summary["adaptation_package"]["ref_audio_id"]

    train_lines = (output / "melotts_train.txt").read_text(encoding="utf-8").splitlines()
    qwen_rows = [json.loads(line) for line in (output / "qwen_train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(ref_id not in line for line in train_lines)
    assert all(ref_id not in row["audio"] for row in qwen_rows)
    assert len({row["ref_audio"] for row in qwen_rows}) == 1
    assert Path(qwen_rows[0]["ref_audio"]).stem == ref_id
    assert json.loads((output / "summary.json").read_text(encoding="utf-8"))["valid_records"] == 4
    assert summary["speakers"] == 1


def test_rejects_non_absolute_data_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="절대"):
        prepare_dataset(Path("data/tts"), tmp_path / "output", 10, target_seconds=3.0)


def test_split_by_group_handles_many_groups_fast() -> None:
    from scripts.data.tts.prepare_aihub_friendly import Record

    records = [
        Record(f"s{i}", 10, f"g{i}", "안내", 5.0, 44_100, 1, "source.zip", f"s{i}.wav")
        for i in range(15)
    ]
    splits = split_by_group(records)
    assert all(splits[name] for name in ("train", "validation", "test"))
    all_assigned = [r.sentence_id for records in splits.values() for r in records]
    assert len(all_assigned) == 15
    assert len(set(all_assigned)) == 15


def test_prepare_relaxes_ref_audio_when_out_of_range(tmp_path: Path) -> None:
    data_root = (tmp_path / "data" / "tts").resolve()
    dataset_root = data_root / "aihub" / DATASET_DIRNAME
    # 3.0~10.0초 범위를 벗어나는 오디오 (예: 1.5초)
    groups = [
        group("g1", "s1", "첫 번째 짧은 안내입니다."),
        group("g2", "s2", "두 번째 짧은 안내입니다."),
        group("g3", "s3", "세 번째 짧은 안내입니다."),
        group("g4", "s4", "네 번째 짧은 안내입니다."),
    ]
    write_pair(dataset_root, "T", groups, {f"s{i}.wav": wav_bytes(seconds=1.5) for i in range(1, 5)})
    output = tmp_path / "derived_relaxed"
    summary = prepare_dataset(data_root, output, 10, target_seconds=3.0)

    assert summary["adaptation_package"]["ref_audio_selection"] == "relaxed_all_durations"
    assert summary["adaptation_package"]["ref_audio_id"] in ["s1", "s2", "s3", "s4"]

