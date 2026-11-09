---
title: "최종 쇼케이스 및 소개 페이지 자산 갱신"
tags: [spec, showcase, release]
---

# 최종 쇼케이스 및 소개 페이지 자산 갱신

## Why

- **페르소나**: 최종 제출물을 확인하는 평가자와 말로를 처음 보는 고객.
- **상황**: 공개 TTS 쇼케이스와 소개 페이지에서 최종 음성 정책과 최신 키오스크 화면을 확인한다.
- **문제**: 최근 Adaptive TTS 상세 개편은 비교 청취보다 설명과 레이아웃이 과도하며, 소개 페이지는 이전 UI 캡처와 시연 영상을 가리킨다.
- **측정 지표**: 모든 로컬 미디어 참조 200 응답, Adaptive WAV 9개 참조 유지, Level 정책 표시 3개 일치.

## Goal

- **해결 목표**: TTS는 간결한 이전 비교 UI로 되돌리되 최신 Adaptive WAV를 유지하고, 소개 페이지 미디어를 최신 시연에서 추출한 화면과 영상으로 통일한다.
- **성공 기준**: Level 0/1/2가 각각 `1.00x / 0ms`, `0.85x / 280ms`, `0.75x / 480ms`로 표시되고, 소개 페이지의 이미지·영상 경로가 모두 존재한다.
- **Out of Scope**: 주문 UI, 소개 페이지 텍스트·브랜드·링크, Baseline/Fine-tuned 모델 비교 페이지·WAV 변경.

## What

**Happy Path**
1. 평가자가 간결한 Adaptive Speed 페이지에서 세 문장과 9개 최신 WAV를 비교 청취한다.
2. 소개 페이지의 고객·평가자 화면에서 최신 시연 영상과 동일한 UI 캡처를 본다.

**Edge Cases**

| 상황 | 처리 방식 |
|---|---|
| 브라우저가 WebP를 지원하지 않음 | 페이지의 기존 alt 텍스트를 유지한다. |
| 비디오 자동 재생 제한 | 기존 `controls`, `preload=metadata`, `playsinline`을 유지한다. |
| 캐시된 이전 미디어 | 기존 경로의 자산을 교체하고 정적 서버로 참조를 검증한다. |

## How

- `artifacts/showcase/tts/`와 `artifacts/intro/`를 proj1-d의 배포 원본으로 먼저 갱신한다.
- Adaptive 페이지는 `tts_showcase`의 `159ab7da` 화면 구성으로 복원하며, WAV 상대 경로는 유지한다.
- 최신 화면 캡처는 `Mallo_demo_1080p30_HQ.mp4`에서 기존 207x360 비율로 추출한 WebP를 사용한다.
- 루트에서 생성되는 WAV는 `/*.wav`로만 ignore한다.

## AC (Given-When-Then)

**AC-01 · Adaptive 정책과 음성 참조**
- GIVEN: Adaptive Speed 페이지
- WHEN: Level 정책과 세 문장 오디오를 확인하면
- THEN: 최신 세 정책값과 9개 `audio/speed-*-level-[0-2].wav` 상대 참조가 존재한다.

**AC-02 · 최신 소개 미디어**
- GIVEN: 고객·평가자 소개 페이지
- WHEN: 화면과 영상을 로드하면
- THEN: 6개 최신 WebP와 최신 H.264/AAC MP4가 경로 오류 없이 표시·재생된다.
