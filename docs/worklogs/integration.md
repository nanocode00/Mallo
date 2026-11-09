---
title: "Integration / Service 작업 로그 (`I-*`)"
tags: [worklog]
---

# Integration / Service 작업 로그 (`I-*`)

Integration과 Service 영역에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다.

## 2026-08-18

### End-to-End 음성 주문 파이프라인 및 어댑터 통합 (I-01, I-02, I-03, I-05, I-06, T-05, T-06)

- **음성 입출력 전체 흐름 연결**:
  - `VoicePipeline.handle_audio(audio: bytes, cart: Cart) -> VoiceInteractionResult`를 구현하여 **음성 입력(WAV) ➔ STT ➔ NLU ➔ Order Engine ➔ Adaptive TTS ➔ 음성 출력(WAV)**의 전 과정을 하나의 세션 컨텍스트 안에서 일괄 처리하도록 연결했다.
- **신규 어댑터 및 도메인 모델 추가**:
  - `src/adapters/tts/melotts_adapter.py`: `MeloTTSAdapter` 구현 (Level 0: 1.0x, Level 1/2: 0.85x 속도 적용, in-memory WAV 생성 및 지연시간/발화시간 측정)
  - `src/adapters/tts/qwen3_adapter.py`: `Qwen3TTSAdapter` 구현 (`calm_friendly` 화자 지원)
  - `src/adapters/stt/mock_stt.py`: `MockSTT` 어댑터 구현 (STT 인터페이스 테스트 지원)
  - `src/domain/voice_interaction.py`: `VoiceInteractionResult` (STT, Order, TTS 결과를 포함하는 종합 인터랙션 모델)
- **통합 에러 핸들링**:
  - STT 실패, 빈 오디오 입력, NLU 파싱 오류, TTS 합성 실패 시 각 모듈별 표준 `create_error_response` 에러 응답을 반환하여 주문 흐름이 중단되지 않고 사용자에게 친절한 복구 힌트를 제공하도록 구현했다.
- **검증**:
  - 단위 테스트(`test_melotts_adapter.py`, `test_mock_stt.py`) 및 전체 음성 주문/적응형 TTS 흐름 통합 테스트(`test_end_to_end_voice_pipeline.py`)를 작성하여 전체 300개 테스트 100% 통과를 확인했다.

## 2026-08-19

### I-07 통합 로그 저장 구현

- 인터랙션 로그를 평가 가능한 형태로 기록하는 `InteractionLogger` 계약과 `FileInteractionLogger`(JSONL append)를 구현했다.
- `SessionLogEvent`(`src/domain/session_log.py`)를 `schemas/session-log.schema.json`(E-04) 형식에 맞춰 정의하고, `utils/schema_validation.py`에 `validate_session_log()` 검증기를 추가했다.
- `VoicePipeline`에 `logger`/`session_id`/`step_index`/`participant_id`/`group`/`task_id`를 추가해, 텍스트·오디오 입력 경로에서 ORDER_INTERACTION / TTS_SPEED_CONTROL / ERROR_RECOVERY 이벤트를, `reset_session()`에서 SESSION_RESET 이벤트를 단계별로 기록하도록 연결했다. 모듈별 latency(ms→초 변환)와 주문 후 장바구니 상태를 함께 기록한다.
- 기존 동작 보존을 위해 `NullInteractionLogger`(no-op)를 기본값으로 두었고, `MalloService.build_mock_service(logger=...)`로 주입한다.
- 단위 테스트 9건(`tests/unit/test_interaction_logger.py`)과 통합 테스트 1건(`tests/integration/test_pipeline_logging.py`)을 추가해 스키마 준수와 이벤트 기록을 검증했으며, 전체 테스트는 기존 5건의 선행 실패(본 작업과 무관) 외 모두 통과했다.

### I-08 전체 End-to-End Latency 측정 (Mock 도구)

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

## 2026-08-20

### Real Warm E2E 최종 판정 규칙 확정

- Provider 조합별 Warm-up 3 Turn은 통계에서 제외한다.
- 대표 주문 문장 10개를 각각 Warm 5회 측정한 50 Turn을 최종 판정 모집단으로 사용한다.
- nearest-rank p95가 1.2초 이하면 Target, 1.5초 이하면 Requirement 후보로 판정한다.
- Requirement 통과에는 1.5초 초과 최대 2 Turn과 처리 실패 0건을 추가로 요구한다.
- Cold Start는 3회 별도로 측정하고 평균·중앙값·p95·최댓값·초과 Turn 수 및 원시값을 함께 보존한다.
- 아래 기존 36회 측정은 병목과 성능 가능성을 보여 주는 과거 결과로 유지하지만, 새 50 Turn 계약의 최종 통과 근거는 아니므로 I-08을 재측정 TODO로 전환했다.

### Mallo Real Pipeline Warm E2E Latency 실측 및 통계 보고 (I-08, E-03, e2e-latency.md)

- **배경 및 측정 목적**:
  - `docs/specs/e2e-latency.md` 기준에 따라, Mock 환경이 아닌 실제 신경망 모델 및 어댑터(`Faster-Whisper`, `MockNLU/Domain Resolver`, `ConversationAgent`, `MeloTTS 친절체 파인튜닝`)를 연결하여 음성 주문 전체 파이프라인(End-to-End)의 실제 지연시간을 측정하고 제품 요구사항(Target <= 1.2s, Requirement <= 1.5s) 충족 여부를 검증했다.
- **측정 환경 및 파이프라인 구성**:
  - **하드웨어/런타임**: NVIDIA GeForce RTX 5070 Ti (CUDA 12.4 / PyTorch 2.6)
  - **STT**: `Faster-Whisper` (CUDA FP16, `scipy.signal.resample_poly` 기반 16kHz 모노 리샘플링 적용)
  - **NLU**: `MockNLU` (의도·엔티티·메뉴 별칭·태그 탐색 규칙 기반 파서)
  - **Order Engine**: `ConversationAgent` (결정론적 상태 머신 / 장바구니 연산)
  - **Adaptive TTS**: `MeloTTS` 친절체 파인튜닝 체크포인트 (`logs/mallo-friendly/G_3600.pth`, GPU 가속)
  - **테스트 데이터**: 메뉴 추가(단일/복합/디저트), 옵션 지정/변경, 삭제, 메뉴/장바구니 조회, 주문 확정, 속도 조절, 다시듣기 등 대표 12개 시나리오 x 3회 반복 (총 36회)
- **Cold Start vs Warm State 분석**:
  - **Cold Start (최초 1회 실행)**: 첫 턴 호출 시 모델 VRAM 로딩, CUDA 커널 초기화 및 MeCab/BERT 토크나이저 초기화로 인해 **총 1,408.0ms (~1.41초)** 소요.
  - **Warm State (2회차 이후)**: 모델이 GPU 메모리에 상주한 뒤 36회 반복 측정 결과 **평균 147.2ms, p95 368.7ms**로 안정적인 초저지연 달성.
- **구간별 및 전체 Warm E2E 실측 결과 (36회 통계)**:

| 구간 (Stage) | 평균 (Mean) | 중앙값 (Median) | p95 (상위 5%) | 최소 (Min) | 최대 (Max) | 표준편차 (Std) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **1. STT 전사** | **48.6 ms** | 46.0 ms | 85.4 ms | 23.2 ms | 96.0 ms | 19.3 ms |
| **2. NLU 의도 파싱** | **9.0 ms** | 8.6 ms | 15.0 ms | 2.4 ms | 20.2 ms | 3.8 ms |
| **3. Order Engine** | **< 0.1 ms** | 0.0 ms | 0.1 ms | 0.0 ms | 0.1 ms | 0.0 ms |
| **4. Adaptive TTS** | **73.6 ms** | 0.0 ms* | 299.3 ms | 0.0 ms | 380.6 ms | 114.6 ms |
| 🚀 **Total Warm E2E** | **147.2 ms** | **78.4 ms** | **368.7 ms** | **31.5 ms** | **441.6 ms** | **118.8 ms** |

> *(참고: TTS의 경우 속도 조절 등 즉시 상태 변경만 수행되는 제어 턴을 제외하고 실제 음성 합성 발생 시 약 150~380ms 소요)*

- **제품 스펙 판정 (`docs/specs/e2e-latency.md`)**:
  - **Target 목표 ($\le 1.2$초 / 1,200ms)**: **✅ 달성** (p95 = 368.7ms로 목표치 대비 약 30% 수준)
  - **Requirement 한계 ($\le 1.5$초 / 1,500ms)**: **✅ 완벽 충족** (최악 케이스 최대값 441.6ms)
  - **Latency Provider Fallback 불필요**: Local 파이프라인이 Requirement(1.5초)를 대폭 상회하여 만족하므로 외부 API로의 Fallback 없이 온디바이스/로컬 배포 적합성을 확인했다.
- **재현 스크립트**:
  - `scripts/measure_real_e2e_latency.py`: `--rounds`, `--whisper-size` 옵션을 통해 언제든 파이프라인 E2E 지연시간을 재측정하고 통계 리포트를 출력할 수 있도록 구성했다.

## 2026-08-21

### STT 데모 페이지와 /api/stt 엔드포인트 추가

**배경:**

- 회의에서 마이크 발화가 STT로 어떤 텍스트가 되는지 즉석 시연할 필요가 있었다.
- 현재 데모·평가에 사용 중인 후보 모델(whisper-medium QLoRA+Domain merged-bf16)의 실동작을 파이프라인 전체 실행 없이 확인할 경로가 없었다.

**변경 내용:**

- `web/stt-demo.html` 신설 — 마이크 녹음 → 16kHz 모노 WAV 변환 → 인식 텍스트 대형 표시. 현재 데모·평가에 사용 중인 후보 모델로 입력 장치 선택 드롭다운(MagicMic 등 가상 오디오 장치 오선택 방지), 실시간 입력 레벨 미터, 신뢰도·STT 지연 표시, WAV/MP3 파일 업로드 테스트 경로를 포함한다.
- `POST /api/stt` 엔드포인트 추가 — NLU·Order Engine·TTS를 생략하고 STT만 수행한다. `VoicePipeline.transcribe_audio()` → `MalloService.transcribe()` 위임 계층을 두었고 기존 `/api/*` 응답 계약은 변경하지 않았다.
- 기존 kiosk GUI(`index.html`/`app.js`)는 수정하지 않았다.

**검증:**

- Mock 서비스 응답 및 웹서버 통합 테스트 통과.
- 실모델 E2E(stt venv + RTX 4060 Ti): "아이스 아메리카노 두 잔 주세요" 발화 → 동일 텍스트 인식(confidence 0.90).

**실행 방법:**

- `src\adapters\stt\.venv\Scripts\python.exe src\app\server.py --stt whisper --stt-variant qlora` 실행 후 `http://127.0.0.1:8000/stt-demo.html` 접속.

**미완료 (다음 작업):**

- 웹 UI 체인(#131~#137)이 `src/app/server.py`를 함께 수정하므로 체인 병합 후 본 PR rebase 필요.
- 시스템 Python의 torch 설치 손상(caffe2_nvrtc.dll 로드 실패) — `pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu124` 재설치 권장. 현재 서버 실행은 `src/adapters/stt/.venv` 사용.

## 2026-08-22

### PR 리뷰 및 P0 수정 진행 (웹 서버/통합)

- 팀원 PR 리뷰 완료: #151, #152, #156, #157, #159, #160, #161, #164 승인. #162는 변경 요청(UI 스택 중간의 app.js가 후순위 #136에만 존재하는 DOM ID와 menu-metadata.js를 참조해 스택 순서가 붕괴됨), #163은 코멘트(menu-metadata.js 부재로 테스트 수집 자체가 실패).
- #155(JSON 파싱 실패 시 핸들러 스레드 보호) 리뷰 반영: `_parse_json_object()` 헬퍼로 dict 타입 검증과 `UnicodeDecodeError` 처리를 추가하고 회귀 테스트 14건을 보강해 재리뷰 요청.

### I-08 E2E Latency 집계 계약 구현

- e2e-latency Spec의 반복·집계 계약을 `src/utils/latency_aggregation.py`로 추출했다: nearest-rank 백분위, Turn 성능 구간 분류(AC-02), Warm-up 3 Turn 제외(AC-07), p95·1.5초 초과 최대 2건·처리 실패 0건 게이트 판정(AC-08). 단위 테스트 13건 추가(STT venv·전역 동일 통과) — **#185로 별도 PR 분리 완료**.
- Real 측정 스크립트(`scripts/measure_real_e2e_latency.py`)를 갱신해 Warm-up 실행 후 제외, measurement_type/cold_start/provider_set 메타데이터, 장비·OS·Python·torch·CUDA·checkpoint 환경 기록, `--report` Turn별 원시 JSON 보고서를 지원한다(#183). **NLU가 MockNLU이고 실제 mic/VAD 입력·실제 재생 first_audio_start가 없으므로 Spec EC-02·EC-03에 따라 모든 레코드를 `MOCK_E2E`로 기록하고 Target/Requirement 최종 판정은 비활성화(AC-03)했다.**
- 본 머신에는 MeloTTS 자산(data/tts/repos/MeloTTS, logs/mallo-friendly/*.pth)이 없어 최종 50 Turn 실측은 자산이 있는 GPU 장비에서 수행 예정이다. tasks.md I-08 진행 상태를 갱신했다.

### 기타

- **GitHub Actions는 사용량/한도 소진으로 CI 실행 불가 상태**(`docs/github-actions-limit-and-local-testing.md`). 승인은 로컬 검증으로 대체하고 있으며, Actions 복구 전까지 CI 자동 체크에 의존하지 않는다(`pytest`/`gitleaks` 필수 체크 일시 해제 권장).
- 오늘 생성·갱신한 PR: #155(재리뷰), #165(병합), #166/#167(병합), #171/#172(셸/로직 재작성 후 재리뷰), #179/#180/#181(병합), #182(재리뷰), #183(harness 재분류·#185 분리 후 재리뷰), #185(집계 모듈 신규 PR·리뷰 대기). 리뷰어: nanocode00.

## 2026-08-24

### 로컬 GPU 통합 테스트 하네스 구축 (#204)

- 실사용자 테스트 전 로컬 실모델 통합 검증을 위해 프로세스 분리형 하네스를 구축했다.
  - **STT 사이드카**: STT venv(transformers 5.x)에서 `WhisperMediumSTT`(merged-bf16, GPU fp16)를 로드하고 `POST :8001/transcribe`로 전사만 제공(`scripts/stt_sidecar_server.py`, `run_stt_sidecar.bat`)
  - **메인 서버**: .venv-melo(transformers 4.27)에서 MeloTTS(G_2800, speaker 10) + MockNLU + Order Engine 구동, STT는 `HTTPClientSTT`로 사이드카 호출(`--stt http --stt-model http://127.0.0.1:8001/transcribe`)
  - 런처: `scripts/run_local_real.bat`(사이드카 기동→health 대기→메인 서버), `scripts/run_local_server.py`(환경 가드+MeCab/eunjeon 스텁)
- **검증 결과(RTX 4060 Ti)**: 텍스트 주문 success(TTS WAV RIFF 283KB 생성), 음성 업로드 시 STT 완벽 전사("안녕하세요. 주문을 도와드릴게요."), warm E2E 0.61초(요구 1.5초 이내), REQUEST_SLOWER→Level 1, VRAM 4.4GB/8GB
- **제약**: NLU는 MockNLU(규칙 기반)라 비주문 발화는 `UNSUPPORTED_UTTERANCE`로 안내되는 것이 정상 동작이다.

### 트러블슈팅 기록 — 같은 에러 재발 시 아래 순서로 대조

**1) `Could not load symbol cudnnGetLibConfig. Error code 127` + 요청 처리 중 네이티브 크래시(클라이언트 ConnectionReset)**
- 원인: 단일 프로세스에서 ctranslate2(STT)와 torch(MeloTTS)가 서로 다른 cuDNN 9를 로드해 충돌. PATH 로더 순서를 바꿔도 한쪽이 반대로 크래시한다.
- 해결: **프로세스 분리**(STT 사이드카). 참고로 `nvidia-cudnn-cu12` pip 휠의 cuDNN을 PATH 최우선 배치하면 단일 프로세스도 일부 조합은 동작하지만 불안정하다.

**2) `ERROR: No matching distribution found for melotts==0.1.2` / `No module named 'melo'`**
- 원인: PyPI의 `melotts`와 무관하다. requirements의 `melotts==0.1.2`는 **MeloTTS repo를 editable 설치했을 때의 패키지명/버전**이다(PyPI 0.1.1은 sdist 빌드 자체가 깨짐).
- 해결: `git clone https://github.com/myshell-ai/MeloTTS data/tts/repos/MeloTTS` 후 `pip install -e data/tts/repos/MeloTTS --no-deps`, 나머지 추론 의존성은 repo requirements.txt 기준으로 수동 설치(torch/torchaudio cu124 포함).

**3) `TypeError: exceptions must derive from BaseException`**
- 원인: 한국어 G2P(`g2pkk`)가 Windows에서 `eunjeon`을 요구하고, 미설치 시 `raise print(...)` 버그로 None을 raise한다.
- 해결: python-mecab-ko로 대체하는 eunjeon 스텁(`run_local_server.py` 참고).

**4) `ImportError: Japanese requires mecab-python3 and unidic-lite.` + `No module named 'mecab'`**
- 원인: mecab-python3(패키지 디렉터 `MeCab`)과 python-mecab-ko(`mecab`)가 Windows 대소문자 비구분 FS에서 공존 불가하며 파일이 서로를 덮어쓴다. melo의 japanese 클리너가 eager import하기 때문에 KR만 써도 막힌다.
- 해결: mecab-python3 제거 + `sys.modules["MeCab"]` 더미 스텁(japanese 파싱은 KR 합성에서 미호출).

**5) `data did not match any variant of untagged enum ModelWrapper at line ...`**
- 원인: transformers 5.x가 저장한 신규 포맷 `tokenizer.json`을 transformers 4.27 번들 tokenizers(0.13)가 파싱 실패.
- 해결: hub `openai/whisper-medium`의 구형 포맷 tokenizer.json으로 교체(vocab.json/merges.txt도 함께 보완).

**6) `WhisperForConditionalGeneration.__init__() got an unexpected keyword argument 'dtype'`**
- 원인: ct2-transformers-converter(ctranslate2 4.8)가 transformers 5.x 방식 dtype kwarg를 전달.
- 해결: `scripts/convert_stt_ct2.py` — `__init__`에서 dtype kwarg를 제거하는 호환 패치 후 변환기 main() 호출.

**7) `ValueError: <|startoftranscript|> token was not found in the prompt` (전사 빈 문자열)**
- 원인: CT2 변환 시 slow tokenizer 기반 어휘 추출이라 특수토큰이 빠진 50,257 vocab가 생성됨(정상은 51,865).
- 해결: fast tokenizer(구형 포맷 파일) 사용해 변환. 확인법: 출력 `vocabulary.json`에 `startoftranscript` 포함 및 어휘 수 51,865.

**8) 동일 포트 이중 바인드 — 두 서버 인스턴스 모두 "running"처럼 보임**
- 원인: Windows에서 `http.server`의 allow_reuse_address가 서로 다른 프로세스의 동일 포트 바인드를 허용한다. 응답은 나중에 바인드한 쪽으로 가서 환경 혼동 유발.
- 해결: 기동 전 기존 인스턴스 정리, `Get-NetTCPConnection -LocalPort 8000`으로 소유 PID의 exe/prefix까지 확인하는 습관.

**9) 리슨 프로세스 exe가 전역 파이썬으로 보이는 것(오탐 아님)**
- 원인: Windows venv의 `Scripts\python.exe`는 베이스 인터프리터를 자식 프로세스로 실행하는 런처이다. exe 경로는 전역 파이썬이지만 sys.prefix/site-packages는 venv다.
- 해결: 판별은 exe가 아니라 `sys.prefix`로 한다(`run_local_server.py` 상단 가드 참고).

**10) bat 파일의 한글 주석이 깨지며 `'U)'은(는) 내부 또는 외부 명령...` 오류**
- 원인: cmd는 bat을 시스템 코드페이지(CP949)로 파싱하는데 UTF-8 한글 주석이 줄을 망가뜨린다.
- 해결: bat에는 영문(ASCII) 주석만 사용한다.

**11) 근본 제약 — transformers 이중 버전**
- whisper-medium HF 어댑터는 5.x, MeloTTS는 4.27을 요구해 한 venv 공존이 불가능하다. STT/TTS를 함께 도는 프로세스는 faster-whisper(CTranslate2) 계열이거나 본 건의 사이드카 분리여야 한다. NLU 추론 러너(#200) 병합 시 요구 transformers 버전을 반드시 먼저 확인할 것.
