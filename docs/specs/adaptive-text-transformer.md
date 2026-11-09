---
title: "T-08~T-15 — Adaptive TTS Text Transformer (Level 0~2 텍스트 변환)"
tags: [spec]
---

# T-08~T-15 — Adaptive TTS Text Transformer (Level 0~2 텍스트 변환)

> 이 문서는 고령 사용자의 청각적·인지적 부담을 줄이기 위해, 시스템 응답 문장을 TTS Level(0: 기본, 1: Pause 강화, 2: 단문 분절 및 핵심 강조)에 맞추어 변환하는 규칙 기반 `AdaptiveTextTransformer` 기준 계약이다.

## Why

- **페르소나**: 청력 저하나 인지적 처리 속도 저하로 인해 빠르고 긴 복합 안내 음성을 한 번에 이해하기 어려운 고령 사용자
- **상황**:
  - `아이스 아메리카노 두 잔, 따뜻한 카페라떼 한 잔을 담았습니다.`와 같이 여러 정보(메뉴명, 온도, 수량, 완료 안내)가 한 문장에 쉼 없이 연속해서 나오면 고령 사용자가 주문 내역을 명확히 확인하지 못하고 혼란을 느낀다.
  - "천천히 말해줘" 또는 "다시 말해줘"라고 요청했을 때 동일한 길이의 빠른 복합문이 다시 나오면 사용자 경험이 크게 저하된다.
- **문제**:
  - 무거운 생성형 AI를 매번 호출하여 텍스트를 재구성하면 Latency가 수백 ms 이상 추가되고(NFR-03 위반), 임의의 환각(Hallucination)이나 메뉴명 변형 위험이 발생한다.
- **측정 지표**:
  - 텍스트 변환 소요 시간 < 5ms (초저지연 결정론적 룰 기반)
  - 핵심 정보(메뉴명, 온도, 수량, 금액) 보존율 100%
  - Level별 변환 규격 준수율 100%

## Goal

- **해결 목표**:
  - 외부 모델 의존성 없는 순수 Python 규칙 기반 `AdaptiveTextTransformer`를 구현한다.
  - **Level 0 (기본)**: 원본 연결형 자연어 응답 유지
  - **Level 1 (속도/Pause 강화)**: 항목 및 절 경계에 휴지기(Pause) 마커를 삽입하여 정보 간 간격을 확보
  - **Level 2 (단문 분절/핵심 강조)**: 복합문을 짧은 독립 단문으로 쪼개고 `[메뉴명]. [수량]입니다.` 형태로 핵심 정보 우선 강조
- **성공 기준**:
  - 단일 메뉴 주문, 복수 메뉴 주문, 주문 확인 질문, 금액 안내, 에러 안내 등 대표 텍스트 변환 테스트 100% 통과.
  - 변환 전후의 핵심 엔티티(메뉴명, 수량, 온도)가 100% 일치.
- **Out of Scope**:
  - 딥러닝 기반 음성 합성 모델 파라미터 제어 (본 티켓은 텍스트 전처리/변환 엔진에 집중)

## What

### Happy Path (Level별 변환 규칙)

1. **단일 메뉴 추가 응답**:
   - Level 0: `아이스 아메리카노 두 잔을 담았습니다.`
   - Level 1: `아이스 아메리카노 두 잔, 담았습니다.`
   - Level 2: `아이스 아메리카노. 두 잔입니다. 장바구니에 담았습니다.`

2. **복수 메뉴 추가 응답**:
   - Level 0: `아이스 아메리카노 두 잔, 따뜻한 카페라떼 한 잔을 담았습니다.`
   - Level 1: `아이스 아메리카노 두 잔, 따뜻한 카페라떼 한 잔, 담았습니다.`
   - Level 2: `아이스 아메리카노. 두 잔입니다. 따뜻한 카페라떼. 한 잔입니다. 장바구니에 담았습니다.`

3. **주문 확인 질문**:
   - Level 0: `아이스 아메리카노 두 잔, 맞으세요?`
   - Level 1: `아이스 아메리카노 두 잔, 맞으세요?`
   - Level 2: `아이스 아메리카노. 두 잔입니다. 맞으세요?`

4. **결제 및 금액 안내**:
   - Level 0: `총 결제 금액은 구천사백원입니다.`
   - Level 1: `총 결제 금액은, 구천사백원입니다.`
   - Level 2: `총 결제 금액입니다. 구천사백원입니다.`

### Edge Cases (최소 5개 + 처리 방식)

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 빈 문자열 또는 공백 입력 | 빈 문자열 그대로 반환 |
| EC-02 | 이미 마침표로 끝나는 짧은 단문 (예: `주문을 말씀해 주세요.`) | 불필요한 분절 없이 Level 1은 쉼표/Pause 미삽입, Level 2도 원형 보존 |
| EC-03 | 정의되지 않은 Level 값 (예: `level=3` 또는 `-1`) | `ValueError` 발생 또는 기본 Level 0 처리 |
| EC-04 | 3개 이상의 복수 메뉴가 나열된 경우 | 모든 메뉴 항목을 Level 2에서 각각 `[메뉴]. [수량]입니다.`로 완벽 분절 |
| EC-05 | 수량 단위가 `개`인 디저트 메뉴 (예: `치즈케이크 한 개를 담았습니다.`) | `치즈케이크. 한 개입니다. 장바구니에 담았습니다.`로 단위 보존 분절 |

## How

### 1. AdaptiveTextTransformer 클래스 구조 (`src/domain/text_transformer.py`)

```python
class AdaptiveTextTransformer:
    @classmethod
    def transform(cls, text: str, level: int = 0) -> str:
        if not text or not text.strip():
            return ""
        
        normalized = normalize_korean_text_for_tts(text)
        if level == 0:
            return cls._transform_level_0(normalized)
        elif level == 1:
            return cls._transform_level_1(normalized)
        elif level == 2:
            return cls._transform_level_2(normalized)
        else:
            raise ValueError(f"Invalid TTS level: {level}. Allowed levels are 0, 1, 2.")
```

### 2. 세부 변환 로직

- **Level 0**:
  - 한국어 수사 및 금액 정규화 후 원본 문장 유지.
- **Level 1**:
  - 절 및 항목 경계, 서술어 직전에 표준 쉼표 `, ` 삽입 (비표준 기호 `...` 배제하여 음향 왜곡 방지).
- **Level 2**:
  - 정규표현식 및 패턴 매칭을 통해 복합 메뉴 및 결제/변경 문장을 추출.
  - 각 항목을 `[메뉴명]. [수량]입니다.` 단문으로 재구성하고 서두/결미 서술어를 간결한 단문으로 결합.

## AC (Given-When-Then)

### AC-01 · Level 0 기본 텍스트 유지
- **GIVEN**: `아이스 아메리카노 두 잔을 담았습니다.` 문장이 주어졌을 때
- **WHEN**: `AdaptiveTextTransformer.transform(text, level=0)`을 호출한다
- **THEN**: 원본 문장과 동일한 텍스트가 반환된다.

### AC-02 · Level 1 Pause 마커 삽입
- **GIVEN**: `아이스 아메리카노 두 잔, 따뜻한 카페라떼 한 잔을 담았습니다.` 문장이 주어졌을 때
- **WHEN**: `level=1`로 변환한다
- **THEN**: 항목 및 서술어 사이에 자연스러운 쉼표(`, `) Pause 마커가 삽입된 텍스트가 반환된다.

### AC-03 · Level 2 단일 메뉴 단문 분절 및 핵심 강조
- **GIVEN**: `아이스 아메리카노 두 잔을 담았습니다.` 문장이 주어졌을 때
- **WHEN**: `level=2`로 변환한다
- **THEN**: `아이스 아메리카노. 두 잔입니다. 장바구니에 담았습니다.` 형태로 분절된 텍스트가 반환된다.

### AC-04 · Level 2 복수 메뉴 분절 및 단위 보존
- **GIVEN**: `아이스 아메리카노 두 잔, 치즈케이크 한 개를 담았습니다.` 문장이 주어졌을 때
- **WHEN**: `level=2`로 변환한다
- **THEN**: `아이스 아메리카노. 두 잔입니다. 치즈케이크. 한 개입니다. 장바구니에 담았습니다.`가 반환된다.

### AC-05 · 유효하지 않은 Level 입력 시 ValueError
- **GIVEN**: `level=5`가 주어졌을 때
- **WHEN**: 변환 함수를 호출한다
- **THEN**: `ValueError`가 발생한다.
