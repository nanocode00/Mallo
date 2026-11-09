---
title: "N-05~N-14 — NLU 주문 데이터셋 기준"
tags: [spec]
---

# N-05~N-14 — NLU 주문 데이터셋 기준

> 이 문서는 STT가 확정한 한국어 문장을 Local LLM/NLU가 해석할 수 있도록
> 수집·정제·라벨링·분할하는 1차 데이터셋의 기준 계약이다.

## Why

- **페르소나**: 음성으로 카페 메뉴를 탐색하고 주문을 추가·수정·확정하는 고령 사용자와 NLU 데이터 작성자
- **상황**:
  - STT 담당 모듈이 최종 한국어 문장을 전달하면 NLU는 문장과 현재 Cart를 해석해
    정상 시 `OrderCommand[]`, 실패 시 `OrderCommandError`를 반환한다.
  - 현재 12개 Intent와 런타임 실행 경로는 구현됐지만, 실제 Local LLM을 학습·평가할
    다양한 한국어 발화와 정답 Label은 아직 없다.
- **문제**:
  1. Intent별 수량과 표현 범위가 정해지지 않으면 간단한 요청에 데이터가 치우칠 수 있다.
  2. 복수 메뉴와 Cart Context를 보존하지 않으면 Batch 순서, 최종 수량, 모호한 대상 규칙을 학습할 수 없다.
  3. 사람이 검수하는 원본과 모델이 읽는 파일을 직접 각각 편집하면 두 산출물이 달라질 수 있다.
  4. 유사 문장이 Train과 Test에 함께 들어가면 실제보다 높은 평가 결과가 나온다.
- **측정 지표**: 목표 수량 충족률, Label Schema 준수율, 공식 Menu ID 준수율,
  중복·Split 누수 건수, 사람 검수 완료율

## Goal

- **해결 목표**: 공식 메뉴명과 승인된 메뉴 별칭 범위의 한국어 발화 3,000개를 한 발화당 한 행으로 관리하고,
  검수된 CSV 원본에서 Train/Validation/Test JSONL을 재현 가능하게 생성한다.
- **성공 기준**:
  - 승인된 데이터가 정확히 3,000행이며 아래 Intent·오류 분포와 80/10/10 Split을 충족한다.
  - 정상 Label은 Local LLM 의미 필드 8개만 포함하고 런타임 `request_id`를 포함하지 않는다.
  - 오류 Label은 발화 의미로 판정 가능한 4개 오류만 사용한다.
  - `src/config/menu.json`에 없는 `target_item_id`와 `category_id` 출력은 0건이다.
  - 완전 중복 발화, 중복 `sample_id`, `paraphrase_group_id`의 Split 누수는 각각 0건이다.
  - 최종 JSONL의 모든 행은 사람 검수 상태가 `approved`이고 CSV로부터 다시 생성할 수 있다.
- **Out of Scope**:
  - 음성 수집, STT 변환·오인식 보정 및 STT 성능 평가
  - `menu_aliases`에 등록되지 않았고 옵션 계약에서도 승인되지 않은 메뉴 별칭·유사어 인식
  - Local LLM 후보 선정, Prompt 작성, Structured Output 구현 및 Fine-tuning
  - P1 다중 턴 Clarification과 `pending_clarification` 상태 학습
  - 가격·총액 계산, Confirmation Policy 및 실제 Cart 변경

## What

### Happy Path

1. 데이터 작성자가 한국어 주문 발화와 해당 발화 직전의 Cart Context를 CSV 한 행에 기록한다.
2. `label_type`을 `commands` 또는 `error`로 정하고 `label_json`에 정답을 기록한다.
3. 정제 과정에서 원문은 `raw_utterance`에 보존하고 학습 입력은 `utterance`에 기록한다.
4. 검수자가 메뉴 ID, Intent, Slot, Batch 규칙과 Context 일치 여부를 확인한다.
5. 승인된 행을 `paraphrase_group_id` 단위로 80/10/10 분할한다.
6. CSV 원본에서 Split별 JSONL을 생성하고 모든 계약을 자동 검증한다.

### 목표 분포

| Label Group | 전체 | Train | Validation | Test |
|---|---:|---:|---:|---:|
| `ADD_ITEM` | 400 | 320 | 40 | 40 |
| `REMOVE_ITEM` | 260 | 208 | 26 | 26 |
| `UPDATE_QUANTITY` | 350 | 280 | 35 | 35 |
| `UPDATE_OPTION` | 300 | 240 | 30 | 30 |
| `QUERY_MENU` | 250 | 200 | 25 | 25 |
| `QUERY_CART` | 180 | 144 | 18 | 18 |
| `CONFIRM_ORDER` | 180 | 144 | 18 | 18 |
| `CANCEL` | 140 | 112 | 14 | 14 |
| `UNDO` | 180 | 144 | 18 | 18 |
| `REQUEST_REPEAT` | 120 | 96 | 12 | 12 |
| `REQUEST_SLOWER` | 120 | 96 | 12 | 12 |
| `REQUEST_DEFAULT_SPEED` | 120 | 96 | 12 | 12 |
| `MISSING_FIELD` | 120 | 96 | 12 | 12 |
| `AMBIGUOUS_TARGET` | 120 | 96 | 12 | 12 |
| `MIXED_INTENT` | 80 | 64 | 8 | 8 |
| `UNSUPPORTED_UTTERANCE` | 80 | 64 | 8 | 8 |
| **합계** | **3,000** | **2,400** | **300** | **300** |

정상 Command Label은 2,600개, 오류 Label은 400개다. 안전한 혼합 Command 행은
첫 번째 Intent의 Label Group 수량에 포함한다. `ADD_ITEM`에는 단일 메뉴, 복수 메뉴,
같은 메뉴·온도 반복, 같은 메뉴·다른 온도 발화를 모두 포함한다.

### 수집 표현 범위

Intent별로 다음 표현 차원을 고르게 포함하되 메뉴 표기는 공식 `name` 또는 승인된 `menu_aliases`만 사용한다.

- 존댓말·해요체·간결한 구어체
- 완전한 문장과 주어·목적어가 생략된 짧은 요청
- `한 잔`, `두 잔`, `3잔`, `하나`, `두 개` 등 유효한 수량 표현
- 조사와 연결어 변화: `하고`, `이랑`, `그리고`, `도`, `더`
- `따뜻하게`, `뜨겁게`, `차갑게`, `아이스로` 등 온도 표현
- `안 단`, `당도 낮은`, `카페인 없는`, `우유 안 들어간` 등 Menu DB 태그 별칭 표현
- `아아`, `뜨아`, `아라`, `뜨라`, `아바라`, `뜨바라` 등 승인된 메뉴 이름 별칭
- `음`, `저기`, `그럼` 같은 의미를 바꾸지 않는 발화 머뭇거림
- Cart가 필요한 추가 수량, 삭제, 수량 변경, 옵션 변경 발화
- `큰 사이즈`, `미디엄`, `작은 사이즈`, `샷 더`, `디카페인`, `시럽 한 번`, `얼음 적게` 등 승인된 음료 옵션 표현. Size Label은 `large`, `medium`, `small`을 사용한다.
- `방금 거 취소`, `마지막 변경 되돌려`처럼 대상을 다시 지정하지 않는 `UNDO` 발화
- 최대 두 개의 장바구니 변경과 마지막 `QUERY_CART`를 연결한 안전한 혼합 요청

띄어쓰기·문장부호 차이는 정제할 수 있지만 공식 메뉴명과 승인 별칭을 임의의 다른 단어로 치환하지 않는다.
메뉴 이름 별칭은 `menu_aliases`에 등록된 메뉴 ID·온도 매핑만 사용한다.
옵션 포함 별칭 `아샷추`, `아바샷`은 Menu ID·ICED·추가 샷 1회를 함께 Label한다.
현재 메뉴에 없는 `아초`, `아초샷`, `아돌라`는 정상 Label로 만들지 않는다.
조건 검색 표현은 `tag_definitions.aliases`에 등록된 표현을 사용해 표준 `query_tags`로 Label한다.

### 파일럿 200행

전체 3,000행 수집 전에 `data/nlu/raw/nlu-orders.csv`에 200행 파일럿을 구성해
문장 자연스러움, Label 정확성, 메뉴 정책과 검수 절차를 먼저 확인한다.

- Split: Train 160 / Validation 20 / Test 20
- 정상 Label: 176행 / 오류 Label: 24행
- 출처: 생성 시 전 행 `llm_synthetic`
- 검수 상태: 생성 시 전 행 `pending`, 검수자가 승인·반려를 직접 결정
- 범위: 12개 Intent, 오류 4종, 복수 메뉴, 조건 검색, 메뉴 상세 질문, UNDO,
  승인된 메뉴 별칭, 샷·카페인·시럽·얼음 옵션

파일럿 승인은 최종 3,000행 완성을 뜻하지 않는다. 검수 결과를 표현 Template과 Label
규칙에 반영한 뒤 전체 데이터 수집을 진행한다.

### Edge Cases

| ID | 상황 | Label 기준 |
|---|---|---|
| EC-01 | 한 발화에 같은 Intent의 메뉴가 여러 개 있음 | 발화 순서의 `OrderCommand[]` 하나로 유지 |
| EC-02 | 같은 메뉴·같은 온도가 반복됨 | 하나의 Command로 합치고 수량 합산 |
| EC-03 | 같은 메뉴의 HOT·ICED가 함께 주문됨 | 온도별 Command를 따로 유지 |
| EC-04 | 기존 수량에 한 잔을 더 요청함 | `cart_before_json`을 참고해 변경 후 최종 수량 Label 생성 |
| EC-05 | 필수 메뉴·수량·온도가 누락됨 | `MISSING_FIELD` |
| EC-06 | Cart에 같은 메뉴 HOT·ICED가 있는데 온도 없이 수정·삭제함 | `AMBIGUOUS_TARGET` |
| EC-07 | 안전한 장바구니 변경이 최대 두 개 섞임 | 발화 순서의 `OrderCommand[]`로 유지 |
| EC-08 | 장바구니 변경 뒤 현재 주문 조회를 요청함 | 마지막 `QUERY_CART` Command로 유지 |
| EC-09 | 결제·전체 취소·실행취소·메뉴 탐색·TTS 제어가 다른 요청과 섞임 | `MIXED_INTENT` |
| EC-10 | 주문 도메인 밖이거나 공식 메뉴 ID로 매핑할 수 없음 | `UNSUPPORTED_UTTERANCE` |
| EC-11 | 수량이 0 이하임 | 유효하지 않은 Command를 만들지 않고 `UNSUPPORTED_UTTERANCE` |
| EC-12 | 모델이 비정상 JSON·Schema·Intent를 출력함 | 학습 Label이 아니라 추론 평가 오류로 집계 |

## How

### 1. 기준 파일과 디렉터리

```text
src/config/menu.json                 # Menu ID·Category ID·온도 정책 SSOT
schemas/order-command.schema.json    # request_id 주입 후 런타임 검증
schemas/order-command-error.schema.json
data/nlu/raw/nlu-orders.csv          # 사람이 편집·검수하는 원본
data/nlu/processed/train.jsonl       # CSV에서 생성
data/nlu/processed/validation.jsonl  # CSV에서 생성
data/nlu/processed/test.jsonl        # CSV에서 생성
```

CSV만 수동 편집한다. `processed/*.jsonl`은 생성 결과이며 직접 수정하지 않는다.
메뉴 기준은 `src/config/menu.json`의 `version`과 함께 기록한다.
Git에는 CSV 원본만 저장하고 `processed/*.jsonl`은 추적하지 않는다. 학습·평가를
시작하기 전에 검증된 CSV에서 필요한 JSONL을 다시 생성한다.

### 2. CSV 한 행 계약

| Column | 필수 | 형식·의미 |
|---|:---:|---|
| `sample_id` | O | 전체에서 유일한 `nlu_000001` 형식 ID |
| `raw_utterance` | O | 수집 당시 원문, 수정 금지 |
| `utterance` | O | 정제 후 Local LLM에 전달할 최종 한국어 문장 |
| `cart_before_json` | O | 발화 직전 Cart의 JSON 배열, 빈 Cart는 `[]` |
| `label_type` | O | `commands` 또는 `error` |
| `label_group` | O | 12개 Intent 또는 학습 대상 오류 4개 중 하나 |
| `label_json` | O | `OrderCommand[]` 의미 Payload 또는 `OrderCommandError` JSON |
| `menu_version` | O | Label 작성에 사용한 Menu DB 버전 |
| `paraphrase_group_id` | O | 동일 의미·Template 변형을 묶는 누수 방지 ID |
| `source` | O | `human`, `template`, `llm_synthetic` 중 하나 |
| `split` | O | `train`, `validation`, `test` 중 하나 |
| `review_status` | O | `pending`, `approved`, `rejected` 중 하나 |
| `reviewer` | △ | 검수자 식별자, 승인 시 필수 |
| `notes` | △ | 판단 근거와 예외 기록 |

`cart_before_json`은 NLU에 필요한 의미 정보만 포함한다. 가격은 Order Engine 책임이므로 넣지 않는다.

```json
[
  {
    "menu_id": "americano",
    "quantity": 1,
    "temperature": "iced",
    "options": {
      "size": null,
      "extra_shots": null,
      "caffeine": null,
      "syrup_pumps": null,
      "ice_amount": null
    }
  }
]
```

### 3. 정상 Label 계약

Local LLM 학습 Label에는 다음 의미 필드 8개를 항상 포함한다. 사용하지 않는 값은 생략하지 않고 `null`로 둔다.

```json
[
  {
    "intent": "ADD_ITEM",
    "target_item_id": "americano",
    "category_id": null,
    "quantity": 2,
    "temperature": "iced",
    "query_tags": null,
    "detail_fields": null,
    "options": null
  }
]
```

- `request_id`는 Label에 넣지 않고 검증된 Payload마다 NLU 어댑터가 UUID v4를 주입한다.
- 가격, 총액, `confirmation_required`와 정의되지 않은 추가 필드는 금지한다.
- `target_item_id`와 `category_id`는 해당 `menu_version`의 공식 ID만 허용한다.
- `quantity`는 증감량이 아니라 명령 실행 후 최종 수량이다.
- `query_tags`는 `QUERY_MENU` 조건 검색에서만 사용하며 Menu DB의 표준 태그 ID를 기록한다.
- `detail_fields`는 단일 메뉴 상세 질문에서만 사용하며 질문한 정보 항목을 발화 순서대로 기록한다.
- `options`는 `ADD_ITEM`, `UPDATE_OPTION`에서만 사용하며 Size·샷·카페인·시럽·얼음 하위 필드를 `docs/specs/order-command.md`와 동일하게 유지한다. 샷·시럽은 Cart Context를 반영한 변경 후 최종 값으로 기록한다.
- Size를 생략한 음료 주문은 `size=null`로 Label하고 Order Engine이 기본 MEDIUM으로 계산한다. SMALL/MEDIUM/LARGE가 명시된 발화만 각각 `small`, `medium`, `large`로 Label한다.
- 같은 Intent의 복수 Command는 기존 계약을 따른다. 서로 다른 Intent는 안전한 장바구니 변경 최대 두 개와 마지막 `QUERY_CART`만 허용한다.
- 혼합 Command 행의 `label_group`은 배열의 첫 번째 Intent로 기록하고 목표 분포도 해당 Group에 포함한다.
- 삭제·수량 변경·옵션 변경 대상은 `cart_before_json`에서 하나로 식별되어야 한다.
- 세부 Intent별 필수·`null` 필드는 `docs/specs/order-command.md`를 따른다.

### 4. 오류 Label 계약

발화 의미로 직접 판정 가능한 다음 오류만 학습 Label로 사용한다.

- `MISSING_FIELD`: `field`와 가능한 경우 `candidates`를 기록한다.
- `AMBIGUOUS_TARGET`: Cart 후보를 근거로 `field`와 `candidates`를 기록한다.
- `MIXED_INTENT`: 순차 실행 허용 목록 밖의 서로 다른 Intent 요청이 한 발화에 함께 있을 때 사용한다.
- `UNSUPPORTED_UTTERANCE`: 주문 외 발화, 공식 메뉴에 없는 요청, 비정상 수량에 사용한다.

오류 Label은 `schemas/order-command-error.schema.json`의 모든 필드를 만족하고,
동일 조건에는 동일한 안내 문장 Template을 사용한다. P0 오류는 모두 `retryable=true`다.

| 오류 조건 | `message` Template |
|---|---|
| `MISSING_FIELD`, `field="temperature"` | `{메뉴명}의 온도를 따뜻한 걸 원하시나요, 차가운 걸 원하시나요?` |
| `MISSING_FIELD`, `field="quantity"` | `{메뉴명}의 수량을 말씀해 주세요.` |
| `MISSING_FIELD`, `field="target_item_id"` | `어떤 메뉴를 원하시나요?` |
| `AMBIGUOUS_TARGET`, `field="temperature"` | `따뜻한 {메뉴명}{과/와} 차가운 {메뉴명} 중 어떤 메뉴를 변경하시나요?` |
| `AMBIGUOUS_TARGET`, `field="target_item_id"` | `어떤 메뉴를 변경하시나요? 메뉴 이름을 말씀해 주세요.` |
| `MIXED_INTENT` | `사용자의 주문을 이해하지 못했습니다. 한 번에 하나씩 주문해 주시면 감사하겠습니다.` |
| `UNSUPPORTED_UTTERANCE` | `죄송합니다. 메뉴 이름과 수량을 다시 말씀해 주세요.` |

예를 들어 아메리카노의 필수 온도가 누락되면 `message`는
`아메리카노의 온도를 따뜻한 걸 원하시나요, 차가운 걸 원하시나요?`로 Label한다.
안내 문구를 모델이 자유롭게 바꾸거나 새로 만들지 않는다.

`INVALID_JSON`, `SCHEMA_ERROR`, `UNKNOWN_INTENT`는 사용자 문장의 정답이 아니다.
이 세 코드는 Baseline/Fine-tuning 추론 결과를 Parser와 Schema Validator가 검사할 때만 집계한다.

### 5. 정제 규칙

- `raw_utterance`는 보존하고 `utterance`에만 Unicode NFC, 앞뒤 공백 제거, 연속 공백 축소를 적용한다.
- 메뉴명, 수량, 온도, 부정·수정 표현처럼 의미에 영향을 주는 단어는 자동 치환하지 않는다.
- 말투, 어미, 조사, 유효한 머뭇거림은 표현 다양성이므로 제거하지 않는다.
- 개인정보, 욕설, 의미 없는 문자 반복과 주문 학습에 사용할 수 없는 문장은 `rejected` 처리한다.
- 같은 `utterance + cart_before_json + label_json` 조합의 완전 중복은 한 건만 유지한다.
- LLM 생성 문장은 반드시 `source=llm_synthetic`로 표시하고 사람이 승인해야 한다.

### 6. Split과 누수 방지

- 최종 비율은 Train 2,400 / Validation 300 / Test 300으로 고정한다.
- 각 `label_group`은 목표 분포표의 수량을 그대로 유지한다.
- 동일 Template, 숫자·메뉴 치환, 존댓말 변형은 같은 `paraphrase_group_id`로 묶는다.
- 같은 `paraphrase_group_id`는 반드시 하나의 Split에만 존재해야 한다.
- Test는 모델·Prompt 선택과 Fine-tuning에 사용하지 않고 최종 비교에서만 사용한다.
- 분할 후 Test를 보고 문장을 수정했다면 새 Dataset 버전으로 올리고 분할을 다시 검증한다.

### 7. JSONL 생성 계약

CSV의 승인된 한 행은 JSONL의 한 줄로 변환한다.

```json
{
  "sample_id": "nlu_000001",
  "input": {
    "utterance": "아이스 아메리카노 두 잔 주세요",
    "cart_before": []
  },
  "output": {
    "type": "commands",
    "value": [
      {
        "intent": "ADD_ITEM",
        "target_item_id": "americano",
        "category_id": null,
        "quantity": 2,
        "temperature": "iced",
        "query_tags": null,
        "detail_fields": null,
        "options": null
      }
    ]
  },
  "metadata": {
    "label_group": "ADD_ITEM",
    "menu_version": "1.3",
    "source": "human",
    "split": "train"
  }
}
```

동일한 CSV와 생성기 버전은 바이트 단위로 동일한 JSONL을 만들어야 한다.
파일 인코딩은 UTF-8, JSON 직렬화는 한국어를 Unicode escape로 강제 변환하지 않는다.
생성된 각 행은 `metadata.split`으로 자신의 Split을 식별한다. 학습·평가 도구는
파일명이 아니라 이 값을 기준으로 Split 역할을 검증하며, Test Split이 학습이나
checkpoint 선택에 쓰이는 것을 차단한다.

### 8. 검증·생성 명령

수집 중에는 일부 행을 허용하는 `draft`, 최종 산출물에는 목표 분포와 전 행 승인을
강제하는 `final`을 사용한다.

```powershell
$env:PYTHONPATH='src'
python -m adapters.nlu.dataset_tooling validate --mode draft
python -m adapters.nlu.dataset_tooling build --mode draft
python -m adapters.nlu.dataset_tooling validate --mode final
python -m adapters.nlu.dataset_tooling build --mode final
```

`build`는 전체 검증과 임시 JSONL 생성이 모두 성공한 뒤에만 Split별 기존 파일을
교체한다. 검증 또는 임시 생성이 실패하면 기존 `processed/*.jsonl`을 유지한다.
생성된 JSONL은 `.gitignore` 대상이며 CSV가 데이터셋의 단일 진실 공급원이다.

## AC (Given-When-Then)

### AC-01 · 전체 수량과 분포
- **GIVEN**: 승인된 NLU CSV가 준비됐을 때
- **WHEN**: `label_group`과 `split`별 행 수를 계산한다
- **THEN**: 전체 3,000행과 목표 분포표의 모든 수량이 정확히 일치한다.

### AC-02 · CSV 한 행과 Batch 보존
- **GIVEN**: 한 발화에 같은 Intent의 메뉴 두 개 또는 허용된 혼합 Intent가 포함됐을 때
- **WHEN**: 원본 CSV와 생성 JSONL을 확인한다
- **THEN**: 발화는 한 행·한 줄이며 두 Command의 순서가 `label_json` 배열에 보존된다.

### AC-03 · 의미 필드와 request_id 경계
- **GIVEN**: `label_type=commands`인 모든 행이 있을 때
- **WHEN**: 각 Command의 필드 집합을 검사한다
- **THEN**: 의미 필드 8개만 존재하고 `request_id`, 가격, 총액, 추가 필드는 0건이다.

### AC-04 · 공식 Menu DB 준수
- **GIVEN**: 데이터셋의 모든 정상 Label이 있을 때
- **WHEN**: `menu_version`에 해당하는 Menu DB와 ID를 대조한다
- **THEN**: 존재하지 않는 메뉴·카테고리 ID는 0건이고 별칭 발화의 Label도 공식 Menu ID를 사용한다.

### AC-05 · Context 기반 최종 수량
- **GIVEN**: Cart에 아이스 아메리카노 1잔이 있고 사용자가 한 잔 더 요청했을 때
- **WHEN**: 정답 Label을 확인한다
- **THEN**: `ADD_ITEM`, `quantity=2`이며 증감량 `1`로 Label하지 않는다.

### AC-06 · 오류 Label 범위
- **GIVEN**: `label_type=error`인 400행이 있을 때
- **WHEN**: 오류 코드와 수량을 검사한다
- **THEN**: `MISSING_FIELD` 120, `AMBIGUOUS_TARGET` 120, `MIXED_INTENT` 80,
  `UNSUPPORTED_UTTERANCE` 80이고 기술 오류 3종은 0건이다.

### AC-07 · 중복과 Split 누수 차단
- **GIVEN**: Train/Validation/Test 분할이 끝났을 때
- **WHEN**: ID, 정제 발화·Context·Label 조합, `paraphrase_group_id`를 검사한다
- **THEN**: 중복 ID, 완전 중복, 둘 이상의 Split에 걸친 그룹이 각각 0건이다.

### AC-08 · 승인 데이터만 생성
- **GIVEN**: `pending`, `approved`, `rejected` 행이 섞인 CSV가 있을 때
- **WHEN**: JSONL 생성기를 실행한다
- **THEN**: `approved` 행만 생성되고 승인 행에는 `reviewer`가 존재한다.

### AC-09 · CSV-JSONL 재현성
- **GIVEN**: 동일한 CSV와 동일한 생성기 버전이 있을 때
- **WHEN**: JSONL을 두 번 생성한다
- **THEN**: 행 수, 행 순서, 파일 내용과 checksum이 모두 동일하다.

### AC-10 · 사람 검수와 출처 추적
- **GIVEN**: 최종 3,000행이 있을 때
- **WHEN**: `source`, `review_status`, `reviewer`를 검사한다
- **THEN**: 출처 누락이 0건이고 모든 행이 사람에게 승인됐다.
