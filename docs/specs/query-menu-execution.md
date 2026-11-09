---
title: "O-03 — QUERY_MENU 실제 실행"
tags: [spec]
---

# O-03 — QUERY_MENU 실제 실행

## Why

- **페르소나**: 메뉴판을 터치로 탐색하지 않고 음성으로 메뉴와 가격을 확인하려는 고령 사용자
- **상황**: NLU는 `QUERY_MENU`를 생성하지만 Order Engine은 현재 이를 실행하지 않는다.
- **문제**: 메뉴 조회 발화가 `UNSUPPORTED_UTTERANCE`로 실패한다.
- **측정 지표**: 조회 정확도 100%, Cart 비변경률 100%

## Goal

- 전체·카테고리·단일 메뉴를 Menu Catalog 기준으로 조회한다.
- 공식 메뉴명·가격과 단일 메뉴의 지원 온도를 안내한다.
- **Out of Scope**: 메뉴 이름 별칭 검색, 개인화·자유 추천, 품절·재고, RAG

## What

1. `target_item_id`가 있으면 단일 메뉴의 가격과 지원 온도를 안내한다.
2. `category_id`가 있으면 해당 카테고리 메뉴명과 가격을 카탈로그 순서로 안내한다.
3. 두 값이 모두 `null`이면 전체 메뉴를 안내한다.
4. 두 값이 모두 있으면 `INVALID_COMMAND`를 반환한다.
5. 존재하지 않는 대상은 `MENU_NOT_FOUND`를 반환하며 Cart를 유지한다.
6. `query_tags`가 있으면 모든 태그를 만족하는 메뉴를 카탈로그 순서로 안내한다.
7. `category_id`와 `query_tags`는 함께 사용할 수 있지만 `target_item_id`와 `query_tags`는 함께 사용할 수 없다.
8. `target_item_id`와 `detail_fields`가 있으면 요청한 상세 항목만 안내한다.
9. 음성 응답의 성공한 `QUERY_MENU`가 대상·태그·상세 필드 없이 `category_id`를 가지면 Web은 같은 Command를 기준으로 ORDER 화면의 해당 카테고리 탭을 연다. `category_id=null`이면 전체 메뉴 탭을 연다.

## How

- `ConversationAgent`가 `QUERY_MENU`를 읽기 전용으로 처리한다.
- `quantity`와 `temperature`는 `null`이어야 한다.
- 자연어 태그 별칭과 표준 태그 목록은 `docs/specs/menu-tag-search.md`를 따른다.
- 단일 메뉴 상세 항목과 응답 규칙은 `docs/specs/menu-detail-questions.md`를 따른다.
- 응답 데이터는 주입된 `MenuItem` 목록만 사용한다.
- NLU fallback이 `QUERY_MENU(category_id=null, query_tags=[category_id])`를 반환하면, 그 tag가 현재 Menu Catalog의 유효한 단일 category ID일 때만 `category_id` 조회로 canonicalize한다. 다른 tag·복수 tag 검색은 변경하지 않는다.

## AC

### AC-01 · 카테고리 조회

- **GIVEN**: MVP Menu Catalog가 있다.
- **WHEN**: `QUERY_MENU`, `category_id=coffee`를 실행한다.
- **THEN**: 커피 메뉴 3개와 가격을 안내하고 Cart를 유지한다.

### AC-02 · 단일·전체 조회

- **GIVEN**: MVP Menu Catalog가 있다.
- **WHEN**: target 메뉴 또는 전체 메뉴를 조회한다.
- **THEN**: 요청 범위의 공식 메뉴 정보를 안내한다.

### AC-03 · 잘못된 조회

- **GIVEN**: 존재하지 않는 ID 또는 target/category 동시 입력이 있다.
- **WHEN**: `QUERY_MENU`를 실행한다.
- **THEN**: 안전한 오류를 반환하고 Cart를 변경하지 않는다.

### AC-04 · 음성 메뉴 탭

- **GIVEN**: 음성 `/api/audio/interpret` 응답에 성공한 전체 또는 카테고리 범위 `QUERY_MENU` Command가 있다.
- **WHEN**: Web이 voice navigation을 적용한다.
- **THEN**: raw transcript를 재해석하지 않고 ORDER 화면의 `category_id` 탭 또는 전체 메뉴 탭을 렌더링한다.
