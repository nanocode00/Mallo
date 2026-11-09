---
title: "NLU 마지막 장바구니 변경 실행취소"
tags: [spec]
---

# NLU 마지막 장바구니 변경 실행취소

## Why

- **페르소나**: 잘못 주문했을 때 메뉴를 다시 찾아 직접 수정하기 어려운 고령 사용자
- **상황**: 사용자가 메뉴 추가·삭제·수량·온도 변경 직후 `방금 거 취소해줘`라고 말한다.
- **문제**: 기존 `CANCEL`은 전체 주문을 비우고 `REMOVE_ITEM`은 대상을 다시 지정해야 하므로 직전 실수를 간단히 복구할 수 없다.
- **측정 지표**: 마지막 Cart 복원 정확도 100%, 실패·조회 명령의 이력 비오염률 100%, 다른 세션 Cart 오복원 0건

## Goal

- **해결 목표**: `UNDO` Intent로 마지막으로 성공한 장바구니 변경 1회를 안전하게 되돌린다.
- **성공 기준**: 추가·삭제·수량·온도·전체 취소 복원과 이력 없음·불일치·연속 UNDO 테스트가 모두 통과한다.
- **Out of Scope**: 다단계 Undo, Redo, 앱 재시작 이후 이력 복원, 결제 취소, 조회·TTS 설정 되돌리기

## What

### Happy Path

1. 성공한 Cart 변경 전에 이전 Cart를 복사한다.
2. 변경 후 Cart와 함께 한 단계 Undo 이력으로 저장한다.
3. `UNDO` 시 현재 Cart가 저장된 변경 후 Cart와 일치하는지 확인한다.
4. 일치하면 변경 전 Cart를 복원하고 복원된 내역·총액을 안내한다.
5. 성공한 Undo 후 이력을 비워 같은 변경을 두 번 취소하지 않는다.

### Edge Cases

| ID | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 취소할 변경 이력 없음 | `INVALID_COMMAND`, 현재 Cart 유지 |
| EC-02 | 현재 Cart가 저장된 변경 후 상태와 다름 | `INVALID_COMMAND`, 오래된 이력 폐기 |
| EC-03 | 실패한 Cart 변경 뒤 UNDO | 실패 명령은 이력을 덮지 않고 직전 성공 변경을 복원 |
| EC-04 | 조회·확정·TTS 요청 뒤 UNDO | 비변경 명령은 이력을 덮지 않고 직전 성공 변경을 복원 |
| EC-05 | Undo를 연속 두 번 요청 | 첫 번째만 성공, 두 번째는 이력 없음 오류 |
| EC-06 | 세션 초기화 뒤 UNDO | 이력이 초기화돼 거부 |

## How

- `UNDO`를 12번째 Intent로 추가한다.
- `OrderCommand`의 `target_item_id`, `category_id`, `quantity`, `temperature`, `query_tags`, `detail_fields`, `options`는 모두 `null`이다.
- Undo 대상 Intent는 `ADD_ITEM`, `REMOVE_ITEM`, `UPDATE_QUANTITY`, `UPDATE_OPTION`, `CANCEL`이다.
- 성공했더라도 Cart가 실제로 달라지지 않은 명령은 Undo 이력을 만들지 않는다.
- Undo 이력은 `ConversationAgent` 인스턴스의 메모리에 변경 전·후 Cart 복사본으로 보관한다.
- `VoicePipeline.reset_session()`은 Order Engine의 Undo 이력도 초기화한다.
- `UNDO`는 복구 명령이므로 추가 Confirmation 없이 즉시 실행한다.
- 이력이 없거나 현재 Cart가 불일치하면 기존 `INVALID_COMMAND`를 사용한다.

### 데이터셋 분포

전체 3,000문장과 80/10/10 Split은 유지한다.

| Label Group | 전체 | Train | Validation | Test |
|---|---:|---:|---:|---:|
| `ADD_ITEM` | 400 | 320 | 40 | 40 |
| `REMOVE_ITEM` | 260 | 208 | 26 | 26 |
| `CANCEL` | 140 | 112 | 14 | 14 |
| `UNDO` | 180 | 144 | 18 | 18 |

나머지 Label Group 수량은 기존 분포를 유지한다.

## AC (Given-When-Then)

### AC-01 · 메뉴 추가 실행취소

- **GIVEN**: 빈 Cart에 아이스 아메리카노를 추가했다.
- **WHEN**: `UNDO`를 실행한다.
- **THEN**: Cart가 빈 상태로 복원되고 Undo 이력이 제거된다.

### AC-02 · 수정·삭제·전체 취소 복원

- **GIVEN**: Cart의 수량·온도·항목 또는 전체 Cart를 변경했다.
- **WHEN**: 각 변경 직후 `UNDO`를 실행한다.
- **THEN**: 해당 변경 직전 Cart의 항목·수량·온도·금액·순서가 복원된다.

### AC-03 · 조회와 실패 명령의 이력 보존

- **GIVEN**: 성공한 Cart 변경 뒤 조회 또는 실패 명령을 실행했다.
- **WHEN**: `UNDO`를 실행한다.
- **THEN**: 조회·실패 명령이 아니라 마지막 성공 Cart 변경을 되돌린다.

### AC-04 · 현재 Cart 일치 검증

- **GIVEN**: 저장된 변경 후 Cart와 다른 Cart가 전달됐다.
- **WHEN**: `UNDO`를 실행한다.
- **THEN**: Cart를 변경하지 않고 `INVALID_COMMAND`를 반환하며 오래된 이력을 폐기한다.

### AC-05 · 세션·연속 실행 안전성

- **GIVEN**: Undo를 이미 실행했거나 세션을 초기화했다.
- **WHEN**: 다시 `UNDO`를 실행한다.
- **THEN**: Cart를 유지하고 취소할 변경이 없다고 안내한다.

### AC-06 · NLU 계약과 데이터셋

- **GIVEN**: 12개 Intent Schema와 최종 NLU CSV가 있다.
- **WHEN**: Schema 및 final 데이터셋 검증을 실행한다.
- **THEN**: `UNDO` 180개를 포함한 정확히 3,000문장이 80/10/10으로 분할된다.
