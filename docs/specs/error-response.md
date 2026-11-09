---
title: "C-16 — 공통 Error Response 정의"
tags: [spec]
---

# C-16 — 공통 Error Response 정의

> 이 문서는 말로(Mallo) 전체 파이프라인(Audio/STT, NLU, Order Engine, TTS, Orchestrator)에서 발생하는 오류를 통합 서비스와 UI가 일관되게 처리하기 위한 `ErrorResponse` 공통 계약이다.

## Why

- **페르소나**: 음성 키오스크를 이용하는 고령 사용자와 각 서브모듈(Audio/STT, NLU, Order Engine, TTS) 및 통합 오케스트레이터를 개발하는 팀원 전원
- **상황**:
  - 음성 인식 불가(무음/잡음), 메뉴 미존재, 필수 온도 누락, 잘못된 수량, 모호한 대상, 시스템 오류 등 다양한 실패 상황이 발생할 수 있다.
- **문제**:
  - 모듈별로 발생하는 예외/에러 형태가 파편화되어 있으면, 오케스트레이터 및 UI에서 일관된 고령자 친화적 음성 안내(`user_message`)와 시각적 복구 힌트(`recovery_hint`), 재시도(`retryable`) 제어가 어렵다.
  - 개발자용 디버깅 정보(`message`)와 사용자용 친절한 안내 문구(`user_message`)가 분리되지 않으면 딱딱하거나 불친절한 시스템 오류 메시지가 고령 사용자에게 그대로 노출된다.
- **측정 지표**:
  - Schema Validation 통과율 100%
  - 에러 상황 발생 시 사용자 친화적 한국어 안내문 매핑 커버리지 100%
  - 오케스트레이터의 통합 에러 처리 테스트 통과율 100%

## Goal

- **해결 목표**:
  - 모든 모듈(Audio/STT, NLU, Order Engine, TTS, System)의 에러를 표준화된 단일 데이터 구조(`ErrorResponse`)와 JSON Schema로 정의한다.
  - 모든 `ErrorCode`에 대해 고령자 친화적인 음성 안내 텍스트(`user_message`), 복구 힌트(`recovery_hint`), 재시도 가능 여부(`retryable`) 기본 매핑 규칙을 확정한다.
  - `OrderResult` 및 `VoicePipeline`과 완벽히 연동되어 어떤 모듈의 실패도 안전하게 사용자 음성/화면 응답으로 변환되도록 한다.
- **성공 기준**:
  - `schemas/error-response.schema.json` 스키마 검증 테스트 100% 통과.
  - 모든 `ErrorCode`가 지정된 모듈(`module`), 기본 `user_message`, `recovery_hint`, `retryable` 정보를 제공.
  - 기존 Mock Pipeline 및 E2E 테스트가 깨지지 않고 하위 호환성을 유지.
- **Out of Scope**:
  - 복잡한 AI 기반 다중 턴 Clarification 대화 엔진 (P1 후속 기능)
  - 실제 외부 PG/카드 결제사 에러 코드 연동
  - 사용자 감정/억양 기반 동적 에러 문구 생성

## What

### Happy Path (오류 발생 시 정상 처리 흐름)

1. 특정 모듈(예: NLU, Order Engine, STT, TTS)에서 오류가 발생하거나 유효성 검증에 실패한다.
2. 해당 모듈 또는 오케스트레이터가 표준 `ErrorCode`를 포함하는 `ErrorResponse` 객체를 생성한다.
3. `ErrorResponse`는 고령 사용자를 위한 명확하고 정중한 `user_message`와 구체적인 재발화 가이드인 `recovery_hint`를 포함한다.
4. 오케스트레이터는 이를 `OrderResult(success=False, ..., response_text=user_message, error_response=...)`로 포장하여 반환한다.
5. Adaptive TTS는 `user_message`를 음성으로 합성하여 출력하고, Minimal GUI는 `user_message`와 `recovery_hint`를 큰 글씨로 화면에 표시한다.

### Edge Cases (최소 5개 + 처리 방식)

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 사용자 발화가 전혀 없음 (무음/빈 입력) | `EMPTY_INPUT` 에러 생성, `retryable=true`, "주문을 말씀해 주세요." 안내 |
| EC-02 | 지원하지 않는 메뉴 또는 엉뚱한 발화 | `MENU_NOT_FOUND` 또는 `UNSUPPORTED_UTTERANCE` 에러 생성, 메뉴판 확인 안내 |
| EC-03 | HOT/ICED 필수 선택 음료에서 온도 누락 | `MISSING_FIELD`, `field=temperature` 에러 생성, "따뜻한 것과 차가운 것 중 어떤 것으로 드릴까요?" 안내 |
| EC-04 | 동일 메뉴의 HOT/ICE가 모두 담긴 상태에서 온도 없이 수량 변경/삭제 요청 | `AMBIGUOUS_TARGET` 에러 생성, "따뜻한 음료인지 차가운 음료인지 말씀해 주세요." 안내 |
| EC-05 | 장바구니가 빈 상태에서 주문 확인/결제/삭제 요청 | `EMPTY_CART` 에러 생성, "장바구니에 담긴 메뉴가 없습니다. 메뉴를 먼저 말씀해 주세요." 안내 |
| EC-06 | 0 이하 또는 비정상적인 수량 주문 | `INVALID_QUANTITY` 에러 생성, "수량은 1잔 이상으로 말씀해 주세요." 안내 |
| EC-07 | TTS 모델 장애 또는 오디오 재생 실패 | `TTS_FAILED` 에러 생성, 화면 텍스트 안내는 유지하고 재시도 유도 |
| EC-08 | 예상치 못한 시스템 예외/런타임 에러 | `INTERNAL_SYSTEM_ERROR` 에러 생성, "일시적인 오류가 발생했습니다. 잠시 후 다시 말씀해 주세요." 안내 |

## How

### 1. ErrorModule 분류

오류가 발생한 파이프라인 영역을 다음 6개 모듈로 표준화한다.

```text
audio        : 마이크 및 오디오 캡처/버퍼
stt          : 음성 인식 모델 및 텍스트 변환
nlu          : 자연어 이해, 의도 분류, 슬롯 추출, OrderCommand 생성
order_engine : 메뉴 검증, 장바구니 상태 변경, 비즈니스 룰 검증
tts          : 텍스트 음성 합성 및 오디오 출력
system       : 오케스트레이션 및 공통 시스템/인프라
```

### 2. ErrorCode 정의 및 모듈 매핑

모든 오류 코드는 고유한 문자열 enum으로 정의된다.

| ErrorCode | Module | 설명 | 기본 user_message | 기본 recovery_hint | retryable |
|---|---|---|---|---|:---:|
| `AUDIO_RECORD_FAILED` | `audio` | 마이크 입력 또는 오디오 장치 오류 | 마이크 입력을 확인할 수 없습니다. 다시 시도해 주세요. | 마이크 버튼을 누르고 다시 말씀해 주세요. | true |
| `EMPTY_INPUT` | `stt` | 발화가 감지되지 않음 (무음/공백) | 주문을 말씀해 주세요. | 예: "따뜻한 아메리카노 한 잔 주세요" | true |
| `STT_FAILED` | `stt` | 음성 인식 처리 실패 | 음성을 정확히 인식하지 못했습니다. 다시 말씀해 주세요. | 마이크 가까이에서 천천히 말씀해 주세요. | true |
| `INVALID_JSON` | `nlu` | Local LLM 출력이 JSON이 아님 | 주문을 처리할 수 없습니다. 다시 말씀해 주세요. | 메뉴 이름과 수량을 다시 말씀해 주세요. | true |
| `SCHEMA_ERROR` | `nlu` | NLU 출력이 OrderCommand Schema 위반 | 주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요. | 메뉴 이름, 수량, 온도를 함께 말씀해 주세요. | true |
| `UNKNOWN_INTENT` | `nlu` | 정의되지 않은 Intent 출력 | 지원하지 않는 요청입니다. | 지원되는 주문 요청을 말씀해 주세요. | true |
| `MISSING_FIELD` | `nlu` 또는 `order_engine` | 필수 의미 필드 누락 | 주문에 필요한 정보가 부족합니다. | 누락된 메뉴·수량·온도를 말씀해 주세요. | true |
| `MIXED_INTENT` | `nlu` | 한 Batch에 서로 다른 Intent 포함 | 사용자의 주문을 이해하지 못했습니다. 한 번에 하나씩 주문해 주시면 감사하겠습니다. | 각 요청을 한 문장씩 나누어 말씀해 주세요. | true |
| `UNSUPPORTED_UTTERANCE` | `nlu` | 주문 도메인 밖의 발화 또는 해석 불가 | 죄송합니다. 요청하신 내용을 이해하지 못했습니다. | 메뉴 이름과 수량을 말씀해 주세요. | true |
| `AMBIGUOUS_TARGET` | `nlu` | 대상 메뉴 또는 옵션이 모호하여 식별 불가 | 어떤 메뉴를 변경할지 명확하지 않습니다. | 따뜻한 음료인지 차가운 음료인지 함께 말씀해 주세요. | true |
| `INVALID_COMMAND` | `nlu` | NLU 출력 포맷/스키마 불일치 | 주문 형식을 확인할 수 없습니다. 다시 말씀해 주세요. | 메뉴와 수량을 다시 말씀해 주세요. | true |
| `MENU_NOT_FOUND` | `order_engine` | 매장에 없는 메뉴 요청 | 메뉴판에 없는 메뉴입니다. 메뉴를 다시 확인해 주세요. | 아메리카노, 카페라떼 등 메뉴판의 이름을 말씀해 주세요. | true |
| `INVALID_OPTION` | `order_engine` | 메뉴에서 지원하지 않는 옵션/온도 | 해당 메뉴에서 선택할 수 없는 옵션입니다. | 메뉴의 지원 온도를 확인해 주세요. | true |
| `INVALID_QUANTITY` | `order_engine` | 수량이 0 이하이거나 비정상 수량 | 수량은 1잔 이상으로 말씀해 주세요. | "한 잔", "두 잔"처럼 말씀해 주세요. | true |
| `EMPTY_CART` | `order_engine` | 장바구니가 비어 있는 상태에서 확인/결제/삭제 요청 | 장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요. | 원하시는 메뉴를 말씀해 주세요. | true |
| `CART_ITEM_NOT_FOUND` | `order_engine` | 장바구니에 없는 메뉴의 변경/삭제 요청 | 장바구니에 해당 메뉴가 없습니다. | 현재 담긴 메뉴를 확인해 주세요. | true |
| `TTS_FAILED` | `tts` | 음성 합성 또는 출력 실패 | 음성 안내 출력 중 오류가 발생했습니다. 화면을 확인해 주세요. | 화면의 주문 내역을 확인해 주세요. | false |
| `INTERNAL_SYSTEM_ERROR` | `system` | 예상치 못한 시스템 런타임 오류 | 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. | 잠시 후 다시 말씀해 주세요. | false |

### 3. ErrorResponse JSON Schema (`schemas/error-response.schema.json`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ErrorResponse",
  "type": "object",
  "required": [
    "error_code",
    "module",
    "message",
    "user_message",
    "retryable"
  ],
  "properties": {
    "error_code": {
      "type": "string",
      "enum": [
        "AUDIO_RECORD_FAILED",
        "EMPTY_INPUT",
        "STT_FAILED",
        "INVALID_JSON",
        "SCHEMA_ERROR",
        "UNKNOWN_INTENT",
        "MISSING_FIELD",
        "MIXED_INTENT",
        "UNSUPPORTED_UTTERANCE",
        "AMBIGUOUS_TARGET",
        "INVALID_COMMAND",
        "MENU_NOT_FOUND",
        "INVALID_OPTION",
        "INVALID_QUANTITY",
        "EMPTY_CART",
        "CART_ITEM_NOT_FOUND",
        "TTS_FAILED",
        "INTERNAL_SYSTEM_ERROR"
      ]
    },
    "module": {
      "type": "string",
      "enum": ["audio", "stt", "nlu", "order_engine", "tts", "system"]
    },
    "message": {
      "type": "string",
      "description": "개발자/로깅용 상세 오류 설명"
    },
    "user_message": {
      "type": "string",
      "description": "고령 사용자를 위한 친절한 음성 및 UI 안내 텍스트"
    },
    "recovery_hint": {
      "type": ["string", "null"],
      "description": "사용자가 어떻게 행동해야 하는지 안내하는 구체적 예시 힌트"
    },
    "retryable": {
      "type": "boolean",
      "description": "동일 세션에서 사용자가 재발화/재시도하여 복구 가능한지 여부"
    },
    "details": {
      "type": "object",
      "description": "선택적 부가 메타데이터 (예: 누락된 필드명, 후보 목록 등)",
      "additionalProperties": true
    }
  },
  "additionalProperties": false
}
```

### 4. 도메인 모델 정의 (`src/domain/models.py`)

```python
from enum import Enum
from dataclasses import dataclass
from typing import Any

class ErrorModule(str, Enum):
    AUDIO = "audio"
    STT = "stt"
    NLU = "nlu"
    ORDER_ENGINE = "order_engine"
    TTS = "tts"
    SYSTEM = "system"

@dataclass(frozen=True)
class ErrorResponse:
    error_code: ErrorCode
    module: ErrorModule
    message: str
    user_message: str
    retryable: bool
    recovery_hint: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code.value,
            "module": self.module.value,
            "message": self.message,
            "user_message": self.user_message,
            "recovery_hint": self.recovery_hint,
            "retryable": self.retryable,
            "details": self.details or {},
        }
```

## AC (Given-When-Then)

### AC-01 · ErrorResponse 스키마 유효성
- **GIVEN**: 표준 `ErrorCode`와 필수 필드를 가진 `ErrorResponse` 객체가 생성되었을 때
- **WHEN**: `schemas/error-response.schema.json`에 대해 JSON 스키마 유효성 검사를 수행한다
- **THEN**: 유효성 검사를 성공적으로 통과해야 한다.

### AC-02 · 모든 ErrorCode의 기본 메타데이터 매핑
- **GIVEN**: 유효한 임의의 `ErrorCode`가 주어졌을 때
- **WHEN**: `get_default_error_response(error_code)`를 호출한다
- **THEN**: 해당 에러 코드에 알맞은 `module`, 고령자 친화적인 `user_message`, `recovery_hint`, `retryable` 플래그가 채워진 `ErrorResponse`가 반환된다.

### AC-03 · 커스텀 메시지 오버라이드 지원
- **GIVEN**: 특정 메뉴나 상황에 맞춘 커스텀 안내 텍스트가 필요할 때
- **WHEN**: `create_error_response(error_code, user_message="아메리카노의 온도를 말씀해 주세요.", details={"menu_id": "americano"})`를 호출한다
- **THEN**: 기본 모듈/재시도 속성을 유지하면서 커스텀 `user_message`와 `details`가 정상 반영된 `ErrorResponse`가 반환된다.

### AC-04 · OrderResult와의 하위 호환 및 연동
- **GIVEN**: 실패한 주문 처리 결과가 발생했을 때
- **WHEN**: `OrderResult.failure(error_response)`를 생성한다
- **THEN**: `success=False`, `error_code=error_response.error_code`, `error_response=error_response`, `response_text=error_response.user_message`가 정확히 설정된다.

### AC-05 · 음성 파이프라인 예외 포획 및 ErrorResponse 변환
- **GIVEN**: `VoicePipeline`에서 `OrderCommandError`가 반환되거나 `ValidationError`가 발생했을 때
- **WHEN**: `pipeline.handle_text(...)`가 실행된다
- **THEN**: 파이프라인이 중단되지 않고 `success=False`와 함께 규정된 `ErrorResponse`를 담은 `OrderResult`를 반환한다.
