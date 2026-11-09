---
title: "말로(Mallo) 작업 로그"
tags: [doc]
---

# 말로(Mallo) 작업 로그

프로젝트 진행 과정에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다. 기능별 상세 요구사항과 인수 조건은 `docs/specs/`, 티켓 상태는 `docs/tasks.md`에서 관리한다.

이 문서는 기존 공통 기록의 요약·진입점이다. 신규 기능별 결정은 `docs/worklogs/`의 담당 영역 파일에 기록한다. worklog는 결정 당시의 이력이며 현재 제품 범위·기술 계약·AC를 재정의하지 않는다. 충돌 시 `docs/documentation-governance.md`의 기준 문서를 따른다.

## 2026-08-17

### O-07~O-11 Order Engine 주문 관리 Intent 확장 구현

- 결정론적 Order Engine(`ConversationAgent`)에 메뉴 삭제, 수량 변경, 옵션 변경, 장바구니 조회, 주문 확정, 전체 취소 기능을 확장 구현했다.
- **`REMOVE_ITEM` (O-07)**: 메뉴 ID 및 온도 기준으로 Cart 항목 삭제 및 총액 갱신
- **`UPDATE_QUANTITY` (O-08)**: 대상 항목 최종 수량 갱신 및 총액 재계산
- **`UPDATE_OPTION` (O-09)**: 메뉴 온도 유효성 검증 후 HOT ↔ ICE 변경 및 동일 온도 항목 합산
- **`QUERY_CART` (O-10)**: 현재 장바구니 품목 및 총 결제 금액 조회 문장 반환
- **`CONFIRM_ORDER` (O-11)**: 빈 카트 검증 및 최종 결제 안내
- **`CANCEL`**: 장바구니 전체 초기화
- 한글 종성(받침)에 따른 올바른 조사(`을/를`, `이/가`, `으로/로`) 자동 선택 로직 추가
- 스펙 문서 `docs/specs/order-engine-operations.md` 작성 및 단위 테스트 70개 통과를 확인했다.

### UI-01~UI-06 Starbuck-style Voice-first Minimal GUI 구현

- 고령 사용자의 시각·인지 부담을 최소화하는 스타벅스 키오스크 스타일(Dark Green `#006241`, Warm Cream `#F7F5F0`, High-contrast Typography)의 Minimal GUI를 구현했다.
- **UI-01**: 단일 화면 반응형 Semantic HTML5 레이아웃 (`web/index.html`, `web/styles.css`)
- **UI-02**: 실시간 장바구니 항목(메뉴명, HOT/ICE 뱃지, 수량, 단가) 및 총 결제 금액 렌더링
- **UI-03**: 시스템 실시간 안내 자막 카드 (`response-card`)
- **UI-04**: 대형 원형 음성 입력 버튼 (`Tap-to-talk`) 및 키보드 입력창
- **UI-05**: 음성 UX 제어 바 (`[다시 듣기]`, `[천천히 듣기]`, `[보통 속도]`, `[직원 호출]`)
- **UI-06**: 상단 시스템 상태 인디케이터 및 `SessionState` 도메인 모델 (`src/domain/session_state.py`)
- 스펙 문서 `docs/specs/minimal-gui.md` 작성 및 단위 테스트 65개 통과를 확인했다.

### T-16~T-19 Adaptive TTS Controller 구현

- 세션별 TTS Level(0, 1, 2) 상태 머신 `AdaptiveTTSController`(`src/domain/tts_controller.py`)를 구현했다.
- `REQUEST_SLOWER`, `REQUEST_REPEAT` 발화 의도 수신 시 1단계씩 레벨 상승(최대 2 상한선 유지) 정책을 적용했다.
- `REQUEST_DEFAULT_SPEED` 수신 시 기본 레벨(Level 0)로 즉시 복귀하도록 처리했다.
- 새 주문 세션 시작 시 `reset()`으로 Level 0으로 안전하게 초기화하는 로직 및 단위 테스트 68개 통과를 확인했다.

### T-08~T-15 Adaptive TTS Text Transformer 구현

- 고령 사용자의 인지·청각 부담을 완화하기 위한 결정론적 룰 기반 `AdaptiveTextTransformer`(`src/domain/text_transformer.py`)를 구현했다.
- **Level 0**: 원본 연결형 자연어 응답 유지 (1.0x 기준)
- **Level 1**: 문장 절 및 메뉴 항목 경계에 Pause 마커(`, ... `) 삽입
- **Level 2**: `[메뉴명]. [수량]입니다.` 형태의 단문 분절 및 핵심 정보 우선 강조
- 스펙 문서 `docs/specs/adaptive-text-transformer.md` 작성 및 단위 테스트 70개 통과를 확인했다.

### C-15 TTS 입출력 형식 정의

- Adaptive TTS 합성 출력 규격인 `TTSResult` JSON Schema(`schemas/tts-result.schema.json`)를 정의했다.
- 합성 텍스트(`text`), 적용 레벨(`level: 0|1|2`), 샘플링 레이트(`sample_rate`), 재생 길이(`duration_ms`), 합성 지연(`latency_ms`), `audio_base64` 필드를 정형화했다.
- 도메인 모델 `src/domain/tts_result.py` 및 `src/interfaces/tts.py`, `src/adapters/tts/mock_tts.py`를 업데이트하고 스키마 검증기 `validate_tts_result`를 추가했다.
- 스펙 문서 `docs/specs/tts-result.md` 작성 및 단위 테스트 69개 통과를 확인했다.

### C-10 OrderCommand Error Schema 정의

- NLU 해석 실패 또는 모호한 발화 발생 시 반환할 `OrderCommandError` JSON Schema(`schemas/order-command-error.schema.json`)를 정의했다.
- `OrderCommandErrorCode` 7종(`INVALID_JSON`, `SCHEMA_ERROR`, `UNKNOWN_INTENT`, `MISSING_FIELD`, `MIXED_INTENT`, `AMBIGUOUS_TARGET`, `UNSUPPORTED_UTTERANCE`)을 지원하고 `command_index`, `field`, `candidates`, `retryable` 등 구조화된 필드를 확정했다.
- 도메인 모델 `src/domain/order_command_error.py` 및 스키마 검증기 `validate_order_command_error`를 구현했다.
- 스펙 문서 `docs/specs/order-command-error.md` 작성 및 단위 테스트 66개 통과를 확인했다.

### C-16 공통 Error Response 정의

- 파이프라인 전체(Audio/STT, NLU, Order Engine, TTS, System)의 오류를 통합 처리하기 위한 `ErrorResponse` 공통 데이터 구조와 `schemas/error-response.schema.json`을 작성했다.
- 14종의 표준 `ErrorCode`와 6종의 `ErrorModule`을 분류하고, 각 오류별 고령자 친화적 기본 안내문(`user_message`), 복구 힌트(`recovery_hint`), 재시도 가능 여부(`retryable`) 기본 매핑 테이블을 구현했다.
- `src/domain/errors.py` 및 `src/domain/models.py`에 `ErrorResponse`, `get_default_error_response`, `create_error_response`를 추가하고 `OrderResult` 및 `VoicePipeline`과 연동했다.
- `src/utils/schema_validation.py`에 `validate_error_response()` 검증 함수를 추가했다.
- 스펙 문서 `docs/specs/error-response.md`를 작성하고 단위/통합 테스트 67개를 100% 통과했다.

### C-12 STT 반환 형식 정의

- STT 변환 출력 규격인 `STTResult` JSON Schema(`schemas/stt-result.schema.json`)를 정의했다.
- 전사 텍스트(`text`), 신뢰도 점수(`confidence`), 소요 시간(`duration_ms`), 인식 언어(`language`), 대체 후보군(`alternatives`), 확정 여부(`is_final`) 메타데이터를 정형화했다.
- 도메인 모델 `src/domain/stt_result.py` 및 `src/interfaces/stt.py`에 `STTResult`, `STTFailure`를 구현하고 스키마 검증기 `validate_stt_result`를 추가했다.
- 스펙 문서 `docs/specs/stt-result.md` 작성 및 단위 테스트 68개 통과를 확인했다.

## 2026-08-14


### NLU OrderCommand Batch 계약 확정

- NLU 출력을 항상 `OrderCommand[]`로 변경하고 Command 하나가 메뉴 하나만 대상으로 하도록 했다.
- TRD Intent 11개와 공통 필드 `request_id`, `intent`, `target_item_id`, `category_id`, `quantity`, `temperature`, `confirmation_required`를 Enum·Schema에 반영했다.
- Command마다 UUID v4를 자동 생성하고 사용하지 않는 공통 필드는 `null`로 유지하도록 했다.
- `quantity`를 증가량이 아닌 최종 수량으로 정의하여 기존 2잔에 1잔 추가 요청 시 3잔으로 설정되게 했다.
- 같은 메뉴·온도는 수량을 합산하고 다른 온도는 별도 Command로 유지하며 발화 순서를 보존했다.
- 일부 Command 실패 시 Batch 전체를 취소하고 혼합 Intent와 추가 JSON 필드를 거부하도록 했다.
- Confirmation Policy를 Order Engine 책임으로 두고 삭제·최종 확정·전체 취소만 확인이 필요하도록 고정했다.
- 수정·삭제는 메뉴 ID와 온도로 대상을 식별하고 후보가 여러 개면 `AMBIGUOUS_TARGET`을 사용하도록 정의했다.
- 온도 누락은 P0에서 재입력, P1에서만 Clarification으로 처리하도록 PRD·TRD·제안서·작업 카드·메뉴 Spec을 통일했다.
- 이번 A안은 11개 Intent의 NLU 계약까지 구현하며 실제 Order Engine 실행은 `ADD_ITEM` Batch만 유지한다.
- 단위·통합 테스트 60개가 통과했다.

### ICE 전용 메뉴 정책 적용

- 자몽에이드와 아이스티의 온도 옵션을 `iced` 하나로 제한했다.
- 두 메뉴에 HOT이 입력되면 Order Engine이 `INVALID_OPTION`을 반환하고 Cart를 변경하지 않도록 검증했다.

### NLU 현재 주문 상태 입력으로 변경

- NLU 계약을 `parse(text, current_order_state)`로 변경했다.
- NLU에는 원본 Cart가 아니라 복사본을 전달하여 상태를 직접 변경하지 못하게 했다.
- OrderCommand 생성은 NLU, 실제 Cart 검증·변경은 Order Engine이 담당하는 경계는 유지했다.

### 동일 이름 메뉴 가격 정책 적용

- 스타벅스에서 동일 메뉴가 확인된 아메리카노와 카페라떼는 스타벅스 가격을 사용했다.
- 스타벅스에서 동일 이름을 확인하지 못한 나머지 8개 메뉴는 다른 카페의 동일 이름 메뉴 가격을 사용했다.
- 비슷한 이름의 메뉴는 대체 가격으로 사용하지 않았으며 브랜드·출처 메뉴명·URL·확인 날짜를 메뉴 데이터에 기록했다.
- 매장 주문 페이지 가격은 지점·주문 방식에 따라 달라질 수 있어 2026-08-14 확인값을 MVP 가격으로 고정했다.

### 한 문장 복수 메뉴 주문 지원

- 기존 한 발화 한 메뉴 제한을 해제하고 `OrderCommand.items` 배열로 계약을 변경했다.
- 한 문장에서 메뉴별 `menu_id`, `quantity`, `temperature`를 각각 표현할 수 있게 했다.
- 복수 항목을 모두 검증한 후 Cart에 반영하여 일부 항목만 담기는 것을 방지했다.
- 당시 실행 Intent는 `ADD_ITEM` 하나였으며 별칭·품절·사이즈 미지원 조건을 유지했다. 이후 NLU 계약은 TRD Intent 11개로 확장했다.
- 당시 현재 주문 상태 격리, 가격 출처와 ICE 전용 메뉴 검증을 포함한 단위·통합 테스트 34개 및 복수 메뉴 CLI Smoke Test를 통과했다.

### ADD_ITEM NLU / Order Engine 범위 확정 및 구현

- 초기 구현에서는 NLU Intent를 `ADD_ITEM` 하나로 제한하고 한 발화에서 메뉴 종류 하나만 허용했다. 이후 복수 메뉴 지원 결정으로 대체했다.
- 초기에는 NLU 인터페이스를 `parse(text)`로 구현했다. 이후 현재 주문 상태 입력 결정에 따라 `parse(text, current_order_state)`로 대체했다.
- 공식 메뉴명만 사용하고 별칭·약칭, 품절 상태, 사이즈 변경을 Schema에서 제외했다.
- 초기에는 메뉴 10개에 MVP 임시 가격을 입력했다. 이후 스타벅스 우선·다른 카페 동일 이름 메뉴 가격 정책으로 대체했다.
- Menu와 OrderCommand를 JSON Schema로 정의하고 NLU 출력 직후 검증하도록 연결했다.
- 결정론적 Order Engine에 메뉴·수량·온도 검증, 장바구니 추가 및 합계 계산을 구현했다.
- 단위·통합 테스트 25개와 CLI Smoke Test를 통과했다.

### 문서 정합성 정리

- 프로젝트 이름을 `말로(Mallo)`로 통일했다.
- 음성 입력 방식을 버튼을 한 번 눌러 시작하고 발화 종료를 자동 감지하는 `Tap-to-talk`로 통일했다.
- 브랜치 예시를 저장소 규칙인 `feat/...` 형식으로 맞췄다.
- 역할 분담을 3인 A/B/C 체계로 통일했다.
- `AGENTS.md`에 프로젝트 개요와 현재 확정된 기술 구성을 작성했다.
- 관련 변경은 GitHub PR #13으로 병합했다.

### C-17 모듈 연결 방식 결정

**결정:** MVP의 STT, NLU, Order Engine, TTS 모듈은 동일 Python 프로세스에서 함수 호출로 연결한다.

**이유:**

- 2주 MVP에서 Mock End-to-End Pipeline을 빠르게 구축할 수 있다.
- 단일 시연 환경에서 서버 프로세스, 포트, 직렬화, Timeout 등 REST 운영 부담을 줄일 수 있다.
- 함수 단위 테스트와 호출 흐름 디버깅이 단순하다.

**제약:**

- 모듈별 입력과 출력은 명시적인 타입 기반 인터페이스로 분리한다.
- Mock 구현과 실제 모델 구현은 같은 인터페이스를 구현하여 교체 가능하게 한다.
- 향후 별도 장비 또는 프로세스 분리가 필요하면 인터페이스 바깥에 REST Adapter를 추가한다.
- MVP에서는 모듈별 REST API와 독립 서비스 배포를 구현하지 않는다.

### 다음 작업 범위

- **C-18:** `docs`, `src`, `tests`와 모듈별 디렉터리 구조를 확정한다.
- **C-19:** 텍스트 직접 입력 → Mock NLU → Order Engine → Baseline TTS 흐름을 실행한다.
- 구현 전에 `docs/specs/mock-e2e-pipeline.md`에 Why, Goal, What, How, AC를 작성한다.

### C-18 Repository 구조 결정

**결정:** 회의안에 따라 `src` 아래에 app, interfaces, adapters, domain, orchestrator, config, utils 계층을 구성한다. 테스트는 `tests/unit`과 `tests/integration`으로 나눈다.

- 상세 구조와 책임 경계는 `docs/specs/mock-e2e-pipeline.md`에 정의했다.
- 모듈은 C-17 결정에 따라 동일 프로세스의 Python 함수로 연결한다.
- STT, TTS, NLU, Agent 구현은 `Protocol` 인터페이스를 통해 교체한다.
- 실제 기술 구현은 `adapters/stt`, `adapters/tts`, `adapters/nlu`로 분리한다.
- 외부 API 기반 Adapter는 구조상 향후 후보 위치만 정의하며 C-19에서는 구현·호출하지 않는다.
- 현재 단계에서는 구조와 계약만 확정하며 실제 디렉터리 및 코드는 C-19에서 생성한다.
- 다음 작업은 Spec의 AC를 기준으로 C-19 Mock End-to-End Pipeline을 구현하는 것이다.

### C-19 Mock End-to-End Pipeline 구축

- 회의에서 확정한 `src` 계층 구조와 `tests/unit`, `tests/integration` 구조를 생성했다.
- 텍스트 입력 → Mock NLU → 결정론적 Conversation Agent → Mock TTS 흐름을 Python 함수 호출로 연결했다.
- 메뉴와 수량 검증 실패 시 기존 Cart를 변경하지 않도록 구현했다.
- NLU와 TTS의 Mock 구현을 `Protocol` 기반으로 교체할 수 있게 구성했다.
- 실제 STT, Local LLM, 음성 합성 및 외부 API Adapter는 구현하지 않았다.
- Spec의 AC를 단위·통합 테스트 10개로 검증했으며 전체 테스트가 통과했다.
- CLI에서 `아메리카노 두 잔 주세요` 입력 시 주문 결과와 Cart가 정상 출력되는 것을 확인했다.

### C-02~C-06 MVP Menu Catalog 확정

- 가상 매장은 커피·논커피·티·디저트를 판매하는 단일 소형 카페로 확정했다.
- MVP 메뉴 10개와 시연용 고정 가격을 확정했다.
- 전 메뉴는 단일 사이즈로 하고 샷·시럽·토핑은 제외했다.
- 음료 옵션은 메뉴별 HOT / ICED 정책만 지원한다.
- 음료 단위는 `잔`, 디저트 단위는 `개`로 확정했다.
- `라떼`처럼 여러 메뉴와 충돌하는 표현은 특정 메뉴 alias에 넣지 않는다.
- 상세 메뉴와 Schema, Edge Case, AC는 `docs/specs/menu-catalog.md`에 기록했다.
- 후속 구현에서 `menu.schema.json`, 최종 `menu.json`, 메뉴 검증 테스트를 작성한다.

## 2026-08-19

### I-07 통합 로그 저장 구현

- 인터랙션 로그를 평가 가능한 형태로 기록하는 `InteractionLogger` 계약과 `FileInteractionLogger`(JSONL append)를 구현했다.
- `SessionLogEvent`(`src/domain/session_log.py`)를 `schemas/session-log.schema.json`(E-04) 형식에 맞춰 정의하고, `utils/schema_validation.py`에 `validate_session_log()` 검증기를 추가했다.
- `VoicePipeline`에 `logger`/`session_id`/`step_index`/`participant_id`/`group`/`task_id`를 추가해, 텍스트·오디오 입력 경로에서 ORDER_INTERACTION / TTS_SPEED_CONTROL / ERROR_RECOVERY 이벤트를, `reset_session()`에서 SESSION_RESET 이벤트를 단계별로 기록하도록 연결했다. 모듈별 latency(ms→초 변환)와 주문 후 장바구니 상태를 함께 기록한다.
- 기존 동작 보존을 위해 `NullInteractionLogger`(no-op)를 기본값으로 두었고, `MalloService.build_mock_service(logger=...)`로 주입한다.
- 단위 테스트 9건(`tests/unit/test_interaction_logger.py`)과 통합 테스트 1건(`tests/integration/test_pipeline_logging.py`)을 추가해 스키마 준수와 이벤트 기록을 검증했으며, 전체 테스트는 기존 5건의 선행 실패(본 작업과 무관) 외 모두 통과했다.

### I-08 전체 End-to-End Latency 측정

- PTT 종료부터 최종 음성 응답 시작까지의 지연을 구간별(stt/nlu/agent/tts/total_e2e)로 측정하는 도구 `scripts/measure_e2e_latency.py`를 구현했다. Mock STT/Order/TTS 환경에서 `VoicePipeline.handle_audio()`를 반복 호출해 평균/최소/최대 지연을 집계한다.
- `tests/integration/test_e2e_latency.py`(3건)로 각 구간 지연이 0 이상이고 E2E 지연이 가장 긴 모듈 지연 이상이며, I-07 로그에 5개 latency 키가 초 단위로 기록됨을 검증했다.

### I-09 End-to-End 시나리오 테스트

- 핵심 주문 흐름을 백엔드 없이 `MalloService.build_mock_service()`로 검증하는 통합 테스트 `tests/integration/test_e2e_order_flows.py`(8건)를 추가했다.
- 추가→조회, 삭제, 수량 변경, 옵션(온도) 변경, 확정→취소, UNDO 복원, TTS 제어(느리게→기본)에 이어 다품목 Happy Path에서 총액(19,300원)을 단언한다.

### I-10 Web 백엔드 서버 브리지 구현

- `web/` GUI와 백엔드 파이프라인을 연결하는 Web 서버 `src/app/server.py`를 표준 라이브러리 `http.server`(ThreadingHTTPServer)로 구현했다. 별도 의존성(FastAPI 등)을 추가하지 않아 `requirements.txt`를 변경하지 않았다.
- 정적 파일(`/`, `/app.js`, `/styles.css`) 제공과 `/api/order`, `/api/audio`, `/api/tts-control`, `/api/reset`, `/api/state` 엔드포인트를 노출하고 CORS(`Access-Control-Allow-Origin: *`)를 설정했다. 단일 세션 cart를 서버에서 유지한다.
- 기존 `web/app.js`의 로컬 목업 파서를 제거하고, 모든 입력을 백엔드 fetch 통신으로 재연결해 실제 주문 상태와 cart를 반영하도록 했다. `tests/integration/test_web_server.py`(6건)로 다회차 주문 누적, TTS 레벨 변경, 오디오 응답 latency/장바구니, reset, 정적 페이지 제공을 검증했다.
- 한계: 현재 서버는 Demo용 단일 세션 기준이며 인증·멀티 세션·실제 STT/TTS 모델은 미연결 상태다. 후속 I-04/UI-07~11 브리지와 연결해 확장한다.

### I-04 + UI-07~11 GUI 주문 확정·결제·리셋 흐름 구현

- I-10 Web 백엔드를 기반으로 `web/index.html`·`web/styles.css`·`web/app.js`에 주문 확인/수정/확정/결제완료/리셋 흐름을 상태 머신(ORDERING→CONFIRMING→COMPLETE)으로 구현했다.
- **I-04**: 다시 듣기/천천히/보통 속도 버튼이 `/api/tts-control`을 호출하고, 헤더 `TTS Lv.0/1/2` 배지가 `/api/state`의 `tts_level`과 동기화된다.
- **UI-07**: `#confirmModal`에 장바구니 품목(메뉴명·온도·수량·금액)과 총액을 `/api/state` 기준으로 렌더링하는 주문 확인 화면.
- **UI-08**: 모달의 `수정하기` 버튼이 편집 단계로 복귀.
- **UI-09**: `주문 확정` 버튼이 `/api/order {text:"주문 확정할게요"}`을 호출해 명시적 확정.
- **UI-10**: 확정 성공 시 `#completeScreen` 가상 결제 완료 화면(실제 PG 없음) 표시.
- **UI-11**: `새 주문 시작하기` 버튼이 `/api/reset`을 호출하고 cart·TTS 레벨·화면을 초기화.
- `tests/integration/test_web_server.py`에 confirm→reset 사이클 및 `/api/state` TTS 레벨 노출 검증 2건을 추가해 총 8건 통과.

## 2026-08-18

### Python 가상환경 및 프로젝트 학습/실험 환경 정책 수립

- 저장소 루트 `.venv` 사용 원칙과 OS(Windows/WSL) 간 가상환경 디렉터리 분리 원칙을 확정했다.
- 일반 개발 환경(Core)은 Python 3.11 또는 3.12를 지원하고, `scripts/check_python_env.py core`로 진단한다.
- 프로젝트 학습 및 STT 재현 환경의 기준을 Python 3.11.9, torch 2.6.0+cu124 및 14개 핵심 패키지 버전(transformers, datasets, evaluate, peft, accelerate, faster-whisper, jiwer, soundfile, noisereduce, numpy, pandas, scipy, librosa 미확인)으로 명문화했다.
- "기존 학습이 정상적으로 진행된 환경이므로 우선 이 버전을 기준으로 유지하고, 호환성이나 실행 문제가 발생할 경우 팀 논의 후 변경한다"는 유지·변경 정책을 확정했다.
- Blackwell 아키텍처(RTX 5070 Ti, sm_120) 환경을 위해 CUDA 12.8 빌드 분리 사용 프로필을 추가하고, 가중치 호환성을 검증했다.
- 상세 요구사항과 인수 조건은 `docs/specs/python-environment.md`에 기록했다.

### 추론 및 배포 아키텍처 수립

- 태블릿 기반 Web/PWA 클라이언트와 GPU 기반 AI 추론 서버(Inference Server)의 분리 배포 구조를 수립했다.
- 초기 MVP는 로컬 데스크톱(RTX 5070 Ti 16GB) 단일 GPU에 STT, NLU, Order Engine, TTS를 상주시키고 순차 실행하여 저지연 응답을 제공한다.
- 긴 지연의 비동기 잡 큐 대신 실시간 직접 추론 경로를 우선 채택했다.
- 로컬 환경 문제 발생 시 클라이언트 수정 없이 Cloud GPU로 서버를 이전할 수 있는 Fallback 전략을 수립했다.
- 상세 내용은 `docs/inference-deployment.md` 및 `docs/trd.md` Section 4.1에 반영했다.


## 2026-08-19

### E-10 최종 데모 리허설

- E-08 5-Turn Happy Path를 통합 파이프라인(MalloService)과 실제 Web 백엔드(ThreadingHTTPServer) 양쪽에서 발표 순서대로 실행하는 리허설 테스트 	ests/integration/test_demo_rehearsal.py를 추가(인텐트 정합성 1건 + 서비스 레벨 1건 + HTTP 서버 레벨 1건, 총 3건 통과).
- AC-01~AC-04 검증: 5턴 인텐트 정합성, Turn 3에서 TTS Level 0→1 상승, Turn 4 후 cart(iced americano:2, basque_cheesecake:1), 오프라인 mock 어댑터 로컬 실행(외부 네트워크 호출 없음).
- 리허설 중 발견한 제약: Order Engine(domain/conversation.py)은 턴당 단일 Intent만 허용하여 "아메리카노 하나는 아이스로"(REMOVE+ADD) 식 온도별 분리가 불가능. 이에 E-08 Turn 4 발화를 "아메리카노를 아이스로 바꿔줘"(전체 아이스 일괄 변경, UPDATE_OPTION)로 정렬하고 AC-03도 iced americano: 2로 갱신, 명세 각주로 근거를 기록했다.
- MockNLU에 데모 전용 발화(복합 주문 / 속도 제어 / 온도 변경 / 결제 확정)를 추가해 리허설 결정성을 보장. 기존 테스트는 영향 없음(전체 480 passed, 5 skipped).

## 2026-08-22

상세 기록은 단일 소유권 원칙(`docs/documentation-governance.md`)에 따라 담당 영역 로그로 이관했다. 본 문서는 진입점 요약만 유지한다.

- **STT/Audio**: P0 webm/opus 오디오 디코딩 폴백(#165), 대형 PR #140(STT 데모 페이지)의 스택 PR 재구성과 셸·로직 분리(#166/#167/#171→#186/#172), stt 문서·테스트 정합성 정리(#179/#180/#181), torch 미가용 환경 테스트 게이트(#182) — [`docs/worklogs/stt.md`](worklogs/stt.md)
- **통합/서버**: 팀원 PR 리뷰(#151~#164)와 웹 서버 안정성 수정(#155 JSON 파싱 실패 시 스레드 보호), I-08 E2E Latency 집계 계약 구현(#183/#185), GitHub Actions 한도 소진에 따른 로컬 검증 전환 — [`docs/worklogs/integration.md`](worklogs/integration.md)
