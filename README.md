# 말로 (Mallo) — 공개 가능한 팀 프로젝트 코드 스냅샷

음성 기반 고령친화 카페 키오스크 팀 프로젝트의 **실제 소스 구조**를 유지한 개인 포트폴리오입니다.

- [직접 배포한 키오스크](https://mallo-kiosk.vercel.app/) · [소개·화면](https://nanocode00.github.io/mallo-intro/)
- [STT 쇼케이스](https://nanocode00.github.io/stt_showcase/) · [TTS 쇼케이스](https://nanocode00.github.io/tts_showcase/)
- 핵심: src/ 주문 엔진과 음성 오케스트레이션, web/ UI, tests/ 검증, schemas/ JSON 계약
- 기여 범위: 팀 리드, 서비스 통합, 주문·모델 인터페이스, STT/TTS 학습 및 통합 일부. **팀 전체 코드를 혼자 작성한 것은 아닙니다.**

## 실행/검증 가이드

아래 명령은 **실행 방법 안내**이며, 새 공개 스냅샷에서 전부 통과했다고 주장하지 않습니다.
외부 STT/LLM 모델, GPU, 배포 인증정보와 제3자 데이터가 필요한 경로는 추가 설정이 필요합니다.

```bash
python -m pip install -r requirements/base.txt
PYTHONPATH=src python -m pytest tests/unit/test_order_engine_operations.py -q
PYTHONPATH=src python -m app.main
```

## 공개 범위

과거 Git 이력, 실제 키·서비스 운영 데이터, 원천 음성/라벨, 모델 가중치, 이용권이 명확하지 않은 평가 데이터, 개인 정보가 담긴 증거 및 generated artifact는 제외합니다.
이 저장소는 개인 포트폴리오 **소스 공개**이지 제3자 콘텐츠의 재배포 허가를 의미하지 않습니다.
코드 사용·배포 권리와 제3자 이미지/모델 라이선스는 각각 별도로 검토해야 합니다.

## 공개본 검증 기록 (2026-11-09)

- 원본 Git 추적 파일을 새 이력으로 가져오되 비공개 자료를 제외했습니다.
- Python 소스 265개 구문 분석과 JSON 파일 9개 파싱을 통과했습니다.
- Node 기본 제공 테스트 러너로 공개 가능한 프런트엔드 테스트 묶음이 통과했습니다.
- 서버, GPU, STT/NLU/TTS 가중치 및 외부 서비스의 전체 E2E 검증은 완료하지 않았습니다.
- 공개본의 web/runtime-config.js는 API 서버 URL을 비워 둔 안전한 예시이며, 배포 시 직접 설정해야 합니다.
- 원래 키오스크 배포는 본인 소유 https://mallo-kiosk.vercel.app/ 입니다.
