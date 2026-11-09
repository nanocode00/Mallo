---
title: "STT 데모 페이지와 /api/stt 엔드포인트"
tags: [spec, stt, demo]
---

# STT 데모 페이지와 /api/stt 엔드포인트

## Why

- **페르소나**: STT로 음성 입력 품질을 시연·검증하려는 개발자 및 제품 리뷰어
- **상황**:
  - 키오스크 전체 주문 파이프라인(STT→NLU→Order Engine→TTS) 없이 STT 전사 품질만 단독으로 확인해야 한다.
  - 브라우저 마이크와 WAV 파일 업로드 두 경로로 실시간 STT를 테스트한다.
- **문제**:
  1. 기존 `/api/audio`는 전 파이프라인을 실행해 STT 지연·정확도를 분리 측정할 수 없음
  2. STT 단독 검증용 UI가 없어 매번 curl/파이썬 스크립트를 작성해야 함
  3. 음성 원본이 서버 디스크에 잔존하면 프라이버시 및 동시성 문제 발생 가능
- **측정 지표**: STT-only 왕복 지연, STT 성공/실패 응답 정확도, 정적 페이지 제공 성공률

## Goal

- **해결 목표**:
  - 브라우저에서 마이크·파일 입력으로 STT를 단독 호출해 전사 결과를 확인하는 데모 페이지(`web/stt-demo.html`)와 전용 API(`POST /api/stt`)를 제공한다.
  - STT-only 위임을 보장하고 음성 원본을 디스크에 영구 저장하지 않는다.
- **성공 기준**:
  - `POST /api/stt` 성공 시 `{text, confidence, alternatives, latency_ms, received_bytes}` 반환, `STTFailure` 시 `{error, received_bytes}` 반환
  - `GET /stt-demo.html`이 200과 `text/html`로 제공된다.
  - 단위/통합 테스트로 성공·실패·정적 제공을 고정한다.
- **Out of Scope**:
  - NLU/Order Engine/TTS 호출, 장바구니 변경, 세션 상태 변경
  - 음성 파일의 장기 저장 및 서버 측 디스크 덤프 (기본 비활성)
  - 실시간 스트리밍 Partial Transcription

## What

**Happy Path**
1. 사용자가 `http://host/stt-demo.html` 접속
2. 마이크 권한 허용 → [녹음] 버튼으로 10초 내 발화 녹음 → 16kHz mono WAV로 인코딩
3. `POST /api/stt` (body: WAV bytes) 전송
4. 서버는 `VoicePipeline.transcribe_audio()`로 STT만 실행 (NLU/TTS/장바구니 변경 없음)
5. 성공 시 전사 텍스트, 신뢰도, 대체 후보, 지연을 화면에 표시하고 히스토리에 누적
6. 파일 업로드 경로도 동일한 API로 처리

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 빈 오디오 body (0 bytes) | STT 어댑터에 위임 → 결과 또는 STTFailure별 응답 반환, 디스크 저장 없음 |
| EC-02 | STT 어댑터 미설정 (`stt=None`) | `STTFailure("STT 어댑터가 설정되지 않았습니다.")` → `{error, received_bytes}` 반환 |
| EC-03 | STT 추론 실패 (디코딩/OOM 등 `STTFailure`) | `{error: str(exc), received_bytes}` 반환, HTTP 200, Cart 변경 없음 |
| EC-04 | `GET /stt-demo.html` 요청 | `web/stt-demo.html`을 `text/html`로 제공, 없으면 404 JSON |
| EC-05 | 동시 STT 요청 | 고정 파일명 덤프 없이 메모리에서만 처리 — 요청 간 덮어쓰기 없음 |
| EC-06 | STT alternatives가 비어 있음 | `alternatives: []`로 반환 (빈 배열 허용) |
| EC-07 | confidence가 None인 모델 | `confidence: null` 반환 (스키마 호환) |

## How

```
POST /api/stt
Request:  body = WAV bytes (Content-Type: any, raw bytes)
Response 성공 (200):
{
  "text": string,
  "confidence": number | null,
  "alternatives": string[],
  "latency_ms": number | null,
  "received_bytes": number
}
Response 실패 (200):
{
  "error": string,
  "received_bytes": number
}

GET /stt-demo.html
Response 성공 (200): text/html; charset=utf-8, body = web/stt-demo.html
Response 실패 (404): {"error": "not found"}
```

- **위임 계층**:
  ```text
  MalloHTTPRequestHandler.do_POST /api/stt
    → MalloServerApp.transcribe(audio: bytes)
      → MalloService.transcribe(audio: bytes)
        → VoicePipeline.transcribe_audio(audio: bytes)
          → STT.transcribe(audio: bytes) : STTResult
  ```
  - NLU, Agent, TTS는 호출하지 않는다. Cart/TTS Level/세션 상태 변경 없음.
- **프라이버시**: 요청 음성 바이트를 `/tmp` 등 디스크에 저장하지 않는다. 디버그 덤프가 필요하면 별도 opt-in 환경변수와 고유 파일명으로 분리 구현한다 (기본 동작 아님).
- **정적 제공**: `MalloHTTPRequestHandler._serve_static("stt-demo.html")`로 제공, 기존 `index.html`/`app.js`/`styles.css`와 동일 경로 규칙.
- **프론트**: `web/stt-demo.html`은 `/api/stt`만 호출, `/api/audio`나 `/api/order`를 호출하지 않는다.

## AC (Given-When-Then)

### AC-01 · STT 성공 응답 계약
- **GIVEN**: `MockSTT(canned_text="아이스 아메리카노 두 잔 주세요", confidence=0.92)`로 구성된 서버
- **WHEN**: `POST /api/stt`에 WAV bytes(임의)로 요청
- **THEN**: 응답은 `text="아이스 아메리카노 두 잔 주세요"`, `confidence=0.92`, `alternatives` 배열, `latency_ms` 숫자, `received_bytes=len(body)`를 포함하고, cart 변경 없음

### AC-02 · STTFailure 응답 계약
- **GIVEN**: `MockSTT(should_fail=True)`로 구성된 서버
- **WHEN**: `POST /api/stt`에 임의 bytes로 요청
- **THEN**: 응답은 `error` 문자열과 `received_bytes`를 포함하고 `text` 필드는 없으며, HTTP 200, Cart 변경 없음

### AC-03 · STT-only 위임 (NLU/TTS/Cart 미변경)
- **GIVEN**: Mock STT/NLU/Agent/TTS로 구성된 `MalloService`
- **WHEN**: `service.transcribe(audio)` 호출
- **THEN**: STT만 호출되고 NLU `parse`와 Agent `execute`와 TTS `synthesize`는 호출되지 않으며 Cart는 변경 없음

### AC-04 · 정적 데모 페이지 제공
- **GIVEN**: 서버가 기동되고 `web/stt-demo.html`이 존재
- **WHEN**: `GET /stt-demo.html` 요청
- **THEN**: 200, `Content-Type: text/html`, body에 `<title>말로 STT 데모` 포함

### AC-05 · 동시 요청 간 디스크 덮어쓰기 없음
- **GIVEN**: 서버의 `transcribe`가 호출됨
- **WHEN**: 두 요청을 연속으로 전송
- **THEN**: 서버는 `/tmp/mallo_last_stt.bin` 등 고정 경로에 파일을 생성하지 않으며, 두 응답의 `received_bytes`가 각각의 요청 길이를 정확히 반영

### AC-06 · 빈 alternatives 처리
- **GIVEN**: alternatives가 없는 STT 결과
- **WHEN**: `POST /api/stt` 성공 응답
- **THEN**: `alternatives`는 `[]` (빈 배열)

