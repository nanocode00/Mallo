---
title: "GitHub Actions 한도 소진 대응 및 로컬 검증 가이드"
tags: [ci, test, guide]
---

# GitHub Actions 한도 소진 대응 및 로컬 검증 가이드

## 1. 현재 문제 및 사용량 현황

* **현재 문제**: GitHub Actions 월간 무료 사용량(조직/계정 한도) 소진으로 CI 워크플로우(`unit-tests.yml`, `secret-scan.yml`)가 실행되지 않거나 실패 처리됨.
* **사용량 현황 (총 1,308분 소모)**:
  * `unit-tests.yml`: **704분** 소모
  * `secret-scan.yml`: **604분** 소모
* **원인 분석**:
  * GitHub Actions 사용 시간의 상당 부분은 실제 테스트 실행(단위 테스트 458개 실행 시간은 약 8.4초에 불과)보다 **매 빌드마다 반복되는 무거운 의존성 패키지 다운로드 및 환경 구축**에서 발생했습니다.
  * `requirements.txt`에 포함된 대용량 머신러닝 패키지(`transformers`, `peft`, `bitsandbytes`, `accelerate`, `datasets`, `faster-whisper` 등)를 캐시 없이 매번 새로 설치하면서 러너 시간의 95% 이상이 의존성 설치에 소모되었습니다.
  * 또한 문서(`docs/**`), 데이터(`data/**`) 변경 시에도 CI가 전체 실행되고, concurrency 제어가 없어 낭비가 누적되었습니다.

## 2. 긴급 대응 방향

* **로컬 테스트 중심 검증 체계 전환**: Actions 한도 복구 전까지 CI 자동 체크에 의존하지 않고, **PR 작성자의 로컬 검증** 및 **리뷰어 확인**을 통해 `main` 브랜치의 안정성을 유지합니다.
* **검증 결과 PR 명시**: PR 본문에 로컬 테스트 실행 결과(통과 로그/요약)를 필수로 기재합니다.

## 3. PR 전 필수 로컬 테스트 및 검증 절차

모든 팀원은 PR을 생성하거나 브랜치에 커밋을 푸시하기 전, 로컬 환경에서 아래 절차를 반드시 실행해야 합니다.

### ① 단위 테스트 (필수)
```bash
# Python 단위 테스트 (458개 전체 통과 확인)
PYTHONPATH=src pytest tests/unit -q
```

### ② 프론트엔드 UI 테스트 (웹/UI 변경 시 필수)
```bash
# Web UI/Javascript 테스트 통과 확인 (26개 전체 통과)
node --test tests/frontend/*.test.js
```

### ③ 통합 테스트 (백엔드 파이프라인 / API 변경 시 필수)
```bash
# 통합 테스트 수행
PYTHONPATH=src pytest tests/integration -q
```

### ④ 시크릿(API 키/비밀번호) 누출 사전 검증 (필수)
* `.env` 파일은 절대 git에 포함되지 않아야 합니다.
* 커밋 전 `git diff`를 통해 민감한 API Key나 토큰이 포함되어 있는지 확인합니다.
```bash
# 변경 내용 중 시크릿 키워드 포함 여부 확인
git diff origin/main | grep -iE 'api[_-]?key|secret|token|password|sk-'
```

### ⑤ PR 생성 및 머지 절차
1. PR 본문에 **"로컬 테스트 완료 결과 (예: 458 passed in 8.4s)"** 를 기록합니다.
2. 조원 1인 이상의 코드 리뷰 및 Approve를 획득한 후 머지합니다.

## 4. Required Status Checks 설정 조정 필요 여부

* **문제점**: GitHub Repository Settings의 Branch Protection Rules(또는 Rulesets)에서 `pytest`나 `gitleaks`가 **Required Status Checks**로 지정되어 있으면, Actions가 돌지 않아 PR 머지 버튼이 차단(Block)됩니다.
* **조치 방안 (관리자/팀장)**:
  * **옵션 A (권장)**: GitHub Repo `Settings > Branches > main Branch protection rule`에서 **"Require status checks to pass before merging" 설정을 일시적으로 체크 해제**.
  * **옵션 B**: 관리자 권한을 가진 팀원이 리뷰 승인(Approve) 확인 후 Admin 권한으로 Override 머지 수행.

## 5. 재발 방지: GitHub Actions 최적화 방안

실제 프로젝트 워크플로우에 즉시 적용 가능한 개선 항목을 정리합니다.

### 1) Workflow Trigger 및 실행 조건 최적화 (불필요한 CI 실행 방지)
* **경로 필터링(`paths` / `paths-ignore`) 도입**: 마크다운(`docs/**`, `*.md`), 데이터(`data/**`) 등 소스코드와 무관한 파일만 변경된 PR/커밋은 CI 실행을 건너뜁니다.
* **동시성 제어(`concurrency`) 추가**: 동일 PR에 새 커밋이 추가되면 이전에 실행 중이던 빌드를 자동 취소(`cancel-in-progress: true`)하여 큐 적체 및 분 낭비를 방지합니다.

```yaml
# 적용 예시
on:
  pull_request:
    paths:
      - 'src/**'
      - 'tests/**'
      - 'requirements*.txt'
      - '.github/workflows/**'

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

### 2) Dependency Caching 적용
* `actions/setup-python`의 `cache: 'pip'` 옵션을 활성화하여 pip 다운로드 및 휠 캐시를 재사용합니다.
* 패키지 변경이 없을 경우 설치 시간을 수 분에서 수 초대로 대폭 단축합니다.

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
    cache: "pip"
```

### 3) 단위 테스트에 불필요한 무거운 패키지 설치 제거 & CI 최소 의존성 분리
* **현황**: `tests/unit`의 대부분은 비즈니스 로직(주문 엔진, 메뉴 카탈로그, 텍스트 변환 등) 검증이며 Mock을 사용하므로, 무거운 학습/추론 라이브러리(`transformers`, `peft`, `bitsandbytes`, `datasets` 등)가 불필요합니다.
* **개선안**:
  * CI 단위 테스트용 최소 의존성 파일(예: `requirements-ci.txt` 또는 `requirements-test.txt`: `pytest`, `jsonschema`, `soundfile`, `numpy` 등 필수 패키지만 포함)을 분리 구성.
  * 전체 환경 설치 대신 최소 의존성만 설치하여 CI 실행 시간을 빌드당 30초 이내로 단축.

### 4) 독립 작업(Secret Scan 등)의 경량화 유지
* **현황**: `secret-scan.yml`은 Python 환경 없이 Gitleaks 독립 도구를 사용하고 있으나, 전체 히스토리 풀 스캔(`fetch-depth: 0`)으로 인해 시간이 누적되었습니다.
* **개선안**:
  * Python/의존성 설치 없는 독립 경량 실행 구조를 유지하되,
  * PR에서는 전체 히스토리 대신 PR 변경분(`--log-opts="origin/main..HEAD"`)만 검사하는 증분(Delta) 검사 방식으로 전환하여 실행 시간과 분 소모를 최소화합니다.

## 6. 한도 복구 후 기존 CI 재활성화 절차

1. **GitHub Actions 사용량 리셋 확인** (다음 과금 주기 또는 사용량 한도 복구 시점)
2. **최적화된 워크플로우 설정 파일(`.github/workflows/*.yml`) 및 CI 최소 의존성 파일 반영**
3. **테스트 PR을 통해 최적화 동작(경로 필터, 캐시, concurrency, 실행 시간 단축) 정상 확인**
4. **GitHub Repo Settings에서 Branch Protection의 Required Status Checks 재활성화**
