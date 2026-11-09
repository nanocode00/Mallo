---
title: "Evaluation / User Test / Demo 작업 로그 (`E-*`)"
tags: [worklog]
---

# Evaluation / User Test / Demo 작업 로그 (`E-*`)

Evaluation, User Test, Demo 영역에서 완료한 작업과 주요 기술 결정을 날짜순으로 기록한다.

---

## 2026-08-19: 고령 사용자 키오스크 설문(13명) 분석 및 파이프라인 변경안 검토

- **작업 내용**:
  - 60대 고령 사용자 13명 대상 키오스크 이용 경험 및 음성 주문 설문 조사 결과 분석 (`docs/survey-pipeline-update.md`)
  - 설문 발견점을 바탕으로 NLU Intent, Menu Schema, Order Engine 상태 관리, TTS/GUI 요구사항 점검 및 우선순위 정렬
- **핵심 발견점 및 결정 사항**:
  1. **메뉴 탐색 및 질문 (`SEARCH_MENU`, `ASK_MENU_INFO`)**: 메뉴 찾기 및 옵션 선택 지연(8/13명) 해결을 위해 Menu Schema에 속성(`attributes`), 키워드(`keywords`) 메타데이터 확장
  2. **실수 복구 (`UNDO`)**: 오입력 시 주문을 처음부터 재시작(7/13명)하는 문제를 막기 위해 `Committed Cart` ↔ `Pending Command` ↔ `Preview Cart` 상태 관리 및 직전 동작 취소 지원
  3. **Voice-First + Minimal GUI 확인 피드백**: 음성 오인식에 대한 불안(6/13명) 해소를 위해 음성 안내와 큰 글씨의 화면 표시를 동시 제공하여 즉시 수정/확인 가능하도록 설계
  4. **Adaptive TTS 단순화**: 분절형 발화보다 일반 자연 발화 선호가 높아, 기본 친절체 자연 발화로 제공하되 필요 시 명시적 요청(`REPEAT`, `SPEAK_SLOWER`)으로 제어
- **관련 문서**:
  - 분석 리포트: `docs/survey-pipeline-update.md`
  - 제품 요구사항: `docs/prd.md`
  - 관련 스펙: `docs/specs/user-test-protocol.md`, `docs/specs/menu-tag-search.md`, `docs/specs/undo-last-cart-change.md`, `docs/specs/adaptive-tts-controller.md`

---

## 2026-08-19: E-10 최종 데모 리허설

- E-08 5-Turn Happy Path를 통합 파이프라인(MalloService)과 실제 Web 백엔드(ThreadingHTTPServer) 양쪽에서 발표 순서대로 실행하는 리허설 테스트 `tests/integration/test_demo_rehearsal.py`를 추가(인텐트 정합성 1건 + 서비스 레벨 1건 + HTTP 서버 레벨 1건, 총 3건 통과).
- AC-01~AC-04 검증: 5턴 인텐트 정합성, Turn 3에서 TTS Level 0→1 상승, Turn 4 후 cart(iced americano:2, basque_cheesecake:1), 오프라인 mock 어댑터 로컬 실행(외부 네트워크 호출 없음).
- 리허설 중 발견한 제약: Order Engine(domain/conversation.py)은 턴당 단일 Intent만 허용하여 "아메리카노 하나는 아이스로"(REMOVE+ADD) 식 온도별 분리가 불가능. 이에 E-08 Turn 4 발화를 "아메리카노를 아이스로 바꿔줘"(전체 아이스 일괄 변경, UPDATE_OPTION)로 정렬하고 AC-03도 iced americano: 2로 갱신, 명세 각주로 근거를 기록했다.
- MockNLU에 데모 전용 발화(복합 주문 / 속도 제어 / 온도 변경 / 결제 확정)를 추가해 리허설 결정성을 보장. 기존 테스트는 영향 없음(전체 480 passed, 5 skipped).

