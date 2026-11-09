from __future__ import annotations


class AudioInputError(RuntimeError):
    """마이크 캡처 장치/라이브러리를 사용할 수 없을 때 발생."""


class NoSpeechError(RuntimeError):
    """최대 녹음 시간 동안 발화가 감지되지 않았을 때 발생."""


class BufferLimitError(RuntimeError):
    """AudioBuffer가 최대 녹음 시간을 초과했을 때 발생."""
