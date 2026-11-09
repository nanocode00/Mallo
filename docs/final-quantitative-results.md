---
title: "말로(Mallo) 최종 발표용 정량 결과"
tags: [doc, evaluation, final]
---

# 말로(Mallo) 최종 발표용 정량 결과

> **Ticket:** E-09 발표용 정량 결과 정리  
> **작성 기준:** 2026-08-28 기능 동결 시점의 저장소 기록과 I-08 최종 Real E2E 측정  
> **원칙:** 검증·기록된 STT/NLU/TTS/통합 결과를 발표 자료에 바로 옮길 수 있는 형태로 집계한다. 성능 기준은 `docs/specs/e2e-latency.md`, I-08 상세 evidence는 `docs/evidence/e2e/i08-final-real-e2e.md`를 따른다.

## 1. 한눈에 보는 핵심 결과

| 영역 | 최종/서비스 후보 | 발표용 핵심 수치 | 해석 |
|---|---|---|---|
| STT | Whisper Medium QLoRA Domain merged BF16 | CER **0.1131**, WER **0.3352**, 메뉴 Recall **89.5%**, 수량 Recall **99.3%**, 옵션 Recall **86.3%**, Latency **0.505s/sample** | 주문 도메인 핵심 정보 인식률을 별도 측정해 최종 STT 선정 |
| NLU | Qwen3-0.6B 서비스 후보 | Intent **100%**, Slot **96.78%**, Error Code **96.67%**, Schema Valid **100%**, Invalid Menu **0%**, Warm p95 **1.182s** | 1.7B보다 낮은 지연으로 서비스 후보화. Exact Match는 **63.71%**로 semantic 지표와 분리 해석 |
| TTS | MeloTTS Friendly | 평균 생성 지연 **0.2041s**, 평균 RTF **0.0485**, 44.1kHz | Qwen 계열 대비 실시간 대화성에서 큰 우위로 최우선 후보 선정 |
| 통합 | I-08 Final Real E2E | Warm 평균 **1.916s**, p95 **3.338s**, 최대 **3.448s**, 1.5초 초과 **30/50**, Playback Failure **0** | 초기 1.5초 Requirement 미달. Rule-First p95 **0.967s** vs Qwen fallback p95 **3.386s**로 병목 경로 분리 |
| 사용자 조사 | 60대 13명 | 메뉴 탐색·옵션 선택 어려움 **8/13**, 실수 후 재시작 경험 **7/13**, 음성 오인식 불안 **6/13** | Voice-first + 큰 글씨 GUI + 오류 복구 방향의 근거 |

## 2. STT 결과

### 2.1 모델 크기 비교

화자 단위 split과 BF16 조건에서 Whisper base/small/medium을 비교했다.

| 모델 | Validation CER | Validation WER | Latency | VRAM |
|---|---:|---:|---:|---:|
| Whisper Base | 0.5577 | 0.9239 | 0.422s | 0.17GB |
| Whisper Small | 0.3655 | 0.6487 | 0.710s | 0.55GB |
| Whisper Medium | **0.2199** | **0.4965** | 1.093s | 1.58GB |

발표 메시지: **정확도를 우선해 Medium을 선택하고, 이후 주문 도메인 적응과 후처리를 진행했다.**

### 2.2 최종 주문 도메인 STT

| 지표 | 최종 결과 |
|---|---:|
| CER | **0.1131** |
| WER | **0.3352** |
| 메뉴 Recall | **89.5%** (453/506) |
| 수량 Recall | **99.3%** (405/408) |
| 옵션 Recall | **86.3%** |
| 추론 지연 | **0.505s/sample** |

최종 선택 모델은 `whisper-medium-qlora-domain/merged-bf16`이다. 일반 CER/WER뿐 아니라 실제 주문 성공에 직접 영향을 주는 메뉴·수량·옵션 Recall을 함께 사용했다.

## 3. NLU 결과

### 3.1 최종 데이터셋

- 총 **3,000행**
- Train **2,400** / Validation **300** / Test **300**
- 전 행 approved
- 16개 Label Group 목표 분포 확정
- 동일 입력에서 processed split을 반복 생성했을 때 checksum이 동일하도록 재현성 검증

### 3.2 Qwen3-0.6B 서비스 후보

| 지표 | 결과 |
|---|---:|
| Intent Accuracy | **100%** |
| Slot Accuracy | **96.78%** |
| Exact Match | **63.71%** |
| Error Code Accuracy | **96.67%** |
| Multi-command Order Accuracy | **100%** |
| Schema Valid Rate | **100%** |
| Invalid Menu Output Rate | **0%** |
| Warm Latency Median | **858ms** |
| Warm Latency p95 | **1.182s** |

발표 메시지: **문자열 완전 일치율보다 실제 주문 의미·슬롯·Schema 안전성을 우선해 평가했다.** Exact Match가 상대적으로 낮아도 Intent/Slot/Schema/Invalid Menu 지표가 높아 실제 주문 결과와 문자열 차이를 분리해서 해석한다.

### 3.3 Qwen3-1.7B 최종 Test 참고 결과

1.7B 보정 adapter는 학습·모델 선택에 사용하지 않은 Test 300건으로 최종 평가했으나 production gate를 통과하지 못했다.

| 지표 | 결과 |
|---|---:|
| Intent Accuracy | 95.3846% |
| Slot Accuracy | 97.1978% |
| Exact Match | 88.6667% |
| JSON Schema Valid Rate | 99.6667% |
| Invalid Menu Output Rate | 0% |
| Error Code Accuracy | **70%** |
| Warm Latency Median | **5.70s** |
| Warm Latency p95 | **8.40s** |

발표 메시지: **모델이 커진다고 서비스 적합성이 자동으로 좋아지지 않았다.** 1.7B는 Exact Match는 높았지만 오류 코드 정확도와 지연 요구 때문에 production gate에 실패했고, 서비스 후보는 0.6B로 축소했다.

## 4. TTS 결과

동일한 대표 주문 문장 20개를 GPU 환경에서 비교했다.

| 모델 | 평균 Latency | Median | 평균 RTF | Sample Rate | 판단 |
|---|---:|---:|---:|---:|---|
| MeloTTS Baseline | 0.1985s | 0.1814s | **0.0403** | 44.1kHz | 빠르지만 어조가 상대적으로 단조로움 |
| **MeloTTS Friendly** | **0.2041s** | **0.1928s** | **0.0485** | **44.1kHz** | **최우선 서비스 후보** |
| Qwen3-TTS Baseline | 6.9075s | 6.5844s | 1.4620 | 24kHz | 자연스러우나 interactive 서빙 지연 큼 |
| Qwen3-TTS Friendly | 28.1953s | 34.0154s | 1.5732 | 24kHz | 친절체 전이는 확인했으나 실시간 서비스 부적합 |

MeloTTS Friendly는 Baseline 대비 지연 증가가 약 5.6ms 수준에 그치면서 0.2초대 합성을 유지했다. Qwen3-TTS 계열은 품질·운율 측면의 장점이 있으나 이번 키오스크의 실시간 응답 조건에서는 지연이 너무 커 최종 서빙 후보에서 제외했다.

### 4.1 Adaptive TTS Level 0/1 Component Latency

| 지표 | Level 0 | Level 1 | Level 1 추가분 |
|---|---:|---:|---:|
| 평균 합성 지연 | 169.4ms | 210.1ms | +40.7ms |
| 중앙값 | 147.8ms | 199.4ms | +51.6ms |
| p95 | 307.2ms | 362.0ms | +54.8ms |
| 평균 RTF | 0.0383 | 0.0391 | +0.0008 |

느린 안내에서 절대 합성 시간은 증가하지만 평균 RTF 증가는 약 2% 수준이며 두 Level 모두 RTF 1.0 미만이다.

## 5. End-to-End Latency

### 5.1 I-08 최종 Real Warm 50 Turn

2026-08-28 최종 실측에서는 실제 Chromium 마이크/VAD·MediaRecorder 경로, 실제 STT/NLU/Order/TTS, 실제 HTML5 `Audio.onplay`를 사용했다. 각 Turn은 고유 Session으로 격리했으며 최초 3 Turn은 warm-up으로 제외했다.

| 지표 | 최종 결과 |
|---|---:|
| Warm Mean | **1,915.6ms** |
| Warm Median | **2,166.5ms** |
| nearest-rank p95 | **3,338ms** |
| Max | **3,448ms** |
| 1.5초 초과 | **30/50** |
| Playback Failure | **0/50** |

초기 `docs/specs/e2e-latency.md`의 Target 1.2초 / Requirement 1.5초는 변경하지 않았으며, **최종 판정은 Requirement 미달**이다.

#### NLU 경로별 분리

| 경로 | Turn | Mean | Median | p95 | 1.5초 초과 |
|---|---:|---:|---:|---:|---:|
| Rule-First | 20 | 729.1ms | 709.0ms | **967ms** | 0 |
| Qwen-0.6B fallback | 30 | 2,706.5ms | 2,668.5ms | **3,386ms** | 30 |

정형 발화가 Rule-First에 적중하면 초기 Target을 충족했지만, Qwen fallback이 발생한 복합·옵션·비정형 발화에서 전체 지연이 커졌다.

#### Stage별 주요 값

| 구간 | 평균 | p95 |
|---|---:|---:|
| STT Network RTT | 495.1ms | 693ms |
| Server STT | 429.6ms | 613.9ms |
| Interpret Network RTT | **1,397.2ms** | **2,641ms** |
| Interpret → Audio onplay | 20.5ms | 32ms |

Interpret 구간이 최종 E2E의 가장 큰 병목 구간으로 확인됐다. 상세 raw Turn과 샘플별 기능 관찰은 `docs/evidence/e2e/i08-final-real-e2e.md`를 따른다.

### 5.2 Cold Start 3회

| Run | Raw startup-to-first-response |
|---:|---:|
| 1 | 8,804ms |
| 2 | 7,274ms |
| 3 | 7,035ms |

평균 **7,704.3ms**, 중앙값 **7,274ms**다. 이 값은 순수 모델 추론이 아니라 프로세스/sidecar 시작, 모델 적재, CUDA context/readiness와 첫 요청을 포함한 **Raw startup-to-first-response latency**이며 Warm 판정에는 포함하지 않는다.

### 5.3 최종 측정 Protocol Deviation

초기 Spec은 대표 문장 10개 × 5회였으나, 최종 제출 측정은 공개 STT Showcase 고정 음원 **5종 × 10회**로 총 50 Turn을 구성했다. 입력 반복 배분만 바뀌었고 Warm-up 3회 제외, Real Provider 경로, VAD→Audio.onplay 경계, Cold Start 3회, nearest-rank p95와 초기 임계값은 유지했다. 이 차이는 `docs/specs/e2e-latency.md`에 명시적으로 기록한다.

### 5.4 기존 Real 36 Turn 참고 결과

최종 계약 확정 이전 실제 모델 연결 환경에서 36회 측정한 참고 결과는 Warm 평균 147.2ms, p95 368.7ms, 최대 441.6ms, Cold 첫 Turn 약 1.408s였다. 이는 최종 I-08 판정값이 아니며, 과거 계측 참고값으로만 유지한다.

## 6. 사용자 조사 근거

60대 사용자 13명 설문에서 확인한 핵심 문제는 다음과 같다.

| 발견 | 응답 |
|---|---:|
| 메뉴 탐색 및 옵션 선택 지연/어려움 | **8/13명** |
| 실수 시 주문을 처음부터 다시 시작한 경험 | **7/13명** |
| 음성 오인식에 대한 불안 | **6/13명** |

이를 바탕으로 Voice-first 주문, 큰 글씨 GUI 동시 확인, UNDO/복구 흐름, 사용자가 요청할 때만 느려지는 Adaptive TTS를 설계했다.

## 7. 발표용 권장 그래프

### 그래프 A — STT 모델 크기별 CER

- Base: 0.5577
- Small: 0.3655
- Medium: 0.2199
- Final Domain STT: 0.1131

**메시지:** 모델 크기 선택과 도메인 적응을 거치며 CER을 단계적으로 낮췄다.

### 그래프 B — TTS 모델별 평균 생성 지연

- MeloTTS Baseline: 0.1985s
- MeloTTS Friendly: 0.2041s
- Qwen3-TTS Baseline: 6.9075s
- Qwen3-TTS Friendly: 28.1953s

**메시지:** 친절체 품질뿐 아니라 실시간 인터랙션 가능성을 함께 고려해 MeloTTS Friendly를 선택했다.

### 그래프 C — NLU 서비스 후보 핵심 정확도

- Intent: 100%
- Slot: 96.78%
- Error Code: 96.67%
- Schema Valid: 100%
- Multi-command: 100%

**메시지:** 단순 Exact Match가 아니라 실제 주문 안전성에 필요한 의미·슬롯·Schema 지표로 평가했다.

### 그래프 D — I-08 NLU 경로별 Real E2E p95

- Rule-First: **0.967s**
- Qwen-0.6B fallback: **3.386s**
- 전체 50 Turn: **3.338s**

**메시지:** 단순히 전체가 느린 것이 아니라 NLU routing에 따라 지연이 두 집단으로 분리되며, Qwen fallback 경로가 핵심 최적화 대상이다.

## 8. 아직 정량 결과로 주장하지 않는 항목

다음 항목은 현재 저장소에 실제 참가자 기반 완료 근거가 없으므로 발표에서 완료된 실험처럼 주장하지 않는다.

- E-05 파일럿 사용자 테스트
- E-06 최종 사용자 평가
- E-07 사용자 평가 결과 분석
- T-24 Adaptive TTS Level별 사용자 이해도 비교
- T-30 외부 참가자 기반 TTS 사용성 테스트

I-08은 최종 실측과 판정 자체를 완료했으며, 성능 Requirement를 달성했다는 의미가 아니라 **Requirement 미달을 포함한 최종 평가 완료**로 기록한다.

## 9. E-09 완료 판정

STT/NLU/TTS/통합의 핵심 정량 지표와 발표용 비교표·그래프 데이터를 한 문서로 집계했으므로 **E-09를 완료 처리할 수 있다.**
