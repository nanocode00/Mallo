---
title: "C-18·C-19 — Repository 구조 및 Mock End-to-End Pipeline"
tags: [spec]
---

# C-18·C-19 — Repository 구조 및 Mock End-to-End Pipeline

## Why

- **페르소나**: STT, NLU, Order Engine, TTS를 나누어 개발하는 말로(Mallo) 팀원 3명
- **상황**: 각 AI 모델과 UI가 확정되기 전에 공통 코드 구조와 모듈 연결 지점을 먼저 합의해야 한다.
- **문제**:
  1. 공통 구조가 없으면 담당자별 코드 위치와 import 경로가 달라진다.
  2. 모듈 입출력 계약이 없으면 실제 모델을 통합할 때 연결 코드를 다시 작성해야 한다.
  3. 모든 모델이 준비될 때까지 기다리면 End-to-End 오류를 늦게 발견한다.
- **측정 지표**: 신규 환경 설치 성공 여부, Mock E2E 테스트 통과율, 실제 구현으로 교체할 때 Orchestrator 수정 파일 수

## Goal

- **해결 목표**: 단일 Python 프로세스에서 텍스트 입력을 받아 Mock NLU → Order Engine → Mock TTS 순으로 실행되는 최소 수직 흐름을 만든다.
- **성공 기준**:
  - 현재 Mock Pipeline은 Python 3.11 이상 환경에서 문서화된 명령 3개 이하로 설치와 실행이 가능하다. 이 조건은 실제 AI 모델 및 프로젝트 공통 Python 버전을 확정하지 않는다.
  - 정상 주문, 존재하지 않는 메뉴, 비정상 수량을 포함한 필수 AC 테스트가 100% 통과한다.
  - Mock NLU 또는 Mock TTS를 동일 인터페이스의 실제 구현으로 교체할 때 Orchestrator 코드를 수정하지 않는다.
  - 동일 입력을 10회 실행해 동일한 주문 결과를 반환한다.
- **Out of Scope**:
  - 마이크 입력, VAD, 실제 STT 모델
  - Local LLM 추론 및 Fine-tuning
  - 실제 음성 합성 모델과 오디오 재생
  - GUI, REST API, 데이터베이스, 컨테이너 배포
  - Clarification, Confirmation, 결제, Adaptive TTS Level 1~2

## What

### Happy Path

1. 사용자가 CLI에 `아이스 아메리카노 두 잔 주세요`를 입력한다.
2. `MockNLU`가 입력과 현재 Cart 복사본을 `ADD_ITEM` OrderCommand 배열로 변환한다.
3. Order Engine이 Schema, 메뉴, 수량을 검증한다.
4. Order Engine이 아메리카노 2잔을 새 Cart State에 반영한다.
5. Response Generator가 `아이스 아메리카노 두 잔을 담았습니다.`를 반환한다.
6. `MockTTS`가 응답 텍스트를 전달받았음을 기록한다.
7. CLI가 응답과 현재 장바구니를 출력한다.

### Edge Cases

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 빈 문자열 입력 | `EMPTY_INPUT` 오류를 반환하고 Cart를 유지한다. |
| EC-02 | Mock NLU가 지원하지 않는 표현 | `UNSUPPORTED_UTTERANCE` 오류를 반환하고 Cart를 유지한다. |
| EC-03 | 존재하지 않는 메뉴 | `MENU_NOT_FOUND` 오류를 반환하고 Cart를 유지한다. |
| EC-04 | 수량이 0 이하 | `INVALID_QUANTITY` 오류를 반환하고 Cart를 유지한다. |
| EC-05 | 필수 필드가 없는 OrderCommand 배열 | `INVALID_COMMAND` 오류를 반환하고 Cart를 유지한다. |
| EC-06 | Mock TTS 실패 | 검증된 Cart는 유지하고 `TTS_FAILED` 결과를 반환한다. |
| EC-07 | Batch 중 하나가 유효하지 않음 | 전체 Batch를 취소하고 Cart를 유지한다. |
| EC-08 | 서로 다른 Intent가 한 Batch에 포함됨 | 계약 검증에서 거부한다. |

## How

### Runtime 및 도구

- Python 3.11 이상 — Mock Pipeline 실행·검증 범위에 한정하며 실제 모델 환경은 팀 회의 후 별도 확정
- 의존성 정의: `requirements.txt`
- 테스트: `pytest`
- 애플리케이션 코드는 `src` layout을 사용한다.
- 모듈 연결은 동일 프로세스 내 Python 함수 호출만 사용한다.
- 데이터 모델은 표준 라이브러리 `dataclasses`와 `Enum`으로 정의한다.
- MVP 구조 단계에서는 웹 프레임워크와 외부 데이터베이스를 추가하지 않는다.

### Repository 구조

```text
.
├── AGENTS.md
├── README.md
├── .env.example
├── requirements.txt
├── .github/
├── docs/
│   ├── prd.md
│   ├── proposal.md
│   ├── tasks.md
│   ├── trd.md
│   ├── worklog.md
│   └── specs/
│       ├── _example.md
│       └── mock-e2e-pipeline.md
├── src/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   └── service.py
│   ├── interfaces/
│   │   ├── __init__.py
│   │   ├── stt.py
│   │   ├── tts.py
│   │   ├── nlu.py
│   │   └── agent.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── stt/
│   │   │   ├── __init__.py
│   │   │   ├── whisper_stt.py
│   │   │   └── azure_stt.py
│   │   ├── tts/
│   │   │   ├── __init__.py
│   │   │   ├── edge_tts.py
│   │   │   ├── azure_tts.py
│   │   │   └── mock_tts.py
│   │   └── nlu/
│   │       ├── __init__.py
│   │       ├── openai_nlu.py
│   │       ├── ollama_nlu.py
│   │       └── mock_nlu.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── intents.py
│   │   ├── confirmation_policy.py
│   │   └── conversation.py
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   └── voice_pipeline.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   └── menu.json
│   └── utils/
│       └── __init__.py
├── tests/
│   ├── unit/
│   │   └── test_conversation.py
│   └── integration/
│       └── test_mock_pipeline.py
└── stt/
    └── test.ipynb
```

각 Python 패키지에는 import 경계를 명확히 하기 위한 `__init__.py`를 둔다. 회의안에 없는 `mock_nlu.py`, `mock_tts.py`, `menu.json`, `__init__.py`는 C-19 실행과 Python 패키지 구성을 위해 최소한으로 추가한다.

`openai_nlu.py`, `azure_stt.py`, `azure_tts.py`는 회의에서 제안된 향후 Adapter 위치만 정의한다. 현재 TRD의 Local-first 원칙에 따라 C-19에서는 파일을 생성하거나 외부 API를 호출하지 않는다. 향후 해당 Adapter를 실제로 도입하려면 별도 Spec에서 기존 범위와 보안·시크릿 정책을 재검토한다.

### 책임 경계

| 경로 | 책임 |
|---|---|
| `app/main.py` | CLI 진입점과 애플리케이션 실행 |
| `app/service.py` | 의존성 구성과 텍스트 요청 처리 Use Case |
| `domain/models.py` | OrderCommand, Cart, CartItem, OrderResult, ErrorCode 정의 |
| `domain/intents.py` | 지원 Intent와 Intent별 필수 값 정의 |
| `domain/conversation.py` | Cart 검증·상태 변경과 응답 생성. 외부 Adapter를 참조하지 않는다. |
| `interfaces/` | STT, TTS, NLU, Agent의 교체 가능한 `Protocol` 인터페이스 정의 |
| `adapters/` | 인터페이스별 외부 기술 및 Mock 구현 |
| `orchestrator/voice_pipeline.py` | STT → NLU → Domain → TTS 호출 순서 조율. C-19에서는 텍스트 입력으로 STT를 우회한다. |
| `config/settings.py` | 환경 변수와 실행 설정 로딩 |
| `config/menu.json` | 메뉴 ID, 이름, 카테고리, 기본 가격, 단위, 온도 정책의 기준 데이터 |
| `utils/` | 둘 이상의 계층에서 재사용하는 기술 중립 유틸리티만 배치 |

### 최소 데이터 계약

```python
class Intent(str, Enum):
    ADD_ITEM = "ADD_ITEM"
    # 지원 Intent 12개

@dataclass(frozen=True)
class OrderCommand:
    request_id: str
    intent: Intent
    target_item_id: str | None
    category_id: str | None
    quantity: int | None
    temperature: Temperature | None

@dataclass(frozen=True)
class CartItem:
    menu_id: str
    quantity: int
    temperature: Temperature | None
    unit_price: int

@dataclass
class Cart:
    items: list[CartItem]

@dataclass(frozen=True)
class OrderResult:
    success: bool
    cart: Cart
    response_text: str
    error_code: ErrorCode | None = None
```

Cart 변경은 `domain/conversation.py`의 결정론적 Agent 구현만 수행한다. 현재 실제 실행 범위는 `ADD_ITEM` Batch이며 다른 10개 Intent는 NLU 계약까지만 지원한다. 실패 결과는 입력 Cart와 동일한 내용을 반환해야 한다.

### 모듈 인터페이스

```python
class NLU(Protocol):
    def parse(self, text: str, current_order_state: Cart) -> list[OrderCommand]: ...

class TTS(Protocol):
    def synthesize(self, text: str, level: int = 0) -> None: ...

class Agent(Protocol):
    def execute(self, commands: list[OrderCommand], cart: Cart) -> OrderResult: ...

class MalloService:
    def handle_text(self, text: str, cart: Cart) -> OrderResult: ...
```

`MockNLU`는 테스트에 정의된 고정 문장만 해석하며 현재 주문 상태의 복사본을 함께 입력받는다. `quantity`는 최종 수량이며 Command마다 UUID v4를 생성한다. Confirmation Policy는 `domain/confirmation_policy.py`에서 Order Engine 책임으로 적용한다. `MockTTS`는 마지막으로 전달받은 텍스트와 Level을 메모리에 기록한다.

### 실행 계약

```bash
python3 -m pip install -r requirements.txt
PYTHONPATH=src python3 -m app.main
PYTHONPATH=src python3 -m pytest
```

## AC (Given-When-Then)

### AC-01 · 정상 주문 처리

- GIVEN: 빈 Cart와 판매 중인 `americano` 메뉴가 있다.
- WHEN: `아이스 아메리카노 두 잔 주세요`를 입력한다.
- THEN: 결과는 성공이고 Cart에는 `americano` 수량 2가 있으며 Mock TTS는 성공 응답을 한 번 전달받는다.

### AC-02 · 존재하지 않는 메뉴로부터 Cart 보호

- GIVEN: 아메리카노 1잔이 담긴 Cart가 있다.
- WHEN: 존재하지 않는 메뉴를 담는 OrderCommand Batch를 실행한다.
- THEN: `MENU_NOT_FOUND`를 반환하고 Cart 내용은 실행 전과 동일하다.

### AC-03 · 비정상 수량으로부터 Cart 보호

- GIVEN: 아메리카노 1잔이 담긴 Cart가 있다.
- WHEN: 수량 0인 ADD_ITEM OrderCommand Batch를 실행한다.
- THEN: `INVALID_QUANTITY`를 반환하고 Cart 내용은 실행 전과 동일하다.

### AC-04 · 미지원 발화 처리

- GIVEN: 빈 Cart가 있다.
- WHEN: Mock NLU가 지원하지 않는 문장을 입력한다.
- THEN: `UNSUPPORTED_UTTERANCE`를 반환하고 Order Engine과 Mock TTS를 호출하지 않는다.

### AC-05 · TTS 실패 시 검증된 Cart 유지

- GIVEN: Order Engine 처리는 성공하고 Mock TTS가 실패하도록 설정되어 있다.
- WHEN: 정상 주문 문장을 입력한다.
- THEN: `TTS_FAILED`를 반환하되 Order Engine이 생성한 Cart에는 주문 결과가 유지된다.

### AC-06 · 결정론적 실행

- GIVEN: 매번 새로 생성한 동일한 빈 Cart가 있다.
- WHEN: 같은 정상 주문 문장을 10회 각각 실행한다.
- THEN: 10회의 OrderResult가 모두 동일하다.

### AC-07 · 인터페이스 교체 가능성

- GIVEN: NLU와 TTS Protocol을 구현한 대체 테스트 Double이 있다.
- WHEN: MalloService 생성 시 해당 구현을 주입한다.
- THEN: `app/service.py`와 `orchestrator/voice_pipeline.py` 수정 없이 전체 통합 테스트가 통과한다.
