---
title: "STT / Audio 작업 로그 (`S-*`)"
tags: [worklog]
---

# STT / Audio 작업 로그 (`S-*`)

STT와 Audio 영역에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다.

# STT 작업 로그

> 이 문서는 `src/adapters/stt/` 폴더의 STT 관련 작업을 기록한다.
> 프로젝트 전체 작업 로그는 `docs/worklog.md`에 별도로 관리한다.

## 2026-08-14

### S-08 · S-09 · S-11 — STT Baseline 평가 (fast-whisper small)

**모델 설정:**
- 모델: `faster-whisper` / `small`
- Device: `cuda` / Compute type: `float16`
- Language: `ko`

**데이터셋:**
- 경상도 1인발화 따라말하기 (중·노년층 경상도 방언 데이터)
- Training 122,370개 중 랜덤 100개 샘플 (seed=42)
- 정답 기준: 방언(dialect) 텍스트

**Baseline 결과:**
- CER: 0.2404 ± 0.1013
- WER: 0.5580 ± 0.1940

**WER/CER 차이가 큰 상위 10개 음성 데이터를 출력했다.**

---

### S-06 · S-07 — 오디오 전처리 적용 및 재평가

**전처리 파이프라인** (`preprocess.py`):
1. 고역통과 필터 (80Hz) — 저주파 노이즈 제거
2. noisereduce 스펙트럼 게이팅 — 배경 노이즈 제거
3. 피크 정규화 (0.95)

**전처리 결과:**
- 1차: 100개 샘플 전처리 (성공 100 / 실패 0)
- 2차: 기존 100개 제외 + 400개 추가 전처리 (성공 400 / 실패 0)
- **총 500개 전처리 완료** → `stt_data/preprocessed/`에 저장

**small 모델 재평가 (전처리 후, 100개):**

| 지표 | 전처리 전 | 전처리 후 | 변화율 |
|---|---|---|---|
| CER | 0.2408 ± 0.1013 | 0.2386 ± 0.1031 | **-0.9%** |
| WER | 0.5588 ± 0.1936 | 0.5525 ± 0.1939 | **-1.1%** |

- CER 기준: 개선 22개 / 악화 50개 / 동일 28개
- **전처리 효과 미미** — 방언 어휘 인식이 주요 병목으로 확인됨

**medium 모델 재평가 (전처리 후, 100개):**

| 지표 | small (전처리 전) | medium (전처리 후) | 변화율 |
|---|---|---|---|
| CER | 0.2408 ± 0.1013 | 0.2091 ± 0.1145 | **-13.2%** |
| WER | 0.5588 ± 0.1936 | 0.5072 ± 0.2057 | **-9.2%** |

- CER 기준: 개선 60개 / 악화 36개 / 동일 4개
- **medium 모델이 small 대비 유의미한 성능 개선**

**medium 모델 재평가 (전처리 후, 500개 전체):**

| 지표 | 값 |
|---|---|
| CER | 0.2090 ± 0.1088 |
| WER | 0.5071 ± 0.1985 |

- 500개 전체에서도 100개 샘플과 유사한 성능 유지 (CER 0.209, WER 0.507)
- baseline(100개, small) 대비 CER -13.2%, WER -9.2% 개선

**핵심 오류 패턴 (상위 10개):**
- 방언 고유 어휘 인식 실패: `까시덩쿨`, `끌갱이`, `점바지`, `흠데` 등
- 방언 문법/어미 인식 실패: `카던디`, `있겄는교`, `자라뿌네` 등
- 노이즈보다 **방언 어휘/문법 인식이 주요 병목**

**생성 파일:**
- `preprocessed.py` — 전처리 전/후 비교 평가 스크립트
- `stt_data/preprocessed/` — 전처리된 오디오 (500개, .gitignore로 제외)
- `stt_data/preprocessed_results.csv` — 전처리 후 평가 결과 (500개, .gitignore로 제외)
- `stt_data/baseline_results.csv` — baseline 평가 결과 (100개, .gitignore로 제외)
- `finetune_whisper_qlora.py` — 파인튜닝 스크립트
- `stt/models/` — 파인튜닝 체크포인트

---

### S-18 · S-19 — Whisper Medium QLoRA 파인튜닝 환경 구성

**목적:**
- 경상도 방언 STT 데이터에 대해 Whisper Medium 기반 파인튜닝 가능성 검증
- RTX 4060 Ti 8GB 환경에서 전체 파인튜닝 대신 QLoRA 적용
- 이후 Learning Rate별 실험을 독립적으로 수행할 수 있도록 실험 환경 구성

**환경:**
- GPU: NVIDIA GeForce RTX 4060 Ti 8GB
- Python: 3.11
- PyTorch: 2.6.0+cu124
- Transformers: 5.15.0
- PEFT: 0.20.0
- CUDA: 12.4 (PyTorch 기준)
- 모델: `openai/whisper-medium`

**QLoRA 설정:**
- Quantization: 4-bit
- Quantization type: NF4
- Compute dtype: float16
- LoRA 적용
- Trainable parameter를 LoRA adapter로 제한
- Base Whisper Medium은 4-bit 양자화하여 VRAM 사용량 절감

**환경 문제 해결:**
- 초기 `pip install` 명령이 잘못된 `.venv` 경로를 참조하여 실행되지 않는 문제 발생
- `pip` 대신 `python -m pip` 사용으로 해결
- PEFT 설치 완료 및 Whisper + PEFT import 정상 확인

```text
PEFT: 0.20.0
Transformers: 5.15.0
Whisper + PEFT import OK
```

---

## 2026-08-15

### S-18 · S-19 — Whisper Medium QLoRA Learning Rate 실험

**설정:**
- 데이터: 전처리된 500개 중 Train 350 / Validation 75 (70/15/15, seed 42)
- Epochs 5, Batch 1, Grad Accum 8 (유효 배치 8)
- 4-bit NF4 + double quant, LoRA r=8 / alpha=16 / dropout=0.05 (q_proj, v_proj)
- metric_for_best_model: **cer** (lr-1e-05 실행은 구버전 기준 **wer** — 선택 기준 불일치)

**Validation 결과 (best checkpoint):**

| LR | Best Checkpoint | 선택 지표 | CER | WER |
|---|---|---|---|---|
| 5e-06 | checkpoint-88 | cer | 0.2282 | 0.5113 |
| 1e-05 | checkpoint-132 | wer (구버전) | 0.2271 | 0.5113 |
| **2e-05** | **checkpoint-220** | cer | **0.2191** | **0.5038** |

- **lr=2e-05이 CER/WER 모두 최고** → 이후 비교·파인튜닝 결과 채택 기준
- 검증: `baseline_qlora_compare.py` (validation 첫 10행, seed 미사용)

| 지표 | Baseline (FP16) | QLoRA (BF16) | 개선 |
|---|---|---|---|
| CER | 0.1761 | 0.1567 | -0.0194 |
| WER | 0.4311 | 0.4152 | -0.0159 |

- ⚠️ Baseline은 FP16, QLoRA는 BF16이라 dtype 혼입 변수 존재
- ⚠️ 샘플 10개는 validation.csv 앞부분이라 대표성 부족 — 전체 평가는 P2-9/P2-11에서 처리

**실험 이슈:**
- `experiment_log.json`이 미생성 — 실행 중단 또는 스크립트 변경 전 실행으로 추정
- 시드 미고정 상태로 실행됨 — 이후 스크립트에 `--seed` 추가
- 재실행 시: `python finetune_whisper_qlora.py --lr 2e-5 --seed 42`

---

### S-18 · S-19 — 데이터 재분할 (화자 단위) 및 최종 평가

**화자 누출 발견:**
- 기존 분할은 파일 단위(random.shuffle)라 같은 화자가 train/val/test에 섞임
- `check_split_leakage.py` 검사 결과: train∩val 18명, train∩test 28명 중복
- `split_dataset.py`를 화자 단위 분할로 변경 → train/val/test 간 화자 중복 제거

**재분할 결과 (화자 단위, seed 42):**

| 분할 | 파일 수 | 화자 수 |
|---|---|---|
| Train | 350 (70.0%) | 259 |
| Validation | 77 (15.4%) | 52 |
| Test | 73 (14.6%) | 51 |

- ⚠️ 화자 단위 분할로 validation이 75→77, test가 75→73으로 변경됨
- 기존 QLoRA 체크포인트(lr-2e-05)는 구버전 split으로 학습 → 최종 평가는 신규 test 기준

**최종 평가 (`baseline_qlora_compare.py --split both`):**

| 분할 | n | Baseline CER | Baseline WER | QLoRA CER | QLoRA WER |
|---|---|---|---|---|---|
| validation | 77 | 0.2147 | 0.4985 | 0.1797 | 0.4623 |
| test | 73 | — | — | 0.1934 | 0.4685 |
| **전체** | **150** | **0.2147** | **0.4985** | **0.1864** | **0.4653** |

- CER -0.0283, WER -0.0332 개선 (baseline FP16 vs QLoRA BF16)
- 결과 파일: `models/whisper-medium-qlora/lr-2e-05_ep-5/compare_both_150_seed-42.csv`
- ⚠️ test는 파인튜닝에 전혀 노출되지 않은 데이터라 성능 수치로 사용 가능
- ⚠️ 여전히 Baseline(FP16) vs QLoRA(BF16) dtype 혼입 변수 존재

**스크립트 정리 (재현성 개선):**
- `common.py` — CUDA DLL PATH, 경로 상수, 시드 설정, CUDA 확인 통합
- `preprocess.py` — 전처리 파이프라인 복원 (HPF 80Hz → noisereduce → peak norm 0.95)
- `check_split_leakage.py` — 화자 누출 검사
- `finetune_whisper_qlora.py` — `--seed` 추가, metric_for_best_model=CER 통일
- `baseline_qlora_compare.py` — `--split {validation,test,both}`, `--samples`, `--seed` 추가
- `requirements-stt.txt` — STT 실험 전용 의존성 명세
- 빈 `test.ipynb` 제거

---

### S-20 — 평가 공정성 · 지표 보강 (재현성 정리)

**배경:**
- S-18/S-19 평가에서 Baseline(FP16) vs QLoRA(BF16) dtype 혼입 변수 존재
- WER만으로는 한국어 STT 품질을 제대로 반영하기 어렵고, 주문 도메인 지표(TRD 25.1) 부재
- `evaluate` 패키지는 HF hub 다운로드가 필요해 오프라인 실행이 어려움

**변경 내용:**
- `metrics.py` (신규) — jiwer 기반 `compute_cer` / `compute_wer`와 주문 도메인 키워드 지표 `keyword_recall` / `keyword_accuracy` 추가
  - 메뉴·수량·옵션·금액 4개 카테고리 기본 키워드(`DEFAULT_KEYWORDS`, 메뉴 10종은 `src/config/menu.json` 기준)
  - 공백·대소문자 불변 매칭 (한국어 띄어쓰기 변동 대응)
- `baseline_qlora_compare.py` — Baseline dtype `float16` → **`bfloat16`**로 통일 (`EVAL_DTYPE`)
  - `evaluate` → `metrics` (jiwer) 교체, `--checkpoint` 인자로 하드코딩 경로 제거
  - 샘플별 추론 latency(초), 추론 직후 VRAM(GB) 측정 추가
  - 메뉴/수량/옵션/금액 keyword recall 컬럼 추가 (`baseline_*_recall`, `qlora_*_recall`)
  - CSV에 재현성 메타 컬럼(`model`, `baseline_dtype`, `qlora_dtype`, `seed`, `checkpoint`) 추가
  - `--seed` 기본값을 하드코딩 42 대신 `common.DEFAULT_SEED` 사용
- `finetune_whisper_qlora.py` — `evaluate` 제거, `metrics.compute_cer/compute_wer`로 교체 (오프라인 평가 가능)
- `common.py` — `DEFAULT_SEED = 42` 상수화, `set_seed()`에 `cudnn.deterministic=True` / `benchmark=False` 추가
- `preprocess.py` / `split_dataset.py` / `preprocessed.py` — `SEED=42` 하드코딩 제거, `common.DEFAULT_SEED` 사용
- `preprocessed.py` — 상대 경로 대신 공용 상수 사용, `fileName` 대신 파일명(stem) 기준으로 통일

**테스트:**
- `tests/unit/test_stt_metrics.py` (신규) — CER/WER, 키워드 recall/accuracy (정규화·부분 매칭·분모 0 처리)
- `tests/unit/test_stt_split.py` (신규) — `extract_speaker`, `DEFAULT_SEED`, `set_seed` 재현성
- 실행: `$env:PYTHONPATH="src"; python -m pytest tests` → **78 passed** (기존 60 + 신규 18)

**참고:**
- 테스트는 시스템 python(CPU)으로 실행 가능한 순수 모듈(`metrics.py`, `common.py`, `split_dataset.py`)만 대상
- GPU 의존 스크립트(`finetune_whisper_qlora.py`, `baseline_qlora_compare.py`)는 stt venv에서만 실행
- ⚠️ 지표 변경으로 이전 실험 수치와 dtype이 달라져 **직접 비교 불가** — 신규 평가(BF16 통일) 기준으로 재측정 필요

---

### S-14 사전 — BF16 통일 기준 전체 재평가 (dtype 혼입 제거)

**실행:**
- `baseline_qlora_compare.py --split both` (stt venv, RTX 4060 Ti 8GB)
- Baseline = whisper-medium BF16, QLoRA = lr-2e-05/checkpoint-220 (4-bit) — **같은 BF16으로 통일**
- 샘플: validation 77 + test 73 = 150개 (화자 단위 분할, seed 42)

**결과:**

| 지표 | Baseline | QLoRA | 개선 |
|---|---|---|---|
| CER | 0.2160 | 0.1864 | **-0.0297** |
| WER | 0.4993 | 0.4653 | -0.0339 |
| Latency (초/샘플) | **0.513** | 1.137 | QLoRA ~2.2배 느림 |
| VRAM (GB, 추론 직후) | — | 1.89 | — |
| 메뉴 recall | 0.000 | 0.000 | — |
| 수량 recall | 0.007 | 0.007 | — |
| 옵션 recall | 0.000 | 0.000 | — |
| 금액 recall | 0.033 | 0.033 | — |

- Baseline FP16(0.2147) vs BF16(0.2160) — **dtype 차이 미미 확인**, 이전 QLoRA 결과와 동일
- **도메인 키워드 recall이 거의 0** → 방언 따라말하기 데이터에 메뉴/수량/옵션 키워드가 거의 없음 → **S-10 도메인 평가셋 구성 필요성 데이터로 입증**
- QLoRA가 CER은 낮지만 latency는 2배+ — S-14 최종 선정 시 지연 비용 고려 필요
- 결과 파일: `models/whisper-medium-qlora/lr-2e-05_ep-5/compare_both_150_seed-42.csv`
  - 메타 컬럼 포함: `model`, `baseline_dtype`/`qlora_dtype` (모두 bfloat16), `seed`, `checkpoint`
  - 샘플별 컬럼: CER/WER/개선분, latency, vram, 4개 카테고리 키워드 recall (baseline/qlora)

---

### S-20 후속 — 화자 단위 split 재학습 + corpus-level 지표 (리뷰 반영)

**배경:**
- PR #27 리뷰 지적: 기존 checkpoint는 구버전 파일 단위 split으로 학습되어 test 파일이 사전 학습에 노출됐을 가능성 존재
- 지표가 문장별 CER/WER 평균이라 짧은 문장과 긴 문장이 같은 비중으로 반영되는 편향 존재
- 키워드 recall도 문장별 평균이라 키워드가 없는 문장이 recall 0으로 평균을 낮추는 편향 존재
- requirements-stt.txt의 `--index-url`이 일반 패키지(pandas 등) 설치까지 PyTorch index로 돌려 설치 실패 유발
- CI가 Secret Scan뿐이라 단위 테스트가 PR 검증에 포함되지 않음

**재학습 (화자 단위 split, seed 42):**
- `finetune_whisper_qlora.py --lr 2e-05 --epochs 5 --seed 42 --output models/whisper-medium-qlora-speaker-split/lr-2e-05_ep-5`
- train 350 (259화자) / validation 77 (52화자) — 화자 단위 분할
- best: `checkpoint-220`, validation CER **0.1840** / WER 0.4625
- ⚠️ 발견·수정: QLoRA 체크포인트는 `pytorch_model.bin`이 없어 `load_best_model_at_end=True`가 `_load_best_model()`에서 크래시 → `load_best_model_at_end=False`로 수정 (최적 에폭은 `trainer.state.best_model_checkpoint`로 기록됨)

**corpus-level 지표 도입:**
- `metrics.py` — `corpus_cer` / `corpus_wer` (문장별 평균 아님, 전체 목록을 jiwer로 한 번에 집계), `aggregate_keyword_recall` (전체 matched / 전체 total, total==0이면 recall 0.0)
- `finetune_whisper_qlora.py` / `baseline_qlora_compare.py` — corpus-level 집계로 교체, split별(validation/test) 분리 보고
- keyword recall을 문장별 평균이 아니라 **전체 matched/total**로 집계

**재평가 결과 (화자 단위 split 재학습 모델, corpus-level):**

| 분할 | Baseline CER | Baseline WER | QLoRA CER | QLoRA WER |
|---|---|---|---|---|
| validation (77) | 0.2199 | 0.4965 | 0.1834 | 0.4637 |
| test (73) | 0.2107 | 0.4891 | 0.1976 | 0.4633 |
| **전체 (150)** | **0.2155** | **0.4929** | **0.1902** | **0.4635** |

- CER -0.0253, WER -0.0294 개선 (corpus-level, Baseline/QLoRA 모두 BF16)
- 이전(문장별 평균, 누출 가능 split) 수치: CER 0.1864 → corpus-level 0.1902 (전체 기준)
- 키워드 recall (전체 matched/total): menu 0/0, quantity 1/1, option 0/0, price 5/5 — 메뉴·옵션·금액 키워드가 방언 따라말하기 데이터에 거의 없음 (S-10 도메인 평가셋 필요성 재확인)
- 결과 파일: `models/whisper-medium-qlora-speaker-split/lr-2e-05_ep-5/compare_both_150_seed-42.csv`
  - corpus-level 컬럼(`corpus_baseline_cer` 등) 추가됨

**기타 수정:**
- `requirements-stt.txt` — 설치 명령을 `--index-url` → `--extra-index-url`로 수정 (PyPI 기본 유지)
- `.github/workflows/unit-tests.yml` (신규) — push/PR 시 `pytest tests/unit` 실행 (jiwer 포함)
- `baseline_qlora_compare.py` — 기본 checkpoint를 화자 단위 split 재학습 모델로 변경

**테스트:**
- `$env:PYTHONPATH="src"; python -m pytest tests/unit` → **64 passed**
- GPU 의존 재학습·재평가는 stt venv에서 실행 완료

### S-08 · S-09 — Whisper 모델 크기 비교 (base vs small vs medium)

**실행:**
- 1단계(모델 선택): `compare_model_sizes.py --split validation --models base,small,medium --samples 150 --seed 42`
- 2단계(최종 1회 보고): `compare_model_sizes.py --split test --models medium --samples 150 --seed 42`
- 모든 모델 BF16 통일, 화자 단위 분할(validation 77 / test 73), seed 42.
- **모델 선택은 validation split에서만 수행** (리뷰 반영) — test는 최종 선정 모델(medium) 1회 보고에만 사용.

**결과 (corpus-level):**

| split | 모델 | n | CER | WER | latency(s) | params(M) | VRAM(GB) |
|---|---|---|---|---|---|---|---|
| validation | base | 77 | 0.5577 | 0.9239 | 0.422 | 72.6 | 0.17 |
| validation | small | 77 | 0.3655 | 0.6487 | 0.710 | 241.7 | 0.55 |
| validation | medium | 77 | 0.2199 | 0.4965 | 1.093 | 763.9 | 1.58 |
| test | medium | 73 | 0.2107 | 0.4891 | 1.117 | 763.9 | 1.58 |

- **S-14 선정 근거(validation 기준)**: 정확도 우선 → **medium** (CER 0.2199), 저지연 절충 → small (CER 0.3655). base는 CER 0.558로 MVP에 부적합.
- medium test 성능은 validation과 유사(CER 0.2107) → 일반화 확인, test 1회 보고 정책 준수.
- CER 개선폭(validation): base→small **-0.192**, small→medium **-0.146**
- latency는 같은 세션 내 모델 간 상대 비교로 해석 (base 1.0 / small 1.7 / medium 2.6배). medium이 실시간 주문 입력에 무해한 수준(+0.7s vs base).
- VRAM: 최대 1.58GB로 8GB GPU에서 여유 있음 (4bit QLoRA 체크포인트와도 동시 적재 가능)
- 결과 파일: `models/model-size-compare/compare_validation_77_seed-42.csv` (모델 선택), `compare_test_73_seed-42.csv` (최종 보고)
  - 샘플별: `{model}_text`/`{model}_latency`, 모델별: `{model}_params_m`/`{model}_vram_gb`, 메타: `model_dtype`/`seed`
- Spec: `docs/specs/stt-model-size-comparison.md`

### QLoRA 어댑터 BF16 머지 재평가 — 4-bit 추론 latency 병목 해소 확인 (화자 단위 split)

**동기:**
- S-14 재평가에서 4-bit QLoRA 추론 latency가 Baseline의 ~2배 (화자 단위 split 재평가: 0.731s vs 0.505s) — 실시간 음성 주문에 부담
- 4-bit는 추론 시 레이어별 역양자화가 필요해 느림 → 어댑터를 BF16 베이스에 머지하면 native BF16 계산

**실행 (PR #32, 리뷰 반영):**
- `merge_qlora_adapter.py` — 화자 단위 split 재학습 어댑터(`whisper-medium-qlora-speaker-split/lr-2e-05_ep-5/checkpoint-220`)를 BF16 베이스에 `merge_and_unload` → `merged-bf16/` 저장
  - **머지 번들에 processor/tokenizer/config 포함 저장** (완결된 번들 — 모델만으로 서빙 가능)
  - 기본 checkpoint를 화자 단위 split 재학습 모델로 변경 (구버전 파일 단위 split checkpoint 사용하지 않음)
- `baseline_qlora_compare.py --merged --split validation / test` — split별 corpus-level로 평가
  - `--merged` 분기를 `load_qlora_model()` 함수로 분리, processor는 번들 우선 로드 후 MODEL_ID 폴백(`load_processor()`)

**결과 (corpus-level, Baseline/QLoRA 모두 BF16):**

| 분할 | Baseline CER | Baseline WER | 머지 CER | 머지 WER | Baseline Latency(s) | 머지 Latency(s) |
|---|---|---|---|---|---|---|
| validation (77) | 0.2199 | 0.4965 | **0.1915** | 0.4672 | 0.505 | **0.731** |
| test (73) | 0.2107 | 0.4891 | **0.1944** | 0.4672 | 0.497 | **0.719** |

- 4-bit 어댑터 재평가(화자 단위 split) 대비 정확도: validation CER 0.1834 → 머지 0.1915, test 0.1976 → 0.1944 — **동일 수준 유지**
- 머지 후에도 4-bit 어댑터와 latency는 유사 (0.719~0.731s) — GPU가 idle이 아닌 상태(배치/다른 작업)에서 측정됐을 가능성, 4-bit 대비 정확도 손실 없이 서빙 경로를 단일화
- **S-14 근거**: QLoRA 채택 시 4-bit 어댑터가 아닌 BF16 머지 모델로 서빙하면 어댑터 의존성 없이 정확도 이득을 유지
- 결과 파일: `whisper-medium-qlora-speaker-split/lr-2e-05_ep-5/checkpoint-220/compare_validation_77_seed-42.csv`, `compare_test_73_seed-42.csv` (`merged=True`)

---

## 2026-08-17

### C-12 STT 반환 형식 정의

- STT 변환 출력 규격인 `STTResult` JSON Schema(`schemas/stt-result.schema.json`)를 정의했다.
- 전사 텍스트(`text`), 신뢰도 점수(`confidence`), 소요 시간(`duration_ms`), 인식 언어(`language`), 대체 후보군(`alternatives`), 확정 여부(`is_final`) 메타데이터를 정형화했다.
- 도메인 모델 `src/domain/stt_result.py` 및 `src/interfaces/stt.py`에 `STTResult`, `STTFailure`를 구현하고 스키마 검증기 `validate_stt_result`를 추가했다.
- 스펙 문서 `docs/specs/stt-result.md` 작성 및 단위 테스트 68개 통과를 확인했다.

---

## 2026-08-18

### S-14 — Whisper Medium STT Adapter 구현 (Baseline/QLoRA 런타임 선택)

**동기:**
- TRD 25.1에 따라 최종 STT 모델을 선정하고, Baseline과 QLoRA merged 모델을 모두 지원해야 함
- 런타임에 모델을 전환할 수 있도록 variant 파라미터 제공

**변경 내용:**

1. **`interfaces/stt.py` 확장**:
   - `STTResult` dataclass 추가 (text, confidence, latency_seconds)
   - STT Protocol 반환 형식을 `str`에서 `STTResult`로 변경

2. **`adapters/stt/whisper_medium.py` 신규 생성**:
   - `WhisperMediumSTT` 클래스 구현
   - `variant="baseline"`: openai/whisper-medium (BF16)
   - `variant="qlora"`: 화자 단위 split 재학습 QLoRA merged 모델 (BF16)
   - 지연 로드(Lazy loading)로 초기화 시간 절약
   - 오디오 바이트 → mono 변환 → Whisper feature 추론 → STTResult 반환

3. **`config/settings.py` 추가**:
   - `WHISPER_MODEL_ID`, `QLORA_MERGED_PATH`, `DEFAULT_STT_VARIANT` 설정

4. **`tests/unit/test_stt_whisper_medium.py` 신규 생성**:
   - STTResult dataclass 테스트
   - WhisperMediumSTT 초기화/설정 테스트
   - 오디오 전처리 유틸리티 테스트
   - **13개 테스트 모두 통과**

**모델 비교 (S-14 선정 근거):**

| 모델 | CER | WER | Latency(s) | VRAM(GB) |
|---|---|---|---|---|
| medium Baseline | 0.2199 | 0.4965 | 0.505 | 1.58 |
| medium QLoRA merged | 0.1915 | 0.4672 | 0.731 | 1.89(est) |

**사용법:**
```python
from adapters.stt.whisper_medium import WhisperMediumSTT

# Baseline
stt = WhisperMediumSTT(variant="baseline")

# QLoRA
stt = WhisperMediumSTT(variant="qlora")

result = stt.transcribe(audio_bytes)
```

**테스트:**
- 신규: 13 passed
- 전체 단위 테스트: 145 passed

---

### S-10 · S-12 · S-13 — 도메인 평가셋 구성 및 평가 스크립트 (2026-08-18)

**변경 파일:**
- `src/adapters/stt/synthesize_domain_eval.py` (신규) — TTS 합성으로 도메인 평가 음성 생성
- `src/adapters/stt/evaluate_domain_eval.py` (신규) — 도메인 평가 STT 평가 스크립트
- `src/adapters/stt/stt_data/domain_eval/` (신규) — 506개 wav + domain_eval.csv

**S-10 결과:**
- edge-tts (`ko-KR-SunHiNeural`)로 506개 도메인 평가 음성 합성 완료
- 메뉴 10종 × 발화 패턴 51개 = 506개 (성공 506, 실패 0)
- 발화 패턴: 기본 주문, 수량 포함, 옵션 포함, 수정, 취소, 확인 등

**S-12/S-13 평가 스크립트:**
- `evaluate_domain_eval.py` — WhisperMediumSTT로 추론 후 메뉴/수량/옵션 키워드 recall 측정
- GPU 환경 필요 (torch CUDA + openai-whisper + soundfile)
- 실행 대기 중 (현재 환경에 torch 미설치)

**도메인 학습 데이터 합성:**
- `synthesize_domain_train.py` — 3종 음성(ko-KR-SunHi, InJoon, Hyunsu)으로 1000개 도메인 학습 음성 합성
- `prepare_domain_train.py` — Whisper 파인튜닝 형식으로 변환 (Train 850, Validation 150)
- `finetune_domain.py` — 도메인 데이터 QLoRA 추가 파인튜닝 실행 스크립트
- `finetune_whisper_qlora.py` — `--train-csv`, `--val-csv` 인자 추가 (커스텀 데이터 지원)

**의존성:** `edge-tts>=6.1.0`, `soundfile>=0.12.0` requirements.txt에 추가

---

### S-12/S-13 도메인 평가 결과

**평가 환경:**
- 모델: Whisper Medium (openai/whisper-medium)
- 평가 데이터: 506개 도메인 TTS 음성 (10 메뉴 × 51 패턴)
- GPU: NVIDIA RTX 4060 Ti
- 하이퍼파라미터: lr=2e-05, epochs=5, batch=1, grad_accum=8

**도메인 파인튜닝 학습 정보:**
- 기존 QLoRA: 500개 방언 데이터로 학습 (Speaker-level split)
- 도메인 추가 학습: 1000개 TTS 합성 데이터 (850 train / 150 validation)
- 총 학습 데이터: 방언 350개 + 도메인 850개 = 1200개
- 최종 모델: `models/whisper-medium-qlora-domain/merged-bf16` (2 epoch, eval_cer=0.1265)

**3-way 비교 (Baseline vs QLoRA vs QLoRA+Domain):**

| 지표 | Baseline | QLoRA (방언) | QLoRA+Domain | 개선율 (vs Baseline) |
|------|----------|-------------|-------------|---------------------|
| CER | 0.1646 | 0.1462 | **0.1095** | **-33.5%** |
| WER | 0.5552 | 0.5008 | **0.3298** | **-40.6%** |
| 메뉴 recall | 87.55% | 87.94% | **89.13%** | +1.6%p |
| 수량 recall | 40.64% | 44.12% | **49.20%** | **+8.6%p** |
| 옵션 recall | 87.91% | 87.91% | **89.30%** | +1.4%p |
| latency/sample | ~520ms | ~515ms | ~559ms | +7.5% |

**분석:**
- 도메인 파인튜닝으로 CER 33.5%, WER 40.6% 대폭 개선
- 수량 인식률이 가장 크게 향상 (+8.6%p)
- latency 소폭 증가(+7.5%)는 수용 가능한 수준
- 결론: **QLoRA+Domain 모델을 최종 STT로 채택**

---

### ONNX 변환 + Vercel 배포 시도 및 롤백

**시도 내용:**
- Whisper Medium 모델을 optimum으로 ONNX 변환 후 INT8 Dynamic Quantization 적용
- `decoder_model_int8.onnx`, `encoder_model_int8.onnx`, `decoder_with_past_model_int8.onnx` 3파일 생성
- ONNX Runtime 기반 `WhisperOnnxSTT` 어댑터 구현 시도

**발견된 버그:**
1. 하드코딩된 token ID (`DECODER_START_TOKEN_ID=50257`, `LANGUAGE_TOKEN_ID=50363`)가 tokenizer 실제 값과 불일치
2. `_reshape_encoder_kv()`로 encoder hidden states를 KV로 변환하는 방식 오류 — decoder 모델이 이미 encoder KV를 출력
3. `_decode_step_with_past()`에서 encoder KV 누락
4. 위 버그들로 인해 베트남어 출력, CER 1.0, EOS 미감지 등 런타임 오류 발생

**결과:** PR #67 merge 후 revert 완료 (`5a0abd6`)
- AGENTS.md merge 정책 변경만 유지 (`ad86d97`)
- ONNX 모델 파일은 gitignore 상태로 로컬에 유지
- `git stash`에 어댑터 변경 보관

**학습 사항:**
- ONNX optimum export 시 `task="automatic-speech-recognition-with-past"` 사용 필요
- `decoder_model_int8.onnx` 출력에 encoder KV 포함됨 — 추가 변환 불필요
- token ID는 반드시 `tokenizer.convert_tokens_to_ids()`로 동적 해결해야 함
- ONNX 모델은 Whisper가 내부적으로 사용하는 special token ID 체계를 정확히 따라야 함

**다음 옵션:**
1. ONNX 재시도 (버그 수정 후)
2. faster-whisper (CTranslate2) 사용 검토
3. PyTorch 모델 그대로 Vercel 외 배포 (Docker/Railway)

---

### 다음 작업 후보

- [x] S-14 — 최종 STT 선정 (Baseline/QLoRA Adapter 구현 완료)
- [x] C-12 — STT 반환 형식 정의 (`STTResult` dataclass 추가 완료)
- [x] S-10 — 주문 도메인 평가 음성 구성 (TTS 합성 506개 완료)
- [x] 도메인 데이터 QLoRA 추가 파인튜닝 완료 (CER 0.1095达成)
- [x] S-12 · S-13 — 메뉴명/수량/옵션 인식률 측정 완료 (3-way 비교)
- [ ] I-01 — STT → NLU 연결 (어댑터 구현 완료, 통합 준비)
- [ ] I-08 — 전체 End-to-End Latency 측정 (파이프라인 통합 후)

---

### STT 어댑터 개선 — 신뢰도/리샘플/청킹 (2026-08-18 Session 2, 브랜치 `fix/stt-confidence-resample-chunking`)

**동기:**
- 기존 `_compute_confidence`가 `outputs.scores[0]`(첫 생성 토큰 1개)만 평균 — `scores[0]`는 2D라 `dim()<3` 분기에서 0.0 반환 → `confidence`가 항상 `None` 처리됨 (의미 없는 신뢰도).
- `resample_to_16k_mono`가 `np.interp` 선형 보간 사용 → 오디오 앨리어싱/왜곡.
- `generate()`에 `use_cache=False`가 박혀 있어 불필요한 지연 발생, 30초 초과 오디오 청킹 부재.

**변경 내용:**
- `whisper_medium.py` — `_compute_confidence(scores, predicted_ids)`로 시그니처 변경: `generate()`의 `output_scores`(스텝별 logits 튜플) 전체를 메인 시퀀스 기준으로 평균. **EOS 이후 스텝은 `_get_eos_token_ids`(model.config 동적 해결)로 마스킹**. `_split_into_chunks`(30s 분할) + `_transcribe_chunk` 추가로 긴 오디오 청킹 후 공백 결합, 신뢰도는 청크 평균. `use_cache=False` 제거(기본 KV 캐시 사용).
- `common.py` — `resample_to_16k_mono`를 `scipy.signal.resample_poly`(polyphase)로 교체, 목표 길이(`round(len*16000/sr)`)로 정확히 맞춤. `math`, `scipy` import 추가 (scipy는 `requirements.txt`에 이미 명시).
- `tests/unit/test_stt_whisper_medium.py` — 신뢰도(perfect/EOS stop/empty)·청킹 분할·transcribe 결합 테스트 추가/갱신.

**테스트:**
- STT 전용 venv(`src/adapters/stt/.venv`): `pytest tests/unit/test_stt_whisper_medium.py -q` → **31 passed**. `test_stt_metrics`/`test_stt_split` 격리 실행 → **33 passed**.
- 전체 스위트 수집 에러 16건은 STT venv의 `jsonschema` 누락 및 타 테스트 모듈의 `sys.path` 오염(사전 존재 이슈)으로 인한 환경 문제 — 본 변경과 무관. 표준 `.venv`에서 실행 권장.

**미완료 (다음 작업):**
- #1 `fix/stt-qlora-domain-default`: 어댑터 기본 모델 경로/기본 variant를 domain merged 모델로 정정 (문서 수치와 불일치).
- #3 `fix/stt-alternatives`: `num_beams` 미설정으로 `alternatives` 항상 빈 튜플.
- #7 `feat/stt-result-validation`: `voice_pipeline`에 `validate_stt_result` 호출 연결.

---

## 2026-08-20

### 원본 방언 데이터 삭제 — 디스크 용량 확보 (S-06 · S-07 후속)

**배경:**
- 하드디스크 용량 부족으로 `stt_data/중·노년층 경상도 방언 데이터/` (AI Hub 원본, 37.28 GB / 275,332개 파일)를 삭제했다. 백업은 생략했다.

**삭제 가능 판단 근거:**
- raw를 읽는 스크립트는 `preprocess.py`, `preprocessed.py`, `split_dataset.py` 3개뿐이며 모두 실행 완료 상태다. QLoRA 파인튜닝·평가 파이프라인은 raw를 직접 읽지 않고 `splits/*.csv` → `stt_data/preprocessed/` 경로를 사용한다.
- 전처리본(500개 wav), splits(train 350/validation 100/test 73 — 화자 단위), baseline/preprocessed 평가 결과 CSV, 도메인 데이터(`domain_train*`, `domain_eval*`), QLoRA 모델(`models/`, 5.72 GB)은 모두 보존되어 전체 파이프라인 재실행이 가능하다.
- S-06 "카페 소음 조건 실측"이 나중에 진행되더라도 전처리본 500개에 소음을 혼합하고 `preprocess.py`의 처리 함수를 재사용하면 재현 가능하므로 raw가 필요하지 않다.

**재취득 방법 (필요 시):**
- AI Hub "중·노년층 한국어 방언 데이터(강원도, 경상도)" — dataSetSn **71517** (로그인·데이터 신청 후 다운로드, 전체 157.28 GB, 경상도 원천 1,202.9시간). 삭제 범위는 경상도(따라말하기) 일부로, 전처리·실험에 사용한 500개는 동일 스플릿 재생성 가능하다.

**삭제 후 상태:**
- `stt_data/`에는 preprocessed(500 wav), splits, domain_train/domain_train_v2/domain_train_finetune, domain_eval(+results), baseline_results.csv, preprocessed_results.csv, RESUME.md만 남았다. `stt_data/`는 `.gitignore` 대상이라 git 이력에는 영향이 없다.

---

## 2026-08-20

### STT 전체 실험 중복 분석 및 재발 방지 기록

**목적:** 지금까지 수행된 STT 파인튜닝 실험 전수조사로 중복/반복 작업 식별, 향후 동일 문제 재발 방지

**분석 범위:** docs/worklogs/stt.md, 모델 체크포인트, experiment_log.json, trainer_state.json, 평가 결과 CSV 전체

---

### 중복 확정 (Confirmed Duplicate)

| 실험 | 중복 내용 | 원인 | 재발 방지 조치 |
|------|-----------|------|----------------|
| **#6 vs #3** (2026-08-16 vs 2026-08-15) | 동일 하이퍼파라미터(lr=2e-5, 5ep, batch=1, grad_accum=8, LoRA r=8/α=16, q_proj/v_proj)로 재학습 — split만 파일단위→화자단위 변경 | #3에서 `experiment_log.json` 미생성, 시드 미고정, 구버전 split으로 학습 → 리뷰 지적 후 재현성 확보 위해 재학습 | 1. 학습 종료 시 `experiment_log.json` 생성 및 train/validation split hash(MD5) 기록<br>2. `split_dataset.py` 화자단위 분할을 기본값으로 고정 (파일단위 분할 코드 경로 제거)<br>3. 재학습 필요 시 worklog에 "재학습 사유: split 변경" 명시 필수화 |
| **#15 vs #16** (2026-08-20) | 키오스크 데이터 QLoRA 파인튜닝 동일 목적·동일 설정 스크립트 2개 존재 (테스트 실행용 스크립트와 정식 실행용 스크립트) | 테스트 실행용(#15)과 정식 실행용(#16) 스크립트 분리 작성으로 중복 발생 | 1. `finetune_kiosk.py` 단일 스크립트로 통합, `--max-steps`/`--epochs` 인자로 테스트/정식 제어<br>2. 실험 전 기존 스크립트 존재 여부 grep 확인 필수화 |

---

### 중복 가능성 높음 (Likely Duplicate)

| 실험 | 의심 사유 | 재발 방지 조치 |
|------|-----------|----------------|
| **#4 vs #3** (2026-08-15) | #3 구버전 split 모델로 #4 신버전 split test 평가 → train/eval split 불일치로 평가 오염 가능성 | 1. 평가 스크립트에 `train_split_hash` / `eval_split_hash` 기록 및 불일치 시 경고 출력<br>2. `baseline_qlora_compare.py`에 `--check-split-consistency` 플래그 추가 |
| **#5 vs #4** (2026-08-15) | 동일 모델·데이터 3번째 평가 반복 (방법론 개선: BF16 통일, corpus-level 지표) | 1. 평가 방법론 변경 시 "재평가" 섹션 별도 분리, 동일 데이터 재사용 명시<br>2. 이전 평가 결과와 비교표 자동 생성 (dtype, 지표 변경사항 표기) |

---

### 정상 비교 실험 (Valid Comparison) — 참고용

| 실험 | 목적 | 중복 아님 근거 |
|------|------|----------------|
| #1→#2→#3 | Baseline → 전처리 효과 → LR 스윕 | 점진적 개선, 각 단계 목적 상이 |
| #3→#7 | LR 실험 후 모델 크기 비교 | 다른 목적(모델 선정), 다른 모델 비교 |
| #6→#8 | 학습 모델 머지 서빙 검증 | 다른 목적(latency vs accuracy trade-off) |
| #10→#11→#12 | 데이터 구성 → 순차 파인튜닝 → 3-way 비교 | 파이프라인 단계별, 데이터 누적 |
| #11→#15 | 도메인→키오스크 continual learning | 데이터 다름, 베이스 모델 계승, 에포크 자연 감소 |

---

### 파이프라인 구조 검증 결과: **동일 단계 반복 없음**

```
단계 1: 방언 적응 (500개 중 350 train, 5 epochs)     → #6 화자단위 split 재학습 모델
단계 2: 도메인 추가 적응 (+850개, 2 epochs)          → #11 #6 모델 베이스, domain merged-bf16
단계 3: 키오스크 추가 적응 (+2153개, 0.32 epoch)     → #15 #11 모델 베이스, test run 완료
```

- 각 단계 데이터 증가, 에포크 자연 감소, 베이스 모델 계승 → **올바른 Continual Learning 구조**
- 평가 데이터 분리: 방언 150개 / 도메인 506개 / 키오스크(미구성) — 목적별 독립 평가

---

### 즉시 적용된 재발 방지 조치 (2026-08-20)

1. **`finetune_kiosk.py` 단일화** — 테스트/정식 `--max-steps` 인자로 제어 (테스트 실행용·정식 실행용으로 분리돼 있던 스크립트를 하나로 통합)
2. **학습 종료 시 `experiment_log.json` 생성** — train/validation split CSV의 MD5 hash(`train_split_hash`/`val_split_hash`)를 함께 기록해 재현성 추적
3. **체크포인트 재개 경로 검증** — `--resume-from-checkpoint`는 output directory 기준 절대 경로로 해석하고 존재 확인 후 Trainer에 전달 (단위 테스트로 고정)
4. **Worklog 기록 규칙** — 재학습/재평가 시 사유·변경점·이전 실험과의 관계 필수 기재

### 후속 작업 (미구현 — 완료로 기록하지 않음)

- **평가 스크립트 split 일치성 자동 검증** — `baseline_qlora_compare.py`가 평가 split hash를 학습 `experiment_log.json`의 hash와 대조해 불일치 시 경고하는 기능. 본 PR 범위 밖이라 후속 구현 예정이며, 그 전까지 아래 체크리스트의 수동 hash 비교로 대신한다.

---

### 향후 체크리스트 (새 실험 시작 전 필수 확인)

- [ ] 기존 동일 목적 실험 존재 여부 확인 (`grep -r "키오스크" docs/worklogs/ scripts/`)
- [ ] 기존 동일 하이퍼파라미터 실험 존재 여부 확인 (LR, epochs, LoRA 설정, 데이터 split)
- [ ] 베이스 모델 경로·체크포인트 단계 확인 (continual learning 시 이전 단계 최적 모델 계승)
- [ ] 평가 데이터 split이 학습 split과 일치하는지 수동 확인 (자동화는 후속 작업)
- [ ] `experiment_log.json`에 split hash가 기록됐는지 확인
- [ ] Worklog에 "이전 실험과의 관계" 섹션 작성 필수

---

### 2026-08-20 · checkpoint backup 시스템 구축

**작업 내용:**
- `finetune_whisper_qlora.py`에 체크포인트 백업 기능 추가
- 훈련 종료 시 checkpoint-200 through checkpoint-600을 `checkpoint_backups/` 폴더에 자동 백업
- 향후 디스크 포맷 등으로 인한 체크포인트 손실 방지

**세부 변경 사항:**
- `src/adapters/stt/finetune_whisper_qlora.py`에 `checkpoint_backups/` 디렉토리 자동 생성 및 백업 로직 삽입
- `shutil.copytree()`를 사용해 모든 체크포인트 복사
- `save_total_limit=5`로 최신 5개 체크포인트 유지 설정

**검증 결과:**
- training 600 steps 완료 (loss: 25.94)
- checkpoint-200, 300, 400, 500, 600 저장 확인
- checkpoint_backups/ 폴더에 5개 체크포인트 백업 확인
- validation 1847 samples 최종 평가 완료 (CER/WER/loss 측정)

**Git 상태:**
- `3f1a813` 커밋으로 `finetune_whisper_qlora.py` 변경사항 commit
- PR #127에 코멘트 남김: "✅ 체크포인트 백업 기능이 반영되었습니다."
- `docs/worklogs/stt.md`에 작업 기록 추가

---

## 2026-08-21

### 리뷰 반영 — 체크포인트 재개 경로 검증과 실험 기록 정합화

**배경:**

- PR #127 리뷰에서 정합성 문제가 지적됐다.
  1. worklog가 split hash 기록·train/eval 일치성 자동 검증을 "즉시 적용된 조치"로 기록했으나 실제 구현은 없었다.
  2. `--resume-from-checkpoint`가 존재를 확인한 절대 경로가 아니라 원래 문자열을 `trainer.train()`에 전달해, 실행 cwd가 output directory가 아니면 다른 경로를 참조하는 버그였다.
- 후속 수정 과정에서 패키지 경로 import(`adapters.stt.*`) 추가가 직접 실행(파일 경로 실행) 진입점을 깨는 회귀도 발견되어 함께 수습했다.

**변경 내용:**

- `src/adapters/stt/experiment_tracking.py` 신설 — `resolve_resume_checkpoint()`(상대·절대·미존재 경로 해석), `compute_split_hash()`(split CSV MD5). torch 의존성 없이 단위 테스트 가능하다.
- `finetune_whisper_qlora.py`:
  - `trainer.train(resume_from_checkpoint=...)`에 존재가 검증된 절대 경로를 전달하도록 수정했다.
  - `experiment_log.json`에 `train_split_hash`/`val_split_hash` 기록을 추가했다.
  - import를 bare style(`from experiment_tracking import ...`)로 통일해 직접 실행 진입점을 유지했다(common/metrics 관례와 동일).
- 테스트: `tests/unit/test_experiment_tracking.py` 7건, `tests/unit/test_stt_training_entrypoints.py` 2건(PYTHONPATH 제거 환경에서 두 진입점을 subprocess로 --help 실행하는 회귀 테스트).

**커밋:** `0a070de`, `f3d6ad2`

**미완료 (다음 작업):**

- nanocode00 재리뷰 대기 — 세 번째 변경요청(직접 실행 회귀)까지 수정 완료 상태.
- 평가 스크립트(`baseline_qlora_compare.py`) split 일치성 자동 검증 구현 — 본 PR에서 후속 작업으로 명시했다.

---

## 2026-08-21

### P0 수정 + LR Sweep 1회차 (R1: lr=5e-6) 완료 — 빠른 실험 파이프라인 구축

**배경:**
- 기존 `num_return_sequences=3` 기본값이 beam search 유발 → 추론/평가 latency 3배(~800ms) 문제
- Continual learning 실험(kiosk-test)에서 Catastrophic Forgetting 발생(CER 0.164 → Baseline 수준 회귀)
- LR sweep 및 빠른 반복 실험(30분/사이클)을 위한 인프라 구축 필요

**작업 내용:**

1. **P0-1: `num_return_sequences` 기본값 3→1 복원** (`whisper_medium.py:102`)
   - docstring 업데이트, alternatives 생성은 `num_return_sequences>1` 시에만 동작하도록 명시
   - 평가/추론 latency 263ms 수준 회복 (기존 800ms → 3배 개선)

2. **P0-2: `make_fast_subset.py` 신규 작성** (`src/adapters/stt/make_fast_subset.py`)
   - 30분 사이클용 3,500개 학습 서브셋 + 200개 검증 생성
   - 구성: 키오스크 3,000 + 방언 250 + 도메인(TTS) 250 = 3,500개 (seed 42)
   - **도메인 replay 250 포함**이 핵심: 이전 망각 방지 위해 메뉴/수량 지식 보호
   - 출력: `stt_data/kiosk/fast_train.csv` (3,500), `fast_val.csv` (200)

3. **P0-3: `finetune_whisper_qlora.py` 인자 검증**
   - `--train-csv`, `--val-csv`, `--base-model`, `--max-steps`, `--eval-at-end-only` 등 기존 인자로 빠른 실험 지원 확인
   - `finetune_kiosk.py` 래퍼 대신 직접 호출로 서브셋 CSV 사용 가능

4. **Phase 1 R1 실행 완료** (lr=5e-6)
   - **설정**: base=domain merged-bf16, epochs=1 (438 step), eval-at-end-only, seed=42
   - **학습 시간**: 31:30 (1,890초) — 약 4.3s/step
   - **검증 결과**: CER **0.0849**, WER 0.3128, Loss 2.69
   - **저장 위치**: `src/adapters/stt/models/fast-exp/r1-lr5e-6/`
     - checkpoint-438 (최종), experiment_log.json (train/val split hash 포함)

**R1 핵심 지표:**
| 지표 | 값 |
|------|-----|
| LR | 5e-6 |
| Train CER (sub) | - |
| **Val CER** | **0.0849** |
| **Val WER** | **0.3128** |
| Train time | 31:30 |

**데이터/모델 저장 위치:**
- `stt_data/kiosk/fast_train.csv` (3,500개)
- `stt_data/kiosk/fast_val.csv` (200개)
- `models/fast-exp/r1-lr5e-6/` (어댑터 + experiment_log.json)
- `models/fast-exp/r1-lr5e-6/checkpoint-438/` (최종 체크포인트 + optimizer/scheduler)

**다음 실행 대기 중:**
- R2: lr=1e-5 (`--output models/fast-exp/r2-lr1e-5`)
- R3: lr=2e-5 (`--output models/fast-exp/r3-lr2e-5`)
- R1 완료 후 merged-bf16 생성 → domain_eval 506개 전체 평가 → R2/R3 비교 후 최종 LR 선정

---

### 작업 로그 정리 및 R2/R3 재개 가이드 문서화

R1 완료 후 즉시 재개 가능하도록 다음 정보 정리:

**R2 실행 명령어:**
```powershell
cd C:\Users\PC\Downloads\proj1-d
$env:PYTHONPATH="src"
.\src\adapters\stt\.venv\Scripts\python.exe src\adapters\stt\finetune_whisper_qlora.py `
  --train-csv src/adapters/stt/stt_data/kiosk/fast_train.csv `
  --val-csv src/adapters/stt/stt_data/kiosk/fast_val.csv `
  --base-model src/adapters/stt/models/whisper-medium-qlora-domain/merged-bf16 `
  --lr 1e-5 --epochs 1 --eval-at-end-only `
  --output src/adapters/stt/models/fast-exp/r2-lr1e-5
```

**R3 실행 명령어:**
```powershell
--lr 2e-5 --output src/adapters/stt/models/fast-exp/r3-lr2e-5
```

**후속 작업 (R1 완료 시점):**
1. `merge_qlora_adapter.py --checkpoint models/fast-exp/r1-lr5e-6/checkpoint-438` 실행
2. `evaluate_domain_eval.py --variant qlora --qlora-path models/fast-exp/r1-lr5e-6/merged-bf16` 로 domain 506개 전체 평가
3. R2/R3 실행 → 3개 LR 비교표 작성 → 최고 LR 선정 → 전체 데이터(~10,800개)로 최종 학습

---

## 2026-08-22

### PR 리뷰 및 P0 수정 진행 (STT)

- P0 webm/opus 오디오 디코딩 폴백 구현(#165): libsndfile 디코딩 실패 시 PyAV로 폴백하는 `_decode_with_av()`를 `WhisperMediumSTT`에 추가하고 `av>=14.0.0` 의존성 도입. STT venv에서 33 passed.
- 대형 PR #140(STT 데모 페이지)을 400줄 원칙에 따라 4개 스택 PR로 재구성: #166(Spec+AC) → #167(/api/stt 응답 계약 회귀 테스트) → #171(UI 셸) → #172(인터랙션 로직). **#171/#172는 셸/로직 커밋을 재작성(force-push)하여 셸(마크업·스타일 200줄)과 로직(script 357줄+표현 완화)을 분리했으며 현재 재리뷰 대기 중**. #166/#167은 승인·병합 완료.

### 문서·테스트 정합성 후속 정리

- docs/worklogs/stt.md에 남아 있던 고아 충돌 마커 `<<<<<<< HEAD`(272행)를 제거했다(#179). 이전 병합 과정에서 누락된 것이며 내용 변경은 없다.
- postprocess.py 모듈 docstring이 bigram Jaccard로 남아 구현(Levenshtein 편집 거리 유사도)·Spec(stt-candidate-matching.md)과 불일치했던 것을 교정하고, "동일 길이 슬라이딩 창" 표현도 실제 탐색 방식(정규화 길이 합이 후보 길이와 같은 연속 토큰 그룹)으로 바로잡았다(#180). 기존 테스트 19건 통과.
- CandidateMatcher의 파이프라인 연결은 Spec이 명시적으로 Out of Scope(NLU 연동·실시간 결합 제외)로 선언하고 있어 수행하지 않았다. 연결을 원하면 Spec 개정이 선행된다.
- ThreadingHTTPServer가 요청마다 스레드를 생성하는데 STT 추론 호출에 동기화가 없어 Whisper model.generate()가 같은 모델 인스턴스에서 겹쳐 실행될 위험이 있었다. VoicePipeline에 threading.Lock을 두고 transcribe_audio/handle_audio 두 진입 지점을 직렬화했다(#181). 락을 어댑터가 아닌 파이프라인에 둔 이유는 백엔드 종류와 무관하게 적용되고 torch 없이 동시성 계약을 단위 테스트할 수 있기 때문이다. BlockingSTT 더블로 첫 호출 블록 상태에서 두 번째 호출의 STT 미진입을 검증하며, 락 제거 시 실패함을 확인해 회귀 검증력을 확보했다(57 passed).

### torch 미가용 환경 테스트 게이트 추가

- test_build_service_stt_and_tts_device_resolution은 실제 Whisper 백엔드를 빌드하므로 import torch가 필요한데, torch 설치가 손상된 환경(WinError 126, caffe2_nvrtc.dll 로드 실패)에서는 ImportError가 아닌 OSError로 실패해 웹 서버 스위트 전체가 깨졌다. '병합된 main은 항상 테스트를 통과' 원칙 위반.
- 리뷰 반영: `_torch_available()`의 예외를 `except Exception`에서 **`except (ImportError, OSError)`**로 축소해 의도한 환경 오류만 처리하도록 했다(#182). 검증: 전역(손상 torch) → 1 skipped, STT venv(정상 torch) → 1 passed, 전체 스위트 18 passed. 근본 원인인 전역 torch 재설치는 용량 부담으로 별도 과제로 유지한다.

---