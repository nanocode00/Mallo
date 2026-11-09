# 말로(Mallo) 저장소 및 로컬 자산 마이그레이션 실행 기록 (Migration Log)

- **작업 일시**: 2026-08-27
- **수행 기준 문서**: `docs/repository-cleanup-audit.md`
- **수행 브랜치**: `chore/repository-cleanup`
- **수행 원칙**: 
  - 기능 추가 금지
  - README 개편 및 scripts 구조 변경 보류
  - "이동 → 경로 수정 → 실행 검증 → 삭제" 원칙 준수
  - UNKNOWN 및 외부 백업 보존
  - 하위 호환을 위한 영구 symlink 지양, canonical path 전용 단일화

---

## 1. 이동 및 재배치 자산 (Moved & Reorganized Assets)

### 1-1. FINAL_RUNTIME 모델 복사 및 표준화
| 영역 | 자산명 | 원본 위치 | 새 표준 위치 (Canonical Path) | 크기 | SHA256 체크섬 일치 여부 |
|---|---|---|---|---|---|
| STT | Whisper-Medium Train65 Merged BF16 | `src/adapters/stt/models/whisper-medium-qlora-train65-v1-lr2e-5-ep2-merged-bf16/` | `models/stt/final-train65-merged-bf16/` | 1.52 GB | `c0e432a4323d0303...` (100% 일치) |
| NLU | Qwen3-0.6B Overnight Merged BF16 | `models/nlu/qwen3-0.6b-sweeps/honorbear-20260825-021532-qwen3-0p6b-overnight/epochs4_seed7/merged-bf16/` | `models/nlu/final-qwen06b-merged-bf16/` | 1.19 GB | `2d72ee3dde4546a3...` (100% 일치) |
| TTS | MeloTTS Korean Friendly Step 2800 가중치 | `logs/mallo-friendly/G_2800.pth` | `models/tts/mallo-friendly/G_2800.pth` | 595 MB | `858d23f61e724167...` (100% 일치) |
| TTS | MeloTTS 모델 아키텍처 설정 | `logs/mallo-friendly/config.json` | `models/tts/mallo-friendly/config.json` | 4.1 KB | 동일 |

### 1-2. AIHub Raw 대용량 데이터(207GB)의 repo 내부 data/ 구조 통일
외부 임시 경로를 거쳐 최종적으로 프로젝트 저장소 내의 표준 `.gitignore` 데이터 구조로 배치 완료:
- **STT 원본 음성 (170GB, 107, 71517, 71558, 94)**:
  - 최종 위치: `data/stt/raw/`
  - `.gitignore` 등록: `data/stt/raw/`
- **TTS 원본 음성 (37GB, '133.감성 및 발화 스타일 동시 고려 음성합성 데이터')**:
  - 최종 위치: `data/tts/raw/aihub/`
  - `.gitignore` 등록: `data/tts/raw/`
- **외부 임시 디렉터리(`/home/honorbear/AI_Human_7th/_local_data`)**: 완전 회수 및 삭제.
- **임시 Symlink**: `src/adapters/stt/stt_data/raw`, `data/tts/aihub` 심링크 완전 제거(영구 심링크 유지 지양).

### 1-3. 데이터/실험 모델 아카이브 및 산출물 분리
- **STT 데이터 분리**:
  - `src/adapters/stt/stt_data/train65_v1` (7.7GB) → `data/stt/processed/train65_v1`
  - `src/adapters/stt/stt_data/heldout` (285MB) → `data/stt/heldout`
  - `src/adapters/stt/stt_data/external` (436MB) → `data/stt/external`
  - `src/adapters/stt/stt_data/reproduction` (522MB) → `data/stt/reproduction`
  - `src/adapters/stt/stt_data/audit` (146MB) → `data/stt/audit`
- **STT 실험 모델 아카이브**:
  - `models/stt/adapters/whisper-medium-qlora-train65-v1-lr2e-5-ep2` (Top-1 QLoRA 어댑터)
  - `models/stt/archive/team_handoff` (이전 도메인 롤백 모델)
  - `models/stt/archive/whisper-medium-train65-v1-merged-bf16`
  - `models/stt/archive/whisper-onnx` (ONNX INT8 모델)
  - `models/stt/archive/whisper-medium-train65-golden-v1` (UNKNOWN 보존)
  - `models/stt/archive/` (golden500-hpf, speaker-split, kiosk-test, whisper-medium-qlora)
- **로그 및 산출물 아티팩트화**:
  - `logs/qa-*.jsonl` (11개 실마이크 QA 로그) → `artifacts/pipeline/qa-logs/`
  - `logs/nlu-*.log` (야간 스윕 및 집중 벤치마크 로그) → `artifacts/nlu/training-logs/`
  - 구버전 standalone HTML, `raw/`, `private-site/` (235MB) → `artifacts/showcase/legacy/tts/`

---

## 2. 변경된 코드 및 하드코딩 경로 (Code Path Updates)

모든 production/runtime 코드가 canonical path만 참조하도록 단일화되었습니다:
1. **`.env.example`**:
   - `MALLO_STT_MODEL_PATH=models/stt/final-train65-merged-bf16`
   - `MALLO_NLU_MODEL_PATH=models/nlu/final-qwen06b-merged-bf16`
   - `MALLO_TTS_MODEL_DIR=models/tts/mallo-friendly`
2. **`src/config/settings.py`**:
   - STT, NLU, TTS 모델 기본 경로를 `PROJECT_ROOT / "models"/...` 기준으로 일원화 및 fallback 제거.
3. **`src/adapters/stt/whisper_medium.py`**:
   - `DEFAULT_TRAIN65_MERGED_PATH`: `models/stt/final-train65-merged-bf16`
   - `DEFAULT_QLORA_MERGED_PATH`: `models/stt/archive/team-handoff-domain/merged-bf16`
4. **`src/adapters/nlu/qwen06b_nlu.py`**:
   - `DEFAULT_SERVICE_MERGED_MODEL`: `models/nlu/final-qwen06b-merged-bf16` (개인명/타임스탬프 하드코딩 완전 제거)
5. **`scripts/run_mallo_server.py`**:
   - `DEFAULT_NLU_MODEL`: `models/nlu/final-qwen06b-merged-bf16`
   - `DEFAULT_TTS_CHECKPOINT`: `models/tts/mallo-friendly/G_2800.pth`
   - `DEFAULT_TTS_CONFIG`: `models/tts/mallo-friendly/config.json`
   - `start_child`: 자식 프로세스 환경에 `PYTHONPATH=src`를 자동 주입하여 gateway 모듈 로드 보장.
6. **`scripts/tts_sidecar_server.py` & `scripts/stt_sidecar_server.py`**:
   - STT: `--model` 인자 지원 및 canonical 모델 기본값 지정.
   - TTS: 기본 체크포인트를 `models/tts/mallo-friendly/G_2800.pth`, 설정을 `config.json`으로 단일화.
7. **`src/adapters/stt/common.py`**:
   - `DATA_ROOT`, `PREPROCESSED_DIR`, `SPLITS_DIR`, `MODELS_DIR`을 `data/stt/` 및 `models/stt/`로 갱신.
8. **유틸리티 스크립트 단일화**:
   - `src/adapters/tts/eval_synthesis.py`: `models/tts/mallo-friendly/G_2800.pth` 우선 탐색.
   - `scripts/benchmark_stt_candidates.py`: `models/stt`, `data/stt/heldout/` 참조로 변경.
   - `scripts/run_nlu_three_candidate_focus.py`: `DEFAULT_06_MERGED`를 `models/nlu/final-qwen06b-merged-bf16`으로 변경.
   - `scripts/generate_adaptive_levels_player.py`, `generate_adaptive_levels_player_v2.py`, `measure_real_e2e_latency.py`, `melo_quality_enhancement.py`, `convert_stt_ct2.py`, `src/app/server.py`: canonical 경로로 일괄 갱신.

---

## 3. 테스트 및 실행 검증 결과 (Verification Results)

1. **모델 경로 resolve 검증**:
   - STT (`models/stt/final-train65-merged-bf16`): `Exists: True`
   - NLU (`models/nlu/final-qwen06b-merged-bf16`): `Exists: True`
   - TTS (`models/tts/mallo-friendly/G_2800.pth`, `config.json`): `Exists: True`
2. **서버 통합 기동 및 Warmup (`python scripts/run_mallo_server.py --tunnel none`)**:
   - STT Sidecar (8001): `models/stt/final-train65-merged-bf16` 로드 및 warmup 완료 (13.1s)
   - NLU Sidecar (8002): `models/nlu/final-qwen06b-merged-bf16` 로드 및 warmup 완료 (3.0s)
   - TTS Sidecar (8003): `models/tts/mallo-friendly/G_2800.pth` 로드 및 warmup 완료
   - Gateway (8000): 헬스체크 `{"status": "ready", "stt": "ready", "nlu": "ready", "tts": "ready", "warmed": true}` 확인.
3. **주문 파이프라인 Smoke Test**:
   - NLU (`POST :8002/parse`): "아이스 카페라떼 두 잔 주세요" → `ADD_ITEM(cafe_latte, qty=2, temp=iced)` 100% 정상 파싱.
   - TTS (`POST :8003/synthesize`): "주문이 완료되었습니다." → **142ms** 초저지연 오디오 합성 완료.
   - Gateway 주문 (`POST :8000/api/order`): "따뜻한 아메리카노 한 잔 주세요" → 4,700원 장바구니 갱신 및 응답 완료.
4. **단위 테스트**:
   - `pytest tests/unit/...`: **114 passed in 6.18s** (100% 통과).

---

## 4. 삭제한 항목 및 확보 용량 (Deleted Items & Freed Space)

### 4-1. 검증 완료된 Legacy Runtime 중복본 삭제 (2차 정리)
| 삭제 자산 | 삭제 위치 | 크기 | 사유 |
|---|---|---|---|
| STT Legacy 머지 모델 | `src/adapters/stt/models/whisper-medium-qlora-train65-v1-lr2e-5-ep2-merged-bf16` | 1.52 GB | `models/stt/final-train65-merged-bf16`과 SHA256 일치 확인 후 제거 |
| NLU Legacy 머지 모델 | `models/nlu/qwen3-0.6b-sweeps/.../epochs4_seed7/merged-bf16` | 1.19 GB | `models/nlu/final-qwen06b-merged-bf16`과 SHA256 일치 확인 후 제거 |
| TTS Legacy 가중치 | `logs/mallo-friendly/G_2800.pth` | 595 MB | `models/tts/mallo-friendly/G_2800.pth`와 SHA256 일치 확인 후 제거 |
| TTS Legacy 설정 | `logs/mallo-friendly/config.json` | 4.1 KB | `models/tts/mallo-friendly/config.json` 일치 확인 후 제거 |
| STT Legacy 전처리 데이터 잔여 | `src/adapters/stt/stt_data/` | ~8.5 GB | `data/stt/`로 완전 복사 및 검증 후 제거 |
| **중복본 삭제 소계** | | **~11.8 GB** | |

### 4-2. 1차 확정 DELETE_CANDIDATE 삭제 (1차 정리)
- STT 중복 모델(`fast-exp`, 1.5GB) 및 중복 zip 2종(2.4GB)
- STT 임시 스모크 모델 3종 및 백업(225MB)
- 폐기된 Qwen3-TTS 전체 체크포인트(28.5GB)
- MeloTTS 손상 실행본(5.1GB) 및 추론 불필요 가중치(D_*, DUR_*, G_0, 2.2GB)
- NLU 비정상 중단 실행본 2종(2.4GB)
- 임시 잔여 파일(`scratch/*`, `decoded_*.wav` 9개, `:memory:.ses`, 324MB)
- **1차 삭제 소계**: **39.0 GB**

**총 누적 확보 용량**: **약 50.8 GB**

---

## 5. 삭제하지 않은 항목과 보존 이유 (Preserved Assets)

1. **외부 Git Worktree (`/home/honorbear/AI_Human_7th/worktrees/proj1d-stt-transcript-web-ux`, 11MB)**:
   - **사유**: UNKNOWN. 타 작업자 미반영 작업 가능성으로 임의 삭제 금지 원칙 준수.
2. **STT Golden v1 모델 (`models/stt/archive/whisper-medium-train65-golden-v1`, 30MB)**:
   - **사유**: UNKNOWN. Golden 350샘플 1에폭 단독 학습 모델로서 연구/비교 가치로 보존.
3. **외부 인계 패키지 (`/home/honorbear/mallo-model-handoff*`, ~3.86GB)**:
   - **사유**: 팀 간 공식 공유 배포판이자 최종 백업 안전망.
4. **NLU Overnight Sweep 15종 어댑터 및 학습 로그 (`models/nlu/qwen3-0.6b-sweeps/`, 약 17.4GB)**:
   - **사유**: EXPERIMENT_ARCHIVE. 머지본만 삭제하고 어댑터 및 `trainer_state.json` 등 연구 증빙 보존.
5. **MeloTTS Steps 3000~3600 (`logs/mallo-friendly/G_*.pth`, 2.38GB)**:
   - **사유**: EXPERIMENT_ARCHIVE. 2800 스텝과의 오버피팅/음질 비교 분석 증빙 보존.
6. **STT 아카이브 모델들 (team_handoff, onnx, golden500-hpf, speaker-split 등 약 10GB)**:
   - **사유**: EXPERIMENT_ARCHIVE. 재현성 및 롤백 대비 보존.
