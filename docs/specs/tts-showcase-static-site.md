---
title: "TTS 최종 제출용 정적 쇼케이스"
tags: [spec, tts, showcase]
---

# TTS 최종 제출용 정적 쇼케이스

## Why

- 검토자가 모델과 Adaptive TTS Level 0·1·2 음성을 backend 없이 비교 청음하고, 숫자 발음 개선의 입력 근거를 함께 확인해야 한다.

## Goal

- 모델 비교와 속도 비교를 `artifacts/showcase/`에 독립 HTML·WAV·JSON으로 생성한다.
- 각 비교 모델에는 단 하나의 공통 텍스트 정규화 결과를 입력한다.
- Out of Scope: 모델 학습, 라이브 TTS API, 외부 공개와 AI Hub 음성의 배포 허용 판정.

## What

1. 원문 주문 문장을 공통 `normalize_korean_text_for_tts()`로 한 번 정규화한다.
2. 모델별 비교는 같은 normalized text로 각 모델의 WAV를 생성한다.
3. Adaptive 비교는 실제 Order Engine 응답을 `AdaptiveResponseRealizer`와 `AdaptiveTextTransformer.transform_to_chunks()`에 전달하고, 각 chunk를 해당 Level로 개별 합성한 뒤 non-final chunk 뒤의 production gap을 WAV에 삽입한다.
4. HTML에는 대표 문장, 실제 realized response/chunk, 모델/레벨, 재생기를 표시한다.

## How

```bash
HF_HUB_OFFLINE=1 PYTHONPATH=src .venvs/runtime/bin/python scripts/showcase/build_tts_offline_showcase.py \
  --adaptive-only --output-dir artifacts/showcase/tts
```

- 대표 세트는 장바구니 요약(매장 이용·아이스 아메리카노 1잔·따뜻한 카페라떼 2잔·15,100원), 복수 메뉴 추가(아이스 아메리카노·바스크 치즈 케이크), 가격 안내(카페라떼 5,200원)로 고정한다.
- 모든 오디오는 출력 디렉터리의 상대 경로만 참조하며 `localhost`와 개인 도메인을 포함하지 않는다.

## AC

- GIVEN: 가격·수량이 든 원문 WHEN: 모델 비교 생성 THEN: 각 모델 행의 normalized text가 같고 한글 수사로 표시된다.
- GIVEN: Level 0·1·2 WHEN: Adaptive 비교 생성 THEN: 각 레벨의 WAV는 production chunk별 합성과 gap을 포함하고 실제 합성 chunk를 표시한다.
- GIVEN: 생성 HTML WHEN: `file://`로 연다 THEN: backend와 외부 URL 없이 WAV를 재생할 수 있다.
