---
title: "Qwen3-0.6B NLU 서비스 후보"
tags: [spec, nlu, qwen3, service-candidate]
---

# Qwen3-0.6B NLU 서비스 후보

PR #209의 실제 서비스 후보는 **Qwen3-0.6B `epochs4_seed7` merged BF16 + Prompt Lookup 8 + deterministic guard**다. Qwen3-1.7B 관련 benchmark/spec은 비교·회귀 확인용 reference이며 서비스 후보 성능으로 해석하지 않는다.

## Why

말로(Mallo)의 NLU는 주문 발화를 `OrderCommand` 계약으로 안정적으로 변환해야 한다. 모델 출력 정확도뿐 아니라 잘못된 메뉴 ID, 스키마 위반, 명령 순서 오류를 막아 Order Engine에 안전하게 전달해야 한다.

또한 PR #209에서 특정 학습 결과를 서비스 후보로 연결하므로 입력 데이터, 모델 artifact, 실행 환경, 평가 결과를 다시 추적할 수 있어야 한다.

## Goal

focused contract-stress 기준 기능/계약 목표는 다음과 같다.

- Intent accuracy: **100%**
- Slot accuracy: **96% 이상**
- Error code accuracy: **95% 이상**
- Multi-command order accuracy: **100%**
- JSON schema valid rate: **100%**
- Invalid menu output rate: **0%**
- Warm NLU latency p95 목표: **1.2초 이하**

기존 benchmark에서는 p95 **1.182초**였지만 PR #209 목표 환경 재검증에서는 p95 **1.610초**로 악화됐다. 따라서 현재 후보는 **기능/계약 호환성은 통과했지만 latency 목표는 미달** 상태다.

Out of Scope:

- STT + NLU + Order Engine + TTS + Web 전체 E2E 성능을 이 문서에서 주장하지 않는다.
- `focused-v1`은 synthetic contract-stress suite이며 pristine final generalization holdout이 아니다.
- Qwen3-1.7B reference benchmark는 0.6B 서비스 후보 채택 근거로 사용하지 않는다.

## What

### 서비스 경로

```text
Qwen/Qwen3-0.6B
  -> epochs4_seed7
  -> merged BF16
  -> clean-greedy generation
  -> Dynamic KV cache
  -> Prompt Lookup 8
  -> deterministic guard
  -> OrderCommand / OrderCommandError
```

### Candidate selection validation

`epochs4_seed7` 선택 당시 일반 validation 결과:

- Exact match: **95.33%**
- Schema valid: **99.33%**
- Warm median: 약 **822 ms**
- Warm p95: 약 **1.317 s**

### Focused contract-stress

입력은 `focused-v1` 124건이며 아래 수치는 deterministic guard까지 포함한 서비스 경로 결과다.

| Metric | Existing benchmark | PR #209 target env |
| --- | ---: | ---: |
| Samples | 124 | 124 |
| Intent accuracy | 100% | 100% |
| Slot accuracy | 96.7787% | 96.7787% |
| Exact match | 63.7097% | 63.7097% |
| Error code accuracy | 96.6667% | 96.6667% |
| Multi-command order | 100% | 100% |
| JSON schema valid | 100% | 100% |
| Invalid menu output | 0% | 0% |
| Warm latency median | 857.502 ms | 1,169.441 ms |
| Warm latency p95 | 1,182.479 ms | 1,610.280 ms |
| Guard changed | 42 / 124 | 42 / 124 |

의미/계약 지표는 목표 환경에서도 동일하게 유지됐다. latency는 median 약 **36.4%**, p95 약 **36.2%** 악화됐다.

## How

### 입력 provenance

- 생성 경로: `data/nlu/challenges/focused-v1.jsonl`
- 종류: `synthetic_contract_stress`
- 샘플 수: `124`
- Linux LF SHA256: `22ba9b893a34e3316ad845a76a221b37b2552f10956ed28ca0a021661d4cf7e1`
- `test_split_opened=false`
- 증빙 manifest: `docs/evidence/nlu/focus3-20260825-115728/focused-v1.manifest.json`

`focused-v1`은 public NLU contract/menu schema와 hand-authored template으로 생성하며 train/validation/test example 파일을 읽지 않는다. Git 추적 대상이 아니므로 clean checkout에서는 builder로 재생성한 뒤 SHA256을 확인한다.

```bash
PYTHONPATH=src python scripts/build_nlu_focused_challenge_v1.py \
  --output data/nlu/challenges/focused-v1.jsonl

printf '%s  %s\n' \
  '22ba9b893a34e3316ad845a76a221b37b2552f10956ed28ca0a021661d4cf7e1' \
  'data/nlu/challenges/focused-v1.jsonl' \
  | sha256sum --check
```

### 모델 provenance

- Base model: `Qwen/Qwen3-0.6B`
- Base revision: `c1899de289a04d12100db370d81485cdf75e47ca`
- Sweep: `honorbear-20260825-021532-qwen3-0p6b-overnight`
- Variant: `epochs4_seed7`
- Merged artifact: `models/nlu/qwen3-0.6b-sweeps/honorbear-20260825-021532-qwen3-0p6b-overnight/epochs4_seed7/merged-bf16`
- `model.safetensors` SHA256: `2d72ee3dde4546a3409bdb433596be9f54039914309b8e2a13ed2500b7e4abe1`
- `config.json` SHA256: `352e422aa5bf719530c0be1d0666929983843a8629b812e8b55ca2976579d3c2`
- `merge-manifest.json` SHA256: `39f17f003782fd5017929dfe65d4ebe0181b420ce5d38e808de5f77f95cc5770`
- `tokenizer.json` SHA256: `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4`
- 전체 top-level 모델 파일 SHA 목록: `docs/evidence/nlu/pr209-target-env/model-files.sha256`
- 위 SHA 목록의 로컬 생성 당시 SHA256: `03faff524dc5e9ac252194bfa26286a875212fa8dbd4fb23c80f16e3fd9194a2`

서비스 시 standalone LoRA adapter를 로드하지 않고 위 merged BF16 artifact를 로드한다.

### 추론 설정

- precision: `bf16`
- model format: `merged`
- attention backend: `sdpa`
- cache implementation: `dynamic`
- prompt lookup tokens: `8`
- generation profile: `clean-greedy`
- output profile: `canonical`
- max new tokens: `96`
- warmup count: `5`
- batch size: `1`
- compile mode: `none`

기존 runtime manifest:

- `docs/evidence/nlu/focus3-20260825-115728/qwen06b-promptlookup8.manifest.json`

### 기존 benchmark 증빙

- guarded summary: `docs/evidence/nlu/focus3-20260825-115728/qwen06b-promptlookup8-guarded.summary.json`
- GitHub 커밋본 SHA256: `9502896f4f4487bd1f3a57963925f995951b132231b4f4e34a201a8fa71caa85`
- 로컬 원본 SHA256: `8fad305578d46592cd7fc27b84fe611cc15946b7782ae60d879526254c92b406`

커밋본은 로컬 JSON을 UTF-8 pretty-printed JSON으로 재직렬화한 사본이므로 byte-identical하지 않다. 성능 수치 감사에는 커밋본을 사용하고 로컬 원본 바이트 식별에는 원본 hash를 사용한다.

추가 로컬 artifact:

- raw prediction: `models/nlu/focused-benchmarks/focus3-20260825-115728/qwen06b-promptlookup8.jsonl`
  - SHA256: `546af40ef76e409fd260064a5c33bc926a6e858dda66347f86ad76b7007a4b03`
- guarded prediction: `models/nlu/focused-benchmarks/focus3-20260825-115728/qwen06b-promptlookup8-guarded.jsonl`
  - SHA256: `03786937dba8be99312b6b36b17628ad7eb2b1ee988a40ca6cc98d4b55f4a130`
- final summary: `models/nlu/focused-benchmarks/focus3-20260825-115728/final-summary.json`
  - SHA256: `2fc1d5185c5e7d2382f12676b5bb0f4dad6452fa54da1d494273dd423cf8a6f1`

### PR #209 목표 환경

실제 재검증 시 관측된 환경:

- Python: `3.11.9`
- PyTorch: `2.11.0+cu128`
- PyTorch CUDA runtime: `12.8`
- CUDA available: `true`
- GPU: `NVIDIA GeForce RTX 5070 Ti`
- Transformers: `5.15.0`
- venv: `.venvs/nlu`
- requirements: `requirements/nlu.txt`

재검증 요약:

- `docs/evidence/nlu/pr209-target-env/validation-summary.json`
- 124건 real-model prediction 완료
- semantic/schema 지표 기존 결과와 동일
- warm latency median **1,169.441 ms** / p95 **1,610.280 ms**
- p95 1.2초 목표 **미달**

### PEFT 의존성 경계

`qwen_prediction_runner.py`는 merged 모델 경로에서 `peft`를 요구하지 않는다. `PeftModel`은 `model_format=peft` 경로에서만 lazy import한다.

목표 환경에서 `peft installed: False`를 확인한 뒤 동일 merged BF16 모델을 대상으로 1건 smoke를 실행했고 model load와 generation이 성공했다.

- sample count: `1`
- model format: `merged`
- model load: 성공
- generation: 성공
- model load: 약 `882.35 ms`
- cold first generation: 약 `2194.54 ms`
- warmup: `1`
- 1건 generation latency: 약 `1419.40 ms`

이 smoke는 성능 대표값이 아니라 **requirements-only merged 경로가 PEFT 없이 실행됨을 검증하는 용도**다.

### 재현 명령

```bash
MODEL="models/nlu/qwen3-0.6b-sweeps/honorbear-20260825-021532-qwen3-0p6b-overnight/epochs4_seed7/merged-bf16"
RUN="models/nlu/focused-benchmarks/pr209-target-env"

PYTHONPATH=src .venvs/nlu/bin/python scripts/run_nlu_qwen06b_prediction.py \
  --input data/nlu/challenges/focused-v1.jsonl \
  --output "$RUN/qwen06b-promptlookup8.jsonl" \
  --model-format merged \
  --merged-model "$MODEL" \
  --experiment-id pr209-target-env-qwen06b-promptlookup8 \
  --warmup-count 5 \
  --max-new-tokens 96 \
  --cache-implementation dynamic \
  --prompt-lookup-num-tokens 8

PYTHONPATH=src .venvs/nlu/bin/python scripts/evaluate_nlu_qwen06b_guard.py \
  --gold data/nlu/challenges/focused-v1.jsonl \
  --predictions "$RUN/qwen06b-promptlookup8.jsonl" \
  --output "$RUN/qwen06b-promptlookup8-guarded.jsonl"
```

## AC

### AC-1 입력 provenance

**Given** 서비스 후보 성능을 검증할 때  
**When** `focused-v1`을 생성하면  
**Then** 124건, SHA256 `22ba9b...f7e1`, `test_split_opened=false`를 확인할 수 있어야 한다.

### AC-2 모델 provenance

**Given** 서비스 후보 artifact를 식별할 때  
**When** merged model을 확인하면  
**Then** `model.safetensors` SHA256 `2d72ee3d...e4abe1`과 `model-files.sha256`의 보조 hash가 일치해야 한다.

### AC-3 목표 환경

**Given** `.venvs/nlu`에서
**When** 환경 버전을 확인하면  
**Then** Python 3.11.9 / torch 2.11.0+cu128 / CUDA 12.8 / transformers 5.15.0 / RTX 5070 Ti가 관측되어야 한다.

### AC-4 guarded 기능/계약 성능

**Given** focused-v1 124건에 deterministic guard를 적용할 때  
**When** target-env 결과를 평가하면  
**Then** Intent 100%, Slot 96.7787%, Error code 96.6667%, Schema 100%, Invalid menu 0%, Multi-command order 100%를 만족해야 한다.

### AC-5 latency

**Given** PR #209 목표 환경에서  
**When** focused-v1 124건을 평가하면  
**Then** 현재 기록값 median 1,169.441 ms / p95 1,610.280 ms와 같은 조건으로 비교 가능해야 하며, p95 1.2초 목표 미달 상태를 숨기지 않아야 한다.

### AC-6 merged dependency boundary

**Given** `peft`가 설치되지 않은 목표 환경에서  
**When** `model_format=merged` prediction을 실행하면  
**Then** PEFT import 오류 없이 model load와 generation이 성공해야 한다.

### AC-7 사용자 안전 경계

**Given** HTTP NLU sidecar 연결 실패 또는 비정상 응답이 발생할 때  
**When** 오류가 VoicePipeline까지 전달되면  
**Then** 내부 URL·파일 경로·socket/CUDA 예외 문자열은 사용자 화면/TTS에 노출되지 않고 고정 복구 안내만 전달되어야 한다.

## Reference boundary

- `qwen06b_nlu.py`, `requirements/nlu.txt`, HTTP NLU sidecar: **현재 0.6B 서비스 경로**
- `benchmark_qwen3_1p7b_reference_pipeline.py`: **1.7B reference benchmark**
- `run_nlu_qwen3_1p7b_reference_cascade.py`: **1.7B reference cascade benchmark**
- `nlu-inference-latency.md`: **1.7B reference optimization spec**
