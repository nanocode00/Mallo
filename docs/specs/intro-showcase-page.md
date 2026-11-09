---
title: "말로(Mallo) 소개 정적 페이지 — 고객·평가자 랜딩"
tags: [spec]
---

# 말로(Mallo) 소개 정적 페이지 — 고객·평가자 랜딩

## Why

- **페르소나**: 배포 직전 말로 MVP를 심사하는 강사·평가자, 사용자 테스트 협조 기관 담당자
- **상황**: URL 하나로 프로젝트를 공유하고, 이후 실사용자 테스트 전 관심과 신뢰를 확보하고 싶다.
- **문제**:
  1. 저장소 문서(prd/trd/specs)는 분량이 많고 개발자 중심이라 평가자가 핵심을 빠르게 파악하기 어렵다.
  2. 시연은 로컬 GPU 환경(`scripts/run_local_real.bat`)에서만 가능해 사전 공유 자료가 없으면 제품 가치가 전달되지 않는다.
- **측정 지표**: 평가자에게 공개 URL 전달 완료, 데모·UI 섹션의 placeholder 동작 확인, 정적 단일 페이지 로딩 체감 3초 이내

## Goal

- **해결 목표**: 말로의 문제 정의·접근 방식·검증된 지표·평가 설계를 한 페이지에서 3분 안에 이해할 수 있는 정적 소개페이지를 제공한다.
- **성공 기준**:
1. Vercel Hobby(무료) 플랜에서 private repo의 `artifacts/intro` 디렉터리만으로 배포되어 공개 URL에 접속된다.
  2. `node --test tests/frontend/*.test.js` 전체(기존 테스트 포함)가 통과한다.
  3. 페이지 내 수치는 저장소 측정 기록과 일치하고, 미확정 수치(E2E Latency)는 "설계 목표"로만 표기된다.
- **Out of Scope**: 사용자 테스트 참여 신청 기능(E-05~E-07 별도), 영어 버전, 본앱 키오스크 UI의 공개 배포, AI Hub 파생 음성 샘플 게시(T-29 라이선스 확인 전까지), 백엔드 연동, 상호작용형 JS 런타임 로직

## What

**Happy Path**

1. 방문자가 공개 URL에 접속해 고객 안내 또는 평가자·쇼케이스 페이지를 선택한다.
2. Hero에서 제품 한 줄 정의와 핵심 키워드(STT · NLU · Order Engine · Adaptive TTS · Minimal GUI)를 확인한다.
3. 시연영상 영역에서 현재는 "준비 중" placeholder를 확인한다(자산 확보 후 교체).
4. 문제 통계 → 해결 방식 → UI 화면 갤러리(placeholder) → 아키텍처 → 검증 지표 → 평가 설계 → 팀 소개 순으로 스크롤한다.
5. 푸터에서 기술 스택과 학습 데이터 출처를 확인한다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 외부 폰트 CDN 차단/오프라인 | 시스템 폰트 fallback로 레이아웃 유지 |
| EC-02 | 모바일 등 좁은 화면 | 반응형 규칙으로 단일 컬럼 재배치 |
| EC-03 | `prefers-reduced-motion` 설정 | 장식 애니메이션 비활성화 |
| EC-04 | JS 비활성화 브라우저 | 순수 HTML/CSS라 모든 콘텐츠 열람 가능(JS 미사용) |
| EC-05 | 데모 자산 업로드 전 노출 | placeholder 박스에 "준비 중"을 명시해 빈 화면 오인 방지 |

## How

- 파일 구성: `artifacts/intro/index.html`(진입점), `customer.html`(고객 안내), `evaluator.html`(평가자·쇼케이스), `styles/intro.css`(공유 CSS)다. 실제 미디어는 `assets/images/`, `assets/videos/`에 고정 파일명으로 추가하며, 없으면 깨진 이미지 대신 placeholder를 표시한다.
- 디자인: 스타벅스 계열 팔레트(`--green-dark: #1e3932`, `--green`, `--cream` 계열)로 본앱 UI(UI-01)와 무드 통일.
- 경로 규칙: 내부 참조는 상대 경로만 허용. 루트 절대 경로(`src="/"`·`href="/"`) 금지(정적 호스팅 하위 경로 호환).
- 수치 정책: 페이지는 수치를 재정의하지 않고 `docs/prd.md` 3.3, `docs/specs/user-test-protocol.md`, `docs/worklogs/stt.md`, `docs/worklogs/tts.md`의 기록만 인용하며, STT와 Adaptive TTS 지표는 각각의 측정 환경(GPU·평가셋·합성 횟수)을 분리해 표기한다. E2E Latency(목표 ≤ 1.2초 / 요구 ≤ 1.5초)는 달성 실적이 아닌 설계 목표로만 표기한다(I-08 최종 재측정 미완료).
- 배포(Vercel): 조장 GitHub 계정의 Vercel Hobby 연동, Framework Preset = Other, Root Directory = `artifacts/intro`, main push 시 자동 배포. GitHub Actions는 미사용(무료 한도 소진, `docs/github-actions-limit-and-local-testing.md`).
- 자산 교체 가이드: `assets/images/kiosk-main.webp`, `voice-overlay.webp`, `order-flow.webp`, `architecture.webp`, `assets/videos/mallo-demo.mp4`를 추가한다. 고정 경로를 HTML이 참조하므로 파일만 추가하면 된다.

## AC (Given-When-Then)

**AC-01 · 섹션 구조**
- GIVEN: `artifacts/intro/evaluator.html`이 존재한다
- WHEN: 파일을 검사하면
- THEN: `hero`, `demo-video`, `problem`, `solution`, `ui-screens`, `architecture`, `metrics`, `evaluation`, `team` 섹션 id가 모두 존재한다

**AC-02 · placeholder**
- GIVEN: 시연 자산이 아직 없다
- WHEN: 페이지를 렌더링하면
- THEN: 데모 영상과 Hero·주문 화면·음성 입력·주문/결제 흐름·구조도 영역이 실제 파일이 없을 때 각각 안내 placeholder로 표시된다

**AC-03 · 경로 및 게시 보류 준수**
- WHEN: HTML을 검사하면
- THEN: 루트 절대 경로 참조(`src="/..."`, `href="/..."`)와 `<audio>` 요소가 없다(AI Hub 파생 음성 게시 보류)

**AC-04 · 팔레트 통일**
- WHEN: CSS를 검사하면
- THEN: 스타벅스 계열 다크 그린 토큰(`--green-dark: #1e3932`)이 정의되어 있다

**AC-05 · 반응형·접근성**
- WHEN: CSS를 검사하면
- THEN: 반응형 `@media` 규칙과 `prefers-reduced-motion` 대응이 존재한다

**AC-06 · 전체 테스트 통과**
- GIVEN: 기존 프론트 테스트가 있는 상태에서
- WHEN: `node --test tests/frontend`를 실행하면
- THEN: 기존 테스트와 신규 intro-page 테스트 전부 통과한다
