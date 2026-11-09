import random
import sys
from pathlib import Path

from adapters.stt.common import DEFAULT_SEED, set_seed
from scripts.data.stt.split_dataset import extract_speaker


def test_extract_speaker_from_file_name() -> None:
    assert extract_speaker("speakergs01_001.wav") == "speakergs01"


def test_extract_speaker_from_utf8_ascii_file_name() -> None:
    assert extract_speaker("aihub001_speakergs14_0023.wav") == "speakergs14"


def test_extract_speaker_raises_without_speaker() -> None:
    try:
        extract_speaker("no_speaker_in_name.wav")
    except ValueError:
        return
    raise AssertionError("extract_speaker가 ValueError를 던져야 합니다")


def test_default_seed_matches_existing_split() -> None:
    assert DEFAULT_SEED == 42


def test_set_seed_makes_random_shuffle_reproducible() -> None:
    items = list(range(20))

    set_seed(DEFAULT_SEED)
    first = items[:]
    random.shuffle(first)

    set_seed(DEFAULT_SEED)
    second = items[:]
    random.shuffle(second)

    assert first == second
