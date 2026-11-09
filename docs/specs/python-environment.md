---
title: "Python 가상환경 및 프로젝트 학습/실험 환경 정책"
tags: [spec]
---

# Python 가상환경 및 프로젝트 학습/실험 환경 정책

## Why

- **페르소나**: 말로(Mallo) 핵심 파이프라인 개발 및 AI 모델(STT / TTS / NLU) 학습·실험을 수행하는 팀원
- **상황**: 팀원들이 Windows와 WSL/Linux 환경에서 일반 기능 개발과 GPU 기반 모델 파인튜닝/실험을 병행하고 있다.
- **문제**:
  1. OS별(Windows / WSL) 가상환경 경로 및 활성화 스크립트가 달라 환경 불일치 및 실행 오류가 발생할 수 있다.
  2. 모델 학습 및 재현에 필요한 패키지 버전이 명확히 고정되지 않으면 환경 간 라이브러리 충돌이나 재현성 실패가 발생한다.
  3. 기존 학습이 정상 진행된 검증된 환경에 대한 명문화된 기준과 유지/변경 정책이 필요하다.
- **측정 지표**: 신규 환경의 일반 테스트 통과율(100%), 환경 진단 도구의 오류 감지 정확도, 모델 학습/실험 재현 시 의존성 충돌 0건

## Goal

- **해결 목표**: Windows와 WSL/Linux에서 역할별 canonical 가상환경을 사용하고, runtime과 NLU의 상충하는 의존성을 분리한다.
- **성공 기준**:
  - 일반 개발 환경은 Python 3.11 또는 3.12에서 설치 후 전체 회귀 테스트가 100% 통과한다.
  - 프로젝트 학습 환경은 Python 3.11.9를 사용하고 CUDA 12.4·12.8 PyTorch 설치 경로를 구분한다.
  - Gateway/STT/TTS runtime과 Qwen NLU runtime의 상충하는 `transformers` 요구사항을 별도 환경으로 격리한다.
  - "기존 학습 성공 환경 기준 우선 유지 및 문제 발생 시 팀 논의 후 변경" 원칙을 합의하고 문서화한다.
  - `scripts/check_python_env.py`가 OS별 활성화 스크립트, Python 버전, 필수 패키지 누락 여부를 정확히 보고한다.
- **Out of Scope**:
  - 하드웨어별 NVIDIA 드라이버 및 CUDA Toolkit 자체의 자동 설치
  - 배포용 컨테이너(Docker) 이미지 빌드 파이프라인

## What

**Happy Path**

1. 개발자는 본인 OS(Windows 또는 WSL/Linux)에서 지원 Python 버전으로 작업별 가상환경을 생성한다.
   - 일반 개발: Python 3.11.x 또는 3.12.x
   - 학습 및 실험: Python 3.11.9
2. Gateway/STT/TTS는 `.venvs/runtime`에 `requirements/runtime.txt`, Qwen NLU runtime은 `.venvs/nlu`에 `requirements/nlu.txt`, 개발·테스트·학습/평가는 `.venvs/dev`에 `requirements/dev.txt`를 설치한다.
3. 셸에 맞는 역할별 `.venvs/*` 활성화 스크립트를 실행한다.
4. `python scripts/check_python_env.py core`, `stt`, `tts-melo`, `tts-qwen` 중 환경에 맞는 범위로 검증한다.
5. 테스트 또는 학습/실험을 실행하고, 신규 실험 시 `pip freeze`와 GPU/CUDA 정보를 결과와 함께 보존한다.
6. 라이브러리 호환성이나 실행 문제가 발생할 경우 임의로 버전을 바꾸지 않고 팀 논의를 거쳐 정책과 문서를 개정한다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 필요한 `.venvs/*` 환경 또는 활성화 스크립트가 없음 | `scripts/check_python_env.py`가 실패를 보고하고 OS별 생성/활성화 명령어를 안내한다. |
| EC-02 | 일반 개발에 Python 3.11/3.12 외 버전 사용 | 미지원 버전 오류로 보고하고 지원 버전 재설치를 안내한다. |
| EC-03 | 학습/실험 환경에 Python 3.11.9 외 버전 사용 | 학습 기준 버전 불일치를 오류로 보고한다. |
| EC-04 | GPU/CUDA를 사용할 수 없는 환경 | 일반 회귀 테스트 및 Mock 파이프라인은 정상 동작을 허용하고, GPU 학습/실험은 실행을 차단한다. |
| EC-05 | 패키지 간 호환성 충돌 또는 런타임 오류 발생 | 임의 수정하지 않고 이슈/회의를 통해 팀 논의 후 버전을 변경하고 문서를 갱신한다. |
| EC-06 | Windows와 WSL/Linux의 CUDA 빌드 차이 | PyTorch/CUDA wheel을 플랫폼별 선행 단계로 분리 설치한다. |
| EC-07 | 한 OS에서 생성한 가상환경을 다른 OS로 복사/공유 | 가상환경 디렉터리를 복사하지 않고 각 OS에서 새로 생성한다. |
| EC-08 | runtime과 NLU를 같은 환경에 설치 | `transformers` 요구사항이 충돌하므로 설치하지 않고 역할별 canonical 환경을 사용한다. |

## How

### 가상환경 정책

- 개발·테스트·학습/평가: 저장소 루트 `.venvs/dev` (Git 추적 제외)
- Gateway·STT·TTS runtime: `.venvs/runtime` (Git 추적 제외)
- NLU runtime/inference: `.venvs/nlu` (Git 추적 제외)
- OS·모델 간 독립성: 가상환경 디렉터리를 복사하거나 공유하지 않는다.
- 버전 힌트: 저장소 루트 `.python-version`에 `3.11.9` 기록

### 프로젝트 환경 기준 및 패키지 명세

기존 학습이 정상적으로 진행된 환경이므로 **우선 아래 버전을 기준으로 유지**하고, 호환성이나 실행 문제가 발생할 경우 **팀 논의 후 변경**한다.

| 패키지 / 환경 | 기준 버전 | 설명 / 용도 |
|---|---|---|
| **Python** | `3.11.9` | 프로젝트 학습 및 STT 재현 기준 Python |
| **runtime torch** | `2.11.0+cu128` | gateway/STT/TTS CUDA 12.8 wheel |
| **NLU torch** | `2.11.0+cu128` | Qwen3-0.6B CUDA 12.8 wheel |
| **runtime transformers** | `4.27.4` | MeloTTS 및 Train65 Whisper runtime |
| **NLU transformers** | `5.15.0` | Qwen3-0.6B merged-BF16 production inference |
| **datasets** | `5.0.1` | Hugging Face Datasets |
| **evaluate** | `0.4.6` | 모델 평가 프레임워크 |
| **peft / bitsandbytes** | 평가·학습 전용 | merged-BF16 production NLU requirements에서는 제외 |
| **accelerate** | `1.14.0` | 분산 및 가속 학습 유틸리티 |
| **faster-whisper** | `1.2.1` | CTranslate2 기반 Whisper STT 엔진 |
| **jiwer** | `4.0.0` | STT WER / CER 산출 |
| **soundfile** | `0.14.0` | 오디오 파일 I/O |
| **noisereduce** | `3.0.3` | 오디오 노이즈 억제 전처리 |
| **numpy** | `2.4.6` | 다차원 배열 및 수치 연산 |
| **pandas** | `3.0.5` | 데이터 조작 및 결과 CSV 분석 |
| **scipy** | `1.17.1` | 과학 계산 및 신호 처리 |
| **librosa** | `0.9.1` | TTS 공통 오디오 분석 및 리샘플링 |

runtime과 NLU의 Transformers pin은 상충하므로 한 virtual environment에 함께 설치하지 않는다. 학습·평가용 의존성은 `.venvs/dev`에서 관리한다.

### OS별 가상환경 생성 및 활성화

| 환경 | 가상환경 생성 | 활성화 |
|---|---|---|
| Windows PowerShell | `py -3.11 -m venv .venvs/dev` | `.\.venvs\dev\Scripts\Activate.ps1` |
| Windows cmd | `py -3.11 -m venv .venvs/dev` | `.venvs\dev\Scripts\activate.bat` |
| WSL / Linux bash | `python3.11 -m venv .venvs/dev` | `source .venvs/dev/bin/activate` |

### 의존성 설치 절차

1. **배포 runtime (gateway + Train65 STT + MeloTTS)**:
   ```bash
   python3.11 -m venv .venvs/runtime
   .venvs/runtime/bin/python -m pip install --upgrade pip
   .venvs/runtime/bin/python -m pip install -r requirements/runtime.txt
   ```

2. **배포 NLU (Qwen3-0.6B merged-BF16)**:
   ```bash
   python3.11 -m venv .venvs/nlu
   .venvs/nlu/bin/python -m pip install --upgrade pip
   .venvs/nlu/bin/python -m pip install -r requirements/nlu.txt
   ```

3. **개발·테스트·학습/평가 및 시스템 의존성**:
   ```bash
   python3.11 -m venv .venvs/dev
   .venvs/dev/bin/python -m pip install --upgrade pip
   .venvs/dev/bin/python -m pip install -r requirements/dev.txt
   # 학습 의존성은 목적별로 추가 설치한다.
   .venvs/dev/bin/python -m pip install -r requirements/train/nlu.txt
   ```
   - `cloudflared`는 Python package가 아니다. Quick Tunnel이 필요한 경우 운영체제 패키지 관리자 또는 공식 binary로 별도 설치한다.
   - 모델 weights/checkpoint는 requirements 또는 자동 download 대상이 아니다.
   ```bash
   PYTHONPATH=src .venvs/runtime/bin/python scripts/run_mallo_server.py
   ```


### 환경 진단 도구

```bash
# 일반 개발 환경 검증
.venvs/dev/bin/python scripts/check_python_env.py core

# 학습 / STT 실험 환경 검증
.venvs/dev/bin/python scripts/check_python_env.py training
# 또는 .venvs/runtime/bin/python scripts/check_python_env.py stt

# 모델별 TTS 환경 검증
.venvs/runtime/bin/python scripts/check_python_env.py tts-melo
.venvs/dev/bin/python scripts/check_python_env.py tts-qwen
```

## AC (Given-When-Then)

**AC-01 · 일반 환경 진단**
- GIVEN: 지원 Python 버전(3.11 또는 3.12)의 저장소 루트 `.venvs/dev`에 일반 의존성이 설치되어 있다.
- WHEN: `.venvs/dev/bin/python scripts/check_python_env.py core`를 실행한다.
- THEN: Python 정보와 가상환경 경로를 출력하고 종료 코드 `0`을 반환한다.

**AC-02 · 활성화 스크립트 누락 감지**
- GIVEN: 저장소 루트 `.venvs/dev`에 현재 OS용 활성화 스크립트가 없다.
- WHEN: `.venvs/dev/bin/python scripts/check_python_env.py`를 실행한다.
- THEN: 누락된 스크립트 경로와 재생성 안내 메시지를 출력하고 종료 코드 `1`을 반환한다.

**AC-03 · 학습 환경 Python 버전 및 패키지 검증**
- GIVEN: Python 버전이 3.11.9가 아니거나 필수 학습 패키지가 누락되어 있다.
- WHEN: 역할에 맞는 canonical interpreter로 `scripts/check_python_env.py training`, `stt`, `tts-melo`, `tts-qwen` 중 해당 범위를 실행한다.
- THEN: 기준 버전 불일치 및 누락된 패키지 목록을 출력하고 종료 코드 `1`을 반환한다.

**AC-04 · 배포 직접 의존성 및 환경 분리**
- GIVEN: production requirements 명세 파일이 있다.
- WHEN: `requirements/runtime.txt`, `requirements/nlu.txt`, `requirements/dev.txt`와 이 문서를 확인한다.
- THEN: runtime의 `transformers==4.27.4`와 NLU의 `transformers==5.15.0`이 별도 venv에 고정되고, merged-BF16 NLU production requirements에는 `peft`와 `bitsandbytes`가 없다.

**AC-05 · 일반 회귀 테스트 통과**
- GIVEN: 일반 의존성이 설치된 지원 환경이다.
- WHEN: `PYTHONPATH=src .venvs/dev/bin/python -m pytest`를 실행한다.
- THEN: 전체 단위 및 통합 테스트가 통과한다.
