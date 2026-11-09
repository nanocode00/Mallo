---
title: "T-01 — TTS 후보 모델 조사"
tags: [spec]
---

# T-01 — TTS 후보 모델 조사

## Why

- **페르소나**: 말로(Mallo)의 P0 한국어 음성 출력과 P1 친절체 연구 모델을 선정해야 하는 TTS 담당자
- **상황**: 한국어 주문 안내를 로컬에서 합성하고, 이후 같은 데이터로 서로 다른 구조의 Fine-tuning 결과를 비교해야 한다.
- **문제**:
  1. 한국어 지원만 보고 고르면 로컬 실행·라이선스·발화 제어·학습 경로가 맞지 않을 수 있다.
  2. 문서상 지원 여부와 실제 개발 환경의 설치·성능 검증을 혼동하면 후보 조사만으로 실행 가능하다고 오판할 수 있다.
  3. 코드·모델 라이선스와 AI Hub 학습 데이터 및 파생 산출물의 이용 범위는 별도로 판단해야 한다.
- **측정 지표**: 후보별 필수 조사 항목 누락 0건, 공식 출처 연결률 100%, T-02 이후 검증 항목과의 경계 명시

## Goal

- **해결 목표**: 한국어 지원, 로컬 실행 경로, 라이선스와 제어 가능성을 공식 자료로 비교하고 후속 PoC 후보와 역할을 확정한다.
- **성공 기준**:
  - 후보별 한국어 지원 근거가 있다.
  - 외부 유료 API 없이 실행 가능한 공식 로컬 경로가 있다.
  - 코드·공개 모델의 라이선스와 데이터 라이선스의 별도 확인 범위가 기록된다.
  - 속도·화자·스타일·학습 등 주문 안내에 필요한 제어 가능성과 제한이 기록된다.
  - MeloTTS와 `Qwen/Qwen3-TTS-12Hz-0.6B-Base`의 후속 역할이 구분된다.
- **Out of Scope**:
  - 현재 개발 장치에서 설치·합성 성공 판정(T-02)
  - VRAM·Latency·RTF 실측(T-03)
  - 자연스러움·명료도와 Baseline 최종 선정(T-04)
  - 서비스 Adapter 구현(T-05~T-06)
  - 모델 라이선스에 대한 법률 자문

## What

### Happy Path

1. 공식 저장소와 모델 카드에서 한국어·로컬 실행·라이선스·제어 기능을 확인한다.
2. 각 기능을 문서상 지원, 후속 실험 필요, 비지원 또는 미확정으로 구분한다.
3. 가벼운 Baseline 우선 후보와 별도 구조 비교 후보의 역할을 정한다.
4. 설치·성능·음질·Fine-tuning 위험을 후속 티켓으로 넘긴다.
5. 조사 결과와 선택 이유를 worklog에 기록한다.

### Edge Cases

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 공식 문서에는 지원하지만 현재 환경에서 실행되지 않음 | T-02 실패로 기록하며 T-01의 문서 조사 결과를 실행 성공 근거로 사용하지 않음 |
| EC-02 | 코드와 모델 가중치의 라이선스가 다름 | 각각 기록하고 더 제한적인 조건을 적용 |
| EC-03 | 모델 라이선스는 허용하지만 학습 데이터 산출물 범위가 불명확함 | T-29 서면 문의 전까지 checkpoint·생성 WAV 비공개 |
| EC-04 | Qwen3-TTS 0.6B Fine-tuning 공식 경로에 결함이 있음 | T-27 스모크 테스트 후 자원 한도 안에서 1.7B fallback 검토 |
| EC-05 | 제어 기능이 모델 variant마다 다름 | 선택한 정확한 checkpoint의 기능만 지원으로 기록 |
| EC-06 | 공식 자료와 제3자 예제가 충돌함 | 공식 저장소·공식 모델 카드를 우선하고 실제 동작은 T-02에서 검증 |

## How

조사 기준일은 `2026-08-16`이다. 이후 설치 또는 공개 전에는 공식 문서와 라이선스 변경 여부를 다시 확인한다.

### 공식 근거

- MeloTTS: [공식 저장소](https://github.com/myshell-ai/MeloTTS), [공식 설치·사용 문서](https://github.com/myshell-ai/MeloTTS/blob/main/docs/install.md), [MIT License](https://github.com/myshell-ai/MeloTTS/blob/main/LICENSE)
- Qwen3-TTS: [공식 저장소](https://github.com/QwenLM/Qwen3-TTS), [0.6B Base 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base), [Apache-2.0 License](https://github.com/QwenLM/Qwen3-TTS/blob/main/LICENSE)
- Qwen3-TTS Fine-tuning: [공식 Fine-tuning 문서](https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning)

### 후보 비교

| 기준 | MeloTTS | Qwen3-TTS 12Hz 0.6B Base |
|---|---|---|
| 한국어 | 공식 `KR` 모델과 한국어 Python 예제 제공 | 공식 모델 카드가 한국어를 포함한 10개 언어 지원 명시 |
| 로컬 실행 | CLI·Python API·Web UI, CPU/CUDA/MPS 장치 선택 제공 | `qwen-tts` Python package와 로컬 모델 loading·Web UI 경로 제공 |
| 외부 API 의존 | 공식 로컬 경로는 유료 API 불필요 | 공식 로컬 경로는 DashScope API와 별개이며 유료 API 불필요 |
| 코드·모델 라이선스 | 공식 저장소 MIT, 상업·비상업 사용 가능 명시 | 공식 저장소와 선택 모델 카드 Apache-2.0 표시 |
| 한국어 Baseline 제어 | speaker ID와 `speed` 값 제어, WAV 파일 출력 | Base는 참조 음성 기반 voice clone과 언어 지정 지원 |
| 고급 제어 | 직접적인 자연어 style instruction은 공식 한국어 API의 기본 기능으로 확인되지 않음 | 제품군은 자연어 기반 음성 속성 제어·streaming을 지원하나 Base checkpoint별 사용 방식은 T-02에서 확인 |
| 학습 경로 | 공식 Custom Dataset 학습 문서 존재. 사전학습 가중치 Fine-tuning 여부는 T-26에서 검증 | 공식 single-speaker Fine-tuning 경로 존재. 0.6B 호환성은 T-27 스모크 테스트 필수 |
| 자원 가설 | CPU 실시간 추론을 공식 문서에서 안내하여 P0 Baseline 우선 검증에 적합 | 0.6B Base 모델 파일과 GPU 예제를 제공하며 실제 자원은 T-03에서 측정 필요 |
| 프로젝트 역할 | P0 Baseline 우선 후보이자 P1 친절체 주 Fine-tuning 후보 | 서로 다른 구조의 P1 비교 Fine-tuning 후보 |

### 결정

- **MeloTTS**를 P0 Baseline 우선 검증 후보와 P1 친절체 주 Fine-tuning 후보로 정한다.
- **`Qwen/Qwen3-TTS-12Hz-0.6B-Base`**를 P1 별도 구조 비교 후보로 정한다.
- Qwen3-TTS 0.6B의 공식 Fine-tuning이 확정 환경에서 실패하고 자원 한도를 만족할 때만 1.7B Base를 fallback으로 검토한다.
- 이 결정은 후보 shortlist이며 최종 Baseline 선정이 아니다. T-02 실행, T-03 성능, T-04 음질 결과에 따라 P0 모델은 선택 보류 또는 변경할 수 있다.
- 모델 라이선스와 별개로 AI Hub 데이터셋 ID `71349`의 원본·checkpoint·생성 WAV 공유 범위는 T-29 계약을 따른다.

## AC (Given-When-Then)

### AC-01 · 한국어 지원 비교

- GIVEN: 두 후보의 공식 저장소와 모델 카드가 있다.
- WHEN: 지원 언어를 검토한다.
- THEN: MeloTTS의 `KR` 경로와 Qwen3-TTS의 한국어 지원 근거가 각각 연결된다.

### AC-02 · 로컬 실행 경로 비교

- GIVEN: 외부 유료 API를 사용하지 않는 프로젝트 제약이 있다.
- WHEN: 공식 실행 경로를 검토한다.
- THEN: 두 후보 모두 로컬 loading·합성 경로가 있고 실제 성공 판정은 T-02로 분리된다.

### AC-03 · 라이선스 경계

- GIVEN: 모델을 연구·제품 후보로 검토한다.
- WHEN: 라이선스를 비교한다.
- THEN: MeloTTS MIT와 Qwen3-TTS Apache-2.0 근거가 기록되고 AI Hub 데이터·산출물의 별도 확인 필요성이 명시된다.

### AC-04 · 제어 가능성 비교

- GIVEN: 주문 안내에서 속도·화자·스타일 또는 참조 음성 제어가 필요하다.
- WHEN: 각 후보의 공식 API를 비교한다.
- THEN: 지원 기능, checkpoint별 제한과 후속 실행 검증 항목이 후보별로 기록된다.

### AC-05 · 후보 역할 확정

- GIVEN: 네 조사 항목이 모두 비교됐다.
- WHEN: 후속 PoC 역할을 결정한다.
- THEN: MeloTTS는 Baseline 우선·주 Fine-tuning 후보, Qwen3-TTS 0.6B Base는 별도 구조 비교 후보로 기록되고 T-02~T-04 미검증 상태가 유지된다.
