---
title: "C-12 — STT 반환 형식 정의"
tags: [spec, stt]
---

# C-12 — STT 반환 형식 정의

> 이 문서는 STT 모듈이 음성 입력을 텍스트로 변환한 후 NLU, 도메인 보정(Post-processing), 오케스트레이터에 전달하는 `STTResult` 기준 계약이다.

## Why

- **페르소나**: STT/Audio 개발자, 도메인 후처리/Candidate Matching 개발자, NLU 개발자, 오케스트레이터 개발자
- **상황**:
  - 마이크 및 오디오 버퍼로부터 음성(WAV/PCM 바이트)을 입력받아 STT 모델이 텍스트로 변환한다.
  - 이 과정에서 인식된 텍스트 외에도 신뢰도 점수(`confidence`), 오디오 처리 시간(`duration_ms`), 대체 인식 후보군(`alternatives`) 등 중요한 메타데이터가 생성된다.
- **문제**:
  - STT 인터페이스가 단순 `str`로만 제한되어 있으면, 신뢰도가 너무 낮을 때 재입력을 유도하는 Confidence Threshold 정책(S-16)이나, 유사 발음 메뉴명을 교정하는 도메인 보정(S-15 Candidate Matching), Latency 구간 측정(I-08)을 적용할 수 없다.
- **측정 지표**:
  - JSON Schema 검증 통과율 100%
  - STT 신뢰도 및 후보군 메타데이터 전달 정확도 100%

## Goal

- **해결 목표**:
  - STT의 출력 데이터 구조인 `STTResult`와 JSON Schema(`schemas/stt-result.schema.json`)를 정의한다.
  - `text` 필수 필드와 `confidence`, `duration_ms`, `language`, `alternatives`, `is_final` 메타데이터 필드를 확정한다.
  - STT 오류 시 발생시킬 `STTFailure` 예외와 실패 처리 계약을 정립한다.
- **성공 기준**:
  - `schemas/stt-result.schema.json` 스키마 검증 테스트 100% 통과.
  - `STTResult` 도메인 모델 및 `STT` 프로토콜 정의 완료.
  - 단위 테스트 및 스키마 유효성 테스트 작성 및 통과.
- **Out of Scope**:
  - 특정 STT 모델(Whisper, SenseVoice 등) 내부 가중치 로딩
  - 실시간 스트리밍 Partial Transcription (MVP는 자동 Listening 또는 수동 마이크 Fallback에서 VAD가 발화를 종료한 뒤 1회 전송)

## What

### Happy Path (정상 STT 변환 흐름)

1. Audio Buffer가 16kHz 모노 WAV 오디오 바이트를 STT 모듈에 전달한다.
2. STT 모듈은 음성을 전사하고 최종 텍스트(`text`), 신뢰도 점수(`confidence`), 소요 시간/길이(`duration_ms`), 다중 인식 후보군(`alternatives`)을 포함한 `STTResult`를 생성한다.
3. 스키마 검증기(`validate_stt_result`)를 통해 형식 유효성을 검증한다.
4. NLU 및 Domain Post-processing 모듈이 `STTResult.text`와 `alternatives`를 기반으로 주문 의도를 파악하고 메뉴 후보를 매칭한다.

### Edge Cases (최소 5개 + 처리 방식)

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 무음 또는 발화가 전혀 없는 오디오 입력 | `text=""`, `confidence=0.0`인 `STTResult` 반환 또는 `EMPTY_INPUT` 에러 유도 |
| EC-02 | 신뢰도 점수를 제공하지 않는 STT 백엔드 | `confidence=None` 허용 |
| EC-03 | 단일 후보만 존재하는 경우 | `alternatives=()` (빈 배열) 반환 |
| EC-04 | 비정상적인 음성 데이터 또는 디코딩 실패 | `STTFailure` 예외 발생 후 파이프라인에서 `STT_FAILED` 에러 응답 변환 |
| EC-05 | 0.0 미만 또는 1.0 초과의 confidence 값 | Schema 검증에서 거부 (0.0 <= confidence <= 1.0) |
| EC-06 | duration_ms가 음수인 경우 | Schema 검증에서 거부 (duration_ms >= 0.0) |

## How

### 1. STTResult JSON Schema (`schemas/stt-result.schema.json`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "STTResult",
  "type": "object",
  "required": [
    "text",
    "language",
    "is_final"
  ],
  "properties": {
    "text": {
      "type": "string",
      "description": "STT 모델이 전사한 최종 한국어 텍스트"
    },
    "confidence": {
      "type": ["number", "null"],
      "minimum": 0.0,
      "maximum": 1.0,
      "description": "전사 신뢰도 점수 (0.0 ~ 1.0), 모델이 미제공 시 null"
    },
    "duration_ms": {
      "type": ["number", "null"],
      "minimum": 0.0,
      "description": "오디오 길이 또는 STT 처리 소요 시간 (밀리초)"
    },
    "language": {
      "type": "string",
      "default": "ko",
      "description": "인식 언어 코드 (기본 'ko')"
    },
    "alternatives": {
      "type": "array",
      "items": { "type": "string" },
      "description": "대체 인식 후보 텍스트 목록 (도메인 보정/후보 매칭용)"
    },
    "is_final": {
      "type": "boolean",
      "default": true,
      "description": "발화 종료 후 확정된 최종 전사 결과인지 여부"
    }
  },
  "additionalProperties": false
}
```

### 2. 도메인 모델 및 프로토콜 정의 (`src/domain/stt_result.py` 및 `src/interfaces/stt.py`)

```python
from dataclasses import dataclass, field
from typing import Any, Protocol

class STTFailure(RuntimeError):
    """STT 변환 과정 실패 시 발생하는 예외"""
    pass

@dataclass(frozen=True)
class STTResult:
    text: str
    confidence: float | None = None
    duration_ms: float | None = None
    language: str = "ko"
    alternatives: tuple[str, ...] = field(default_factory=tuple)
    is_final: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "language": self.language,
            "alternatives": list(self.alternatives),
            "is_final": self.is_final,
        }

class STT(Protocol):
    def transcribe(
        self, audio: bytes, language: str = "ko"
    ) -> STTResult: ...
```

### 3. 언어 정책 (Design Decision)

> **"ko" 고정 언어 정책**: 말로(Mallo)는 한국어 카페 주문 전용 시스템이므로,
> `STT.transcribe()`의 `language` 매개변수 기본값은 `"ko"`로 고정한다.
> 이는 하드코딩이 아닌 의도적 설계 결정이다.
> 향후 다국어 지원이 필요한 경우 이 섹션과 Protocol을 함께 수정한다.

## AC (Given-When-Then)

### AC-01 · 필수 필드만 포함된 기본 STTResult 검증
- **GIVEN**: `text="아이스 아메리카노 두 잔 주세요"`가 주어졌을 때
- **WHEN**: 기본값(`language="ko"`, `is_final=True`)으로 `STTResult`를 생성하고 스키마를 검증한다
- **THEN**: `schemas/stt-result.schema.json` 검증을 성공적으로 통과한다.

### AC-02 · 신뢰도, 소요시간, 후보군 메타데이터 검증
- **GIVEN**: `confidence=0.95`, `duration_ms=1250.0`, `alternatives=("아이스 아메리카노 두잔", "아이스 아메리카노 2잔")`이 주어졌을 때
- **WHEN**: `STTResult`를 생성하고 직렬화하여 스키마를 검증한다
- **THEN**: 스키마 검증을 통과하고 `to_dict()`에 모든 메타데이터가 보존된다.

### AC-03 · confidence 유효 범위 검증 (0.0 ~ 1.0)
- **GIVEN**: `confidence` 값이 `-0.1` 또는 `1.5`로 잘못 입력되었을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.

### AC-04 · duration_ms 음수 값 거부
- **GIVEN**: `duration_ms`가 `-50.0`으로 잘못 입력되었을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.

### AC-05 · 미정의 추가 필드 거부
- **GIVEN**: 정의되지 않은 `raw_tokens` 필드가 최상위에 포함된 JSON 데이터가 주어졌을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.
