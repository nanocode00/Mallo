---
title: "Mallo 배포용 Multi-service Gateway"
tags: [spec, deployment, gateway, sidecar]
---

# Mallo 배포용 Multi-service Gateway

## Why

음성 주문 모델은 서로 다른 CUDA 의존성과 가상환경을 사용한다. 사용자는 여러 터미널을 관리하지 않고 한 명령으로 기존 음성 주문 UI와 전체 파이프라인을 실행해야 한다. 이 기능은 모델 초기화·장애가 브라우저에 노출되는 일을 줄이고, sidecar 상태를 운영자가 구분할 수 있게 한다.

## Goal

`PYTHONPATH=src python scripts/run_mallo_server.py` 한 번으로 gateway와 STT/NLU/TTS sidecar를 실행한다. gateway만 `127.0.0.1:8000`을 공개하며, sidecar는 각각 `:8001`, `:8002`, `:8003` loopback bind를 사용한다. 기본 `--tunnel none`은 외부 공개를 하지 않는다. `--tunnel quick`은 개발/임시 QA용 Quick Tunnel URL을 출력한다. Production `--tunnel named`는 remotely-managed `mallo-gateway`를 `CLOUDFLARE_TUNNEL_TOKEN`으로 실행하고 `https://mallo-api.honorbear.dev`를 출력한다. token은 환경변수 또는 로컬 `.env`에만 두며 코드·Git·로그에 저장하지 않는다. 기존 `/api/*`, 특히 `/api/audio`의 STT→NLU→Order Engine→TTS 계약은 유지한다.

Out of Scope: gateway의 non-loopback bind, Cloudflare token/certificate/hostname의 코드·Git 저장, 컨테이너 오케스트레이터, 모델·checkpoint 교체, 브라우저의 sidecar 직접 호출.

## What

launcher는 포트 사용 여부를 먼저 확인하고 Gateway/STT/TTS를 `.venvs/runtime`, NLU를 `.venvs/nlu` subprocess로 기동한다. 각 `/health`가 ready가 된 뒤 STT→NLU→TTS 순서로 `/warmup`을 호출한다. warmup은 각각 실제 Train65 전사, Qwen normalize→generate→guard, MeloTTS 한국어 합성을 한 번 수행하며 사용자 cart/session과 생성 audio를 남기지 않는다. 세 warmup이 모두 성공한 뒤에만 gateway를 시작한다. gateway는 HTTP adapter로 sidecar를 호출하며 `POST /stt`, `/nlu`, `/tts`를 해당 sidecar에 프록시한다. `GET /health`는 세 sidecar가 ready 및 warmed일 때만 ready를 반환한다. SIGINT/SIGTERM 및 child 비정상 종료에서는 서비스 이름을 로그로 남기고 모든 child를 종료한다.

`--tunnel quick`은 `cloudflared tunnel --url http://127.0.0.1:8000` child를 마지막으로 실행한다. launcher는 stdout/stderr에서 URL을 감지할 때까지 대기하며, binary가 없거나 URL 생성 전에 종료하면 모든 Mallo child를 종료한다. `--tunnel named`는 `cloudflared tunnel run --token <CLOUDFLARE_TUNNEL_TOKEN>` child를 마지막으로 실행한다. `--tunnel-name`은 backwards compatibility만 유지하며 remotely-managed token 실행에는 사용하지 않는다. `MALLO_PUBLIC_URL` 또는 `--public-url`로 public URL을 override할 수 있고 기본값은 `https://mallo-api.honorbear.dev`다.

정적 `web/`은 Vercel에서 단독 제공할 수 있다. `runtime-config.js`의 `window.MALLO_API_BASE_URL`은 localhost에서는 빈 값으로 기존 same-origin gateway를 사용하고, 외부 배포에서는 HTTPS Quick/Named Tunnel gateway를 설정한다. `api-url.js`만 base와 API path를 결합하며, 브라우저는 `/api/audio` 등 gateway API만 호출한다. gateway의 CORS preflight는 credential 없는 cross-origin 호출을 허용하고 HTTPS 웹에서는 HTTP gateway base를 거부한다.

gateway 주문 상태는 `X-Mallo-Session-ID`별 `SessionContext`로 격리한다. context에는 cart와 per-session `MalloService/VoicePipeline/ConversationAgent` 상태(TTS level, last response/TTS result, undo/conversation state)가 포함되고, 같은 context의 요청은 lock으로 순차화한다. HTTP STT/NLU/TTS adapters와 sidecar 모델은 공유한다. header 없는 요청은 legacy local/test session으로만 fallback하며, web은 sessionStorage UUID를 모든 `/api/*` 요청에 자동 전송한다. 요청 시 60분 idle context를 cleanup하며 warmup은 context를 만들지 않는다. production CUDA 안정성을 위해 각 sidecar는 inference를 하나씩 직렬 처리한다.

## How

sidecar 내부 경로는 `/transcribe`, `/parse`, `/synthesize`이며 gateway만 그 경로를 안다. STT는 Train65 merged BF16/CUDA 기본 설정, NLU는 Qwen3-0.6B merged BF16 normalization/guard 경로, TTS는 `logs/mallo-friendly/G_2800.pth`, `logs/mallo-friendly/config.json`, speaker `10`, CUDA를 사용한다. launcher는 child stdout/stderr를 각각 `[STT]`, `[NLU]`, `[TTS]` prefix로 전달한다.

`GET /health` 성공 응답은 다음 상태 필드를 모두 포함한다.

```json
{"status":"ready","stt":"ready","nlu":"ready","tts":"ready","warmed":true}
```

## AC

- **GIVEN** 세 loopback 포트가 비어 있고 모델 환경이 준비됨 **WHEN** launcher를 실행함 **THEN** sidecar 세 개가 ready 후 gateway `127.0.0.1:8000`이 시작된다.
- **GIVEN** gateway가 ready임 **WHEN** `POST /api/audio`를 호출함 **THEN** 기존 응답 필드와 서버 측 STT→NLU→TTS orchestration이 유지된다.
- **GIVEN** gateway가 ready임 **WHEN** `GET /health`를 호출함 **THEN** `status`, `stt`, `nlu`, `tts`가 모두 `ready`다.
- **GIVEN** sidecar가 실행 중임 **WHEN** launcher가 순차 `/warmup`을 호출함 **THEN** 실제 production inference가 각각 한 번 성공하고, 어느 하나라도 실패하면 gateway는 시작하지 않는다.
- **GIVEN** 각 sidecar가 ready임 **WHEN** `POST /stt`, `/nlu`, `/tts`를 호출함 **THEN** 브라우저는 내부 포트에 직접 연결하지 않고 gateway의 대응 sidecar 응답을 받는다.
- **GIVEN** Mallo 포트 하나가 이미 사용 중임 **WHEN** launcher를 실행함 **THEN** 충돌 주소를 포함한 오류로 child 시작 전에 종료한다.
- **GIVEN** child가 readiness 전 또는 실행 중 종료함 **WHEN** launcher가 감시함 **THEN** 죽은 서비스 이름과 exit code를 로그로 남기고 나머지 child를 종료한다.
- **GIVEN** SIGINT 또는 SIGTERM을 받음 **WHEN** launcher가 종료됨 **THEN** 모든 child에 terminate를 보내고 남은 child는 제한 시간 뒤 kill한다.
- **GIVEN** `--tunnel quick`과 설치된 `cloudflared` **WHEN** gateway health가 ready/warmed가 됨 **THEN** launcher는 Quick Tunnel을 시작하고 감지한 `https://*.trycloudflare.com` URL을 출력한다.
- **GIVEN** `--tunnel named`와 `CLOUDFLARE_TUNNEL_TOKEN` **WHEN** gateway health가 ready/warmed가 됨 **THEN** launcher는 token을 로그에 남기지 않고 remotely-managed tunnel child를 시작한 뒤 `https://mallo-api.honorbear.dev`를 출력한다.
- **GIVEN** Vercel 정적 web 배포 **WHEN** `MALLO_API_BASE_URL`이 HTTPS gateway로 설정됨 **THEN** 기존 `/api/audio` 호출은 해당 gateway URL로 향하고 sidecar에는 직접 연결하지 않는다.
- **GIVEN** 서로 다른 `X-Mallo-Session-ID` 두 개 **WHEN** 각각 주문·reset·state 요청을 보냄 **THEN** cart와 대화/TTS 상태는 서로 보이지 않으며 reset은 요청 session만 초기화한다.
- **GIVEN** 같은 `X-Mallo-Session-ID`의 동시에 도착한 주문 변경 **WHEN** gateway가 처리함 **THEN** session lock이 순서대로 처리해 cart lost update가 없다.
