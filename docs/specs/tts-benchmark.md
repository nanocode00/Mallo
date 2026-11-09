---
title: "T-22 — TTS 성능 Benchmark"
tags: [spec]
---

# T-22 — TTS 성능 Benchmark

## Why

- **페르소나**: 말로(Mallo)의 TTS 후보를 같은 장치에서 비교하고 시연 가능성을 판단하는 TTS 담당자
- **상황**: MeloTTS Baseline과 Fine-tuned MeloTTS·Qwen3-TTS의 생성 지연·TTFB·RTF·메모리를 동일한 20문장으로 측정해야 한다.
- **문제**:
  1. 모델별 측정 코드가 다르면 로딩 시간과 WAV 저장 시간을 포함하는 범위가 달라진다.
  2. 평균만 기록하면 일부 문장에서 발생하는 긴 지연을 발견하기 어렵다.
  3. 스트리밍과 non-streaming의 TTFB 의미가 달라 결과를 직접 비교하기 어렵다.
- **측정 지표**: 문장당 cold 1회·warm 5회 충족률, 유효 WAV 비율, 필수 통계 필드 생성률, 재실행 가능한 환경 정보 기록률

## Goal

- **해결 목표**: T-21 평가 문장 20개에 대해 모든 TTS 후보가 같은 측정 경계와 결과 Schema를 사용하도록 공통 Benchmark runner를 제공한다.
- **성공 기준**:
  - 각 문장마다 새 backend를 생성하여 모델 로딩을 포함한 cold 1회와 같은 backend의 warm 5회를 기록한다.
  - 총 120개 성공 측정에서 생성 지연, TTFB, 음성 길이, RTF와 Peak RAM을 기록한다.
  - VRAM 측정을 지원하는 backend는 Peak VRAM을 기록하고, 지원하지 않으면 `null`과 측정 불가 사유를 기록한다.
  - cold/warm별 평균·중앙값·nearest-rank p95를 계산한다.
  - 결과에 Git SHA, OS, CPU, RAM, Python, 모델·revision, device와 streaming 여부를 기록한다.
- **Out of Scope**:
  - MeloTTS·Qwen3-TTS 실제 Adapter와 모델 설치
  - MOS·SIM 및 블라인드 청취 평가
  - 여러 모델의 최종 점수 계산
  - 후처리 time-stretch 또는 모델별 text 수정
  - 공통 `TTS.synthesize()` 반환 타입 변경

## What

### Happy Path

1. runner가 검증된 T-21 JSON을 읽는다.
2. 문장마다 backend factory 호출 직전부터 첫 WAV 저장 완료까지 cold 시간을 측정한다.
3. 생성 WAV를 decode하여 실제 음성 길이를 계산한다.
4. 같은 backend로 같은 문장을 5회 더 합성하여 warm 결과를 기록한다.
5. 20문장을 모두 측정한 뒤 cold/warm별 통계와 환경 정보를 JSON으로 저장한다.

### Edge Cases

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | backend 생성 또는 합성 실패 | 해당 run에 오류 유형·메시지를 기록하고 나머지 문장을 계속 측정 |
| EC-02 | WAV가 없거나 decode 불가 | run 실패로 기록하고 RTF를 계산하지 않음 |
| EC-03 | WAV 길이가 0초 | run 실패로 기록하고 0으로 나누지 않음 |
| EC-04 | streaming backend가 첫 chunk 시간을 주지 않음 | 계약 오류로 실패 처리 |
| EC-05 | 첫 chunk 시간이 전체 생성 시간보다 큼 | 계약 오류로 실패 처리 |
| EC-06 | VRAM 측정 미지원 | `peak_vram_mb=null`, 사유 `unsupported` 기록 |
| EC-07 | 일부 run 실패 | 성공 run만 통계에 사용하되 실패 수와 성공률을 함께 기록 |

## How

### Backend 계약

Benchmark 전용 계약은 공통 애플리케이션 `TTS` Protocol을 변경하지 않는다.

```python
class BenchmarkBackend(Protocol):
    model_id: str
    model_revision: str
    device: str
    streaming: bool

    def synthesize_to_file(self, text: str, output_path: Path) -> BackendMeasurement:
        ...
```

`BackendMeasurement.first_audio_seconds`는 합성 호출 직후부터 첫 재생 가능 chunk까지 backend가 측정한 시간이다. non-streaming에서는 runner가 WAV 저장 완료 시점을 TTFB로 사용하므로 `None`이어도 된다. `peak_vram_mb`는 backend가 실행 직전 peak 통계를 초기화하고 실행 직후 읽은 값이며 미지원 시 `None`이다.

### 측정식

```text
generation_latency_seconds = backend factory 호출 직전(cold) 또는 합성 호출 직전(warm)부터 WAV 저장 완료까지
TTFB_seconds               = streaming 첫 chunk 시간, non-streaming은 generation_latency_seconds
audio_duration_seconds     = 저장 WAV frame 수 / sample rate
RTF                        = generation_latency_seconds / audio_duration_seconds
Peak RAM                   = 실행 직후 프로세스 ru_maxrss의 MiB 환산값
```

- cold는 문장마다 새 backend를 만들므로 모델 로딩을 포함한다.
- warm은 해당 문장의 cold에 사용한 backend를 그대로 사용한다.
- 출력 파일은 `{sentence_id}/{cold|warm}_{repeat}.wav`로 분리한다.
- p95는 정렬된 값의 `ceil(0.95 × N)`번째 값을 사용하는 nearest-rank 방식이다.
- 실패 메시지는 내부 stack trace 없이 예외 클래스와 한 줄 메시지만 저장한다.
- 결과 JSON은 원문 T-21 text를 포함할 수 있으나 AI Hub 원문과 학습 manifest는 포함하지 않는다.

## AC (Given-When-Then)

### AC-01 · 동일 문장·반복 횟수

- GIVEN: 검증된 T-21 평가 문장 20개와 backend factory가 있다.
- WHEN: Benchmark를 실행한다.
- THEN: 문장별 cold 1회·warm 5회, 총 120개 run이 동일 ID·text 순서로 기록된다.

### AC-02 · 측정값 계산

- GIVEN: decode 가능한 WAV를 생성한 성공 run이 있다.
- WHEN: 결과를 계산한다.
- THEN: 생성 지연·TTFB·음성 길이·RTF·Peak RAM 및 지원 시 Peak VRAM이 0보다 큰 유효값으로 기록된다.

### AC-03 · cold와 warm 경계

- GIVEN: backend factory와 합성 호출을 구분할 수 있다.
- WHEN: cold와 warm을 측정한다.
- THEN: cold latency만 backend 생성 시간을 포함하고 warm 5회는 같은 backend instance를 사용한다.

### AC-04 · 통계와 실패 격리

- GIVEN: 성공 run과 실패 run이 섞여 있다.
- WHEN: 결과를 집계한다.
- THEN: 성공값만으로 평균·중앙값·nearest-rank p95를 계산하고 전체·성공·실패 수를 함께 기록한다.

### AC-05 · 재현 환경

- GIVEN: Benchmark 결과 JSON이 있다.
- WHEN: 환경 metadata를 검사한다.
- THEN: Git SHA, 실행 시각, OS, CPU, RAM, Python, 모델·revision, device, streaming과 반복 정책이 존재한다.
