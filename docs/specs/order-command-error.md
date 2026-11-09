---
title: "C-10 — OrderCommand Error Schema 정의"
tags: [spec]
---

# C-10 — OrderCommand Error Schema 정의

> 이 문서는 NLU가 사용자 발화를 해석하는 과정에서 모호하거나 잘못된 출력이 발생했을 때 반환하는 `OrderCommandError` 기준 계약이다.

## Why

- **페르소나**: Local LLM/NLU 개발자, Order Engine 개발자, 통합 오케스트레이터 개발자
- **상황**:
  - 사용자의 발화가 주문 도메인 밖이거나, 필수 슬롯(온도 등)이 누락되었거나, 동일 메뉴의 HOT/ICE가 모두 존재하는 상태에서 모호한 수정 요청이 들어오는 등 NLU가 정상적인 `OrderCommand[]`를 생성할 수 없는 상황이 발생한다.
  - 또한 Local LLM의 출력 결과가 JSON 형식이 깨지거나 스키마를 위반할 수 있다.
- **문제**:
  - NLU 단계의 실패 결과가 정형화된 구조 없이 단순 텍스트나 예외로만 던져지면, 어떤 커맨드의 어떤 필드가 문제인지(`command_index`, `field`), 선택 가능한 후보군(`candidates`)이 무엇인지 파악하기 어렵고, 향후 P1 Clarification(역질문) 기능으로의 확장이 불가능하다.
- **측정 지표**:
  - JSON Schema 검증 통과율 100%
  - NLU 에러 케이스의 `OrderCommandError` 구조화 준수율 100%

## Goal

- **해결 목표**:
  - NLU 정상 출력(`OrderCommand[]`)에 대응되는 정형화된 실패 출력 규격 `OrderCommandError`와 JSON Schema를 정의한다.
  - 실패한 커맨드 위치(`command_index`), 누락/오류 필드(`field`), 보정/선택 후보(`candidates`), 사용자 안내문(`message`), 재시도 가능 여부(`retryable`)를 정형 필드로 고정한다.
- **성공 기준**:
  - `schemas/order-command-error.schema.json` 스키마 검증 테스트 100% 통과.
  - 지원 오류 코드(`INVALID_JSON`, `SCHEMA_ERROR`, `UNKNOWN_INTENT`, `MISSING_FIELD`, `MIXED_INTENT`, `AMBIGUOUS_TARGET`, `UNSUPPORTED_UTTERANCE`) 지원.
  - 단위 테스트 및 스키마 유효성 테스트 작성 및 통과.
- **Out of Scope**:
  - LLM 모델 내부의 Token Decoding 제약 로직 (Grammar Constraint 등)
  - 다중 턴 Clarification 대화 세션 상태 머신 (P1 구현 범위)

## What

### Happy Path (NLU 실패 시 정형 에러 출력 흐름)

1. Local LLM/NLU가 입력 발화를 파싱하는 도중 오류 상황(예: 필수 온도 누락, 비정상 JSON, 모호한 대상 등)을 감지한다.
2. NLU는 빈 배열이나 비정형 텍스트 대신 `OrderCommandError` 구조화 객체를 생성한다.
3. 스키마 검증기(`validate_order_command_error`)가 에러 객체의 형식 유효성을 검증한다.
4. 오케스트레이터 및 Order Engine은 `OrderCommandError`의 `code`, `message`, `field`, `candidates` 정보를 바탕으로 사용자에게 정확한 재입력 안내 또는 Clarification을 제공한다.

### Edge Cases (최소 5개 + 처리 방식)

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | LLM 출력이 JSON 파싱 불가능한 텍스트임 | `INVALID_JSON` 에러 생성, `retryable=true` |
| EC-02 | JSON 형식은 맞으나 필수 필드가 빠지거나 스키마 위반 | `SCHEMA_ERROR` 에러 생성, `retryable=true` |
| EC-03 | 지원하지 않는 Intent가 모델에서 출력됨 | `UNKNOWN_INTENT` 에러 생성, `retryable=true` |
| EC-04 | HOT/ICED 필수 선택 메뉴에서 온도가 누락됨 | `MISSING_FIELD` 에러 생성, `field="temperature"`, `candidates=["hot", "iced"]` |
| EC-05 | 결제·전체 취소·실행취소·메뉴 탐색·TTS 제어가 다른 요청과 섞임 | `MIXED_INTENT` 에러 생성, 요청을 나누어 말하도록 안내 |
| EC-06 | 장바구니에 동일 메뉴의 HOT/ICE가 모두 있는데 온도 없이 수량 변경/삭제 요청 | `AMBIGUOUS_TARGET` 에러 생성, `field="temperature"`, `candidates=["hot", "iced"]` |
| EC-07 | 주문과 전혀 상관없는 도메인 밖의 발화 | `UNSUPPORTED_UTTERANCE` 에러 생성, 메뉴 주문 안내 |

## How

### 1. OrderCommandError JSON Schema (`schemas/order-command-error.schema.json`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "OrderCommandError",
  "type": "object",
  "required": [
    "code",
    "message",
    "retryable"
  ],
  "properties": {
    "code": {
      "type": "string",
      "enum": [
        "INVALID_JSON",
        "SCHEMA_ERROR",
        "UNKNOWN_INTENT",
        "MISSING_FIELD",
        "MIXED_INTENT",
        "AMBIGUOUS_TARGET",
        "UNSUPPORTED_UTTERANCE"
      ]
    },
    "message": {
      "type": "string",
      "description": "사용자에게 전달할 정중하고 명확한 한국어 안내 문장"
    },
    "command_index": {
      "type": ["integer", "null"],
      "minimum": 0,
      "description": "실패가 발생한 Command의 배열 인덱스 (0부터 시작)"
    },
    "field": {
      "type": ["string", "null"],
      "description": "오류 또는 누락이 발생한 필드명 (예: temperature, quantity 등)"
    },
    "candidates": {
      "type": ["array", "null"],
      "items": { "type": "string" },
      "description": "재입력 또는 Clarification용 선택 가능한 후보 목록"
    },
    "retryable": {
      "type": "boolean",
      "description": "동일 세션에서 사용자의 재발화로 복구 가능한지 여부"
    }
  },
  "additionalProperties": false
}
```

### 2. 필드 규격 및 의미

| Field | Type | 필수 여부 | 의미 |
|---|---|:---:|---|
| `code` | enum | O | 기계/시스템이 처리할 고유 에러 코드 |
| `message` | string | O | 사용자에게 전달할 명확하고 친절한 안내 문장 |
| `command_index` | integer 또는 null | △ | 복수 Command 중 오류가 발생한 위치 (해당 없으면 `null`) |
| `field` | string 또는 null | △ | 오류/누락된 필드 이름 (해당 없으면 `null`) |
| `candidates` | string[] 또는 null | △ | 사용자가 선택할 수 있는 후보군 (예: `["hot", "iced"]`) |
| `retryable` | boolean | O | 사용자가 다시 말하여 복구 가능한지 여부 (기본 `true`) |

### 3. 데이터 구조 (`src/domain/models.py` 또는 `src/domain/errors.py`)

```python
from dataclasses import dataclass
from enum import Enum

class OrderCommandErrorCode(str, Enum):
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    UNKNOWN_INTENT = "UNKNOWN_INTENT"
    MISSING_FIELD = "MISSING_FIELD"
    MIXED_INTENT = "MIXED_INTENT"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    UNSUPPORTED_UTTERANCE = "UNSUPPORTED_UTTERANCE"

@dataclass(frozen=True)
class OrderCommandError:
    code: OrderCommandErrorCode
    message: str
    retryable: bool = True
    command_index: int | None = None
    field: str | None = None
    candidates: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "command_index": self.command_index,
            "field": self.field,
            "candidates": list(self.candidates) if self.candidates is not None else None,
            "retryable": self.retryable,
        }
```

## AC (Given-When-Then)

### AC-01 · 필수 필드를 포함한 정상 스키마 검증
- **GIVEN**: `code`, `message`, `retryable` 필수 필드가 올바르게 채워진 `OrderCommandError`가 주어졌을 때
- **WHEN**: `schemas/order-command-error.schema.json`에 대해 유효성 검사를 수행한다
- **THEN**: 스키마 검증을 통과한다.

### AC-02 · 선택 필드(command_index, field, candidates) 유효성
- **GIVEN**: `command_index=0`, `field="temperature"`, `candidates=["hot", "iced"]`가 설정된 `OrderCommandError`가 주어졌을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: 스키마 검증을 통과하고 `to_dict()` 결과에 해당 값들이 정상 보존된다.

### AC-03 · 필수 필드 누락 시 거부
- **GIVEN**: `message` 또는 `code` 필수 필드가 누락된 JSON 데이터가 주어졌을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.

### AC-04 · 미정의 추가 필드 거부
- **GIVEN**: 스키마에 정의되지 않은 `extra_info` 필드가 최상위에 포함된 JSON 데이터가 주어졌을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.

### AC-05 · 음수 인덱스 거부
- **GIVEN**: `command_index` 값이 `-1`과 같은 음수로 지정되었을 때
- **WHEN**: 스키마 검증을 수행한다
- **THEN**: `ValidationError`가 발생한다.
