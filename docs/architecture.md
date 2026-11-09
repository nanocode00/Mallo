# Mallo — 아키텍처와 설계 선택

## 사용 흐름

```text
마이크 입력
  ↓
VAD / Whisper STT → 전사 텍스트
  ↓
Qwen NLU → 구조화 OrderCommand 또는 오류
  ↓
Schema Validator → 주문 명령 검사
  ↓
Order Engine → Cart 상태 변경 · 가격/옵션 계산 (SSOT)
  ↓
응답 문장 → Adaptive TTS Controller / MeloTTS
  ↓
음성 재생 + 키오스크 화면 갱신
```

위는 **팀 전체 시스템 흐름**이며 전 단계의 개인 단독 구현을 뜻하지 않습니다.

## 중요한 판단

1. **LLM 생성 텍스트와 상태 변경 분리:** NLU가 장바구니 객체를 직접 쓰지 않고, 스키마로 검증된 명령을 Order Engine에 전달하도록 설계했습니다.
2. **모델의 독립적인 서비스 구성:** Whisper, Qwen, MeloTTS의 의존성 충돌과 모델 적재 지연을 고려해 독립 resident sidecar 및 Gateway 통합을 실험했습니다.
3. **사용성 중심의 UI:** 화면 탐색 부담을 줄이고 음성 응답·주문 상태를 함께 확인하도록 Senior-first UI로 재정리했습니다.
4. **TTS 반응성과 발화 스타일을 함께 측정:** 단순 음질 비교가 아니라 사용 흐름에 영향을 주는 latency를 조건별로 비교했습니다.

## 기술 스택

- 음성 인식: Whisper / VAD
- 언어 이해: Qwen 계열 Local LLM / QLoRA
- 주문 상태: JSON Schema 기반 명령 검증 / deterministic Order Engine
- 음성 합성: MeloTTS Friendly / Adaptive Controller
- API·연동: Python / FastAPI 및 독립 모델 서비스, Cloudflare Tunnel
- 화면: 웹 기반 키오스크, Vercel 배포

## 구현과 배포의 구분

서비스 구성과 실제 실험 결과는 [evaluation.md](evaluation.md)에 따로 정리합니다. 원본 팀 저장소가 Private인 상태에서 모든 코드·빌드를 공개 재현한 것으로 단정하지 않습니다.
