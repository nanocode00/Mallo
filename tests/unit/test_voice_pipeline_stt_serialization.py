from __future__ import annotations

import threading
import time

from adapters.nlu.mock_nlu import MockNLU
from adapters.tts.mock_tts import MockTTS
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.stt_result import STTResult
from orchestrator.voice_pipeline import VoicePipeline


class BlockingSTT:
    def __init__(self) -> None:
        self._state_guard = threading.Lock()
        self.entry_count = 0
        self.proceed = threading.Event()

    def transcribe(self, audio: bytes, language: str = "ko") -> STTResult:
        with self._state_guard:
            self.entry_count += 1
            is_first_entry = self.entry_count == 1
        if is_first_entry:
            assert self.proceed.wait(timeout=5.0), "첫 STT 호출이 해제되지 않았습니다."
        return STTResult(text="카페라떼", confidence=1.0, duration_ms=1.0, is_final=True)


def build_pipeline(stt: BlockingSTT) -> VoicePipeline:
    return VoicePipeline(
        nlu=MockNLU(),
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
        stt=stt,
    )


def entry_count(stt: BlockingSTT) -> int:
    with stt._state_guard:
        return stt.entry_count


def wait_for_entries(stt: BlockingSTT, count: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if entry_count(stt) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"STT 진입 {count}회를 기다리다 시간 초과")


def test_concurrent_transcribe_audio_serializes_stt_access() -> None:
    stt = BlockingSTT()
    pipeline = build_pipeline(stt)
    results: dict[str, STTResult] = {}

    def worker(key: str) -> None:
        results[key] = pipeline.transcribe_audio(b"fake-audio")

    first = threading.Thread(target=worker, args=("first",))
    second = threading.Thread(target=worker, args=("second",))
    first.start()
    wait_for_entries(stt, 1)

    second.start()
    second.join(timeout=0.5)

    assert first.is_alive(), "첫 호출이 아직 STT 안에서 대기 중이어야 합니다."
    assert entry_count(stt) == 1, "락 없이 두 번째 호출이 STT에 동시 진입했습니다."

    stt.proceed.set()
    first.join(timeout=5.0)
    second.join(timeout=5.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert results["first"].text == "카페라떼"
    assert results["second"].text == "카페라떼"
    assert entry_count(stt) == 2


def test_lock_released_after_transcribe_audio_completes() -> None:
    stt = BlockingSTT()
    stt.proceed.set()
    pipeline = build_pipeline(stt)

    first_result = pipeline.transcribe_audio(b"fake-audio")
    second_result = pipeline.transcribe_audio(b"fake-audio")

    assert first_result.text == "카페라떼"
    assert second_result.text == "카페라떼"
    assert entry_count(stt) == 2
