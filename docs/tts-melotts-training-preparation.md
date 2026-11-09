---
title: "T-26 MeloTTS 학습 준비 절차"
tags: [doc]
---

# T-26 MeloTTS 학습 준비 절차

이 문서는 T-26 실행을 위한 명령 진입점만 설명한다. 학습 조건과 합격 기준은 `docs/specs/melotts-friendly-finetuning-poc.md`가 기준이다. Python 환경이 팀 회의에서 확정되기 전에는 설치·전처리·학습 결과를 공식 PoC 판정에 사용하지 않는다.

## 현재 준비 범위

- MeloTTS 저장소의 필수 학습 파일과 commit SHA 확인
- T-25 train/validation manifest의 형식·화자·WAV 경로·상호 중복 검사
- 한국어 Baseline checkpoint와 학습용 `G.pth`, `D.pth`, `DUR.pth`의 존재·크기·SHA-256 기록
- 고정 split을 보존하는 공식 전처리 명령 생성
- Spec의 seed, learning rate, batch size, checkpoint 간격을 공식 config에 적용
- 사전학습 가중치를 명시적으로 전달하는 `torchrun` 명령 생성

의존성 설치, 모델 다운로드, 공식 전처리, GPU 학습 및 추론은 이 준비 작업에서 실행하지 않는다.

## 공식 구현에서 확인한 주의점

- [공식 학습 문서](https://github.com/myshell-ai/MeloTTS/blob/main/docs/training.md)는 `preprocess_text.py` 이후 `train.sh`를 실행하는 Custom Dataset 경로를 안내한다.
- [공식 전처리 코드](https://github.com/myshell-ai/MeloTTS/blob/main/melo/preprocess_text.py)는 하나의 metadata를 내부에서 다시 섞어 train/validation으로 나눈다. T-25의 녹음 그룹 단위 split을 보존하기 위해 준비 도구는 train과 validation을 각각 전처리하는 명령을 만든다.
- [공식 학습 코드](https://github.com/myshell-ai/MeloTTS/blob/main/melo/train.py)는 `G.pth`, `D.pth`, `DUR.pth`를 각각 받을 수 있고 optimizer를 제외한 상태로 불러온다. 세 파일은 명령에서 명시하고 로딩 로그를 보존한다.
- 공식 `train.sh`는 실패 여부와 관계없이 학습을 계속 재시작하는 무한 auto-resume wrapper다. 2,000-step 판정과 5,000-step 상한을 지켜야 하는 이번 PoC에서는 직접 사용하지 않는다. 정확한 step 종료 자동화는 T-26 실행 단계에서 공식 commit을 고정한 뒤 추가한다.

## 입력 경로

아래 네 경로를 먼저 준비한다. 모두 절대 경로를 사용한다.

- `MeloTTS` 공식 저장소 clone
- T-25 산출물 `data/tts/derived/aihub-71349`
- 학습용 `G.pth`, `D.pth`, `DUR.pth`가 있는 로컬 디렉터리
- 한국어 Baseline `checkpoint.pth`

가중치와 학습 산출물은 Git에 추가하지 않는다. 실행 계획과 전처리 산출물은 `data/tts/runs/melotts/` 아래에 만들며 이 경로는 `.gitignore`에 등록되어 있다.

## 실행 계획 생성

저장소 루트에서 다음 명령의 placeholder를 실제 절대 경로로 바꿔 실행한다.

```bash
PYTHONPATH=src python -m adapters.tts.prepare_melotts_training plan \
  --melotts-repository /absolute/path/to/MeloTTS \
  --derived-root /absolute/path/to/proj1-d/data/tts/derived/aihub-71349 \
  --pretrain-root /absolute/path/to/pretrained \
  --baseline-checkpoint /absolute/path/to/checkpoint.pth \
  --run-root /absolute/path/to/proj1-d/data/tts/runs/melotts/t26
```

성공하면 `run-plan.json`에 revision, 입력 건수, checksum, 실행 계약과 단계별 명령이 기록된다. 상태값 `PREPARED_NOT_EXECUTED`는 학습 성공을 의미하지 않는다.

## 환경 확정 후 실행 순서

1. `run-plan.json`의 `preprocess_train`을 실행한다.
2. `preprocess_validation`을 실행한다.
3. 두 전처리 로그에서 오류 행이 0개인지 확인한다. 오류가 있으면 T-25 또는 전처리 계약을 수정하고 학습하지 않는다.
4. 프로젝트 저장소 루트에서 `finalize_config`를 실행한다.
5. 생성된 config의 train/validation 경로와 학습 조건을 검토한다.
6. `train` 명령을 실행하고 G/D/DUR 로딩 로그와 shape mismatch를 저장한다.
7. 2,000 step에서 첫 판정하고, 계속할 경우에도 5,000 step을 넘기지 않는다.

T-26 완료 처리는 공식 전처리, checkpoint 생성, 저장 checkpoint 추론까지 성공한 뒤에만 수행한다.
