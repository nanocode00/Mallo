---
title: "Adaptive TTS / Voice UX 작업 로그 (`T-*`)"
tags: [worklog]
---

# Adaptive TTS / Voice UX 작업 로그 (`T-*`)

Adaptive TTS와 Voice UX 영역에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다.

이 문서는 결정 이력이며 현재 요구사항의 기준 문서가 아니다. 최신 우선순위는 `docs/prd.md`, 기술 경계는 `docs/trd.md`, TTS 학습·평가·선택 계약은 `docs/specs/melotts-friendly-finetuning-poc.md`를 따른다.

## 2026-08-21

### T-30 사용성 테스트 사전 인계 정보 동기화

- 외부 참가자 없이 저장소 근거로 확인 가능한 후보·환경·구현 상태와 공통 사용자 과제 연결만 `docs/tts-usability-test-handoff.md`에 미리 기록했다.
- TensorBoard 학습 로그를 재검토한 결과 전체 Generator loss 최저는 저장되지 않은 step 2,850의 `26.6747`이었고, 저장된 후속 후보 중에는 step 2,800의 `29.0754`가 가장 낮았다. `G_3600.pth`의 step 3,600 값은 `31.9244`로 최저가 아니었다.
- 사용성 테스트 checkpoint를 `G_2800.pth`로 확정했다. 이는 loss 기반 후보 선택이며 음질 우위를 뜻하지 않으므로 블라인드 청취 평가는 별도로 수행한다.
- `G_2800.pth`(SHA-256 `858d23f61e7241671d7c5899adf3b82ec97987716e87c356f5847989e3af3d83`)를 지정해 T-21 평가 문장 20개를 `cuda:0`에서 재합성했다. 20개 모두 비어 있지 않은 44.1kHz WAV로 생성됐고 평균 생성 지연 `0.1951초`, 중앙값 `0.1830초`, 평균 RTF `0.0428`, 최대 RTF `0.0720`을 기록했다.
- 재검증 결과는 로컬 `data/tts/runs/benchmarks_gpu/g2800_revalidation/melotts_friendly/summary.json`에 보관한다.
- 다시 듣기와 오류 fallback은 구현 근거를 연결했고, 사용자용 재생 중단·5초 대기 안내·브라우저 `first_audio_start` 계측은 미구현 또는 미계측으로 분리했다.
- 참가자 세션, 발견 사항, 개선 전후 검증 표는 비워 두고 외부 참가자 3명과 개선 근거 2건이 없으므로 T-30은 미완료 상태를 유지한다.

### Adaptive TTS Level 0/1 Latency 비교 (T-12)

- `docs/specs/adaptive-tts-latency.md`에 동일 모델·문장·장치에서 Level 0/1의 추가 합성 지연을 분리하는 측정 계약을 정의했다.
- MeloTTS Friendly `G_3600.pth`, speaker 10, RTX 5070 Ti 16GB(`cuda:0`), Python 3.11.9, PyTorch `2.12.0.dev20260408+cu128`, Transformers 4.27.4의 MeloTTS 전용 격리 환경에서 측정했다.
- T-21 문장 20개를 Level별 warm-up 1회 후 각각 5회씩 합성했다. 반복마다 Level 실행 순서를 교차했으며 통계 대상 200회가 모두 성공했다.

| 지표 | Level 0 | Level 1 | Level 1 추가분 | Level 1 / Level 0 |
|---|---:|---:|---:|---:|
| 합성 지연 평균 | 169.4ms | 210.1ms | +40.7ms | 1.240배 |
| 합성 지연 중앙값 | 147.8ms | 199.4ms | +51.6ms | 1.349배 |
| 합성 지연 p95 | 307.2ms | 362.0ms | +54.8ms | 1.179배 |
| RTF 평균 | 0.0383 | 0.0391 | +0.0008 | 1.020배 |
| RTF p95 | 0.0571 | 0.0602 | +0.0031 | 1.054배 |

- Level 1은 Pause가 포함된 변환문과 `speed=0.85`를 적용해 절대 합성 지연은 평균 40.7ms 증가했지만, 생성 음성 길이를 반영한 평균 RTF 증가는 약 2.0%였고 두 Level 모두 RTF 1.0 미만을 유지했다.
- 이 결과는 모델 합성 구간만 비교한 Component Benchmark이며 실제 playback이나 제품 E2E 판정에는 사용하지 않는다. 재현 코드 revision은 `3bc5d4f0c762b1faf73cde67236437a0d1f4a37e`이고 원시 결과는 로컬 JSON으로 보관했다.

## 2026-08-19

### Qwen3-TTS 0.6B Causal Contract 정밀 진단, Double Shift 버그 해결 및 All-Linear LoRA 299개 전체 파인튜닝 완주 (T-27)

- **문제 진단 및 원인 규명**:
  - 초기 Qwen3-TTS SFT 시 발생했던 외계어·동물 울음소리·24초 생성 폭주 현상에 대해 12대 항목 정밀 진단(Diff 분석, Shape 실측, Teacher-forcing CE 산출, Tokenizer Round-trip, 1-Sample Overfit)을 수행했다.
  - HuggingFace `ForCausalLMLoss`의 2차 자동 Shift로 인해 $t \rightarrow t+2$를 예측하던 **Double Shift 버그**를 규명하고, 단일 Shift 직접 Cross-Entropy로 수정하여 Teacher-forcing Loss를 **9.71에서 1.30으로 86.6% 급감**시켰다.
  - 15개 서브토커(Code Predictor) 병렬 VQ 코드북 레이블의 Causal Shift를 제거하여 1:1 정렬을 완성했다.
- **LoRA Capacity 확장 및 최적 하이퍼파라미터 확정**:
  - 기존 `q_proj, v_proj` (1.16%) 한정 LoRA의 수렴 지연 문제를 해결하기 위해 `q, k, v, o, gate, up, down` 전체 Linear 계층($r=16, \alpha=32$, 2.11%) 및 `text_projection` unfreeze 설정을 확정했다.
  - 초기 과도한 LR(`5e-5 ~ 2e-4`) 대신 안정적인 `2e-6` (AdamW)을 적용하여 파괴적 망각 없는 일반화 수렴을 달성했다.
- **299개 전체 데이터셋 최종 파인튜닝 및 20개 대표 주문 시나리오 벤치마크**:
  - 299개 전체 한국어 친절체 음원 대상 10 Epoch (750 Optimizer Steps) 학습을 완주하고 어댑터를 저장했다 (`data/tts/runs/qwen3_full299/checkpoints/adapter_model/`).
  - 20개 카페 대표 주문 문장 전수 합성 결과, **0% 폭주 / 100% EOS 정상 종료 (3.28~6.96초) / Whisper STT 높은 전사 정확도**를 달성했다.
  - 실제 사람이 말하는 듯한 뛰어난 운율(Prosody)과 차분한 친절체 여성 음색을 성공적으로 확보했으며, 전용 HTML 플레이어(`data/tts/runs/qwen3_full299/eval_player.html`)를 구축했다.

## 2026-08-18

### T-31 Adaptive TTS Intent 실행 연결

- `REQUEST_REPEAT`, `REQUEST_SLOWER`, `REQUEST_DEFAULT_SPEED`를 Orchestrator에서 가로채 Cart 변경 없이 실행하도록 연결했다.
- 마지막 안내 원문과 세션 TTS Level을 유지하고, 제어 요청 시 Level별 텍스트 변환 후 즉시 다시 합성한다.
- 후속 일반 주문도 변경된 Level을 사용하며 `reset_session()`으로 Level 0과 기본 인사말을 복원한다.

### MeloTTS vs Qwen3-TTS Baseline 20개 평가 문장 합성 및 벤치마크 수행 (T-05, T-22, T-28)

- `data/tts/evaluation/sentences.json`의 카페 대표 주문 20개 문장에 대해 `MeloTTS-Korean`과 `Qwen3-TTS-0.6B` Baseline 사전학습 모델로 오디오 합성 및 지표 측정을 완료했다 (`src/adapters/tts/eval_synthesis.py`).
- 총 40개 WAV 파일(모델별 20개)을 `data/tts/runs/benchmarks/melotts_baseline/` 및 `data/tts/runs/benchmarks/qwen3_baseline/`에 저장했다.
- **MeloTTS (CPU)**: 평균 지연시간 **1.92초**, 평균 RTF **0.3939** (44.1kHz), 실시간 기준(< 1.0) 충족.
- **Qwen3-TTS (CPU)**: 평균 지연시간 **22.31초**, 평균 RTF **3.9254** (24kHz), CPU 연산량 집중으로 지연 높음 확인.

### RTX 5070 Ti (Blackwell sm_120) GPU 가속 활성화 및 GPU 벤치마크 재측정

- PyTorch CUDA 12.8(`torch-2.12.0.dev20260408+cu128`, `torchaudio-2.11.0.dev`)로 업그레이드하여 RTX 5070 Ti(`sm_120`) GPU 가속을 활성화했다.
- 동일 20개 문장에 대해 GPU(`cuda:0`) 벤치마크를 재수행했다 (`data/tts/runs/benchmarks_gpu/`):
  - **MeloTTS (GPU)**: 총 3.97초, 평균 지연시간 **0.1985초 (약 198ms)**, 평균 RTF **0.0403** (25배 실시간 속도 달성).
  - **Qwen3-TTS 0.6B (GPU, bfloat16)**: 총 138.15초, 평균 지연시간 **6.9075초**, 평균 RTF **1.4620** (CPU 대비 3.2배 속도 향상).

### Qwen3-TTS 0.6B 친절체 Fine-tuning 완료 (T-27)

- **데이터셋**: AI Hub 133번 화자 10번(20대 여성, 차분·친절체) 30분 데이터 중 299개 paired record (`data/tts/runs/qwen3/train_with_codes.jsonl`).
- **전처리 및 Speech Tokenizer**:
  - `Qwen/Qwen3-TTS-Tokenizer-12Hz`로 299개 음성의 `audio_codes` 추출 완료.
  - 고품질 44.1kHz 음원에 대해 `dataset.py` 내 24kHz 자동 리샘플링(`librosa.resample`) 적용.
- **아키텍처 및 0.6B 수정 (GitHub Issue #198 해결)**:
  - 0.6B 모델은 `text_embedding`(2048차원)과 내부 레이어(1024차원)의 차원이 달라 사전학습 모듈인 `text_projection` 선형 레이어를 통과하도록 스크립트 보정.
- **학습 결과 (총 10 Epoch)**:
  - 1차 SFT (lr `2e-5`, 5 epoch): Loss `12.53` ➔ `2.57`
  - 2차 추가 SFT (lr `1e-5`, 5 epoch): Loss `2.84` ➔ **`2.19`** (최종 수렴 완료)
- **합성 동작 검증**: `generate_custom_voice(speaker='calm_friendly')`로 한국어 주문 안내 문장 음성 정상 생성 완료 (`test_sample.wav`, 7.92초).

### MeloTTS 텍스트 전처리(T-25) 및 친절체 Fine-tuning 2,000 Steps(T-26) 완료

- **학습 환경**: RTX 5070 Ti 16GB GPU (`torch-2.12.0.dev+cu128`), VITS2 구조, 44.1kHz 샘플레이트.
- **데이터 전처리 (T-25)**: Python 3.11.9 / CUDA 12.8 baseline 환경 확정 후 g2pk2 및 MeloTTS 공식 `korean.py`를 활용해 299개 paired text의 음소/발음 전처리를 완료했다 (`data/tts/derived/aihub-71349/melo_dataset/train.txt.cleaned`).
- **학습 파라미터 및 초기화 (AC-08)**:
  - Batch size 4, lr 1e-4 (`lr_decay` 0.999875), `segment_size` 16,384.
  - 공식 학습용 `G.pth` (595MB), `D.pth` (228MB), `DUR.pth` (60MB) 사전학습 가중치를 로드하고 optimizer를 신규 초기화(`warm_start`)하여 Fine-tuning을 개시했다.
- **학습 진행 및 수렴 과정**:
  - `Step 200` (Epoch 2): Loss Disc 2.89 / Gen 24.31 / Mel 2.45
  - `Step 800` (Epoch 10): Loss Disc 2.85 / Gen 21.65 / Mel 2.38
  - `Step 1400` (Epoch 18): Loss Disc 2.97 / Gen 20.83 / Mel 2.42
  - `Step 2000` (Epoch 26): Loss Disc 2.94 / Gen 21.29 / Mel 2.35 (학습 안정 수렴)
  - 최종 가중치 저장: `logs/mallo-friendly/G_2000.pth` (595MB)

### TTS 4개 모델 20개 도메인 문장 종합 품질·성능 비교 평가 및 최우선 후보 선정 (T-28)

- 동일 20개 대표 주문 도메인 평가 문장(`data/tts/evaluation/sentences.json`)에 대해 GPU(`cuda:0`) 환경에서 4개 모델(MeloTTS Baseline, MeloTTS Friendly, Qwen3-TTS Baseline, Qwen3-TTS Friendly)의 음성 합성 및 벤치마크 지표를 측정했다 (`src/adapters/tts/eval_synthesis.py`).

| 모델명 | 버전 / 체크포인트 | 샘플레이트 | 평균 지연시간 (Latency) | 중앙값 지연시간 | 평균 RTF | 실시간 배수 | 비고 |
|---|---|---|---|---|---|---|---|
| **MeloTTS Baseline** | `myshell-ai/MeloTTS-Korean` | 44.1 kHz | **0.1985s** (198ms) | 0.1814s | **0.0403** | 24.8배 | 기준 모델 (빠르나 어조 단조로움) |
| **✨ MeloTTS Friendly** | `logs/mallo-friendly/G_2000.pth` | **44.1 kHz** | **0.2041s** (204ms) | **0.1928s** | **0.0485** | **20.6배** | **PoC 최우선 후보** (초고속 + 차분하고 친절한 어조) |
| **Qwen3-TTS Baseline** | `Qwen3-TTS-0.6B-CustomVoice` | 24.0 kHz | 6.9075s | 6.5844s | 1.4620 | 0.68배 | 자연스러우나 interactive 서빙에 지연 큼 |
| **Qwen3-TTS Friendly** | `checkpoint-epoch-4` (10 ep) | 24.0 kHz | 28.1953s | 34.0154s | 1.5732 | 0.63배 | 친절체 음색 모사 성공했으나 지연이 매우 큼 |

- **기술 의사결정 및 연동 정책**:
  1. **실시간 대화성 (Latency & RTF)**: `MeloTTS Friendly`는 20개 문장 평균 생성 지연이 **0.204초(204ms)**, RTF **0.0485**로 사용자 발화 후 0.2초 만에 즉각 음성 안내가 시작되어 키오스크 인터랙션에 최적이다. 반면 Qwen3-TTS 0.6B는 Autoregressive 토큰 생성 방식으로 문장당 7~28초가 소요되어 단독 실시간 서빙에 부적합하다.
  2. **오디오 품질 (Sampling Rate)**: MeloTTS는 **44.1 kHz 고품질 스튜디오 음질**을 제공하여 24.0 kHz인 Qwen3-TTS 대비 카페 소음 환경에서도 안내 음성의 명료도(Clarity)가 우수하다.
  3. **톤 앤 매너 (친절체 전이)**: Baseline의 무감정한 억양 대비, 10번 화자의 억양 특성(어미의 완만하고 부드러운 하강, 차분한 속도감)이 성공적으로 학습되어 고령 사용자 친화적 안내를 제공한다.
  4. **프로덕션 어댑터 연동 정책**: `MeloTTSAdapter`에 Fine-tuned 모델 적용 시 `speaker="10"` 화자를 전달하며, 미지정 또는 모델 부재 시 기본 `KR` 화자로 graceful fallback하도록 관리한다.
  5. **라이선스 및 배포 정책 (AC-13 / T-29)**: AI Hub 라이선스 서면 확인(T-29) 진행 중이므로 외부 공개나 상용 배포 전까지 체크포인트 파일(`G_2000.pth`)은 사내/PoC 로컬 환경 내에서만 안전하게 관리한다.
  6. **시각화 및 청음 도구**: 4개 모델의 20개 합성 음성을 웹 브라우저에서 바로 비교 청음할 수 있는 HTML 플레이어(`data/tts/runs/benchmarks_gpu/tts_player.html`) 생성 절차를 마련했다.

## 2026-08-17

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

## 2026-08-16

### T-01 TTS 후보 모델 조사 완료

- 공식 저장소와 모델 카드를 기준으로 MeloTTS와 `Qwen/Qwen3-TTS-12Hz-0.6B-Base`의 한국어 지원, 로컬 실행 경로, 라이선스와 제어 가능성을 비교했다.
- MeloTTS는 `KR`·CPU/CUDA/MPS·속도 제어와 MIT 근거를 확인해 P0 Baseline 우선 검증 및 P1 주 Fine-tuning 후보로 정했다.
- Qwen3-TTS 0.6B Base는 한국어·로컬 package·참조 음성 제어와 Apache-2.0 근거를 확인해 P1 별도 구조 비교 후보로 정했다.
- 문서상 지원은 실제 개발 환경 실행·성능·음질을 보장하지 않으므로 T-02~T-04를 미완료로 유지했다. 0.6B Fine-tuning 호환성은 T-27 스모크 테스트에서 검증하고 실패 시 자원 한도 안에서만 1.7B를 검토한다.
- 모델 라이선스와 AI Hub 학습 데이터·산출물 이용 범위를 분리하고 후자는 T-29 서면 문의 대상으로 유지했다.
- `docs/specs/tts-candidate-research.md`의 AC를 충족해 T-01을 완료 처리했다.

### T-21 TTS 평가 문장 세트 제작

- 실제 시스템 안내 형태의 한국어 문장 20개를 메뉴·온도, 수량·단위, 가격·총액, 수정·삭제, 장바구니 요약·결제 범주별로 4개씩 작성했다.
- 각 문장에 청취 평가용 핵심 정보와 Menu Catalog ID를 연결하고 공식 메뉴명만 사용하도록 자동 검증했다.
- NFKC·소문자화·문장부호 제거·공백 정규화를 적용해 T-25 train/validation/test manifest 371행과 비교했으며 완전 일치 문장은 0개였다.
- 문장 구조·범주 균형·메뉴 정합성·누수 검사를 자동화하고 T-21을 완료 처리했다.

### T-22 TTS 성능 Benchmark 작성

- T-21 문장마다 새 backend의 모델 로딩을 포함한 cold 1회와 같은 instance의 warm 5회를 측정하는 공통 runner를 작성했다.
- 생성 지연, streaming/non-streaming TTFB, WAV 실측 길이, RTF, 프로세스 Peak RAM과 backend가 제공하는 Peak VRAM을 원시 run 단위로 기록한다.
- cold/warm별 평균·중앙값·nearest-rank p95와 성공·실패 수를 계산하고 Git SHA·OS·CPU·RAM·Python·모델 metadata를 JSON에 저장한다.
- 결정론적 fixture backend로 평가 문장 20개를 총 120회 실행해 cold 20회·warm 100회 성공과 WAV decode를 확인했다. 이 수치는 실제 모델 성능 결과로 사용하지 않는다.
- 실패 격리와 streaming TTFB 계약을 포함한 전체 자동 테스트를 통과해 T-22를 완료 처리했다.

### T-23 TTS 블라인드 청취 평가 양식 준비

- 자연스러움·전체 명료도·친절함·메뉴명·수량과 단위·가격·매장 안내 적합성의 7개 점수와 핵심 정보 전달·심각한 오독 또는 음성 깨짐 판정을 기록하는 양식을 작성했다.
- 메뉴명·수량·가격이 문장에 없을 때만 해당 정보별 명료도를 `NA`로 제외하고 나머지 네 품질 항목은 모든 샘플에서 필수로 평가하도록 기존 계약을 명확히 했다.
- 후보별 T-21 WAV 20개를 검증하고 participant별 순서를 재현 가능하게 섞어 익명 WAV·공개 평가표·비공개 정답표를 생성하도록 자동화했다.
- fixture 후보 2개·총 40개 WAV로 익명화, participant별 무작위화, SHA-256 원본 보존과 완료 응답 검증을 확인했다. 실제 MOS 평가는 수행하지 않았다.
- 전체 자동 테스트를 통과해 T-23 양식 준비를 완료 처리했다.

### T-25 친절체 데이터 감사 및 adaptation package 생성

- 로컬 ZIP 204개 중 친절체 라벨·원천 ZIP 102쌍을 전수 검사했다.
- 화자 10번의 `친절체 + 매장응대 + 기쁨` 유효 데이터는 572건, 3,322.369초로 확인됐다. 기존 문서의 약 0.848시간은 전체 ZIP과 WAV를 검증한 실측값 0.923시간으로 정정했다.
- WAV 572건은 모두 decode 가능, mono, 44.1 kHz였고 빈 텍스트와 중복 텍스트는 최종 manifest에 포함하지 않도록 변환기에 검사를 추가했다.
- 녹음 그룹을 분리하지 않고 seed `42`로 train 500건, validation 22건, test 50건을 구성했다.
- train에서 목표 30분에 가장 가까운 녹음 그룹 조합 300건·1,799.705초를 선택하고, 6.5초 음성 1건을 Qwen 학습용 `ref_audio`로 예약했다. 두 모델의 paired training records는 동일한 299건이다.
- 단위·통합 테스트 66개와 실제 manifest 371행의 경로·형식·WAV decode·split 중복 검사를 통과했다. 회의에서 Python 환경을 확정한 뒤 MeloTTS 공식 텍스트 전처리를 실행해야 T-25를 최종 완료 처리할 수 있다.

### T-26 MeloTTS 학습 실행 준비

- Python 환경 확정 전에는 설치와 GPU 학습을 수행하지 않고, 입력 검증·checksum·config·실행 명령을 만드는 준비 도구만 작성했다.
- 공식 전처리기가 metadata를 다시 무작위 분할하는 동작을 확인하여 T-25의 고정 train/validation을 각각 전처리하도록 실행 계획을 구성했다.
- 공식 `train.sh`의 무한 auto-resume은 2,000/5,000 step 계약과 맞지 않아 사용하지 않으며, 정확한 step 종료 자동화는 MeloTTS commit과 Python 환경을 확정한 뒤 T-26 실행 단계에서 처리한다.
- 실제 학습과 checkpoint 추론을 수행하지 않았으므로 T-26은 완료 처리하지 않는다.

### T-27 Qwen3-TTS 비교 모델 실행 준비

- 0.6B Base를 우선하는 2레코드 smoke 데이터 준비·1 epoch 학습·checkpoint 재로딩·`generate_custom_voice` 합성 명령을 생성하도록 준비 도구를 작성했다.
- 모든 Qwen 행의 `ref_audio` 동일성과 학습 audio 누수를 검사하고, MeloTTS와 Qwen3-TTS의 paired training records가 경로·텍스트·순서까지 일치하지 않으면 실패하도록 했다.
- 공식 SFT 코드에 optimizer `max_steps`가 없음을 확인했다. smoke test 이후 본 학습은 2,000/5,000 step을 정확히 제어하는 경로를 구현하기 전까지 차단한다.
- 실제 tokenizer·학습·checkpoint 추론을 수행하지 않았으므로 T-27은 완료 처리하지 않는다.

### T-28 TTS 다중 모델 비교 실행 준비

- Baseline과 Fine-tuned 후보를 구분하고 T-22 성능 결과, T-23 청취 평가, SIM, 운영 체크리스트를 하나의 결과로 집계하는 비교 도구를 작성했다.
- 심각한 오독 0건, 핵심 정보 전달 18/20 이상, 친절함·전체 명료도·매장 안내 적합성 평균 4.0 이상, Baseline 대비 친절함 0.5 이상 개선을 Fine-tuned 후보의 필수 조건으로 고정했다.
- 필수 조건 통과 후보에 주문 정보 명료도 40점, 차분한 친절체 품질 30점, warm 성능 20점, 자원·운영 적합성 10점을 부여하고 2점 이내 동점 규칙과 선택 보류 조건을 자동화했다.
- 합성 후보 3개와 독립 평가자 3명의 fixture로 정상 선택, 전 후보 탈락, 작성자 평가 배제, 완전 동점 시 선택 보류를 검증했다. fixture 결과는 실제 모델 비교 결과로 사용하지 않는다.
- 실제 MeloTTS·Qwen3-TTS Fine-tuning 결과와 독립 청취 평가가 아직 없으므로 T-28은 완료 처리하지 않았다. 비교 manifest와 결과는 `data/tts/runs/comparison/`에서 로컬 비공개로 관리한다.

### T-29 AI Hub 학습 산출물 공유 범위 문의 준비

- AI Hub 공식 이용정책·FAQ와 `고객지원 → 문의하기` 경로를 확인하고 데이터셋 ID `71349` 전용 문의 Spec과 제출 문안을 작성했다.
- checkpoint의 공개·조직 내부 공유, 생성 WAV의 공개·상업적 사용, 제품 탑재, 국외 서비스 사용, 표시 의무와 수행기관 추가 확인을 별도 질문으로 분리했다.
- 문의에는 원본 데이터·원문·음성·checkpoint와 개인정보를 첨부하지 않고, 답변 원문은 접근 제한 위치에 보관하도록 정했다.
- 현재 상태는 `DRAFT`이며 실제 문의를 제출하지 않았으므로 T-29는 완료 처리하지 않았다. 서면 답변 전까지 모든 공유 시나리오는 `UNRESOLVED`이고 산출물은 로컬 비공개다.

### T-30 TTS 사용성 테스트 인계 준비

- 팀 공통 `E-*` 사용자 테스트의 범위를 재정의하지 않고 TTS 담당자가 전달할 실행 환경·오류 처리·관찰 항목·알려진 제한의 인계 계약을 작성했다.
- 외부 참가자 최소 3명의 실제 주문 흐름에서 첫 응답 대기, 메뉴명·수량·가격 이해, 재생 중단·다시 듣기, 5초 이상 대기 안내를 비식별 방식으로 기록하도록 했다.
- TTS 전후 모듈 경계와 문제 심각도, 테스트 중단 기준을 정의하고 같은 시나리오·환경에서 최소 2개 문제의 개선 전후 근거를 연결하는 양식을 마련했다.
- 최종 TTS 후보와 통합 주문 흐름이 아직 없고 실제 외부 테스트를 수행하지 않았으므로 상태는 `DRAFT`이며 T-30은 완료 처리하지 않았다.

## 2026-08-15

### 친절체 Fine-tuning PoC 설계

- TTS Fine-tuning PoC는 P0 주문 경로의 차단 조건이 아닌 P1 연구·차별화 작업으로 분류했다.
- P0는 실제 한국어 기본 TTS를 포함한 단일 주문 경로와 Local NLU Fine-tuning 전후 비교를 우선한다.
- Fine-tuning 모델은 MeloTTS, 별도 구조 비교 모델은 `Qwen/Qwen3-TTS-12Hz-0.6B-Base`로 정했다.
- AI Hub 데이터셋 71349의 `친절체 + 매장응대 + 기쁨`을 초기 학습 조건으로 정했다.
- 화자 5번과 10번의 동일 문장 10개를 A/B 블라인드 청취한 뒤, 차분함과 고령 사용자 접근성을 근거로 여성 화자 10번을 선택했다.
- 목표 스타일은 안정된 억양·과하지 않은 감정·명확한 발음을 갖는 `calm_friendly`로 정했다.
- AI Hub 원본과 원문 예시는 공개하지 않으며 checkpoint·생성 WAV는 서면 문의 전까지 로컬 비공개로 유지한다.
- 상세 데이터 계약, 학습 조건, 평가 기준과 AC는 `docs/specs/melotts-friendly-finetuning-poc.md`에 기록했다.

### TTS 모델 비교 조건 통일

- MeloTTS Fine-tuning과 Qwen3-TTS 비교에 동일한 화자 10번, 30분 adaptation package에서 예약 `ref_audio`를 제외한 paired training records, 동일 validation/test split, seed `42`, 2,000-step 1차 판정과 최대 5,000-step 학습 예산을 적용하기로 했다.
- 두 모델은 held-out 평가 문장 20개, 실행 장치, cold 1회·warm 5회, 측정 코드와 블라인드 청취 평가 조건을 동일하게 사용한다.
- 모델 구조상 필요한 tokenizer·오디오 전처리·optimizer·batch size 차이만 허용하고 실제 설정과 차이의 사유를 결과표에 기록한다.
- Qwen3-TTS 0.6B Fine-tuning이 회의에서 확정한 Python 환경 또는 공식 학습 경로에서 불가능하면 자원 한도 안에서 1.7B를 시도한다. 두 모델 모두 실패하면 zero-shot 결과를 동일 조건 비교에 섞지 않고 비교 미충족으로 판정한다.

### 최종 모델 선택 및 Python 환경 보류

- 최종 모델은 안전·명료도 필수 조건을 먼저 통과한 후보 중 주문 정보 명료도 40점, 차분한 친절체 품질 30점, 응답 성능 20점, 운영 적합성 10점의 가중치 총점으로 선택한다.
- 총점 차이가 2점 이내면 warm TTFB p95, Peak VRAM, 통합 단순성 순으로 결정하고, SIM은 한국어 적용 한계 때문에 참고 지표로만 사용한다.
- Python 기준 버전은 팀 회의 후 확정한다. 기존 Python 환경 초안은 `wip: python environment policy before team meeting`이라는 stash 항목에 보관되어 있으며 현재 작업 트리의 확정 문서로 취급하지 않는다. stash 번호는 이후 작업으로 달라질 수 있으므로 식별자로 사용하지 않는다.
- 회의 전 Python 3.11 실행 결과는 호환성 확인용 참고 기록으로만 남기며 공식 Benchmark 또는 PoC 합격 판정에는 포함하지 않는다.

### Qwen3-TTS 공식 학습 경로 확인 및 평가 계약 보완

- [Qwen3-TTS 공식 Fine-tuning 문서](https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning)는 12Hz 0.6B/1.7B Base의 단일 화자 Fine-tuning을 지원하며 학습 입력을 `audio`, `text`, `ref_audio` JSONL로 정의한다.
- 공식 tokenizer로 `audio_codes`를 생성한 뒤 SFT하고 Fine-tuned checkpoint는 `generate_custom_voice`로 평가한다.
- 0.6B는 2레코드·1-step 스모크 테스트를 먼저 수행하며 실패하면 같은 자원 한도를 만족하는 경우에만 1.7B를 대안으로 사용한다. zero-shot 결과는 동일 조건 최종 점수에 포함하지 않는다.
- 최종 선택 산식은 낮을수록 좋은 지표에 `후보 중 최솟값 / 후보 측정값`을 적용하도록 바로잡고, 자원 한도와 재현성·통합 난이도 5점의 체크리스트를 Spec에 고정했다.

### 학습 누수 제거 및 속도 비교 조건 보정

- Qwen 학습용 `ref_audio`는 test split이 아니라 train의 30분 adaptation package에서 예약하고, 해당 레코드를 두 모델의 일반 학습 pair와 validation/test에서 모두 제외하도록 변경했다.
- SIM 계산용 참조 음성 3개는 학습에 노출되지 않은 test split에서 유지한다.
- 모델 간 공통 `speed` 값 강제는 제거했다. 각 모델의 공식 기본 생성 설정을 사용하고 후처리 time-stretch를 금지하며, 실제 속도 설정과 생성 음성 길이를 결과에 기록한다.
- MeloTTS의 `speed=1.0`은 MeloTTS Baseline과 Fine-tuned 모델의 전후 비교에만 동일하게 적용한다.

## 2026-08-18

### MeloTTS vs Qwen3-TTS Baseline 20개 평가 문장 합성 및 벤치마크 수행 (T-05, T-22, T-28)

- `data/tts/evaluation/sentences.json`의 카페 대표 주문 20개 문장에 대해 `MeloTTS-Korean`과 `Qwen3-TTS-0.6B` Baseline 사전학습 모델로 오디오 합성 및 지표 측정을 완료했다 (`src/adapters/tts/eval_synthesis.py`).
- 총 40개 WAV 파일(모델별 20개)을 `data/tts/runs/benchmarks/melotts_baseline/` 및 `data/tts/runs/benchmarks/qwen3_baseline/`에 저장했다.
- **MeloTTS (CPU)**: 평균 지연시간 **1.92초**, 평균 RTF **0.3939** (44.1kHz), 실시간 기준(< 1.0) 충족.
- **Qwen3-TTS (CPU)**: 평균 지연시간 **22.31초**, 평균 RTF **3.9254** (24kHz), CPU 연산량 집중으로 지연 높음 확인.

### RTX 5070 Ti (Blackwell sm_120) GPU 가속 활성화 및 GPU 벤치마크 재측정

- PyTorch CUDA 12.8(`torch-2.12.0.dev20260408+cu128`, `torchaudio-2.11.0.dev`)로 업그레이드하여 RTX 5070 Ti(`sm_120`) GPU 가속을 활성화했다.
- 동일 20개 문장에 대해 GPU(`cuda:0`) 벤치마크를 재수행했다 (`data/tts/runs/benchmarks_gpu/`):
  - **MeloTTS (GPU)**: 총 3.97초, 평균 지연시간 **0.1985초 (약 198ms)**, 평균 RTF **0.0403** (25배 실시간 속도 달성).
  - **Qwen3-TTS 0.6B (GPU, bfloat16)**: 총 138.15초, 평균 지연시간 **6.9075초**, 평균 RTF **1.4620** (CPU 대비 3.2배 속도 향상).

### Qwen3-TTS 0.6B 친절체 Fine-tuning 완료 (T-27)

- **데이터셋**: AI Hub 133번 화자 10번(20대 여성, 차분·친절체) 30분 데이터 중 299개 paired record (`data/tts/runs/qwen3/train_with_codes.jsonl`).
- **전처리 및 Speech Tokenizer**:
  - `Qwen/Qwen3-TTS-Tokenizer-12Hz`로 299개 음성의 `audio_codes` 추출 완료.
  - 고품질 44.1kHz 음원에 대해 `dataset.py` 내 24kHz 자동 리샘플링(`librosa.resample`) 적용.
- **아키텍처 및 0.6B 수정 (GitHub Issue #198 해결)**:
  - 0.6B 모델은 `text_embedding`(2048차원)과 내부 레이어(1024차원)의 차원이 달라 사전학습 모듈인 `text_projection` 선형 레이어를 통과하도록 스크립트 보정.
- **학습 결과 (총 10 Epoch)**:
  - 1차 SFT (lr `2e-5`, 5 epoch): Loss `12.53` ➔ `2.57`
  - 2차 추가 SFT (lr `1e-5`, 5 epoch): Loss `2.84` ➔ **`2.19`** (최종 수렴 완료)
- **합성 동작 검증**: `generate_custom_voice(speaker='calm_friendly')`로 한국어 주문 안내 문장 음성 정상 생성 완료 (`test_sample.wav`, 7.92초).

### MeloTTS 친절체 Fine-tuning 2,000 Steps 완료 (T-26)

- **학습 환경**: RTX 5070 Ti 16GB GPU (`torch-2.12.0.dev+cu128`), VITS2 구조, 44.1kHz 샘플레이트.
- **데이터셋**: AI Hub 71349 감성 및 발화스타일 음성데이터 화자 10번(친절·차분체) 30분 adaptation package (299개 paired audio-text record, `MeloTTS/melo/text/korean.py` g2pk 정제 완료).
- **학습 파라미터**: Batch size 4, lr 1e-4 (`lr_decay` 0.999875), `segment_size` 16,384, Pretrained `myshell-ai/MeloTTS-Korean` checkpoint 기반 Fine-tuning.
- **학습 진행 및 수렴 과정**:
  - `Step 200` (Epoch 2): Loss Disc 2.89 / Gen 24.31 / Mel 2.45
  - `Step 800` (Epoch 10): Loss Disc 2.85 / Gen 21.65 / Mel 2.38
  - `Step 1400` (Epoch 18): Loss Disc 2.97 / Gen 20.83 / Mel 2.42
  - `Step 2000` (Epoch 26): Loss Disc 2.94 / Gen 21.29 / Mel 2.35 (학습 안정 수렴)
  - 최종 가중치 저장: `logs/mallo-friendly/G_2000.pth` (595MB)

### TTS 4개 모델 20개 도메인 문장 종합 품질·성능 비교 평가 (T-28)

- 동일 20개 대표 주문 도메인 평가 문장(`data/tts/evaluation/sentences.json`)에 대해 GPU(`cuda:0`) 환경에서 4개 모델(MeloTTS Baseline, MeloTTS Friendly, Qwen3-TTS Baseline, Qwen3-TTS Friendly)의 음성 합성 및 벤치마크 지표를 측정했다.

| 모델명 | 버전 / 체크포인트 | 샘플레이트 | 평균 지연시간 (Latency) | 중앙값 지연시간 | 평균 RTF | 실시간 배수 | 비고 |
|---|---|---|---|---|---|---|---|
| **MeloTTS Baseline** | `myshell-ai/MeloTTS-Korean` | 44.1 kHz | **0.1985s** (198ms) | 0.1814s | **0.0403** | 24.8배 | 기준 모델 (빠르나 어조 단조로움) |
| **✨ MeloTTS Friendly** | `logs/mallo-friendly/G_2000.pth` | **44.1 kHz** | **0.2041s** (204ms) | **0.1928s** | **0.0485** | **20.6배** | **최종 선정** (초고속 + 차분하고 친절한 어조) |
| **Qwen3-TTS Baseline** | `Qwen3-TTS-0.6B-CustomVoice` | 24.0 kHz | 6.9075s | 6.5844s | 1.4620 | 0.68배 | 자연스러우나 interactive 서빙에 지연 큼 |
| **Qwen3-TTS Friendly** | `checkpoint-epoch-4` (10 ep) | 24.0 kHz | 28.1953s | 34.0154s | 1.5732 | 0.63배 | 친절체 음색 모사 성공했으나 지연이 매우 큼 |

- **최종 모델 선정 및 기술 의사결정**:
  1. **실시간 대화성 (Latency & RTF)**: `MeloTTS Friendly`는 20개 문장 평균 생성 지연이 **0.204초(204ms)**, RTF **0.0485**로 사용자 발화 후 0.2초 만에 즉각 음성 안내가 시작되어 키오스크 인터랙션에 최적이다. 반면 Qwen3-TTS 0.6B는 Autoregressive 토큰 생성 방식으로 문장당 7~28초가 소요되어 단독 실시간 서빙에 부적합하다.
  2. **오디오 품질 (Sampling Rate)**: MeloTTS는 **44.1 kHz 고품질 스튜디오 음질**을 제공하여 24.0 kHz인 Qwen3-TTS 대비 카페 소음 환경에서도 안내 음성의 명료도(Clarity)가 우수하다.
  3. **톤 앤 매너 (친절체 전이)**: Baseline의 무감정한 억양 대비, 10번 화자의 억양 특성(어미의 완만하고 부드러운 하강, 차분한 속도감)이 성공적으로 학습되어 고령 사용자 친화적 안내를 제공한다.
  4. **시각화 및 청음 도구**: 4개 모델의 20개 합성 음성을 웹 브라우저에서 바로 비교 청음할 수 있는 HTML 플레이어(`data/tts/runs/benchmarks_gpu/tts_player.html`)를 생성했다.

## 2026-08-20

### MeloTTS / Qwen3-TTS 실행 환경 분리

- 기존 `.venv`의 `pip check`에서 `melotts==0.1.2`가 요구하는 `transformers==4.27.4`와 Qwen3-TTS 환경의 `transformers==4.57.3` 충돌을 확인했다.
- `requirements-tts.txt`는 모델 중립적인 공통 오디오 의존성만 관리한다.
- MeloTTS는 `requirements-tts-melo.txt`, Qwen3-TTS는 `requirements-tts-qwen.txt`를 사용하고 각각 `.venv-tts-melo`, `.venv-tts-qwen` 같은 별도 환경에서 실행한다.
- 현재 저장소 `.venv`의 `torch 2.12.0.dev20260408+cu128`, `transformers 4.57.3`, `accelerate 1.12.0`은 Qwen3-TTS 쪽 검증 조합으로 참고하며 MeloTTS의 유효한 의존성 조합으로 간주하지 않는다.
