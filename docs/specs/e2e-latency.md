---
title: "음성 주문 E2E Latency 측정 및 Provider Fallback"
tags: [spec]
---

# 음성 주문 E2E Latency 측정 및 Provider Fallback

> 이 문서는 음성 주문의 성능 수치와 판정 규칙의 Source of Truth다. 배포 위치 변경은
> `docs/trd.md`의 **Deployment Plan B**, 모델 교체는 이 문서의 **Latency Provider
> Fallback**으로 구분한다.

## Why

- **페르소나**: 시스템이 자신의 말을 들었는지 확신하기 어려워 긴 침묵에 부담을 느끼는 고령 사용자
- **상황**: Local STT·NLU·Order Engine·TTS를 거쳐 화면과 음성으로 주문 결과를 안내한다.
- **문제**:
  1. TTS 단일 모델 생성 시간과 전체 음성 주문 응답 시간이 같은 `Latency`로 기록돼 왔다.
  2. Mock Pipeline 수치와 실제 모델·재생 경로 수치가 구분되지 않으면 제품 요구 충족 여부를 판정할 수 없다.
  3. Local Pipeline이 느릴 때 병목 확인 없이 모든 모델을 외부 API로 바꾸면 Context 처리와 운영 경계가 불필요하게 달라질 수 있다.
- **측정 지표**: Warm Time to First Audio, Time to Visual Response, Cold Start, 구간별 Latency

## Goal

- **해결 목표**: 정상적인 Warm 주문 Turn에서 발화 종료부터 첫 음성 응답 시작까지의 시간을 재현 가능하게 측정하고, 병목에 한정해 Provider Fallback을 판단한다.
- **성공 기준**:
  - Target: `E2E <= 1.2초`
  - Requirement: `E2E <= 1.5초`
  - 대표 주문 문장 10개를 각각 Warm 5회 측정한 50 Turn의 nearest-rank p95로 최종 판정한다.
  - Requirement 판정에는 p95 1.5초 이하, 1.5초 초과 최대 2 Turn, 처리 실패 0건을 모두 요구한다.
  - Real Pipeline, Mock Pipeline, 개별 STT/TTS Benchmark 결과를 서로 다른 결과 유형으로 기록한다.
  - Time to Visual Response와 Cold Start를 Warm E2E와 별도 지표로 기록한다.
- **Out of Scope**:
  - 사용자가 말하는 데 걸린 시간
  - Visual Response와 Cold Start의 목표 수치 확정
  - Runtime 자동 Provider 전환
  - 외부 STT/TTS 공급자 선정
  - Deployment Plan B의 External Server 공급자·전환 절차

## What

### 측정 구간과 판정

```text
input_end
  = 사용자 발화가 끝나 VAD가 입력 종료를 확정한 시점

first_audio_start
  = Mallo 응답의 첫 재생 가능 오디오가 실제 재생을 시작한 시점

warm_e2e
  = first_audio_start - input_end

visual_response
  = order_result_visible - input_end
```

Warm E2E는 필요한 모델과 서비스가 이미 로딩된 일반 주문 Turn에서 측정한다. Cold
Start는 최초 로딩·초기화를 포함한 별도 지표이며 Warm 요구사항 판정에 포함하지 않는다.

| 50 Turn 집계 결과 | 판정 |
|---|---|
| `p95 <= 1.2초`, 1.5초 초과 최대 2 Turn, 실패 0건 | 목표 성능 달성 |
| `1.2초 < p95 <= 1.5초`, 1.5초 초과 최대 2 Turn, 실패 0건 | 목표 미달, 요구사항 충족 |
| `p95 > 1.5초`, 1.5초 초과 3 Turn 이상 또는 처리 실패 1건 이상 | 요구사항 미달, 병목 분석·최적화·Fallback 검토 |

최종 판정은 nearest-rank p95를 사용한다. 보고서에는 평균·중앙값·p95·최댓값·1.5초 초과 Turn 수·처리 실패 수와 원시 Turn별 값을 함께 보존한다.

### 반복 및 Warm-up 조건

- Provider 조합별 최초 3 Turn은 모델·CUDA kernel·캐시 Warm-up으로 실행하고 통계에서 제외한다.
- 대표 주문 문장 10개를 고정하고 각 문장을 Warm 상태에서 5회 측정해 총 50 Turn을 판정 모집단으로 사용한다.
- Cold Start는 프로세스를 초기화한 상태에서 3회 별도 측정하며 Warm 판정에 포함하지 않는다.
- 대표 문장, 실행 순서, 장비, OS, Python, torch, CUDA, Provider와 checkpoint를 결과에 기록한다.

#### 2026-08-28 최종 제출 측정 Protocol Deviation

기능동결 이후 I-08 최종 실측에서는 입력 재현성과 공개 근거를 우선해 **STT Showcase 고정 음원 5종 × 10회 = 50 Turn**으로 반복 배분을 변경했다. 이는 위의 최초 `10문장 × 5회` 계약을 소급 변경하는 것이 아니라 최종 제출 측정에서 사용한 예외를 기록하는 것이다.

- 총 판정 모집단 50 Turn은 유지한다.
- 최초 Warm-up 3 Turn 제외, 실제 Provider 조합, VAD `input_end` → 실제 `Audio.onplay` 경계, Cold Start 3회, nearest-rank p95는 그대로 유지한다.
- Target `1.2초`, Requirement `1.5초`와 1.5초 초과 Turn 허용 수는 변경하지 않는다.
- 결과가 기준을 넘으면 그대로 Requirement 미달로 기록한다.
- 최종 측정 결과와 raw Turn evidence는 `docs/evidence/e2e/i08-final-real-e2e.md`를 따른다.

### 측정 유형 분리

| `measurement_type` | 의미 | 제품 E2E 판정 사용 |
|---|---|---:|
| `REAL_E2E` | 실제 마이크/VAD, 실제 STT·NLU·Order Engine·TTS, 실제 UI·재생 경로 | O |
| `MOCK_E2E` | 하나 이상의 Mock Adapter를 사용한 계약·계측 검증 | X |
| `COMPONENT_BENCHMARK` | STT 또는 TTS 단일 컴포넌트 측정 | X |

Mock E2E와 Component Benchmark는 계측 도구 및 병목 후보를 검증하는 자료다. 두 결과를
발화 종료부터 첫 음성 재생까지의 Real E2E 달성 근거로 사용하지 않는다.

### Latency Provider Fallback

```text
Real E2E 측정
  ↓
병목 Pipeline 확인
  ↓
Local 최적화
  ↓
다른 Local 모델 검토
  ↓
여전히 Requirement 미달
  ↓
병목 Pipeline만 교체
```

- `Plan B-1`: Local STT → Local NLU → External TTS
- `Plan B-2`: External STT → Local NLU → Local TTS
- NLU는 주문 상태와 Context 처리에 밀접하므로 Local 유지가 우선이다.
- Real E2E가 1.5초를 초과했다는 이유만으로 모든 모델을 외부 API로 교체하지 않는다.

### Edge Cases

| ID | 상황 | 처리 |
|---|---|---|
| EC-01 | 모델 로딩이 포함된 첫 Turn | `cold_start=true`로 기록하고 Warm 판정에서 제외 |
| EC-02 | Mock Adapter가 하나라도 포함됨 | `MOCK_E2E`로 기록하고 제품 요구 충족 근거로 사용하지 않음 |
| EC-03 | TTS 생성 완료 시각만 있고 실제 재생 시작 시각이 없음 | E2E 판정 불가로 기록 |
| EC-04 | UI가 음성보다 먼저 갱신됨 | Visual Response와 First Audio를 각각 기록 |
| EC-05 | 개별 TTS TTFB가 1.2초 이하임 | 컴포넌트 결과로만 보존하고 E2E 달성으로 판정하지 않음 |
| EC-06 | Real E2E가 1.5초를 초과함 | 구간별 병목 없이 Provider 교체를 결정하지 않음 |

## How

각 Turn은 최소 다음 timestamp와 metadata를 남긴다.

```text
input_end
stt_end
nlu_end
order_end
order_result_visible
tts_request
first_audio_start
tts_end

measurement_type = REAL_E2E | MOCK_E2E | COMPONENT_BENCHMARK
cold_start = true | false
provider_set = STT/NLU/TTS provider 식별자
```

- `input_end`는 오디오 청크 수신 시각이 아니라 VAD가 사용자 발화 종료를 확정한 시각이다.
- `first_audio_start`는 합성 함수 반환이나 WAV 저장 완료가 아니라 사용자 단말의 실제 재생 시작 이벤트다.
- UI는 Order Engine 결과가 확정되면 TTS 전체 생성을 기다리지 않고 갱신할 수 있어야 한다.
- 구간별 값과 전체 값은 같은 monotonic clock 기준으로 계산한다.
- 장비, 네트워크, 대표 문장, 실행 순서, 패키지·CUDA 버전과 집계 통계를 결과와 함께 기록한다.

## AC (Given-When-Then)

### AC-01 · Warm E2E 경계

- GIVEN: 모델과 서비스가 로딩된 실제 주문 Turn의 `input_end`와 `first_audio_start`가 있다.
- WHEN: 두 시각의 차이를 계산한다.
- THEN: 사용자 발화 시간과 Cold Start를 제외한 Warm E2E가 산출된다.

### AC-02 · Target과 Requirement 구분

- GIVEN: Warm E2E가 각각 `1.1초`, `1.3초`, `1.6초`인 Turn이 있다.
- WHEN: 성능 구간을 분류한다.
- THEN: 차례대로 `목표 달성`, `요구사항만 충족`, `요구사항 미달`로 기록된다.

### AC-03 · Mock 결과 격리

- GIVEN: Mock STT 또는 Mock TTS를 사용하는 측정이 있다.
- WHEN: 결과를 저장한다.
- THEN: `measurement_type=MOCK_E2E`이며 Real E2E 요구 충족 판정에는 포함되지 않는다.

### AC-04 · TTS Benchmark 격리

- GIVEN: TTS 합성 호출부터 첫 chunk 또는 WAV 완료까지의 단일 모델 수치가 있다.
- WHEN: E2E 보고서를 생성한다.
- THEN: `COMPONENT_BENCHMARK`로 표시되고 사용자 발화 종료 기준 E2E로 표현되지 않는다.

### AC-05 · Visual Response 분리

- GIVEN: Order Engine 완료 뒤 UI가 갱신되고 이후 음성 재생이 시작된다.
- WHEN: 두 응답 시간을 계산한다.
- THEN: Time to Visual Response와 Time to First Audio가 별도 필드로 기록된다.

### AC-06 · 병목 한정 Fallback

- GIVEN: Real Warm E2E가 Requirement를 넘고 구간별 측정에서 TTS가 병목으로 확인됐다.
- WHEN: Local 최적화와 다른 Local 모델 검토 후에도 미달한다.
- THEN: External TTS를 우선 검토하고 STT·NLU·Order Engine을 일괄 교체하지 않는다.

### AC-07 · 반복과 Warm-up

- GIVEN: 하나의 고정된 Real Provider 조합과 대표 주문 문장 10개가 있다.
- WHEN: 최초 Warm-up 3 Turn을 제외하고 문장별 5회씩 측정하며 Cold Start 3회를 별도 실행한다.
- THEN: Warm 판정 모집단은 정확히 50 Turn이고 Cold Start 결과는 포함되지 않는다.

### AC-08 · 최종 집계 판정

- GIVEN: 50개 Warm Time to First Audio와 각 Turn의 성공 여부가 있다.
- WHEN: nearest-rank p95, 평균, 중앙값, 최댓값, 1.5초 초과 Turn 수와 실패 수를 계산한다.
- THEN: p95가 1.2초 이하면 Target, 1.5초 이하면 Requirement 후보이며, Requirement는 1.5초 초과 최대 2 Turn과 실패 0건을 함께 충족할 때만 통과한다.
