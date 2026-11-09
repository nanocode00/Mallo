---
title: "C-02~C-06 — MVP Menu Catalog"
tags: [spec]
---

# C-02~C-06 — MVP Menu Catalog

## Why

- **페르소나**: 음성으로 카페 메뉴 여러 종류를 한 번에 주문하는 말로(Mallo)의 고령 사용자
- **상황**: 기존 Mock Pipeline에는 아메리카노 1개와 임시 가격만 존재한다.
- **문제**:
  1. NLU와 Order Engine이 사용할 메뉴 ID·가격·온도 규칙이 확정되지 않았다.
  2. 공식 메뉴와 승인된 줄임말을 분리하지 않으면 NLU 표현 사전이 메뉴 데이터에 섞인다.
  3. 품절 처리는 ADD_ITEM 기본 흐름 검증과 직접 관련이 없다.
- **측정 지표**: 메뉴 10개 등록률, Schema 검증 통과율, 공식 메뉴·승인 별칭 매칭 정확도

## Goal

- **해결 목표**: 메뉴 10개의 ID·공식 이름·카테고리·가격·온도·음료 옵션 정책·탐색 태그를 하나의 카탈로그로 고정한다.
- **성공 기준**:
  - Category 4개와 MenuItem 10개가 존재한다.
  - 모든 ID가 소문자 snake_case이며 중복되지 않는다.
  - 모든 가격이 0보다 큰 대한민국 원 단위 정수다.
  - 음료 6개는 `hot`, `iced`, 자몽에이드와 아이스티는 `iced`만 지원하고 디저트 2개는 온도 옵션이 없다.
  - MenuItem에는 alias를 저장하지 않고 승인된 메뉴 별칭은 최상위 `menu_aliases`에 분리한다.
  - 모든 MenuItem은 Size·샷·디카페인·시럽·얼음 허용 범위를 `option_policy`로 가진다.
  - 스타벅스에 같은 메뉴가 없으면 다른 카페의 동일 이름 메뉴 가격만 사용한다.
  - 모든 가격에 브랜드, 출처 메뉴명, URL, 확인 날짜를 기록한다.
- **Out of Scope**:
  - `menu_aliases`에 등록되지 않은 약칭·유사어
  - 품절 및 재고 관리
  - 시럽 맛·휘핑·우유 종류·토핑 변경과 옵션 추가 요금
  - 할인·쿠폰·세트·다국어·알레르기·영양 정보

## What

### 최종 메뉴

가격은 2026-08-14 확인값이다. 스타벅스에서 동일 메뉴를 먼저 확인하고, 없으면 다른 카페의 동일 이름 메뉴를 사용한다. 띄어쓰기 차이는 같은 이름으로 보지만 수식어가 추가된 비슷한 메뉴는 대체 가격으로 사용하지 않는다. 매장 주문 페이지에서 확인한 가격은 지점·주문 방식에 따라 달라질 수 있으므로 MVP 카탈로그에는 확인 당시 가격을 고정한다.

| ID | 메뉴명 | Category | Price | Unit | Temperature | Price Source |
|---|---|---|---:|---|---|---|
| `americano` | 아메리카노 | `coffee` | 4,700 | 잔 | HOT / ICED | 스타벅스 `카페 아메리카노 Tall` |
| `cafe_latte` | 카페라떼 | `coffee` | 5,200 | 잔 | HOT / ICED | 스타벅스 `카페 라떼 Tall` |
| `vanilla_latte` | 바닐라라떼 | `coffee` | 3,400 | 잔 | HOT / ICED | 메가MGC커피 `바닐라라떼` |
| `grapefruit_ade` | 자몽에이드 | `non_coffee` | 3,500 | 잔 | ICED만 | 메가MGC커피 `자몽에이드` |
| `matcha_latte` | 말차라떼 | `non_coffee` | 3,500 | 잔 | HOT / ICED | 더벤티 `말차라떼` |
| `milk_tea` | 밀크티 | `tea` | 3,500 | 잔 | HOT / ICED | 빽다방 `밀크티` |
| `chamomile_tea` | 캐모마일티 | `tea` | 3,700 | 잔 | HOT / ICED | 매머드커피 `캐모마일티` |
| `iced_tea` | 아이스티 | `tea` | 4,700 | 잔 | ICED만 | 할리스 `아이스티` |
| `croffle_icecream` | 크로플 아이스크림 | `dessert` | 5,500 | 개 | 없음 | 에브리커피 `크로플 아이스크림` |
| `basque_cheesecake` | 바스크 치즈 케이크 | `dessert` | 6,500 | 개 | 없음 | 어쏠트먼트 `바스크 치즈 케이크` |

### 스타벅스에서 동일 이름을 확인하지 못한 메뉴

- 바닐라라떼
- 자몽에이드
- 말차라떼
- 밀크티
- 캐모마일티
- 아이스티
- 크로플 아이스크림
- 바스크 치즈 케이크

`제주 말차 라떼`, `스타벅스 클래식 밀크 티`, `캐모마일 블렌드 티`, `복숭아 아이스 티`, `모찌 쏙 바스크 치즈 케이크` 등은 이름이 다르므로 가격 대체에 사용하지 않았다.

### 공식 메뉴명과 승인된 별칭

- 최종 메뉴 대상 식별과 `OrderCommand.target_item_id`에는 공식 `id`만 사용한다.
- `아아`, `뜨아`, `아라`, `뜨라`, `아바라`, `뜨바라`만 승인된 메뉴 별칭으로 지원한다.
- MenuItem에는 `aliases` 필드가 없고 별칭은 최상위 `menu_aliases`에서 메뉴 ID·온도와 연결한다.
- 등록되지 않은 약칭 입력은 `UNSUPPORTED_UTTERANCE`로 처리한다.

### Happy Path

1. 사용자가 `아이스 아메리카노 두 잔이랑 따뜻한 카페라떼 한 잔 주세요`라고 말한다.
2. NLU가 두 메뉴를 발화 순서대로 각각의 `ADD_ITEM` Command로 구조화한다.
3. Order Engine이 `menu.json`에서 모든 메뉴와 온도를 먼저 검증한다.
4. 모든 항목이 유효하면 아메리카노 2잔과 카페라떼 1잔을 Cart에 함께 추가한다.
5. GUI와 TTS가 두 주문과 총액을 안내한다.

### Edge Cases

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | `아아 두 잔 주세요` | `americano`, `iced`, 수량 2로 정규화 |
| EC-02 | 아메리카노 온도 누락 | P0는 Cart를 변경하지 않고 `MISSING_FIELD`, `field=temperature`와 재입력 안내, P1만 Clarification |
| EC-03 | 디저트에 온도 지정 | Cart를 변경하지 않고 `INVALID_OPTION` |
| EC-04 | 존재하지 않는 메뉴 | Cart를 변경하지 않고 `MENU_NOT_FOUND` |
| EC-05 | 수량이 0 또는 음수 | Cart를 변경하지 않고 `INVALID_QUANTITY` |
| EC-06 | 메뉴 두 종류가 한 문장에 포함됨 | 발화 순서대로 두 개의 `ADD_ITEM` Command 생성 |
| EC-07 | 복수 Command 중 하나가 잘못됨 | Batch 전체를 취소하고 Cart를 유지 |
| EC-08 | 자몽에이드 또는 아이스티에 HOT 지정 | Cart를 변경하지 않고 `INVALID_OPTION` |

## How

### Menu Catalog 구조

```text
MenuCatalog
├── version: string
├── currency: "KRW"
├── categories: Category[4]
├── menu_aliases: MenuAliasDefinition[6]
├── tag_definitions: MenuTagDefinition[]
└── items: MenuItem[10]
```

### Category

| Field | Type | Required | Constraint |
|---|---|---|---|
| `id` | string | O | 소문자 snake_case, 고유값 |
| `name` | string | O | 비어 있지 않은 표시명 |
| `sort_order` | integer | O | 1 이상의 고유 정수 |

### MenuItem

| Field | Type | Required | Constraint |
|---|---|---|---|
| `id` | string | O | 소문자 snake_case, 고유값 |
| `category_id` | string | O | 존재하는 Category ID |
| `name` | string | O | 공식 메뉴명 |
| `description` | string | O | 사용자 안내용 설명 |
| `base_price` | integer | O | KRW, 0보다 큼 |
| `unit` | enum | O | `잔` 또는 `개` |
| `temperature_options` | string[] | O | 일반 음료는 `hot`, `iced`; 자몽에이드·아이스티는 `iced`; 디저트는 빈 배열 |
| `tags` | string[] | O | `tag_definitions`에 존재하는 표준 태그 ID, 중복 금지 |
| `option_policy` | object | O | Size·샷·디카페인·시럽·얼음 허용 범위 |
| `price_source_brand` | string | O | 기준 가격을 확인한 카페 브랜드 |
| `price_source_menu_name` | string | O | 출처에 표시된 실제 메뉴명 |
| `price_source_url` | string | O | 가격 확인 URL |
| `price_checked_at` | `YYYY-MM-DD` | O | 가격 확인 날짜 |

`aliases`, `available` 필드는 사용하지 않는다. 음료 Size는 `SMALL`, `MEDIUM`, `LARGE`를 지원하고 기본값은 `MEDIUM`이다. `base_price`는 MEDIUM 가격이며 SMALL은 500원 차감, LARGE는 500원 추가한다. 디저트의 Size는 `null`이다.

### MenuAliasDefinition

| Field | Type | Required | Constraint |
|---|---|---|---|
| `alias` | string | O | 승인된 한국어 줄임말 |
| `target_item_id` | string | O | 존재하는 공식 Menu ID |
| `temperature` | `hot`, `iced`, null | O | 메뉴가 지원하는 내장 온도 |

별칭 정책과 충돌 처리는 [`menu-name-aliases.md`](menu-name-aliases.md)를 따른다.

### MenuOptionPolicy

| Field | Type | Required | Constraint |
|---|---|---|---|
| `size_supported` | boolean | O | 음료 `true`, 디저트 `false` |
| `shot_supported` | boolean | O | 추가 샷 적용 가능 여부; 지원 메뉴의 횟수 상한 없음 |
| `caffeine_options` | string[] | O | `REGULAR`, `DECAF` 중 메뉴가 지원하는 값 |
| `syrup_supported` | boolean | O | 시럽 펌프 적용 가능 여부; 지원 메뉴의 횟수 상한 없음 |
| `ice_amount_options` | string[] | O | ICED 음료에 적용 가능한 `NONE`, `LESS`, `NORMAL`, `MORE`; 미지원이면 빈 배열 |

메뉴별 적용 가능성은 다음 표가 기준이다. Size 지원 음료에는 `SMALL | MEDIUM | LARGE`를 적용한다. 생략값 `null`은 기본 `MEDIUM`과 동일하게 해석하되 Cart에는 `null`로 유지해 기존 주문과 중복 품목을 만들지 않는다.

| Menu ID | Size | Shot | Decaf | Syrup | Ice amount |
|---|:---:|:---:|:---:|:---:|:---:|
| `americano` | O | O | O | O | ICED일 때 O |
| `cafe_latte` | O | O | O | O | ICED일 때 O |
| `vanilla_latte` | O | O | O | O | ICED일 때 O |
| `iced_tea` | O | O | X | O | O |
| `grapefruit_ade` | O | X | X | O | O |
| `matcha_latte` | O | X | X | O | ICED일 때 O |
| `milk_tea` | O | X | X | O | ICED일 때 O |
| `chamomile_tea` | O | X | X | O | ICED일 때 O |
| 디저트 2종 | X | X | X | X | X |

옵션 값, 변경 의미와 검증 규칙은 [`beverage-option-adjustments.md`](beverage-option-adjustments.md)를 따른다.

### MenuTagDefinition

| Field | Type | Required | Constraint |
|---|---|---|---|
| `id` | string | O | 소문자 snake_case, 고유한 표준 태그 ID |
| `name` | string | O | 화면·음성 안내에 사용할 표시명 |
| `aliases` | string[] | O | 동일 조건을 뜻하는 한국어 표현, 전체 정의에서 중복 금지 |

태그는 메뉴 탐색용 정성 메타데이터이며 영양·알레르기 보증으로 사용하지 않는다.

### 파일 책임

| File | Responsibility |
|---|---|
| `docs/specs/menu-catalog.md` | 사람이 읽는 메뉴 정책과 AC |
| `src/config/menu.json` | 런타임 메뉴 데이터의 Single Source of Truth |
| `schemas/menu.schema.json` | Menu Catalog 기본 구조 검증 |
| `tests/unit/test_menu_schema.py` | 참조 무결성·개수·온도·금지 필드 검증 |

## AC (Given-When-Then)

### AC-01 · 메뉴 카탈로그 완전성

- GIVEN: 최종 `menu.json`이 있다.
- WHEN: 메뉴 Schema 테스트를 실행한다.
- THEN: Category 4개와 MenuItem 10개가 존재하고 모든 ID가 고유하다.

### AC-02 · 가격과 필수 필드

- GIVEN: 최종 `menu.json`이 있다.
- WHEN: `menu.schema.json`으로 검증한다.
- THEN: 모든 가격은 0보다 큰 정수이며 필수 필드가 누락되지 않는다.

### AC-03 · Size 지원 상태

- GIVEN: 최종 `menu.json`이 있다.
- WHEN: 메뉴별 `size_supported`를 검사한다.
- THEN: 음료 8개는 `true`, 디저트 2개는 `false`이며 음료 Size 생략값 `null`은 MEDIUM 가격으로 계산되고 디저트는 `null`만 허용한다.

### AC-03-1 · Size 가격

- GIVEN: `base_price`가 MEDIUM 가격인 Size 지원 음료가 있다.
- WHEN: 같은 음료를 SMALL, MEDIUM, LARGE로 각각 주문한다.
- THEN: 단가는 차례대로 `base_price - 500`, `base_price`, `base_price + 500`원이다.

### AC-04 · 온도 정책

- GIVEN: 일반 음료 6개, ICE 전용 음료 2개와 디저트 2개가 있다.
- WHEN: 온도 옵션을 검사한다.
- THEN: 일반 음료는 `hot`, `iced`, 자몽에이드와 아이스티는 `iced`, 디저트는 빈 배열만 가진다.

### AC-05 · 카테고리 참조 무결성

- GIVEN: 모든 MenuItem에 `category_id`가 있다.
- WHEN: 참조 무결성 테스트를 실행한다.
- THEN: 모든 `category_id`가 실제 Category를 가리킨다.

### AC-06 · 동일 이름 가격 출처

- GIVEN: 최종 MenuItem 10개가 있다.
- WHEN: 가격과 출처 정보를 검사한다.
- THEN: 스타벅스 동일 메뉴 2개와 다른 카페 동일 이름 메뉴 8개의 검증된 고정 가격을 가진다.

### AC-07 · 가격 출처 추적 가능성

- GIVEN: 모든 MenuItem에 가격 출처 필드가 있다.
- WHEN: URL과 확인 날짜를 검사한다.
- THEN: 모든 항목에 HTTPS URL과 `2026-08-14` 확인 날짜가 존재한다.

### AC-08 · 태그 참조 무결성

- GIVEN: 모든 MenuItem에 조건 검색 태그가 있다.
- WHEN: 태그 ID와 온도 태그를 검사한다.
- THEN: 모든 태그가 실제 정의를 가리키고 `hot`, `iced` 태그가 `temperature_options`와 일치한다.

### AC-09 · 메뉴 별칭 참조 무결성

- GIVEN: 승인된 메뉴 별칭 6개가 있다.
- WHEN: 별칭의 Menu ID와 온도를 검사한다.
- THEN: 모든 대상 메뉴가 존재하고 내장 온도가 해당 메뉴의 `temperature_options`에 포함된다.

### AC-10 · 음료 옵션 정책

- GIVEN: MenuItem 10개의 `option_policy`가 있다.
- WHEN: Schema와 메뉴별 허용 범위를 검사한다.
- THEN: `max_extra_shots`, `max_syrup_pumps` 필드는 없고 `shot_supported`, `syrup_supported`만 존재하며, 디저트의 모든 음료 옵션 capability는 비활성화돼 있다.
