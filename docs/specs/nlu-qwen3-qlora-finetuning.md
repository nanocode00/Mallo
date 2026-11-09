---
title: "NLU Qwen3-1.7B QLoRA Fine-tuning과 평가"
tags: [spec, nlu, fine-tuning]
---

# NLU Qwen3-1.7B QLoRA Fine-tuning과 평가

## Why

- **페르소나**: 메뉴 탐색과 장바구니 수정을 음성으로 수행하는 고령 사용자
- **상황**: STT가 전달한 한국어 발화와 현재 장바구니를 Local NLU가 해석한다.
- **문제**:
  1. 범용 모델은 주문 Intent, 메뉴 ID, 옵션과 수량을 일관된 JSON으로 출력하지 못할 수 있다.
  2. 복수 Command 순서, 장바구니 대상 모호성, 지원하지 않는 요청의 오류 코드를 함께 판정해야 한다.
  3. JSON 파싱·Schema·Menu DB 검증 실패는 주문 지연을 만들고 재입력을 요구한다.
- **측정 지표**: Intent Accuracy, Slot Accuracy, Exact Match, JSON Schema Valid Rate,
  Invalid Menu Output Rate, Error Code Accuracy, 복수 Command 순서 정확도, Warm inference
  latency, Peak RAM/VRAM과 Intent별 혼동 행렬

## Goal

- **해결 목표**: `Qwen/Qwen3-1.7B`를 주문 도메인 데이터로 4-bit QLoRA SFT하여,
  한국어 발화와 `cart_before`를 `OrderCommand[]` 또는 `OrderCommandError` JSON으로 변환한다.
- **성공 기준**:
  1. Validation Exact Match가 동일 Prompt의 Baseline보다 5%p 이상 높다.
  2. Validation JSON Schema Valid Rate가 99% 이상이다.
  3. Validation Invalid Menu Output Rate가 1% 이하이다.
  4. Validation Error Code Accuracy와 복수 Command 순서 정확도가 각각 Baseline 이상이다.
  5. 최종 보고서에 Test 300건의 Baseline/Fine-tuned 필수 지표, latency, Peak RAM/VRAM,
     실패 사례와 Intent별 혼동 행렬이 모두 기록된다.
- **Out of Scope**:
  - STT, TTS, Order Engine 또는 Menu DB의 기능 변경
  - Test Split을 이용한 Prompt·checkpoint·하이퍼파라미터 선택
  - Schema Validator와 Order Engine 검증의 제거 또는 우회
  - 모델 가중치, adapter, checkpoint, 캐시와 생성된 processed JSONL의 Git 저장
  - 유료 클라우드 사용, 모델 Hub 배포와 제품 런타임 통합

## What

### Happy Path

1. 고정된 시스템 Prompt와 사용자 메시지를 Baseline 모델에 입력한다.
2. Train 2,400건을 Qwen Chat Template의 non-thinking 대화 형식으로 변환한다.
3. Validation 300건으로 Baseline을 측정하고 Prompt를 고정한다.
4. 같은 Base Model에 4-bit QLoRA SFT를 수행한다.
5. Validation 지표로 checkpoint와 하이퍼파라미터를 하나만 확정한다.
6. 확정 모델과 고정된 Baseline을 Test 300건에서 각각 한 번 평가한다.
7. Parser와 Validator를 통과한 출력에만 런타임 어댑터가 `request_id`를 주입한다.

### Edge Cases

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | CUDA GPU 또는 4-bit backend가 없음 | 데이터 변환·설정·CPU 스모크 테스트만 수행하고 학습은 명시적으로 실패한다. |
| EC-02 | 모델 출력이 JSON으로 파싱되지 않음 | `INVALID_JSON`으로 집계하고 Schema·Exact Match 실패로 기록한다. |
| EC-03 | JSON은 유효하지만 계약과 다름 | `SCHEMA_ERROR`로 집계하며 Order Engine에 전달하지 않는다. |
| EC-04 | 존재하지 않는 메뉴·카테고리·태그 ID 출력 | Invalid Menu로 별도 집계하며 장바구니를 변경하지 않는다. |
| EC-05 | 복수 Command의 순서가 다름 | 순서 정확도와 Exact Match를 실패 처리한다. |
| EC-06 | `request_id`를 모델이 출력함 | Schema 실패 처리하고 런타임 값으로 인정하지 않는다. |
| EC-07 | 생성 길이 제한까지 JSON이 닫히지 않음 | 잘린 원문과 종료 사유를 기록하고 `INVALID_JSON`으로 집계한다. |
| EC-08 | 학습 중 OOM 발생 | 자동으로 다른 실험을 선택하지 않고 실패 설정과 Peak VRAM을 기록한다. |
| EC-09 | Test 결과가 낮음 | Test를 다시 보며 수정하지 않고 결과를 그대로 보고한다. 후속 변경은 새 데이터 버전에서 수행한다. |
| EC-10 | 동일 `sample_id`가 결과에 중복·누락됨 | 평가를 실패시키고 지표를 확정하지 않는다. |

## How

### 1. 기준 모델과 라이선스

- Base Model은 `Qwen/Qwen3-1.7B`의 학습 실행 시 고정한 revision을 사용한다.
- 모델 라이선스는 Apache-2.0이며 결과 문서에 model ID, revision, 라이선스를 기록한다.
- Qwen3를 지원하는 `transformers>=4.51.0`을 사용한다.
- NLU 학습용 격리 가상환경을 사용하며 TTS 가상환경을 재사용하지 않는다.
- 실제 설치 버전과 lock 파일은 학습 CLI 구현 PR에서 확정한다.

참고 자료:

- [Qwen3-1.7B 모델 카드](https://huggingface.co/Qwen/Qwen3-1.7B)
- [Qwen3 Transformers Quickstart](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/quickstart.md)
- [Transformers bitsandbytes 4-bit 안내](https://huggingface.co/docs/transformers/main/quantization/bitsandbytes)

### 2. 입력과 정답 계약

Source of Truth는 다음 문서다.

- 데이터와 Split: [`nlu-dataset.md`](nlu-dataset.md)
- 정상 Command wire format: [`order-command.md`](order-command.md)
- 오류 wire format: [`order-command-error.md`](order-command-error.md)
- 메뉴·카테고리·태그: [`menu-catalog.md`](menu-catalog.md)

학습기 입력은 `data/nlu/processed/{train,validation}.jsonl`만 허용한다. 각 행은 아래 메시지로
결정론적으로 변환한다.

```text
system: 고정된 NLU 역할, 허용 Schema, Menu DB 식별자, 출력 제약, /no_think
user: {"utterance": <문자열>, "cart_before": <배열>}
assistant: <output.value의 공백 없는 canonical JSON>
```

- `output.type`은 assistant 출력에 포함하지 않는다. JSON 최상위가 배열이면 정상 Command,
  객체이면 오류다.
- 시스템 Prompt의 필드·enum·메뉴 식별자는 기준 문서와 런타임 파일에서 생성하며 손으로 복제하지 않는다.
- assistant 정답에는 `request_id`가 없어야 한다.
- 키 순서와 JSON 직렬화 규칙을 고정하고 UTF-8 한글을 이스케이프하지 않는다.
- tokenizer의 `apply_chat_template`에 `enable_thinking=False`를 전달한다.
- 학습 loss는 assistant completion token에만 적용한다.
- 변환 결과는 캐시 또는 임시 산출물이며 Git에 커밋하지 않는다.

### 3. QLoRA 초기 설정

| 항목 | 초기값 |
|---|---|
| quantization | 4-bit NF4, double quantization |
| compute dtype | BF16 지원 GPU는 BF16, 그 외 CUDA GPU는 FP16 |
| LoRA target | 모든 Linear layer |
| LoRA `r` / `alpha` / `dropout` | 16 / 32 / 0.05 |
| max sequence length | 2,048 tokens |
| epoch | 3 |
| learning rate / scheduler | 2e-4 / cosine |
| warmup steps / weight decay | `ceil(전체 optimizer step × 0.03)` / 0.01 |
| micro batch / gradient accumulation | 2 / 8 |
| gradient checkpointing | 활성화 |
| seed | 42 |

- 실제 GPU 메모리에 맞지 않으면 micro batch만 1로 낮추고 gradient accumulation을 16으로 올려
  effective batch 16을 유지한다.
- 첫 실행 뒤 비교가 필요하면 learning rate `{1e-4, 2e-4}`와 epoch `{2, 3}`만 Validation으로
  비교한다. Test는 어떤 선택에도 사용하지 않는다.
- checkpoint 선택 우선순위는 Validation Exact Match, JSON Schema Valid Rate, Error Code
  Accuracy, 낮은 Invalid Menu Output Rate 순이다. 앞 지표가 같을 때만 다음 지표를 사용한다.
- 생성은 greedy decoding(`do_sample=false`)과 고정 `max_new_tokens`를 사용해 재현성을 유지한다.

### 4. 하드웨어와 실행 경계

- 학습 전 Python, PyTorch, CUDA availability, GPU 이름, Compute Capability, 총 VRAM,
  `transformers`, `trl`, `peft`, `accelerate`, `bitsandbytes` 버전을 기록한다.
- NVIDIA NF4 학습은 Compute Capability 6.0 이상에서만 허용한다.
- 권장 기준 장비는 CUDA 지원 NVIDIA GPU와 VRAM 8GB 이상이다. 실제 가능 여부는 모델을
  다운로드하기 전 dry-run과 메모리 추정으로 다시 판정한다.
- 모델 다운로드 예상 용량과 캐시 위치를 출력하고 사용자의 승인을 받은 뒤 다운로드한다.
- GPU가 없으면 실제 QLoRA 학습과 모델 Baseline 평가는 실행하지 않는다. fixture tokenizer/model을
  사용하는 CPU 스모크 테스트로 메시지 변환, 설정 검증, 출력 경로만 확인한다.

### 5. 평가 계약

평가 단위는 `sample_id` 한 건이며 예측 원문, 정규화 결과, 실패 단계, latency와 자원 사용량을
JSONL로 기록한다. 정답 Command와 예측 Command는 배열 위치로 정렬하며 재정렬하지 않는다.

| 지표 | 정의 |
|---|---|
| Intent Accuracy | 정상 정답 표본에서 위치별 Intent 전체가 일치한 표본 수 / 정상 정답 표본 수 |
| Slot Accuracy | 위치가 대응되는 정상 Command의 의미 필드 7개 값 중 일치한 수 / 비교한 전체 필드 수 |
| Exact Match | canonical prediction이 canonical `output.value`와 같은 표본 수 / 전체 표본 수 |
| JSON Schema Valid Rate | JSON 파싱과 정상·오류 Schema를 모두 통과한 표본 수 / 전체 표본 수 |
| Invalid Menu Output Rate | 허용되지 않은 메뉴·카테고리·태그 ID를 하나라도 출력한 표본 수 / 전체 표본 수 |
| Error Code Accuracy | 오류 정답 표본에서 `code`가 일치한 수 / 오류 정답 표본 수 |
| 복수 Command 순서 정확도 | 복수 정상 정답 표본에서 Command Intent와 대상의 순서가 모두 일치한 수 / 복수 정상 정답 표본 수 |

의미 필드 7개는 `intent`를 제외한 `target_item_id`, `category_id`, `quantity`, `temperature`,
`query_tags`, `detail_fields`, `options`다. 누락 필드는 `null`과 같게 보지 않고 실패로 계산한다.

- Baseline과 Fine-tuned 모델은 동일 revision, Prompt, tokenizer, decoding, Split과 장비를 사용한다.
- Prompt와 하이퍼파라미터 선택은 Validation까지만 수행한다.
- Test는 최종 설정을 잠근 뒤 Baseline과 확정 Fine-tuned 모델에 각각 한 번만 실행한다.
- Warm latency는 같은 프로세스에서 warm-up 5건 후 표본별 generation 구간을 측정해 median과
  p95를 보고한다. 데이터 로드와 최초 모델 로드는 제외한다.
- Peak RAM은 프로세스 RSS 최댓값, Peak VRAM은 CUDA peak allocated와 peak reserved를 함께 기록한다.
- JSON 파싱 실패, Schema 실패, Invalid Menu, Command 순서 실패를 중복 가능한 원인으로 따로 집계한다.
- 정상 Intent 및 오류 code를 합친 label group 기준 혼동 행렬과 label group별 지표를 생성한다.
- 원본 발화나 Cart를 포함한 평가 산출물은 저장소 밖 또는 Git ignore 경로에 둔다.

### 6. 최종 Test 확정 결과 (2026-08-25)

Validation으로 확정한 2차 보정 adapter를 잠근 뒤, 학습과 모델 선택에 사용하지 않은 Test
300건을 실험 ID `qwen3-1.7b-error-remediation-v2-final-test`로 한 번만 평가했다. Test와
adapter checksum은 실행 전에 고정값과 대조했으며 예측 300건의 중복·누락은 없었다.

| 지표 | 결과 | 실행 전 고정 기준 | 판정 |
|---|---:|---:|---|
| Intent Accuracy | 95.3846% | 95% 이상 | 통과 |
| Slot Accuracy | 97.1978% | 95% 이상 | 통과 |
| Exact Match | 88.6667% | 85% 이상 | 통과 |
| JSON Schema Valid Rate | 99.6667% | 99% 이상 | 통과 |
| Invalid Menu Output Rate | 0% | 1% 이하 | 통과 |
| Error Code Accuracy | 70% (28/40) | 90% 이상 | 실패 |

- Warm latency는 median 5,701.64ms, p95 8,401.95ms였다.
- Error Code 오답 12건은 `MISSING_FIELD`, `MIXED_INTENT`, `UNSUPPORTED_UTTERANCE`와
  오류 대신 Command를 생성한 사례에 집중됐다.
- 최종 판정은 **production gate 실패**다. 이 adapter는 명시적으로 선택하는 데모·파일럿
  후보로만 보존하고, 기본 Web 실행은 `MockNLU`와 기존 fail-closed 경계를 유지한다.
- 이 Test 결과를 본 뒤 같은 Split로 Prompt, guard, checkpoint 또는 하이퍼파라미터를
  다시 선택하지 않는다. 후속 개선은 새 데이터 버전과 새 holdout에서 평가한다.

재현 식별자는 다음과 같다.

- Base model: `Qwen/Qwen3-1.7B`
- Revision: `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`
- Test SHA256: `57F2882CCE362106507C6BA921C4D5763E7778D99DCFE8521C8372C38FACF42F`
- Adapter SHA256: `CFC1591D08E2EDB70F5848928A5540D621DBB8007C701DFDBBDA6DA9BF10D71D`
- 결과 ZIP SHA256: `547D64ABF84F27353A2D3B05690A38FE61C09EE40B32F6E0A5CA273B3936B2CA`

가중치·원문 예측·processed JSONL은 AC-10에 따라 Git에 저장하지 않는다.

## AC (Given-When-Then)

### AC-01 · Chat Template 변환

- GIVEN: 승인된 processed JSONL 한 행이 있다.
- WHEN: 학습 메시지로 변환한다.
- THEN: system/user/assistant 순서, `enable_thinking=False`, canonical `output.value`가 적용된다.
- AND: 같은 입력을 두 번 변환하면 바이트가 같다.

### AC-02 · 학습 Split 격리

- GIVEN: train, validation, test 파일이 있다.
- WHEN: 학습과 checkpoint 선택을 실행한다.
- THEN: train만 gradient update에 사용하고 validation만 선택에 사용한다.
- AND: test 파일 접근 시도는 최종 평가 명령 외에는 실패한다.

### AC-03 · 출력 계약

- GIVEN: 정상과 오류 정답이 각각 있다.
- WHEN: assistant 정답을 직렬화한다.
- THEN: 정상은 `OrderCommand[]`, 오류는 `OrderCommandError`이고 wrapper와 `request_id`가 없다.

### AC-04 · 모델 없는 CPU 스모크 테스트

- GIVEN: CUDA, 실제 tokenizer와 모델 파일이 없다.
- WHEN: fixture로 스모크 테스트를 실행한다.
- THEN: 데이터 변환, 설정 검증과 dry-run이 네트워크·모델 다운로드 없이 통과한다.

### AC-05 · GPU 사전 검사

- GIVEN: CUDA 또는 지원되는 4-bit backend가 없다.
- WHEN: 실제 학습 명령을 실행한다.
- THEN: 다운로드와 학습 전에 필요한 장비와 현재 감지값을 포함한 오류로 종료한다.

### AC-06 · QLoRA 설정

- GIVEN: 지원 GPU와 고정 revision이 준비됐다.
- WHEN: 학습 설정을 생성한다.
- THEN: NF4 4-bit Base Model과 LoRA adapter만 학습 가능하고 전체 Base Model parameter는 고정된다.

### AC-07 · 평가 실패 단계 분리

- GIVEN: invalid JSON, Schema 위반, 존재하지 않는 메뉴 ID, 순서 오류 예측이 있다.
- WHEN: 평가기를 실행한다.
- THEN: 네 실패 유형을 각각 기록하고 해당 지표의 분모·분자가 정의대로 계산된다.

### AC-08 · Test 단회 사용

- GIVEN: Prompt, checkpoint와 하이퍼파라미터가 Validation으로 확정됐다.
- WHEN: 최종 비교를 실행한다.
- THEN: Baseline과 Fine-tuned Test 결과가 한 번씩 생성되고 재실행은 명시적 새 실험 ID 없이는 거부된다.
- AND: 실행 기록은 런타임 재시작 후에도 유지되는 저장소에 남아 같은 실험의 재실행을 차단한다.

### AC-09 · 안전 경계

- GIVEN: 모델 예측이 JSON 파싱 또는 검증에 실패한다.
- WHEN: 런타임으로 전달하려 한다.
- THEN: `request_id`를 주입하거나 Order Engine으로 전달하지 않고 Cart를 유지한다.

### AC-10 · Git 산출물 제외

- GIVEN: 변환, 학습 또는 평가가 완료됐다.
- WHEN: Git 변경 파일을 검사한다.
- THEN: 코드·설정·문서 외의 가중치, checkpoint, adapter, 캐시, processed JSONL과 평가 결과 원문이 없다.
