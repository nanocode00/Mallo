---
title: "T-27 Qwen3-TTS 비교 모델 준비 절차"
tags: [doc]
---

# T-27 Qwen3-TTS 비교 모델 준비 절차

이 문서는 T-27의 0.6B smoke test 진입점을 설명한다. 모델·데이터·fallback·동일 조건 비교 계약은 `docs/specs/melotts-friendly-finetuning-poc.md`가 기준이다. 팀의 Python 환경이 확정되기 전에는 설치·tokenization·GPU 학습 결과를 공식 PoC 판정에 사용하지 않는다.

## 현재 준비 범위

- Qwen3-TTS 저장소의 공식 Fine-tuning 파일과 commit SHA 확인
- T-25 `qwen_train.jsonl`의 `audio`, `text`, `ref_audio` 및 파일 경로 검사
- 모든 행의 `ref_audio` 동일 여부와 일반 학습 audio 누수 검사
- MeloTTS manifest와 Qwen3-TTS paired training records의 경로·텍스트·순서 일치 검사
- 0.6B 모델용 2레코드 smoke JSONL 생성
- 공식 tokenizer의 `audio_codes` 생성, 1 epoch smoke 학습, checkpoint 재로딩 및 `generate_custom_voice` 합성 명령 생성
- 전체 299건의 `audio_codes` 생성 명령 준비

의존성 설치, 모델 다운로드, tokenizer 실행, GPU 학습과 합성은 이 준비 작업에서 실행하지 않는다. T-27은 smoke test와 본 학습·평가가 실제로 성공한 뒤에만 완료한다.

## 공식 구현에서 확인한 주의점

- [공식 Fine-tuning 문서](https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning)는 0.6B와 1.7B Base의 단일 화자 학습을 지원하며 각 행에 `audio`, `text`, `ref_audio`를 요구한다.
- [공식 데이터 준비 코드](https://github.com/QwenLM/Qwen3-TTS/blob/main/finetuning/prepare_data.py)는 `Qwen/Qwen3-TTS-Tokenizer-12Hz`로 `audio_codes`를 추가한다.
- [공식 SFT 코드](https://github.com/QwenLM/Qwen3-TTS/blob/main/finetuning/sft_12hz.py)는 epoch마다 checkpoint를 저장하고 Fine-tuned 모델을 `custom_voice`로 바꾸지만 `max_steps` 인자를 제공하지 않는다.
- 공식 SFT 코드는 checkpoint 저장 시 초기 모델 디렉터리를 직접 복사하고 그 안의 `config.json`을 읽는다. 0.6B snapshot을 `run-plan.json`의 `required_local_path`에 먼저 내려받고 해당 로컬 경로를 학습에 전달한다.
- 2레코드·batch size 2·1 epoch smoke test는 checkpoint 생성과 재로딩 경로를 확인하는 데 사용한다. 본 학습은 optimizer 기준 2,000/5,000 step을 정확히 제한하는 코드를 확정하기 전에는 시작하지 않는다.
- 0.6B가 실패하면 오류·revision·자원 사용을 기록한 뒤 시연 장치 한도 안에서만 1.7B를 시도한다. zero-shot 결과는 Fine-tuned 비교 결과로 대체하지 않는다.

## 로컬 출력

실행 계획, smoke JSONL, `audio_codes`, checkpoint와 생성 WAV는 `data/tts/runs/qwen3-tts/` 아래에 생성하며 Git에 포함하지 않는다. AI Hub 원문이 포함된 JSONL과 생성 음성은 라이선스 확인 전까지 로컬 비공개로 유지한다.

## 실행 계획 생성

Qwen3-TTS 공식 저장소를 준비한 뒤 저장소 루트에서 placeholder를 실제 절대 경로로 바꿔 실행한다.

```bash
PYTHONPATH=src python -m adapters.tts.prepare_qwen3_tts_training \
  --qwen-repository /absolute/path/to/Qwen3-TTS \
  --derived-root /absolute/path/to/proj1-d/data/tts/derived/aihub-71349 \
  --run-root /absolute/path/to/proj1-d/data/tts/runs/qwen3-tts/t27
```

성공하면 `run-plan.json`, `smoke-raw.jsonl`, `smoke-text.txt`가 생성된다. `SMOKE_PREPARED_NOT_EXECUTED`는 모델을 설치하거나 학습했다는 의미가 아니다.

## 환경 확정 후 smoke test 순서

1. `run-plan.json`의 Qwen3-TTS revision과 primary model이 0.6B인지 확인하고 snapshot을 `required_local_path`에 준비한다.
2. `prepare_smoke`를 실행하고 출력 2행 모두에 `audio_codes`가 생겼는지 검사한다.
3. `train_smoke`를 실행하고 `checkpoint-epoch-0`이 생성됐는지 확인한다.
4. `infer_smoke`로 checkpoint를 새 프로세스에서 다시 불러와 참조 음성 없이 합성한다.
5. WAV decode, 심각한 깨짐, CUDA OOM 및 자원 사용을 기록한다.
6. smoke 성공 후 `prepare_full_data`를 실행한다.
7. optimizer step을 정확히 제한하는 실행 경로를 구현·검증한 다음에만 본 학습을 시작한다.

Smoke 실패 시 임의로 모델·데이터·참조 음성을 바꾸지 않는다. 실패 원인과 commit SHA를 먼저 기록하고 Spec의 1.7B fallback 조건을 적용한다.
