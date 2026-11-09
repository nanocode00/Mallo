---
title: "공통 / 설계 작업 로그 (`C-*`)"
tags: [worklog]
---

# 공통 / 설계 작업 로그 (`C-*`)

공통 설계 영역에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다.

## 2026-08-14

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
- **C-19:** 텍스트 직접 입력 → Mock NLU → Order Engine → Mock TTS 흐름을 실행한다.
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

### MVP 메뉴 옵션 문서 정합성 반영

- `docs/specs/menu-catalog.md`를 기준으로 PRD·TRD·proposal·tasks의 메뉴 범위와 예시를 통일했다.
- 전 메뉴 단일 사이즈와 음료의 메뉴별 HOT / ICED 온도 정책을 MVP 기준으로 명시했다.
- Size / Large 변경 예시는 온도 변경 예시로 교체했다.
- 다중 사이즈와 샷·시럽·휘핑·토핑·우유 변경을 MVP Out of Scope로 명시했다.
- PRD와 TRD의 P0/P1/P2 우선순위는 최신 기준으로 유지했다.

### P0·TTS·STT 정책 정합성 반영

- Local NLU Fine-tuning 수행과 동일 평가셋 기준 Baseline 대비 정량 비교가 P0 완료 조건임을 PRD에 명시했다.
- Mock TTS는 파이프라인 계약 검증용 가상 구현, Baseline TTS는 Fine-tuning 전 실제 기본 모델로 구분했다.
- 외부 LLM API는 사용하지 않지만, STT는 PoC 결과에 따라 Perso.ai 등 외부 API Adapter를 사용할 수 있도록 열어 두었다.
- 외부 STT 인증 정보는 환경변수로만 주입하고 저장소에는 커밋하지 않는다.
- P1 Adaptive TTS는 TTS Fine-tuning PoC에서 선정한 모델을 후보 기본 음성으로 사용하고, 런타임에 속도·pause·문장 분절·핵심 정보 전달 방식을 사용자 요청에 맞게 조절하는 구성으로 정의한다.
- 최종 메뉴에 없는 콜라와 지원하지 않는 디카페인 변경 예시를 실제 메뉴·온도 변경 시나리오로 교체했다.
- 향후 외부 STT Adapter 예시는 현재 후보인 Perso.ai 기준으로 정리했다.

### 프로젝트 외부 API·모델 학습 조건 확인

- 프로젝트 가이드 원문에 따라 유료 외부 LLM API 호출은 금지하고, 주문 이해와 의사결정을 직접 구현한다.
- STT는 외부 API 연결만 사용해도 감점이 없으며 Perso.ai 등의 Adapter를 사용할 수 있다.
- 상용 TTS API는 선택 근거를 제시하면 사용할 수 있지만, 외부 API만 단독으로 사용해서는 딥러닝 기반 TTS 요건을 충족하지 못한다.
- P0에서는 딥러닝 TTS 모델을 최소 하나 직접 실행해 기본 주문 경로를 성립시키고, 프로젝트의 필수 Fine-tuning은 Local NLU를 대상으로 수행한다.
- TTS Fine-tuning·도메인 적응과 별도 구조 모델 비교는 P1 연구축으로 두고, 데이터 감사·학습·Qwen3-TTS 비교·평가·라이선스·사용성 인계를 T-25~T-30으로 추가했다.

### 프로젝트 가이드 필수 조건 작업 반영

- P0는 Tap-to-talk → STT → NLU → Schema Validation → Menu DB/Order Engine → 기본 TTS/GUI 단일 경로와 Local NLU Fine-tuning 전후 비교로 고정했다.
- TTS Fine-tuning·도메인 적응·다중 모델 비교와 Adaptive TTS Level 0~2는 P1로 유지했다.
- Conversational Auto-open, SYSTEM_PROMPTED 입력, Echo·동시 입력·Timeout 처리, 멱등성 고도화와 T0~T7 구간별 Latency 계측은 P2로 분리했다.
- STT 후보 최소 2개를 동일 평가 음성과 실행 환경에서 비교하도록 TRD와 S-08·S-14 완료 기준을 보강했다.
- 고객 여정 지도, 서비스 소개 페이지, 전체 애플리케이션 배포 및 배포 URL 검증 작업을 추가했다.
- 파이프라인 캡처, 음성·텍스트 결과물, 모델 비교 표·그래프·오디오, 5분 데모 영상, 결과보고서 발표자료를 제출물 티켓으로 추가했다.
- 모듈별 독립 서비스는 배포하지 않지만 하나의 통합 애플리케이션은 공개 URL로 배포한다는 범위를 구분했다.

### 메뉴 Schema 및 복수 메뉴 발화 회의 결정

- MVP에서는 공식 메뉴명만 인식하며 별칭은 사용하지 않는다.
- MVP에서는 품절 필드·검증·안내를 구현하지 않는다. 별칭과 품절은 시간이 남을 경우 P2로 추가한다.
- NLU 입력 Context, 지원 Intent, 메뉴별 온도 정책과 단일 메뉴 `OrderCommand` 구조는 현재안을 유지한다.
- 한 문장의 복수 메뉴는 NLU가 발화 순서대로 `OrderCommand[]`로 분해하여 반환한다.
- Batch 안의 Command를 모두 검증한 뒤 실행하며, 하나라도 실패하면 기존 Cart를 유지한다.
- 스타벅스 코리아에 동일 메뉴가 있으면 Tall 가격을 사용하고, 나머지는 다른 카페 가격의 출처와 기준일을 확인한다.
- 팀이 조사한 스타벅스·메가커피·투썸플레이스 가격을 기준으로 10개 메뉴의 MVP 고정 가격을 확정하고 C-04를 완료 처리했다.

### 회의 정책의 문서 전체 정합성 반영

- `docs/specs/menu-catalog.md`를 별칭·품절·가격·온도 정책의 기준 문서로 명시했다.
- `docs/specs/order-command.md`를 NLU 입력, 지원 Intent, 단일 메뉴 Command 필드와 복수 메뉴 출력의 기준 문서로 명시했다.
- 작업 티켓과 제안서의 Intent 이름을 TRD의 `UPDATE_QUANTITY`, `UPDATE_OPTION`, `QUERY_CART` 계약으로 통일했다.
- OrderCommand 예시를 `request_id`, `target_item_id`, `quantity`, `temperature`, `confirmation_required` 필드로 통일했다.
- Intent별 필수·선택 필드는 아직 확정되지 않았으므로 C-09를 다시 TODO로 두고 후속 OrderCommand 회의 항목으로 분리했다.
- 완료된 C-19 Mock Pipeline의 `ADD_ITEM` 전용 구조는 당시 구현 범위를 기록한 축소 계약이며, 현재 전체 MVP 계약이 아님을 명시했다.

### OrderCommand 최종 계약 확정

- NLU 정상 출력은 단일 메뉴도 길이 1의 `OrderCommand[]`로 반환한다.
- Command 하나는 메뉴 하나를 표현하며 모든 Command가 동일한 6개 공통 필드를 포함한다.
- 사용하지 않는 필드는 생략하지 않고 `null`을 사용하며 정의되지 않은 추가 필드는 거부한다.
- `target_item_id`와 `category_id`는 Menu DB의 공식 ID, `temperature`는 `hot`·`iced`·`null`로 제한한다.
- 복수 메뉴는 발화 순서를 유지하고 동일 메뉴·동일 온도는 수량을 합치며, 온도가 다르면 별도 Command로 유지한다.
- Batch 안의 모든 Command를 실행 전에 검증하며 하나라도 실패하면 전체를 실행하지 않는다.
- 서로 다른 Intent가 섞인 한 발화는 MVP에서 실행하지 않고 요청을 나누어 말하도록 안내한다.
- Intent별 필수·선택·`null` 규칙을 확정하고 C-09를 완료 처리했다.
- 확인 필요 여부는 NLU 필드에서 제외하고 Order Engine의 Confirmation Policy가 결정하도록 정리했다.
- 메뉴 조회용 `category_id`를 추가하고 `QUERY_MENU`의 전체·카테고리·특정 메뉴 조회 규칙을 확정했다.
- 수정·삭제 후보가 여러 개인 경우 온도로 구분하며, 불충분하면 `AMBIGUOUS_TARGET`으로 Cart를 보호한다.
- 정상 `OrderCommand[]`와 실패 `OrderCommandError`를 구분하고 C-10을 완료 처리했다.
- 선택 온도가 누락되면 P0에서는 Command를 저장하지 않고 재입력을 안내하며, P1에서는 Clarification으로 복구하도록 구분했다.

## 2026-08-17

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

## 2026-08-18

### Python 가상환경 및 프로젝트 학습/실험 환경 정책 수립

- 저장소 루트 `.venv` 사용 원칙과 OS 간 가상환경 디렉터리 독립성 원칙을 확정했다.
- 일반 개발 환경(Core)은 Python 3.11 또는 3.12를 지원하고, `scripts/check_python_env.py core`를 통해 검증한다.
- 프로젝트 학습 및 STT 재현 환경의 기준을 기존 학습 성공 환경(Python 3.11.9, torch 2.6.0+cu124, transformers 5.15.0, datasets 5.0.1, evaluate 0.4.6, peft 0.20.0, accelerate 1.14.0, faster-whisper 1.2.1, jiwer 4.0.0, soundfile 0.14.0, noisereduce 3.0.3, numpy 2.4.6, pandas 3.0.5, scipy 1.17.1, librosa 미확인)으로 명문화했다.
- "기존 학습이 정상적으로 진행된 환경이므로 우선 이 버전을 기준으로 유지하고, 호환성이나 실행 문제가 발생할 경우 팀 논의 후 변경한다"는 유지·변경 정책을 수립했다.
- `docs/specs/python-environment.md` Spec과 `tests/unit/test_environment_policy.py` 검증 테스트를 추가했다.
- Blackwell 아키텍처(RTX 5070 Ti, sm_120) 환경을 위해 CUDA 12.8 빌드 분리 사용 프로필을 환경 정책 문서에 추가하고, safetensors/PEFT 가중치 무결성 및 호환성을 검증했다.

### 추론 및 배포 아키텍처 수립

- 태블릿 기반 Web/PWA 클라이언트와 GPU 기반 AI 추론 서버(Inference Server)의 물리적/논리적 분리 배포 원칙을 확정했다.
- 초기 MVP는 로컬 데스크톱(RTX 5070 Ti 16GB VRAM)에 STT(Whisper Medium), NLU(Rule/Local LLM), Order Engine, TTS(MeloTTS/Qwen3-TTS)를 상주시키고 순차 실행(Sequential Execution)하여 피크 연산을 분산한다.
- 긴 대기 시간의 비동기 작업 큐 대신 저지연 직접 추론 경로를 우선 채택했다.
- 로컬 GPU 성능 미달 또는 시연 환경 불안정 시 클라이언트 수정 없이 Cloud GPU로 서버를 전환할 수 있는 Fallback 전략을 수립했다.
- 상세 배포 구조와 로드맵은 `docs/inference-deployment.md`에 문서화하고 `docs/trd.md`에 요약을 반영했다.

## 2026-08-20

### 문서 책임 및 Python 환경 정합화

- 삭제된 `requirements-stt.txt`의 남은 참조를 제거하고 STT 의존성의 기준을 `requirements.txt`로 통일했다.
- GPU 차이는 requirements에서 억지로 통일하지 않고 PyTorch CUDA 12.4 안정 빌드와 CUDA 12.8 nightly 설치 단계로 분리했다.
- `tasks.md`에 복제돼 있던 제품 범위·기술 계약·파이프라인을 제거하고 PRD·TRD·기능 Spec 링크와 티켓 상태만 유지하도록 책임을 재정리했다.
- Size는 지원 capability가 최신 합의이며 enum·기본값·가격은 미확정이라는 기능 Spec을 C-05 결과에 연결했다.
- Adaptive TTS 문서와 데모 예시를 실제 구현의 `REQUEST_*` Intent, 1.0/0.85/0.75 속도, 표준 쉼표 Pause 규칙에 맞췄다.

### 음료 Size 계약 확정

- 음료 Size enum을 `SMALL`, `MEDIUM`, `LARGE`로 확정한다. 생략값 `null`은 기본 `MEDIUM`으로 계산하되 기존 Cart 호환을 위해 `null`로 유지한다.
- Menu DB의 `base_price`는 MEDIUM 가격으로 해석하며 SMALL은 500원 차감, LARGE는 500원 추가한다.
- 디저트는 Size를 지원하지 않고 Size 요청 시 `INVALID_OPTION`으로 Cart를 보호한다.
- Size Schema·Order Engine·GUI 표시는 구현됐고 자연어 Size 표현의 Mock/Local NLU 연결은 N-23 후속 티켓으로 분리했다.

### 샷·시럽 무상한 정책 반영

- 최신 합의에 따라 샷·시럽 횟수는 0 이상의 정수이며 서비스 상한을 두지 않는다.
- Menu DB는 `max_extra_shots`, `max_syrup_pumps`를 제거하고 `shot_supported`, `syrup_supported` capability만 유지한다.
- OrderCommand Schema, Order Engine과 NLU Dataset 검증 도구에서 기존 최대 3회 제한을 제거했다.
