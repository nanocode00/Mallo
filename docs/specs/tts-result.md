---
title: "C-15 — TTS 입출력 형식 정의"
tags: [spec]
---

# C-15 — TTS 입출력 형식 정의

> 이 문서는 말로(Mallo)의 Adaptive TTS 엔진이 입력받는 파라미터(`response_text`, `tts_level`)와 음성 합성 후 오케스트레이터 및 UI/오디오 재생 모듈에 반환하는 `TTSResult` 기준 계약이다.

## Why

- **페르소나**: Adaptive TTS 개발자(A), 오디오 재생/GUI 개발자(C), 통합 오케스트레이터 개발자
- **상황**:
  - Order Engine에서 생성된 안내 문장(`response_text`)과 세션 상태에 따른 `tts_level`(0~2)을 전달받아 TTS 모델(MeloTTS 등)이 음성을 합성한다.
  - 합성된 오디오는 스피커로 재생되거나 프론트엔드/GUI에 전달되며, 합성 레이턴시(NFR-03) 및 오디오 재생 시간(duration)이 시스템 상태 전이(A-07 Playback 완료 후 Listening 전환 등)에 사용된다.
- **문제**:
  - 인터페이스가 단순 `synthesize(text, level) -> None`으로만 되어 있으면, 오디오 바이트 데이터, 샘플레이트, 재생 길이(`duration_ms`), 합성 지연(`latency_ms`) 등을 캡처할 수 없어 UI 연동, 벤치마크 평가(T-22), 오디오 재생 완료 시점 제어가 불가능하다.
- **측정 지표**:
  - JSON Schema 검증 통과율 100%
  - 오디오 메타데이터(샘플레이트, 길이, 레이턴시) 누락율 0%

## Goal

- **해결 목표**:
  - TTS 입출력 규격인 `TTSResult`와 JSON Schema(`schemas/tts-result.schema.json`)를 정의한다.
  - 입력 파라미터(`text`, `level: 0|1|2`)와 출력 데이터(`audio_bytes`, `sample_rate`, `duration_ms`, `latency_ms`, `level`, `text`)의 구조를 확정한다.
  - `TTS` 프로토콜 인터페이스(`src/interfaces/tts.py`)와 `TTSFailure` 예외 발생 조건을 명시한다.
- **성공 기준**:
  - `schemas/tts-result.schema.json` 스키마 검증 테스트 100% 통과.
  - `TTSResult`, `TTSLevel` 도메인 모델 구현 및 기존 MockTTS 호환.
  - 단위 테스트 및 스키마 유효성 테스트 작성 및 통과.
- **Out of Scope**:
  - 특정 TTS 백엔드 딥러닝 모델의 가중치 로딩
  - 실시간 PCM 오디오 장치 스트리밍 재생 드라이버 구현

## What

### Happy Path (정상 TTS 합성 흐름)

1. Order Engine 또는 오케스트레이터가 `text`와 `level`(0: 기본, 1: 느리게/Pause, 2: 분절/핵심강조)을 TTS 모듈에 전달한다.
2. TTS 모듈은 한국어 음성을 합성하고 `audio` 바이트, `sample_rate`(Hz), `duration_ms`(재생 길이), `latency_ms`(합성 시간), 적용된 `level`, 원본 `text`를 포함하는 `TTSResult`를 생성한다.
3. 스키마 검증기(`validate_tts_result`)가 메타데이터의 형식 유효성을 검증한다.
4. 오디오 재생기가 `audio` 바이트를 스피커로 출력하고, 재생 종료 후 시스템 상태를 `LISTENING` 또는 `IDLE`로 전이한다.

### Edge Cases (최소 5개 + 처리 방식)

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 텍스트가 빈 문자열이거나 공백만 있는 경우 | `ValueError` 발생 또는 무음 `TTSResult(duration_ms=0.0)` 반환 |
| EC-02 | 유효하지 않은 TTS Level (예: -1, 3 등) | Schema 검증에서 거부 (`level`은 0, 1, 2 중 하나여야 함) |
| EC-03 | 모델 메모리 부족(OOM) 또는 합성 실패 | `TTSFailure` 예외 발생 후 파이프라인에서 `TTS_FAILED` 에러 응답 변환 |
| EC-04 | Mock 또는 테스트 환경에서 audio 바이트 미생성 | `audio_base64=null` 허용 (메타데이터만 검증 가능) |
| EC-05 | duration_ms 또는 latency_ms가 음수인 경우 | Schema 검증에서 거부 (>= 0.0) |
| EC-06 | sample_rate가 0 이하인 경우 | Schema 검증에서 거부 (sample_rate >= 8000) |

## How

### 1. TTSResult JSON Schema (`schemas/tts-result.schema.json`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "TTSResult",
  "type": "object",
  "required": [
    "text",
    "level",
    "sample_rate"
  ],
  "properties": {
    "text": {
      "type": "string",
      "description": "합성 대상이 된 원본 또는 Level 변환 텍스트"
    },
    "level": {
      "type": "integer",
      "enum": [0, 1, 2],
      "description": "적용된 Adaptive TTS Level (0: 기본, 1: 속도감소/Pause, 2: 분절강조)"
    },
    "sample_rate": {
      "type": "integer",
      "minimum": 8000,
      "description": "오디오 샘플링 레이트 (Hz, 기본 24000 또는 16000)"
    },
    "duration_ms": {
      "type": ["number", "null"],
      "minimum": 0.0,
      "description": "합성된 오디오의 총 재생 길이 (밀리초)"
    },
    "latency_ms": {
      "type": ["number", "null"],
      "minimum": 0.0,
      "description": "음성 합성에 소요된 처리 시간 (밀리초)"
    },
    "audio_base64": {
      "type": ["string", "null"],
      "description": "Base64로 인코딩된 오디오 바이트 (선택 사항)"
    }
  },
  "additionalProperties": false
}
```

### 2. 도메인 모델 및 프로토콜 정의 (`src/domain/tts_result.py` 및 `src/interfaces/tts.py`)

```python
import base64
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Protocol

class TTSLevel(IntEnum):
    LEVEL_0_DEFAULT = 0
    LEVEL_1_SLOW_PAUSE = 1
    LEVEL_2_CONCISE_EMPHASIS = 2

@dataclass(frozen=True)
class TTSResult:
    text: str
    level: int = 0
    sample_rate: int = 24000
    duration_ms: float | None = None
    latency_ms: float | None = None
    audio: bytes | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "level": self.level,
            "sample_rate": self.sample_rate,
            "duration_ms": self.duration_ms,
            "latency_ms": self.latency_ms,
            "audio_base64": base64.b64encode(self.audio).decode("utf-8") if self.audio else None,
        }

class TTSFailure(RuntimeError):
    """TTS 합성 또는 출력 실패 시 발생하는 예외"""
    pass

class TTS(Protocol):
    def synthesize(self, text: str, level: int = 0) -> TTSResult | None: ...
```

## AC (Given-When-Then)

### AC-01 · 필수 필드 포함 기본 TTSResult 검증
- **GIVEN**: `text="아메리카노 두 잔을 담았습니다."`, `level=0`, `sample_rate=24000`이 주어졌을 때
- **WHEN**: `TTSResult`를 생성하고 스키마를 검증한다
- **THEN**: `schemas/tts-result.schema.json` 스키마 검증을 통과한다.

### AC-02 · 오디오 메타데이터 및 Base64 직렬화 검증
- **GIVEN**: `duration_ms=2100.0`, `latency_ms=180.5`, `audio=b"RIFF..."`가 포함된 `TTSResult`가 주어졌을 때
- **WHEN**: `to_dict()`로 직렬화하고 스키마를 검증한다
- **THEN**: 스키마 검증을 통과하고 `audio_base64`에 유효한 base64 문자열이 포함된다.

### AC-03 · 유효하지 않은 TTS Level 거부
- **GIVEN**: `level` 값이 `-1` 또는 `3`으로 주어졌을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.

### AC-04 · sample_rate 최소값 검증 (8000Hz 이상)
- **GIVEN**: `sample_rate`가 `4000`으로 주어졌을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.

### AC-05 · 미정의 추가 필드 거부
- **GIVEN**: 정의되지 않은 `pitch` 필드가 최상위에 포함된 JSON 데이터가 주어졌을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.
