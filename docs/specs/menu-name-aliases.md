# NLU 메뉴 이름 별칭 정규화

## Why

- **페르소나**: 긴 메뉴명을 반복해서 말하기 어려운 고령 사용자
- **상황**: 사용자가 `아이스 아메리카노` 대신 `아아`처럼 익숙한 줄임말로 주문한다.
- **문제**: 현재 NLU는 공식 메뉴명만 인식하므로 유효한 주문도 지원 불가로 거부한다.
- **측정 지표**: 등록 별칭 해석 성공률, 잘못된 메뉴·온도 매핑 건수, 모호한 별칭 재질문 성공률

## Goal

- **해결 목표**: 승인된 메뉴 별칭을 공식 Menu ID와 필요한 온도로 결정론적으로 정규화한다.
- **성공 기준**:
  - 현재 Menu DB에 존재하는 사진 기준 별칭 6개가 모두 정확한 메뉴·온도로 해석된다.
  - Menu DB에 없는 아이스 초코·돌체라떼 관련 별칭은 등록하지 않는다.
  - 하나의 별칭이 여러 메뉴를 가리키면 Command를 만들지 않고 후보를 제시한다.
  - 별칭을 사용해도 NLU 출력의 `target_item_id`에는 공식 Menu ID만 기록한다.
- **Out of Scope**:
  - 사진에 없는 줄임말과 일반 상품군 표현
  - `아샷추`, `아바샷`처럼 메뉴와 추가 옵션을 동시에 뜻하는 복합 별칭
  - Local LLM 학습과 3,000문장 데이터셋 작성

## What

### Happy Path

| 별칭 | 공식 메뉴 | Menu ID | 온도 |
|---|---|---|---|
| `아아` | 아이스 아메리카노 | `americano` | `iced` |
| `뜨아` | 따뜻한 아메리카노 | `americano` | `hot` |
| `아라` | 아이스 카페라떼 | `cafe_latte` | `iced` |
| `뜨라` | 따뜻한 카페라떼 | `cafe_latte` | `hot` |
| `아바라` | 아이스 바닐라라떼 | `vanilla_latte` | `iced` |
| `뜨바라` | 따뜻한 바닐라라떼 | `vanilla_latte` | `hot` |

### Edge Cases

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | `아초`, `아돌라` 입력 | 현재 Menu DB에 대상이 없으므로 `UNSUPPORTED_UTTERANCE` |
| EC-02 | 정규화한 동일 별칭이 여러 메뉴를 가리킴 | `AMBIGUOUS_TARGET`, `field=target_item_id`, 공식 Menu ID 후보 반환 |
| EC-03 | 별칭에 수량이 없음 | 기존 계약대로 `MISSING_FIELD`, `field=quantity` 반환 |
| EC-04 | 한 발화에 여러 등록 별칭이 있음 | 별칭별 등장 순서를 보존해 NLU가 Batch 해석에 사용할 수 있게 반환 |
| EC-05 | 공식 메뉴명을 사용함 | 별칭 정규화 없이 기존 NLU 경로 유지 |

## How

- `src/config/menu.json`의 최상위 `menu_aliases`가 별칭, 공식 Menu ID, 내장 온도의 SSOT다.
- MenuItem 내부에는 `aliases`를 두지 않아 메뉴 정보와 NLU 표현 사전을 분리한다.
- 별칭 비교는 Unicode NFC와 대소문자 정규화 후 독립 어절 및 허용 조사 경계에서 수행한다.
- Resolver는 특정 Local LLM과 독립적으로 별칭 해석 목록을 반환한다.
- Mock NLU는 단일 별칭 주문을 E2E로 검증하고, 실제 학습 Label에는 공식 Menu ID와 온도만 기록한다.
- 별칭 충돌 시 임의 우선순위를 적용하지 않는다.

## AC (Given-When-Then)

### AC-01 · 여섯 별칭의 메뉴·온도 매핑

- GIVEN: Menu DB의 별칭 6개가 로드돼 있다.
- WHEN: 각 별칭을 해석한다.
- THEN: 표에 정의한 공식 Menu ID와 온도가 정확히 반환된다.

### AC-02 · 현재 메뉴에 없는 별칭 제외

- GIVEN: 현재 Menu DB에는 아이스 초코와 돌체라떼가 없다.
- WHEN: `아초`, `아돌라`를 해석한다.
- THEN: 별칭 결과가 없고 Mock NLU는 `UNSUPPORTED_UTTERANCE`를 반환한다.

### AC-03 · 모호한 별칭 재질문

- GIVEN: 정규화한 동일 별칭이 서로 다른 Menu ID에 연결돼 있다.
- WHEN: Resolver가 해당 발화를 해석한다.
- THEN: NLU는 `AMBIGUOUS_TARGET`과 중복 없는 후보를 반환하고 주문을 실행하지 않는다.

### AC-04 · 기존 공식 메뉴명 회귀 방지

- GIVEN: 기존 공식 메뉴명 주문·조회 테스트가 있다.
- WHEN: 전체 NLU·Order Engine 테스트를 실행한다.
- THEN: 기존 결과가 모두 유지된다.
