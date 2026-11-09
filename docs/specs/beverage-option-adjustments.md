# 음료 옵션 조절 — Size·샷·카페인·시럽·얼음

## Why

- **페르소나**: 터치 화면에서 여러 옵션 단계를 찾기 어려워 음성으로 음료를 맞춤 주문하려는 고령 사용자
- **상황**: 사용자는 `큰 사이즈로`, `아메리카노 디카페인으로 줘`, `시럽 넣어줘`, `얼음 조금 넣어줘`, `카페라떼에 샷을 더 넣어줘`처럼 말한다.
- **문제**:
  1. 현재 `UPDATE_OPTION`은 HOT·ICED 변경만 지원한다.
  2. 옵션 조합을 Cart에 저장하지 않으면 같은 메뉴·온도의 서로 다른 맞춤 주문을 구분할 수 없다.
  3. 메뉴가 지원하지 않는 옵션을 임의 적용하면 실제 제공 불가능한 주문이 만들어진다.
  4. 옵션 가격 출처가 없으므로 임의 가격을 더하면 총액이 부정확해진다.
- **측정 지표**: 옵션 상태 전이 정확도, 미지원 옵션 차단률, Cart 원자성, 기존 주문 회귀 테스트 통과율

## Goal

- **해결 목표**: `ADD_ITEM`과 `UPDATE_OPTION`에서 Size·샷·카페인·시럽·얼음 양을 결정론적으로 검증하고 Cart에 보존한다.
- **성공 기준**:
  - Size는 `SMALL`·`MEDIUM`·`LARGE`이며 생략 시 `MEDIUM`을 적용한다.
  - 샷·시럽은 0 이상의 정수이며 서비스 정책상 최대 횟수 제한이 없다.
  - 카페인은 `REGULAR`·`DECAF`, 얼음은 `NONE`·`LESS`·`NORMAL`·`MORE`를 지원한다.
  - 옵션별 Menu DB 정책과 온도 제약을 위반한 요청은 `INVALID_OPTION`으로 거부하고 기존 Cart를 유지한다.
  - 같은 메뉴·온도라도 옵션 조합이 다르면 별도 CartItem으로 유지한다.
  - `base_price`는 MEDIUM 가격이며 SMALL은 500원 차감, LARGE는 500원 추가한다. 기존 샷·시럽·디카페인·얼음 옵션의 추가 금액은 MVP에서 0원이다.
  - `options=null`인 기존 Command와 옵션이 없는 기존 CartItem 동작을 모두 유지한다.
- **Out of Scope**:
  - 샷·시럽·디카페인 추가 요금
  - 시럽 맛, 우유 종류, 휘핑, 토핑
  - 여러 CartItem 중 대상을 추측하는 자동 우선순위
  - Local LLM 학습과 전체 3,000문장 데이터셋 제작

## What

### 옵션 값

| 옵션 | Command 값 | 의미 |
|---|---|---|
| Size | `size: SMALL/MEDIUM/LARGE` | 생략 시 MEDIUM, 디저트는 null |
| 추가 샷 | `extra_shots: integer >= 0` | 최종 추가 샷 횟수, 서비스 상한 없음 |
| 카페인 | `caffeine: REGULAR/DECAF` | 일반 카페인 또는 디카페인 |
| 시럽 | `syrup_pumps: integer >= 0` | 최종 시럽 펌프 수, 서비스 상한 없음 |
| 얼음 | `ice_amount: NONE/LESS/NORMAL/MORE` | 얼음 없음·적게·보통·많이 |

Command의 옵션 객체에서 `null`인 하위 필드는 변경하지 않는다는 뜻이다. NLU는 상대 증감 표현도 현재 Cart Context를 이용해 변경 후 최종 정수로 출력한다. `0`, `REGULAR`, `NORMAL`은 각각 확정된 canonical 값이며, 어떤 값을 메뉴 기본값으로 사용할지는 별도 메뉴 정책이 확정하기 전까지 가정하지 않는다.

### 메뉴별 허용 정책

메뉴별 Size·샷·디카페인·시럽·얼음 적용 가능성은 [`menu-catalog.md`](menu-catalog.md)의 `MenuOptionPolicy` 표를 단일 기준으로 사용한다. 이 문서에서는 같은 표를 복사하지 않는다. `아초샷`은 아이스 초코가 Menu DB에 없으므로 지원하지 않는다.

### Happy Path

1. 완전한 신규 주문 `아이스 아메리카노 한 잔 디카페인으로 주세요`는 `ADD_ITEM`과 `caffeine=DECAF`로 Cart에 추가한다.
2. Cart에 대상이 하나일 때 `시럽 넣어줘`는 최종 `syrup_pumps`를 1 증가시킨 `UPDATE_OPTION`을 실행한다.
3. Cart의 카페라떼에 `샷을 더 넣어줘`라고 하면 최종 `extra_shots`를 1 증가시킨다.
4. 아이스 음료에 `얼음 조금 넣어줘`라고 하면 `ice_amount=LESS`로 변경한다.
5. `아샷추 한 잔 주세요`는 아이스티·ICED·추가 샷 1회, `아바샷 한 잔 주세요`는 바닐라라떼·ICED·추가 샷 1회로 해석한다.
6. Query Cart와 주문확인 응답은 적용된 옵션과 기존 총액을 함께 안내한다.

### Edge Cases

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | HOT 음료에 얼음 양 지정 | `INVALID_OPTION`, Cart 유지 |
| EC-02 | 디저트에 음료 옵션 지정 | `INVALID_OPTION`, Cart 유지 |
| EC-03 | 샷·시럽이 음수 또는 정수가 아님 | Schema Validation 실패, Cart 유지 |
| EC-04 | 디카페인 미지원 메뉴에 요청 | `INVALID_OPTION`, Cart 유지 |
| EC-05 | 짧은 수정 발화인데 Cart가 비어 있음 | `MISSING_FIELD`, 대상 메뉴 재입력 안내 |
| EC-06 | 같은 메뉴 후보가 여러 개임 | `AMBIGUOUS_TARGET`, 후보를 추측하지 않음 |
| EC-07 | 같은 메뉴·온도·옵션 조합이 반복됨 | Command를 합치고 수량 합산 |
| EC-08 | 같은 메뉴·온도지만 옵션 조합이 다름 | 별도 CartItem 유지 |
| EC-09 | `아메리카노 디카페인으로 줘`에 수량·온도가 없고 Cart 대상도 없음 | 기존 누락 정책에 따라 필요한 필드를 재질문 |
| EC-10 | `아초샷` 요청 | 대상 메뉴가 없으므로 `UNSUPPORTED_UTTERANCE` |
| EC-11 | 디저트 또는 Size 미지원 메뉴에 Size 요청 | `INVALID_OPTION`, Cart 유지 |

## How

### OrderCommand

기존 의미 필드에 `options`를 추가한다. 사용하지 않으면 `null`이다.

```json
{
  "intent": "ADD_ITEM",
  "target_item_id": "americano",
  "category_id": null,
  "quantity": 1,
  "temperature": "iced",
  "query_tags": null,
  "detail_fields": null,
  "options": {
    "size": null,
    "extra_shots": null,
    "caffeine": "DECAF",
    "syrup_pumps": null,
    "ice_amount": null
  }
}
```

- Local LLM 의미 필드는 8개, 런타임 `request_id` 포함 필드는 9개다.
- `options`는 `ADD_ITEM`, `UPDATE_OPTION`에서만 값이 허용된다.
- `UPDATE_OPTION`은 `temperature` 또는 하나 이상의 옵션 하위 필드를 가져야 한다.
- NLU는 Cart Context를 참고해 샷·시럽의 증감량이 아닌 변경 후 최종 값을 출력한다.

### CartItem

```text
CartItem
├── menu_id
├── quantity
├── temperature
├── unit_price
└── options
    ├── extra_shots
    ├── size
    ├── caffeine
    ├── syrup_pumps
    └── ice_amount
```

- CartItem 동일성 키는 `menu_id + temperature + normalized options`다.
- `unit_price`는 MEDIUM에서 `base_price`, SMALL에서 `base_price - 500`, LARGE에서 `base_price + 500`이다. 나머지 옵션 추가 요금은 0원이다.
- Query·Confirm·UNDO·Session 직렬화는 옵션을 보존한다.

### Menu DB

각 MenuItem의 `option_policy`가 메뉴별 허용 범위의 SSOT다.

```json
{
  "size_supported": true,
  "shot_supported": true,
  "caffeine_options": ["REGULAR", "DECAF"],
  "syrup_supported": true,
  "ice_amount_options": ["NONE", "LESS", "NORMAL", "MORE"]
}
```

`shot_supported`와 `syrup_supported`는 적용 가능성만 나타내며 최대 횟수를 정의하지 않는다.

## AC (Given-When-Then)

### AC-01 · 신규 디카페인 주문

- GIVEN: 빈 Cart와 디카페인을 지원하는 아메리카노가 있다.
- WHEN: ICED 아메리카노 1잔, `caffeine=DECAF`인 `ADD_ITEM`을 실행한다.
- THEN: CartItem에 디카페인 옵션이 저장되고 총액은 4,700원이다.

### AC-02 · 기존 메뉴 샷 추가

- GIVEN: Cart에 추가 샷이 없는 카페라떼가 하나 있다.
- WHEN: `extra_shots=1`인 `UPDATE_OPTION`을 실행한다.
- THEN: 같은 CartItem의 추가 샷 최종 값이 1이 된다.

### AC-03 · 시럽과 얼음 변경

- GIVEN: Cart에 아이스 음료가 하나 있다.
- WHEN: 시럽 1회와 얼음 적게를 각각 요청한다.
- THEN: 두 변경이 순서대로 누적되고 Query Cart 응답에 두 옵션이 표시된다.

### AC-04 · 메뉴 정책 검증과 원자성

- GIVEN: 디저트 또는 HOT 음료가 Cart에 있다.
- WHEN: 지원하지 않는 샷·시럽·얼음 옵션을 요청한다.
- THEN: `INVALID_OPTION`을 반환하고 Cart는 요청 전과 같다.

### AC-05 · 옵션 조합별 Cart 분리

- GIVEN: 빈 Cart가 있다.
- WHEN: 같은 ICED 아메리카노를 일반·디카페인으로 각각 추가한다.
- THEN: 옵션 조합이 다른 CartItem 두 개로 유지된다.

### AC-06 · 옵션 복합 별칭

- GIVEN: 현재 Menu DB에 아이스티와 바닐라라떼가 있다.
- WHEN: `아샷추 한 잔 주세요`, `아바샷 한 잔 주세요`를 각각 입력한다.
- THEN: 각 공식 Menu ID·ICED·추가 샷 1회 Command가 생성된다.

### AC-07 · 기존 기능 회귀 방지

- GIVEN: `options=null`인 기존 주문·조회·수정·UNDO 테스트가 있다.
- WHEN: 전체 테스트를 실행한다.
- THEN: 기존 Cart 상태·가격·응답이 유지된다.

### AC-08 · 샷·시럽 무상한 계약

- GIVEN: 샷 또는 시럽을 지원하는 메뉴가 있다.
- WHEN: `extra_shots=4` 또는 `syrup_pumps=12`인 Command를 검증한다.
- THEN: 두 값은 0 이상의 정수이므로 횟수 상한만을 이유로 거부하지 않는다.

### AC-09 · Size 기본값과 가격

- GIVEN: `base_price=4,700원`인 Size 지원 음료가 있다.
- WHEN: Size 생략, SMALL, LARGE로 각각 주문한다.
- THEN: Size와 단가는 차례대로 MEDIUM·4,700원, SMALL·4,200원, LARGE·5,200원이다.
