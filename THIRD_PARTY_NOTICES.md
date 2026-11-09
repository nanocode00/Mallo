# 말로(Mallo) 제3자 모델·데이터 라이선스 및 사용 고지

이 문서는 말로(Mallo) 프로젝트에서 최종 서비스 또는 비교 실험에 사용한 주요 제3자 모델·데이터의 라이선스와 사용 범위를 정리한다.

> 이 문서는 **제3자 구성요소의 출처·라이선스·프로젝트 적용 범위를 기록하기 위한 고지**다. 말로 프로젝트 자체 소스코드에 새로운 오픈소스 라이선스를 부여하는 문서가 아니며, 각 upstream 라이선스 원문과 데이터 제공기관의 최신 이용조건이 우선한다.

## 1. 핵심 모델

| 영역 | 모델 / upstream | 프로젝트 사용 | 확인한 라이선스 | 공식 근거 |
|---|---|---|---|---|
| STT | OpenAI Whisper Medium | 주문 음성 STT, QLoRA/domain adaptation 및 최종 추론 | MIT | [openai/whisper LICENSE](https://github.com/openai/whisper/blob/main/LICENSE) |
| NLU | Qwen3-0.6B | 주문 의도·슬롯 해석용 QLoRA 및 Local fallback | Apache-2.0 | [Qwen/Qwen3-0.6B model card](https://huggingface.co/Qwen/Qwen3-0.6B) |
| NLU 비교 | Qwen3-1.7B 계열 | 최종 후보 비교 평가 | Apache-2.0 계열 | [Qwen model collection](https://huggingface.co/Qwen) |
| TTS | MeloTTS | 한국어 주문 안내 TTS 및 Friendly fine-tuning | MIT | [myshell-ai/MeloTTS](https://github.com/myshell-ai/MeloTTS) |
| TTS base checkpoint | MeloTTS-Korean | Friendly fine-tuning의 한국어 base checkpoint | MIT | [myshell-ai/MeloTTS-Korean model card](https://huggingface.co/myshell-ai/MeloTTS-Korean) |
| TTS 비교 실험 | Qwen3-TTS | Baseline/Friendly 비교 실험, 최종 서비스에서는 미사용 | Apache-2.0 | [QwenLM/Qwen3-TTS LICENSE](https://github.com/QwenLM/Qwen3-TTS/blob/main/LICENSE) |

### 1.1 재배포 시 주의

- **MIT 계열**: upstream 저작권 고지와 라이선스 문구를 유지한다.
- **Apache-2.0 계열**: 재배포 시 Apache-2.0 라이선스 사본, upstream 저작권·귀속 고지, 필요한 경우 NOTICE를 유지하고 수정한 파일/파생물은 변경 사실을 명확히 표시한다.
- Fine-tuned adapter나 merged checkpoint를 외부 배포할 경우에는 **base model의 당시 model card와 LICENSE를 다시 확인**하고 필요한 라이선스·귀속 고지를 함께 제공한다.
- 프로젝트 제출물과 공개 쇼케이스에는 모델 원본 라이선스 파일을 임의로 수정해 재게시하지 않고, 공식 upstream URL과 본 고지를 통해 출처를 명확히 한다.

## 2. 학습·평가 데이터

| 영역 | 데이터 | 사용 범위 | 공개/배포 정책 |
|---|---|---|---|
| STT | AI Hub — 자유대화 음성(노인남여) | 고령층 한국어 STT 학습·평가 | AI Hub 원천·라벨 데이터는 저장소/공개 웹에 포함하지 않음 |
| STT | AI Hub — 중·노년층 한국어 방언 데이터(강원도, 경상도) | 방언·중노년층 STT 실험 | AI Hub 원천·라벨 데이터는 저장소/공개 웹에 포함하지 않음 |
| TTS | AI Hub — 감성 및 발화스타일 동시 고려 음성합성 데이터 (ID 71349) | `친절체`·`매장응대`·`기쁨` 조건 선별 및 MeloTTS fine-tuning | 원천·라벨·재가공 데이터 비공개, 프로젝트 자체 문장으로 생성한 합성 결과 중심 공개 |
| NLU | 팀 자체 구축 주문 도메인 3,000문장 | Train 2,400 / Validation 300 / Test 300 | 프로젝트 학습·평가용으로 관리 |

### 2.1 AI Hub TTS 데이터 사용 범위 확인

TTS 학습에 사용한 AI Hub 데이터셋 71349에 대해서는 프로젝트 팀이 AI Hub에 별도 문의했고, 2026-08-28 서면 답변을 수신했다. 공개 가능한 판단 근거는 `docs/aihub-tts-license-inquiry.md` (공개본에서 제외)에 기록한다.

프로젝트 적용 원칙은 다음과 같다.

- AI Hub 데이터로 학습해 도출한 AI 모델 및 결과물은 AI Hub 답변 범위에서 활용한다.
- AI Hub가 제공한 **원천데이터·라벨링데이터 및 이를 편집·추출·변환한 재가공 데이터 자체는 외부 공개·공유·판매·재배포하지 않는다.**
- GitHub, GitHub Pages, 발표자료, 포트폴리오에는 원천·라벨 데이터가 포함되지 않도록 한다.
- 공개 TTS 샘플은 프로젝트가 직접 작성한 주문 안내 문장을 Fine-tuned 모델로 합성한 결과를 사용한다.
- 프로젝트와 서비스 문서에서 `감성 및 발화스타일 동시 고려 음성합성 데이터 · AI 허브` 출처를 상시 확인 가능하게 표시한다.
- 프로젝트 범위를 넘어 새로운 모델 배포 또는 상업 활용을 수행할 때에는 당시 최신 AI Hub 이용조건과 base model 라이선스를 다시 확인한다.

## 3. 공개 산출물별 적용

| 공개 산출물 | 현재 원칙 |
|---|---|
| GitHub Repository | 코드·설정·집계 결과만 공개하고 AI Hub 원천/라벨/재가공 데이터는 제외 |
| STT Showcase | 프로젝트가 공개 가능한 테스트 음원과 STT 결과만 제공하며 AI Hub 원천 데이터는 재배포하지 않음 |
| TTS Showcase | 프로젝트 자체 작성 문장의 합성 WAV와 모델 비교 결과를 제공하고 AI Hub 원본 음성을 포함하지 않음 |
| 발표자료 / 결과보고서 | 모델명·라이선스·데이터 출처와 성능 집계치를 표시하고 제한 데이터 원본은 삽입하지 않음 |
| Fine-tuned checkpoint | 현재 공개 배포를 전제로 하지 않으며, 향후 배포 시 base model 라이선스와 AI Hub 데이터 이용조건을 다시 점검 |

## 4. 프로젝트 제출 전 라이선스 체크리스트

- [x] Whisper upstream 라이선스 확인 — MIT
- [x] Qwen3-0.6B upstream 라이선스 확인 — Apache-2.0
- [x] MeloTTS 라이브러리 라이선스 확인 — MIT
- [x] MeloTTS-Korean checkpoint model card 라이선스 확인 — MIT
- [x] 비교 실험용 Qwen3-TTS upstream 라이선스 확인 — Apache-2.0
- [x] AI Hub TTS 데이터 외부 활용 범위 서면 문의 및 답변 보관
- [x] README에 AI Hub 데이터 출처와 원천 데이터 비공개 원칙 표시
- [x] 공개 TTS Showcase를 프로젝트 자체 작성 문장 합성본으로 제한
- [ ] Fine-tuned model checkpoint를 외부에 별도로 배포할 경우 배포 시점의 upstream LICENSE/NOTICE 및 AI Hub 최신 정책 재확인

## 5. 참고

주요 라이선스의 상세 의무는 반드시 각 공식 원문을 기준으로 확인한다. 의존 패키지 전체에 대한 라이선스 SBOM을 생성한 것은 아니며, 본 문서는 프로젝트 평가에서 핵심적으로 사용하는 **모델·checkpoint·학습 데이터**를 중심으로 정리한 것이다.
