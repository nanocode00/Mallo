---
title: "UI-01~UI-07 — Starbuck-style Voice-first Minimal GUI"
tags: [spec]
---

# UI-01~UI-07 — Starbuck-style Voice-first Minimal GUI

> 이 문서는 스타벅스 키오스크 톤앤매너(시그니처 다크 그린, 웜 크림 배경, 고대비 타이포그래피)를 적용한 Voice-first Minimal GUI의 초기 화면 구조 및 상태 인터페이스 계약이다.
> 최종 구현된 7개 화면(`WELCOME`, `SERVICE_MODE`, `ORDER`, `ORDER_REVIEW`, `OPTION_CHANGE`, `PAYMENT`, `COMPLETE`) 상태 머신, 5버튼 접근성 Footer, Footer 일체형 Voice Overlay 및 세부 레이아웃 계약은 [`docs/specs/senior-first-web-ui.md`](senior-first-web-ui.md)를 Source of Truth로 따른다.

## Why

- **페르소나**: 복잡한 메뉴 탭과 작은 옵션 팝업으로 인해 기존 터치 키오스크 이용을 포기하거나 부담을 느끼는 고령 사용자
- **상황**:
  - 익숙하고 신뢰감 있는 카페(스타벅스 스타일)의 정갈한 디자인을 바탕으로, 복잡한 메뉴 그리드 대신 음성으로 자연스럽게 주문하고 화면은 **상태 확인 및 보조 제어(실시간 자막, 장바구니, 음성 버튼, TTS 제어, 직원 호출)** 용도로만 최소화하여 제공한다.
- **문제**:
  - 시각적으로 혼란스러운 수많은 버튼과 작은 글씨는 고령자의 인지적 과부하를 초래한다.
  - 음성 비서가 무엇을 하고 있는지(듣는 중/처리 중/말하는 중) 명확한 시각적 피드백이 없으면 사용자가 불안감을 느낀다.
- **측정 지표**:
  - 화면 내 핵심 정보(시스템 상태, 장바구니, 자막) 인지 시간 < 1초
  - 고대비(WCAG AAA 준수) 및 최소 폰트 크기 18px 이상 유지

## Goal

- **해결 목표**:
  - 스타벅스 키오스크 스타일(Dark Green `#006241`, Warm Cream `#F7F5F0`, High-contrast Typography)을 적용한 Voice-first Minimal GUI를 구축한다.
  - **`UI-01` Main Layout**: 고령자 친화적 단일 화면 반응형 레이아웃
  - **`UI-02` Current Cart Display**: 매장/포장, 메뉴명, 온도, Size, Decaf, Ice amount, Shot, Syrup, 수량, 단가 및 총액 표시
  - **`UI-03` Response Subtitle**: 시스템 안내 발화 자막 표시
  - **`UI-04` Voice Trigger**: 대기 화면의 `주문하기`, TTS 종료 후 자동 Listening 상태, 수동 재입력용 마이크 버튼
  - **`UI-05` Voice UX Control Bar**: `다시 듣기`, `천천히`, `보통 속도`, `직원 호출` 버튼
  - **`UI-06` System Status Badge**: `대기중(IDLE)`, `매장/포장 선택(SERVICE_MODE)`, `듣는중(LISTENING)`, `처리중(PROCESSING)`, `말하는중(TTS_PLAYING)`
  - **`UI-07` Recognition Result**: 최근 STT 원문과 구조화된 주문 결과를 구분해 표시
  - GUI 상태를 표현하는 `SessionState` 도메인 모델 정의
- **성공 기준**:
  - React Web UI에서 대기→매장/포장→주문→확인·수정→결제→완료 상태가 동작한다.
  - `SessionState` 도메인 모델 단위 테스트 100% 통과.
- **Out of Scope**:
  - 실제 카드 리더기 하드웨어 PG 결제 모듈

## What

### Happy Path (화면 영역별 구성 및 동작)

1. **대기 및 세션 시작 (`UI-01`, `UI-04`)**:
   - 대기 화면에 `[주문하기]`와 `[직원 호출]`을 제공한다.
   - `주문하기` 1회 후 `[매장에서]`, `[포장]` 버튼과 음성 선택 안내를 표시한다.
2. **상단 브랜드 & 시스템 상태 바 (`UI-01`, `UI-06`)**:
   - 스타벅스 그린 톤 헤더에 `말로(Mallo) 카페` 로고 및 우측에 시스템 상태 뱃지 (`대기중`, `🎧 듣는 중...`, `⚙️ 처리 중...`, `🔊 말하는 중...`) 표시.
3. **시스템 안내·인식 결과 영역 (`UI-03`, `UI-07`)**:
   - 상단 중앙에 시스템이 발화하는 텍스트를 크고 명확한 글씨로 말풍선 카드 형태로 표시.
   - 최근 사용자 발화(STT)와 실제 반영된 구조화 주문 카드를 구분하고 주문 카드를 더 강조한다.
4. **중앙 음성 입력 영역 (`UI-04`)**:
   - 응답이 필요한 TTS가 끝나면 자동으로 `듣고 있어요`와 Waveform을 표시한다.
   - 대형 원형 마이크 버튼은 인식 실패·Timeout·추가 주문을 위한 `다시 말하기` Fallback으로 제공한다.
   - 키보드 입력을 위한 하단 보조 텍스트 인풋 제공.
5. **우측/하단 장바구니 영역 (`UI-02`)**:
   - 현재 주문된 메뉴 리스트와 지원 옵션, 매장/포장 및 총 결제 금액을 명확하게 표시.
6. **하단 보조 제어 바 (`UI-05`)**:
   - `[🔄 다시 듣기]`, `[🐢 천천히]`, `[⚡ 보통 속도]`, `[🔔 직원 호출]` 버튼 제공.
   - Adaptive TTS 제어는 별도 화면이 아니라 주문·확인·수정 화면에서 공통으로 사용할 수 있는 접근성 기능이다.

### Edge Cases (최소 4개 + 처리 방식)

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 장바구니가 비어있는 초기 상태 | `담긴 메뉴가 없습니다. 음성으로 주문해 주세요.` 안내 문구 표시 |
| EC-02 | 시스템 에러 발생 시 | 상태 뱃지에 `⚠️ 안내` 표시 및 자막 카드에 에러 안내문 노출 |
| EC-03 | 화면 크기가 작은 모바일/태블릿 접속 | 1열 수직 반응형 스택 레이아웃으로 유연하게 적응 |
| EC-04 | 음성 인식 실패 또는 무음 | 자막 영역에 `말씀을 잘 듣지 못했습니다. 다시 말씀해 주세요.` 표시 |
| EC-05 | 자동 Listening Timeout | Cart와 현재 질문을 유지하고 수동 마이크·터치 선택 제공 |
| EC-06 | TTS 재생 중 사용자 발화 | MVP에서는 Barge-in을 받지 않고 마이크 비활성 상태를 표시 |

## How

### 1. SessionState 도메인 모델 (`src/domain/session_state.py`)

```python
from dataclasses import dataclass, field
from enum import Enum
from domain.models import Cart, ErrorCode

class SessionStatus(str, Enum):
    IDLE = "IDLE"
    SERVICE_MODE = "SERVICE_MODE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    RESULT = "RESULT"
    TTS_PLAYING = "TTS_PLAYING"
    CONFIRMING = "CONFIRMING"
    CLARIFYING = "CLARIFYING"
    PAYMENT = "PAYMENT"
    COMPLETE = "COMPLETE"

@dataclass
class SessionState:
    status: SessionStatus = SessionStatus.IDLE
    cart: Cart = field(default_factory=Cart)
    last_response: str = "안녕하세요! 원하시는 메뉴를 말씀해 주세요."
    recent_transcript: str = ""
    listening_mode: str | None = None
    tts_level: int = 0
    error_code: ErrorCode | None = None

    def to_dict(self) -> dict: ...
```

### 2. 웹 프론트엔드 경계

- 최종 사용자 UI는 React로 구현하고 Vercel에 배포한다.
- API endpoint는 환경 설정으로 주입해 Local FastAPI(Plan A)와 External Server(Deployment Plan B)를 UI 코드 변경 없이 선택한다.
- 실제 구현 전환 상태는 `docs/notion-reconciliation-report.md`의 구현 gap을 따른다.

## AC (Given-When-Then)

### AC-01 · SessionState 기본값 생성
- **GIVEN**: 새 `SessionState`가 인스턴스화되었을 때
- **WHEN**: 상태 속성을 확인한다
- **THEN**: `status`는 `SessionStatus.IDLE`, `cart.items`는 빈 리스트, `tts_level`은 `0`이어야 한다.

### AC-02 · SessionState 직렬화 및 복사
- **GIVEN**: 장바구니 항목과 `last_response`가 포함된 `SessionState`가 주어졌을 때
- **WHEN**: `to_dict()`를 호출한다
- **THEN**: UI 렌더링에 필요한 모든 필드가 올바른 JSON 호환 dict로 반환된다.

### AC-03 · 세션 시작과 Trigger UI
- **GIVEN**: 대기 화면이 로드됐을 때
- **WHEN**: 사용자가 `주문하기`를 누르고 매장/포장을 선택한다.
- **THEN**: 메뉴 주문 안내 TTS 종료 후 자동 Listening이 표시되고 수동 마이크는 재입력 Fallback으로 제공된다.

### AC-04 · 장바구니 항목 추가 시 총액 갱신
- **GIVEN**: 장바구니에 아메리카노(4,700원) 2잔이 추가되었을 때
- **WHEN**: `SessionState.to_dict()`를 확인한다
- **THEN**: `total_price`가 `9400`으로 계산되어 포함된다.

### AC-05 · STT와 주문 결과 분리
- **GIVEN**: 사용자 발화의 STT 원문과 Order Engine이 확정한 구조화 결과가 있다.
- **WHEN**: 결과 화면을 렌더링한다.
- **THEN**: 최근 STT와 주문 카드를 시각적으로 구분하고 주문 카드를 더 강조한다.

### AC-06 · Adaptive TTS 공통 제어
- **GIVEN**: 주문·수정·최종 확인 중 하나의 화면이다.
- **WHEN**: 사용자가 다시 듣기 또는 천천히 듣기를 선택한다.
- **THEN**: 현재 화면과 Cart를 유지한 채 Adaptive TTS가 실행되며 별도 단계로 이동하지 않는다.
