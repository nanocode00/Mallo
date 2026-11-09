---
title: "Local LLM / NLU 작업 로그 (`N-*`)"
tags: [worklog]
---

# Local LLM / NLU 작업 로그 (`N-*`)

Local LLM과 NLU 영역에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다.

## 2026-08-14 — NLU 현재 주문 상태 입력으로 변경

- NLU 계약을 `parse(text, current_order_state)`로 변경했다.
- NLU에는 원본 Cart가 아니라 복사본을 전달하여 상태를 직접 변경하지 못하게 했다.
- OrderCommand 생성은 NLU, 실제 Cart 검증·변경은 Order Engine이 담당하는 경계는 유지했다.

## 2026-08-18 — NLU 런타임 계약 정합화

- Local LLM payload는 5개 의미 필드만 생성하고 NLU 어댑터가 UUID v4 `request_id`를 주입하도록 경계를 분리했다.
- `confirmation_required`를 `OrderCommand`와 JSON Schema에서 제거하고 Order Engine의 `requires_confirmation()` 정책 결과로 분리했다.
- NLU 실패는 예외 문자열 대신 `OrderCommandError`를 반환하도록 연결하고 오류 코드를 공통 `ErrorResponse`까지 보존했다.
- 필수 온도 누락 코드는 `MISSING_FIELD`, `field=temperature`로 통일했다.

## 2026-08-19 — 메뉴 이름 별칭 정규화

- 사용자 제공 목록 중 현재 Menu DB에 존재하는 `아아·뜨아·아라·뜨라·아바라·뜨바라` 6개만 채택했다.
- 별칭은 공식 Menu ID뿐 아니라 발화에 포함된 `hot`·`iced` 온도까지 함께 정규화한다.
- MenuItem과 표현 사전을 분리하기 위해 최상위 `menu_aliases`를 SSOT로 추가했다.
- 중복 별칭은 임의 메뉴에 우선 배정하지 않고 `AMBIGUOUS_TARGET` 후보 재질문으로 처리한다.
- 메뉴가 없는 `아초·아돌라`와 옵션 복합 별칭 `아샷추·아바샷`은 이번 범위에서 제외했다.

## 2026-08-25 — 고립된 NLU 스택의 main 통합과 데이터셋 3천 행 확정

- 원인 파악: NLU 데이터셋 확장 PR들(#138~#193)과 Qwen3 QLoRA 파이프라인 PR들(#195~#201)이 서로를 base로 하는 stacked 구조여서 GitHub MERGED 표시와 무관하게 main에는 커밋이 반영되지 않았다.
  - 그 결과 main의 `data/nlu/raw/nlu-orders.csv`는 1,140행에 머물렀고, 16개 Label Group 중 ADD_ITEM·REMOVE_ITEM·UPDATE_QUANTITY 3개만 목표 분포를 충족했다.
  - 스택 꼭대기(`test/nlu-dataset-final-qa-v2`)에는 최종 QA까지 끝난 3,000행(전 행 approved, Train 2,400/Validation 300/Test 300)이 존재했다.
- 통합: 스택 전체(데이터셋 확장 + Qwen3 파이프라인)를 origin/main 위 단일 로컬 브랜치 `feat/nlu-stack-integration`으로 병합하고 원격에 푸시해 PR #205를 생성했다. 배포 일정상 스택 병목을 한 번에 해소하기 위한 결정이다.
- 충돌 해결 근거: 병합 전 스택 CSV가 main의 1,140행을 sample_id·utterance·label_json 기준 100% 포함함을 확인해 CSV·dataset_tooling.py·데이터셋 테스트는 스택 버전을 채택했다(검수 수정본 유실 없음).
- requirements.txt는 main의 `av>=14.0.0`(오디오 디코딩)과 스택의 `trl>=1.10.0,<2.0`(NLU 학습)을 모두 보존하도록 병합했다.
- 검증 결과:
  - `dataset_tooling validate --mode final` PASS — 3,000행, 전 행 approved, 16개 Label Group 목표 분포 정확히 일치
  - `build --mode final`로 `data/nlu/processed/{train,validation,test}.jsonl` 생성, 2회 빌드 SHA256 체크섬 동일(nlu-dataset.md AC-09 재현성 충족)
  - `pytest tests/unit` 481 passed / 2 failed — 실패 2건(`test_stt_split`, `test_stt_training_entrypoints`)은 clean origin/main에서도 재현되는 전역 Python torch CUDA DLL 손상 환경 문제로 본 작업과 무관
  - diff 시크릿 스캔(hf_/sk-/api key 패턴) 0건
- 현재 상태: PR #205 리뷰 승인 대기 중. 병합 확정 전까지 tasks.md의 N-05~N-15 상태는 완료로 바꾸지 않는다. CI는 GitHub Actions 요금 소진으로 중단되어 로컬 검증으로 갈음했음을 함께 기록한다.
- 리뷰 반영(동일 날짜): nanocode00의 CHANGES_REQUESTED 2건(blocker)을 다음과 같이 수정했다.
  - Test Split 차단을 파일명 휴리스틱에서 내용 기반 검증으로 교체했다. 생성기(`dataset_tooling`)가 JSONL `metadata.split`을 기록하도록 계약을 확장(nlu-dataset.md §7 동시 갱신)했고, 학습 CLI는 파일명이 아닌 행별 `metadata.split`과 파일 간 sample_id 중복을 검사해 rename/copy 우회를 차단한다.
  - eval_loss 기반 checkpoint 자동 선택(`load_best_model_at_end`, `metric_for_best_model="eval_loss"`)을 제거했다. 모든 checkpoint를 보존하고, model_evaluator의 semantic 지표(Exact Match > Schema Valid Rate > Error Code Accuracy > Invalid Menu Output Rate)로 Validation 평가 후 `--finalize-from`으로 최종 adapter를 명시적으로 확정하는 흐름으로 바꿨다. Colab 노트북도 같은 순서로 갱신했다.

## 2026-08-25 — Qwen QLoRA adapter의 Web 런타임 연결

- 학습 당시 Menu DB·Schema 기반 system prompt를 그대로 재생성하는 `QwenNLU`를 추가했다.
- 모델 JSON은 도메인 객체 변환과 Schema 검증을 통과한 경우에만 Order Engine으로 전달하고,
  잘못된 출력은 장바구니를 유지하는 복구 가능한 NLU 오류로 닫았다.
- 서버에서 `mock`과 `qwen` NLU를 선택하고 PEFT adapter·device를 실행 인자로 주입할 수 있게 했다.
- 모델 생성은 단일 Lock으로 보호하며 2차 보정 결과는 코드 변경 없이 adapter 경로만 교체한다.
- 현재 계약과 AC는 [`qwen-nlu-runtime.md`](../specs/qwen-nlu-runtime.md)를 따른다.
