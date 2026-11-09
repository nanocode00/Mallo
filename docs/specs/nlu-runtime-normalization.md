---
title: "Spec — NLU runtime 입력 정규화"
tags: [spec, nlu, runtime]
---

# NLU runtime 입력 정규화

## Why

- 실제 음성 전사는 메뉴 철자와 한국어 수량을 흔들 수 있으며, 이 값이 그대로 모델에 전달되면 주문 의도와 무관한 실패가 발생한다.
- 원문 발화와 정규화 결과를 함께 보존해 진단 가능해야 한다.

## Goal

- Qwen3-0.6B runtime 입력에서 승인된 메뉴 오인식과 수량 표현을 canonical 텍스트로 바꾼다.
- 명시된 메뉴가 여러 개인 추가 주문은 메뉴별 수량과 순서를 보존한다.
- Out of Scope: Qwen 모델 교체·재학습, 메뉴 ID를 직접 반환하는 규칙 기반 NLU, UI/E2E 변경.

## What

- 승인된 STT 메뉴 오인식만 메뉴 경계에서 canonical 메뉴명으로 바꾼다.
- `한/두/세 잔·개`, `하나/둘/셋`, 숫자+단위를 수량 parser가 읽을 수 있는 숫자+단위로 바꾼다.
- 원문, 정규화문, 적용 규칙은 runtime diagnostic에서 확인 가능하다.

## How

- 정규화는 Qwen 입력 직전에 수행하며 model output은 기존 OrderCommand contract로만 파싱한다.
- 온도가 없는 ADD_ITEM은 먼저 `temperature=null`으로 유지한다. Order Engine은 Menu DB가 단일 온도 메뉴인 경우에만 그 값을 적용하며, HOT/ICE 둘 다 가능한 메뉴에는 새로운 default를 만들지 않는다.
- 여러 명시 메뉴의 추가 요청은 일반 메뉴 mention 분해로만 보정하며, 전체 utterance 일치 규칙은 두지 않는다.

## AC

- GIVEN `카페라테 한 잔` WHEN runtime 입력을 만들면 THEN `카페라떼 1잔`이 되고 원문과 치환 기록이 남는다.
- GIVEN 서로 다른 수량의 명시 메뉴 세 개 WHEN ADD_ITEM을 해석하면 THEN 명령 세 개의 메뉴·수량·발화 순서가 보존된다.
- GIVEN 온도를 말하지 않은 ADD_ITEM WHEN Order Engine이 실행하면 THEN `MISSING_FIELD.temperature` 없이 `temperature=null`으로 추가된다.
