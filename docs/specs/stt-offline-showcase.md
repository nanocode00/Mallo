---
title: "STT 오프라인 최종 제출 쇼케이스"
tags: [spec, stt, showcase]
---

# STT 오프라인 최종 제출 쇼케이스

## Why

- 최종 제출 검토자는 서버, 마이크, 개인 도메인 없이도 Train65 STT 결과와 입력 음성을 확인할 수 있어야 한다.
- 재현 가능한 WAV 배치 추론 결과와 정적 HTML을 같은 산출물에 남긴다.

## Goal

- 여러 WAV를 `models/stt/final-train65-merged-bf16`으로 배치 추론하고, WAV·결과 JSON·정적 HTML을 하나의 출력 디렉터리에 생성한다.
- 생성 HTML은 `file://`로 열어도 재생과 결과 확인이 가능하며 localhost 또는 외부 URL을 사용하지 않는다.
- Out of Scope: 라이브 마이크, HTTP API, Cloudflare 배포, 모델 학습 및 음성 데이터 공개 허용 판정.

## What

1. 명시한 WAV 파일 또는 디렉터리의 WAV를 정렬해 읽는다.
2. 모델을 한 번만 로드해 각 파일의 전사와 추론 시간을 기록한다.
3. 입력 WAV를 결과물 `audio/`로 복사하고 `results.json` 및 `index.html`을 생성한다.

## How

```bash
PYTHONPATH=src .venvs/runtime/bin/python scripts/showcase/build_stt_offline_showcase.py \
  --input-wav path/to/a.wav path/to/b.wav \
  --output-dir artifacts/showcase/stt-final
```

- HTML은 상대 `audio/...` 경로만 사용한다.
- JSON에는 모델 경로, 장치, 생성 시각, 파일명, 전사와 추론 시간을 저장한다.

## AC

- GIVEN: 둘 이상의 WAV WHEN: 생성기를 실행 THEN: 모든 WAV마다 오디오와 전사·시간이 HTML과 JSON에 있다.
- GIVEN: 생성된 HTML WHEN: backend 없이 파일로 연다 THEN: 외부 URL 없이 내장 오디오 컨트롤을 사용할 수 있다.
- GIVEN: 재실행 WHEN: 같은 출력 경로를 사용한다 THEN: 이전 결과를 원자적으로 교체하고 불완전한 결과를 남기지 않는다.
