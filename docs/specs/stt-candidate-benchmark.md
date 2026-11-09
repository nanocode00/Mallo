---
title: "Spec — STT 후보 전체 벤치마크"
tags: [spec, stt, evaluation]
---

# Spec — STT 후보 전체 벤치마크

## Why

- Whisper Medium baseline, 배포용 merged BF16, 여러 PEFT adapter, ONNX INT8의 결과를 같은 도메인 음성으로 비교할 재현 가능한 도구가 필요하다.
- 후보가 많고 일부 adapter가 같은 가중치이므로, 잘못된 checkpoint 선택이나 중복 실행은 모델 선택 근거를 왜곡하고 GPU 시간을 낭비한다.

## Goal

- 한 CLI 실행으로 발견 가능한 STT 후보를 동일한 `domain_eval.csv`와 decoding 설정에서 비교한다.
- corpus CER/WER, 주문 키워드 recall, latency, VRAM, 샘플별 전사와 실패를 보존한다.
- smoke 및 backup은 평가하지 않고, 동일 SHA256 adapter는 한 번만 실행한다.

Out of Scope: 모델 학습·병합·변환, 평가 음성 및 기존 모델 파일 변경, 모델 선정 자체.

## What

1. baseline, `team_handoff/domain/merged-bf16`, 유효 PEFT adapter, ONNX INT8 후보를 탐색한다.
2. 실험 디렉터리에 top-level adapter가 있으면 항상 그것을 선택한다. top-level adapter가 없는 경우에만 가장 큰 `checkpoint-N`을 fallback으로 선택한다.
3. 각 모델을 완전히 unload하고 CUDA cache를 비운 뒤 다음 후보를 로드한다. 하나가 실패해도 나머지는 실행한다.
4. timestamp artifact에 leaderboard, 후보 목록, 모델별 샘플 결과, 오류 로그를 쓴다.

## How

- 진입점: `scripts/benchmark_stt_candidates.py`; 기본 모델 루트는 `src/adapters/stt/models`, 평가셋은 `src/adapters/stt/stt_data/domain_eval`.
- PEFT는 `adapter_config.json`의 `base_model_name_or_path`를 읽어 BF16 CUDA fresh base model에 `PeftModel.from_pretrained`를 적용한다. baseline/merged도 BF16 CUDA를 기본으로 한다.
- 모든 후보는 `WhisperProcessor`의 Korean transcription prompt, `max_new_tokens=440`, 16 kHz mono 입력을 사용한다. latency 필드는 반드시 `latency_ms`로 표기한다.
- ONNX는 `onnxruntime` session으로 encoder/decoder를 로드하고 실제 execution provider/device를 후보/leaderboard에 기록한다. CUDA 뒤에 CPU fallback이 있으면 `onnx-cuda+cpu`로 보수적으로 분리한다. accuracy는 공통 비교하되 latency rank는 `pytorch-cuda`, `onnx-cuda`, `onnx-cuda+cpu`, `onnx-cpu` 그룹 안에서만 계산한다.
- `--eval-csv`는 `sample_id,audio_path,reference` generic schema를 읽는다. 기존 `hypothesis`, `latency_sec` 등 추가 입력 컬럼은 무시한다. generic manifest에는 주문 semantic 컬럼이 없으므로 menu/quantity/option recall은 `null`로 기록한다.
- `--eval-preset clean-kiosk|clean-general|cafe15|cafe10|cafe5`는 heldout golden CSV를 가리킨다. clean-kiosk와 cafe SNR manifest를 함께 실행하면 공통 `sample_id`만으로 model별 corpus CER 및 clean 대비 증가량을 `noise_degradation.csv/json`에 쓴다.
- PyTorch Whisper는 processor의 `return_attention_mask=True` 출력을 `generate()`에 전달한다. official baseline generation config를 deepcopy한 benchmark 전용 `GenerationConfig`에 Korean greedy 조건과 suppression 목록을 설정해 baseline/merged/PEFT에 똑같이 사용한다. suppress 값은 generate kwargs로 중복 전달하지 않는다. Transformers 4.57.3 Whisper는 자체 processor 생성 뒤 inner `GenerationMixin.generate`가 4.50+ model defaults를 다시 채울 수 있으므로, 호출 범위의 복사 config로 inner fallback만 차단하고 원본 객체·bundle은 복원/무변경한다. 모델별 관측값, 실제 적용 config, forced decoder ids, attention mask 여부는 `metadata.json`에 기록한다.
- PEFT 후보는 로드 직후 active adapter, PEFT type, base model, LoRA module/parameter 규모와 `diagnostic_error`를 기록한다. 첫 평가 샘플에 대해 processor/config의 Korean no-timestamp prefix를 `decoder_input_ids`로 고정하고, `input_features`/`attention_mask`/`decoder_input_ids`/`use_cache=False`만 사용하는 Whisper teacher-forced forward를 수행한다. 공식 `disable_adapter()` context의 base logits와 비교해 최대/평균 절대 차이, `adapter_effect_verified`, 정확히 0인 경우의 warning을 metadata/errors.log에 기록한다. adapter 병합·저장·수정은 하지 않는다.
- leaderboard 정렬은 CER↑ 우선이 아니라 CER 오름차순, WER 오름차순, menu recall 내림차순, p95 latency 오름차순이다.

## AC

- GIVEN adapter 경로에 smoke, checkpoint_backups, 같은 SHA adapter가 있을 때 WHEN 후보를 탐색하면 THEN 제외 규칙과 `duplicate_of`가 `candidates.json`에 기록된다.
- GIVEN top-level adapter와 checkpoint-200/600이 함께 있을 때 WHEN 탐색하면 THEN top-level adapter만 평가 대상이다.
- GIVEN top-level adapter 없이 checkpoint-200/600만 있을 때 WHEN 탐색하면 THEN checkpoint-600만 평가 대상이다.
- GIVEN 한 후보의 loader 또는 전사가 실패할 때 WHEN sweep을 실행하면 THEN errors.log와 실패 수를 남기고 다음 후보를 계속 평가한다.
- GIVEN 평가가 끝났을 때 WHEN artifact를 열면 THEN leaderboard CSV/JSON, candidates JSON, per-model CSV가 있고 모든 latency 컬럼의 단위는 ms다.
