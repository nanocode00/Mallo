---
title: "말로(Mallo) 추론 및 배포 검증 계획"
tags: [doc]
---

# 말로(Mallo) 추론 및 배포 검증 계획

이 문서는 [`docs/trd.md`](trd.md)의 배포 아키텍처를 검증하기 위한 보조 계획이다. 배포
기본안의 Source of Truth는 TRD이며, E2E 수치와 모델 Provider Fallback은
[`docs/specs/e2e-latency.md`](specs/e2e-latency.md)를 따른다. 이 문서는 별도의 제품
정책이나 병렬 아키텍처를 정의하지 않는다.

---

## 1. 두 Fallback의 구분

| 구분 | 기본안 | 검토 조건 | 변경 범위 |
|---|---|---|---|
| Deployment | Vercel React UI → Local PC FastAPI/AI Pipeline | 브라우저 보안, HTTPS→Local 접근, CORS, 네트워크, 시연 장소 접근 실패 | Backend와 AI Pipeline 전체를 External Server로 이동 |
| Latency Provider | Local STT + Local NLU + Local TTS | Real Warm E2E 병목이 Local 최적화·다른 Local 모델 후에도 Requirement 미달 | 병목인 STT 또는 TTS Provider만 교체, NLU Local 유지 우선 |

Deployment Plan B와 Latency Provider Fallback은 모두 과거 문서에서 `Plan B`로 불렸지만
서로 다른 결정이다. E2E가 1.5초를 초과했다는 이유만으로 Backend 전체를 External
Server로 옮기지 않으며, Local 연결 실패를 모델 API 교체로 해결하지 않는다.

---

## 2. Deployment Plan A

```text
GitHub
  ↓
Vercel
  ↓
React Web UI (사용자 단말)
  ↓
Local PC / FastAPI
  ↓
Local STT → Local NLU → Order Engine → Local TTS
```

| 컴포넌트 | 실행 위치 | 책임 |
|---|---|---|
| React Web UI | Vercel / 사용자 브라우저 | 화면·터치, 마이크 입력, 오디오 재생, `first_audio_start`·Visual Response 계측 |
| FastAPI | Local PC | Frontend API, 세션과 주문 상태, Pipeline orchestration |
| STT/NLU/Order Engine/TTS | Local PC | 기본 AI·주문 처리 Pipeline |
| Vercel | Cloud | Web UI 배포·팀 공유·변경 확인 |

Vercel에서 AI Backend나 모델을 직접 실행하는 것은 기본안이 아니다. Streamlit은 필요할
경우 모델 테스트나 개발자 디버깅 화면에만 사용하며 최종 키오스크 UI로 사용하지 않는다.

### Plan A 연결 검증

- Vercel HTTPS UI에서 Local FastAPI endpoint 접근 가능
- HTTPS 페이지의 Local/Private Network 접근에 대한 브라우저 정책 충족
- CORS 설정과 preflight 성공
- 사용자 단말의 마이크 권한과 오디오 재생 권한 확보
- 시연 네트워크에서 Local PC 주소에 안정적으로 접근
- API endpoint를 환경 설정으로 주입하고 UI 코드에 주소를 고정하지 않음
- 세션·오류·오디오 계약이 Local/External 배포에서 동일함

Local Server 주소 탐색, TLS, 인증, 브라우저 Private Network Access 대응의 구체 방식은
아직 확정하지 않았다. Plan A 적용 전 실제 시연 장비와 네트워크에서 검증한다.

---

## 3. Deployment Plan B — External Server

Plan A 연결 조건을 안정적으로 만족하지 못하면 다음 구조를 배포 Fallback으로 사용한다.

```text
Vercel React Web UI
  ↓
External Server / FastAPI
  ↓
STT → NLU → Order Engine → TTS
```

- Backend와 AI Pipeline 전체를 External Server로 옮긴다.
- Frontend의 API endpoint 설정만 변경하고 요청·응답 계약은 유지한다.
- External Server는 Plan A와 동급의 기본 구조가 아니다.
- 공급자, 인스턴스, 컨테이너 방식과 운영 비용은 아직 확정하지 않았다.
- `Warm Standby`, 무중단 전환, Runtime 자동 전환은 확정 요구사항이 아니다.

---

## 4. Local AI Pipeline과 Provider 경계

```text
Audio Input
  ↓
STT Provider (Local 기본 / External 후보)
  ↓
Domain Post-processing
  ↓
Local NLU
  ↓
Deterministic Order Engine
  ├─→ UI Result
  └─→ TTS Provider (Local 기본 / External 후보)
```

STT와 TTS Adapter는 Provider가 바뀌어도 Frontend, NLU, Order Engine을 수정하지 않도록
공통 인터페이스를 유지한다. NLU는 주문 상태와 Context 처리에 밀접하므로 Local 유지가
우선이다.

현재 저장소에서 검토 중이거나 실험한 모델명과 장비 수치는 후보·실험 기록이다. 고정된
배포 정책으로 해석하지 않는다. 모델의 최종 선택은 관련 Spec과 동일 조건 PoC 결과를
따른다.

---

## 5. 자원 검증

초기 Local PC 후보 장비는 RTX 5070 Ti 16GB와 Python 환경이다. 다음 항목은 모델 조합을
결정하기 전 실제 실행 조건에서 다시 측정한다.

- 모델별 상주 VRAM과 Pipeline Peak VRAM
- Cold load와 Warm 추론의 분리
- 동시 상주 시 OOM 여부
- 순차 실행과 UI/TTS 병렬 분기의 영향
- CPU/RAM과 오디오 I/O 병목

과거 예상 VRAM 표는 실측값이 아니므로 배포 가능성을 확정하는 근거로 사용하지 않는다.

---

## 6. Latency 검증

E2E의 제품 기준은 정상 Warm 주문 Turn에서 `input_end → first_audio_start`다.

- Target: `<= 1.2초`
- Requirement: `<= 1.5초`
- Time to Visual Response와 Cold Start는 별도 측정
- Mock E2E와 TTS/STT Component Benchmark는 Real E2E 판정에서 제외

구간별 timestamp, 판정 구간, Real/Mock 구분과 Latency Provider Fallback 순서는
[`docs/specs/e2e-latency.md`](specs/e2e-latency.md)의 AC로 검증한다.

---

## 7. 단계별 검증

1. **개발 검증**
   - Mock Pipeline으로 계약·오류·계측 구조를 검증한다.
   - 실제 STT/NLU/TTS Component Benchmark는 E2E와 별도 기록한다.
2. **Real Local Pipeline 검증**
   - Local FastAPI에 실제 Provider를 연결한다.
   - 실제 브라우저 마이크·UI·오디오 재생까지 Real E2E를 측정한다.
3. **Deployment Plan A 검증**
   - Vercel React UI와 Local FastAPI의 HTTPS/CORS/네트워크 경계를 시연 환경에서 검증한다.
4. **Fallback 검증**
   - 연결 조건 실패 시 Deployment Plan B를 검증한다.
   - 성능 미달 시 별도로 Latency Provider Fallback 절차를 검증한다.

---

## 8. 아직 미확정인 기술 항목

- Vercel UI에서 Local FastAPI에 안전하게 접근하는 구체적 네트워크·TLS·인증 방식
- HTTP multipart와 WebSocket 중 오디오 전송 방식
- VAD 완료 후 단일 WAV와 streaming audio 중 전송 단위
- External Server 공급자와 인스턴스
- 외부 STT/TTS Provider
- 최종 STT/NLU/TTS 모델과 시연 하드웨어 최소 사양
- Real E2E 측정의 네트워크 통제 조건 (나머지 측정·판정 계약은 `docs/specs/e2e-latency.md`에서 확정)
