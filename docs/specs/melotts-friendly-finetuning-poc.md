---
title: "MeloTTS 친절체 Fine-tuning PoC"
tags: [spec]
---

# MeloTTS 친절체 Fine-tuning PoC

## Why

- **페르소나**: 시각·터치 중심 키오스크 이용에 부담을 느끼지만 일상적인 음성 대화가 가능한 고령 사용자
- **상황**: 말로(Mallo)가 메뉴명, 수량, 옵션, 가격과 주문 확인 문장을 로컬 환경에서 음성으로 안내해야 한다.
- **문제**:
  1. 현재 파이프라인에는 호출 기록만 남기는 `MockTTS`만 있고 실제 한국어 음성 출력이 없다.
  2. 기본 한국어 TTS가 카페 주문의 메뉴명·수량·금액을 충분히 명료하게 전달하는지 측정한 결과가 없다.
  3. 친절한 매장 응대 음성으로 도메인 적응했을 때 기본 모델보다 주문 정보 전달이 개선되는지 검증되지 않았다.
  4. MeloTTS의 공개 학습 절차가 사전학습 한국어 체크포인트의 Fine-tuning을 지원하는지, 또는 Custom Dataset 신규 학습만 지원하는지 확인되지 않았다.
- **측정 지표**: 설치·추론 성공률, 데이터 유효성 검사 통과율, 학습 스모크 테스트 성공 여부, 생성 지연, TTFB, RTF, Peak RAM·VRAM, MOS, SIM, 자연스러움, 메뉴명·수량·가격 명료도

## Goal

- **프로젝트 우선순위**: 본 PoC는 P1 TTS 연구·차별화 작업이다. P0는 기본 한국어 TTS를 포함한 단일 주문 경로와 Local NLU Fine-tuning 전후 비교이며, 본 PoC가 미완료여도 P0 데모 성립을 차단하지 않는다.
- **해결 목표**: MeloTTS 한국어 사전학습 모델을 Baseline으로 실행하고, 현재 보유한 AI Hub `감성 및 발화스타일 동시 고려 음성합성 데이터`의 친절체 중 `src_type=매장응대`, `emotion=기쁨` 데이터에서 목표 화자 한 명을 선정하여 기본 출력이 차분하고 편안한 친절체 매장 안내 억양에 가까워지도록 도메인 적응한다. 여기서 차분함은 단순히 발화 속도를 늦추는 것이 아니라 안정된 억양, 과도하지 않은 감정 표현과 명확한 발음을 뜻한다.
- **성공 기준**:
  - 팀 회의에서 확정한 Python 환경에서 MeloTTS 한국어 Baseline으로 평가 문장 20개를 모두 WAV로 생성한다.
  - Python 기준 버전은 팀 회의 후 확정한다. 회의 전에는 3.11을 임시 호환성 확인에 사용할 수 있지만 공식 Benchmark와 PoC 합격 판정에는 사용하지 않는다.
  - 동일한 평가 문장 20개에 대해 cold latency 1회와 warm latency 5회를 측정하고, 평균·중앙값·p95·RTF·Peak RAM 및 사용 가능한 경우 Peak VRAM을 기록한다.
  - 현재 보유한 ZIP 204개를 고정 입력으로 사용하고 파일 목록, 크기와 분석 시점을 기록한다. AI Hub 공식 통계와의 수량 차이는 보고하되 PoC를 차단하지 않는다.
  - AI Hub 원본에서 `style.style=친절체`, `src_type=매장응대`, `style.emotion=기쁨` 조건에 해당하는 레코드 수·총 음성 시간·화자 수·문장 길이 분포를 산출한다.
  - 선택 레코드의 WAV 존재 여부, WAV decode, mono 여부, 44.1 kHz 여부, 빈 텍스트 여부를 전수 검사하고 검사 결과를 기록한다.
  - 조건을 만족하는 화자별 유효 음성 시간과 품질 검사 결과를 산출하고, 블라인드 청취로 선택한 `target_speaker_id=10`을 실험 설정에 기록한다.
  - 동일 녹음 세션이 여러 split에 섞이지 않는 train/validation/test manifest를 고정 seed `42`로 생성하며 각 split의 레코드 수·시간·세션 수를 기록한다.
  - 공식 학습용 사전학습 `G.pth`, `D.pth`, `DUR.pth`를 초기값으로 불러왔다는 로그를 남긴다. 세 가중치 중 하나라도 로드되지 않으면 Fine-tuning 성공으로 판정하지 않는다.
  - 현재 다운로드본에서 목표 화자의 조건 일치 유효 데이터는 약 0.923시간이므로 30분 adaptation package로 전처리·학습·checkpoint·추론 경로를 검증한다.
  - 2,000 step에서 1차 판정하고 최대 5,000 step까지만 수행하며, 500 step마다 checkpoint와 고정 평가 음성을 생성한다.
  - Baseline과 학습 모델을 동일한 held-out 평가 문장으로 비교한 결과표와 음성 샘플을 생성한다.
  - 별도 구조의 비교 모델 `Qwen/Qwen3-TTS-12Hz-0.6B-Base`도 MeloTTS와 동일한 목표 화자·30분 adaptation package·paired training records·split·seed·학습 step 예산으로 Fine-tuning한다.
  - MeloTTS와 Qwen3-TTS의 Fine-tuned 모델은 같은 평가 문장·장치·측정 규칙으로 MOS·SIM·생성 지연·TTFB·RTF·Peak RAM·VRAM을 비교한다. 모델별 필수 전처리와 optimizer 차이는 허용하되 실제 설정을 모두 기록한다.
  - 개발 중 평가는 TTS 담당자 1명이 수행하고, 최종 후보 비교는 작성자가 아닌 팀원을 포함한 최소 3명이 모델 정보를 가린 상태에서 수행한다.
  - 최종 평가에서 학습 모델의 `친절함`, `전체 명료도`, `매장 안내 음성으로서의 적합성`이 각각 평균 4.0/5 이상이고, `친절함`은 Baseline보다 평균 0.5점 이상 높아야 한다.
  - 고정 평가 문장 20개에서 심각한 오독·음성 깨짐이 0개이고, 최소 18개 문장에서 핵심 주문 정보 전달에 성공해야 한다.
- **Out of Scope**:
  - AI Hub 친절체 전체 167.4시간을 사용한 최종 학습
  - 현재 데이터만으로 단일 화자 1시간 또는 5시간 학습 단계를 충족하는 것
  - 여러 화자를 함께 학습하는 Multi-speaker 모델
  - 밝은 친절체, 공감형, 격식형 등 복수 성격의 동시 학습 및 런타임 스타일 전환
  - 한국어 추론용 `checkpoint.pth`를 Generator 초기값으로 사용하는 비교 실험
  - PoC 이후 제품용 최종 화자·성별·연령의 재선정
  - Adaptive TTS Level 0~2, 세션 상태, GUI 버튼 연동
  - STT, NLU, Order Engine 및 전체 애플리케이션 통합
  - `TTS.synthesize()` 반환 타입과 Playback 종료 이벤트를 포함한 C-15 공통 계약 변경
  - 대규모 고령 사용자 실험 또는 통계적 유의성 검정
  - 모델 checkpoint, AI Hub 원본 WAV·JSON 및 생성 WAV의 Git 저장소 커밋
  - 배포 URL, 소개 페이지, 고객 여정 지도와 전체 서비스 데모의 구현. 단, TTS 비교 결과와 오류 처리 계약은 팀 공통 산출물에 제공한다.

## What

### Happy Path

1. 작업자는 별도의 실험 환경에 MeloTTS를 설치하고 사용한 MeloTTS commit SHA, Python, PyTorch, CUDA, GPU 정보를 기록한다.
2. MeloTTS와 Qwen3-TTS의 사전학습 한국어 모델이 각각 학습·추론 가능한지 확인한다.
3. Benchmark가 모델별 cold 1회와 warm 5회의 생성 시간, TTFB, 음성 길이, RTF, Peak RAM·VRAM을 기록한다.
4. 데이터 변환기가 AI Hub JSON과 WAV를 읽고 `style.style=친절체`, `src_type=매장응대`, `style.emotion=기쁨`인 레코드만 선택한다.
5. 데이터 검증기가 텍스트와 오디오의 유효성을 검사하고 화자별 유효 시간과 제외 사유별 개수를 기록한다.
6. 화자 5번과 10번의 동일 문장 10개를 A/B 블라인드 청취한 결과, 차분한 친절체와 고령 사용자 접근성에 더 적합하다고 판단한 여성 음성 A, 즉 화자 10번을 `target_speaker_id`로 기록한다.
7. 변환기가 동일 녹음 세션을 한 그룹으로 유지하여 train/validation/test로 분리하고 MeloTTS 형식의 manifest를 만든다.
8. 공식 학습용 사전학습 G/D/DUR 가중치에서 30분 subset으로 학습한다.
9. 저장된 checkpoint로 held-out 주문 평가 문장 20개를 합성한다.
10. MeloTTS와 Qwen3-TTS를 동일한 30분 학습 데이터와 학습 step 예산으로 Fine-tuning한 뒤 동일 평가 문장·장치·측정 규칙으로 비교하고, 기술 지표와 친절체 청취 평가 결과 및 최종 모델 선택 근거를 작성한다.

### Edge Cases

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 기준 환경이 아닌 임시 Python 환경에서 MeloTTS 설치, 전처리, 학습 또는 한국어 추론 실패 | 실패 단계, 명령, 오류 로그와 충돌한 의존성을 참고 기록으로 남긴다. `Python 3.11.9`와 MeloTTS 전용 격리 환경에서 재현한 결과만 PoC 성공·실패 판정에 사용한다. |
| EC-02 | AI Hub JSON 필드명이 예상 매핑과 다름 | 원본 JSON 한 건의 키 구조를 검사하고 명시적 매핑 설정을 추가한다. 값의 위치를 추측하거나 파일명만으로 라벨을 생성하지 않는다. |
| EC-03 | WAV 누락·손상·stereo·샘플레이트 불일치 | 해당 레코드를 제외하고 사유별 개수를 보고한다. 원본 파일을 덮어쓰지 않는다. |
| EC-04 | 같은 녹음 세션에서 분리된 문장이 여러 split에 포함됨 | manifest 생성을 실패시키고 녹음 세션 그룹 단위로 다시 분리한다. |
| EC-05 | 선택 화자의 매장응대·기쁨 데이터가 30분 미만 | 해당 화자를 선택 대상에서 제외한다. 다른 화자·스타일·감정을 자동 혼합하지 않는다. |
| EC-06 | 공식 학습용 G/D/DUR 중 하나가 로드되지 않거나 핵심 계층에서 shape mismatch가 발생함 | 신규 학습과 Fine-tuning을 구분하여 기록하고 Fine-tuning은 실패 또는 미확정으로 판정한다. speaker embedding shape mismatch는 허용하되 해당 계층이 신규 초기화되었음을 기록한다. |
| EC-07 | CUDA OOM 발생 | batch size만 절반씩 줄여 최소 1까지 재시도한다. 오디오·텍스트·split은 변경하지 않으며 최종 batch size를 기록한다. |
| EC-08 | 학습 중단 또는 비정상 종료 | 마지막 checkpoint에서 1회 resume하고, 재실패하면 로그와 마지막 step을 기록한다. |
| EC-09 | 숫자·금액 발음이 잘못됨 | 원문과 실제 발음을 평가 결과에 기록한다. 평가 문장을 학습 데이터에 편입하거나 정답 발음을 수동 합성하지 않는다. |
| EC-10 | 생성 WAV나 checkpoint가 Git 변경 목록에 포함됨 | 커밋하지 않고 저장 위치와 재생성 절차만 문서화한다. |
| EC-11 | `Python 3.11.9`와 Qwen3-TTS 전용 격리 환경에서 0.6B 설치·Fine-tuning 또는 추론이 불가능함 | 오류와 commit SHA를 기록하고 자원 한도 안에서 1.7B 스모크 테스트를 수행한다. 1.7B도 실패하면 동일 조건 모델 비교를 `BLOCKED`로 판정한다. Python 버전을 임의 변경하거나 zero-shot 결과를 Fine-tuned 결과 대신 사용하지 않는다. |
| EC-12 | 빈 텍스트·제한 초과 텍스트·모델 오류·CUDA OOM·재생 실패 | 사용자에게 실패 원인과 재시도 가능 여부를 반환하고 오류 유형·입력 길이·모델·장치를 기록한다. 원문 데이터나 내부 stack trace는 사용자 화면에 노출하지 않는다. |

## How

### 고정 입력

- Python 기준 버전: `3.11.9` — 프로젝트 학습·실험 환경 기준은 `docs/specs/python-environment.md`를 따른다.
- 모델: `myshell-ai/MeloTTS`의 한국어 사전학습 모델
- 별도 비교 모델: `Qwen/Qwen3-TTS-12Hz-0.6B-Base`의 한국어 Fine-tuning 결과
- Qwen 대체 순서: 0.6B 공식 학습 스모크 테스트가 실패하고 시연 장치의 자원 한도를 충족하는 경우에만 `Qwen/Qwen3-TTS-12Hz-1.7B-Base`를 사용한다. 1.7B도 불가능하면 임의 모델이나 zero-shot 결과로 교체하지 않고 비교 모델 재선정을 별도 결정으로 남긴다.
- 비교 모델 선택 근거: 서로 다른 TTS 구조, 한국어·3초 voice clone 지원, 0.6B급 공개 가중치, Apache-2.0 라이선스
- 학습 초기값: MeloTTS가 제공하는 학습용 사전학습 `G.pth`, `D.pth`, `DUR.pth`
- 언어 코드: `KR`
- MeloTTS Baseline speed: `1.0` — MeloTTS 내부 Baseline/Fine-tuned 전후 비교에만 적용
- 데이터셋: AI Hub 데이터셋 ID `71349`, `감성 및 발화스타일 동시 고려 음성합성 데이터`
- 현재 로컬 입력: ZIP `204개`, 친절체 라벨 JSON `1,868개`, 라벨 문장 `88,777개`
- 데이터 가용성 정책: 현재 로컬 파일을 PoC의 기준 입력으로 사용하며 공식 통계와의 차이는 `docs/tts-friendly-script-analysis.md`에 기록한다. 접근할 수 없는 공식 통계상의 문장을 복원하거나 추정하지 않는다.
- 데이터 선택 조건:
  - `style.style`: `친절체`
  - `src_type`: `매장응대`
  - `style.emotion`: `기쁨`
- 학습 화자 수: `1명`
- 목표 화자: `10` (여성, 20대, 전수 WAV 검증 후 조건 일치 유효 데이터 572건·약 0.923시간)
- 목표 화자 설정: `MALLO_TTS_TARGET_SPEAKER_ID=10`으로 명시하며 자동 선택하지 않음
- 선정 근거: 화자 5번·10번의 동일한 `친절체 + 매장응대 + 기쁨` 문장 10개를 화자 ID를 가린 A/B 세트로 청취했고, A가 더 차분하며 고령 사용자의 접근성에 적합하다고 판단했다. 블라인드 해제 결과 A는 화자 10번이었다.
- 데이터 원본 특성: WAV, mono, 44.1 kHz
- 난수 seed: `42`
- 학습 데이터: 목표 화자의 `30분` adaptation package. 이 안에서 Qwen 학습용 `ref_audio` 1개를 예약하고, 해당 레코드를 제외한 동일한 paired training records를 두 모델에 사용
- 비교 학습 조건: 두 모델 모두 동일한 30분 adaptation package에서 예약 `ref_audio`를 제외한 paired training records, 동일 validation/test split, seed `42`, 2,000-step 1차 판정과 최대 5,000-step 예산을 사용한다.
- 모델별 허용 차이: 공식 구현에 필요한 tokenizer·오디오 전처리·optimizer·batch size는 다를 수 있다. 차이를 숨기지 않고 설정과 변경 사유를 결과표에 기록하며, 학습 데이터와 최대 step은 변경하지 않는다.
- Learning rate: `1e-4`
- 초기 batch size: `4` (`CUDA OOM`일 때만 `2 → 1` 순서로 감소)
- `skip_optimizer`: `true`
- 1차 판정: `2,000 step`
- 최대 학습: `5,000 step`
- 평가·checkpoint 간격: `500 step`
- 평가 문장 수: `20개`
- 반복 측정: 모델 로딩을 포함한 cold 1회, 동일 프로세스 warm 5회
- 목표 발화 성격: `calm_friendly` 한 가지
- 향후 스타일 이름 예약: `bright_friendly`, `empathetic`, `formal` (이번 PoC에서는 입력·학습·평가하지 않음)
- 로컬 자원 한도: warm RTF `< 1.0`, 합성 중 CUDA OOM·프로세스 강제 종료 `0건`, Peak VRAM은 시연 GPU 물리 VRAM의 `90% 이하`, Peak RAM은 시연 장치 물리 RAM의 `80% 이하`
- 현재 통합·사용성 테스트 후보 checkpoint: `logs/mallo-friendly/G_2800.pth`. 저장된 후속 후보 중 학습 Generator total loss가 가장 낮은 지점을 선택했으며, 음질 우위는 블라인드 청취 평가를 통과해야 확정한다. 선택 근거와 실행 결과는 `docs/worklogs/tts.md`를 따른다.

AI Hub 원본의 고정 위치는 저장소의 로컬 전용 경로 `data/tts/aihub/133.감성 및 발화 스타일 동시 고려 음성합성 데이터/`다. `.gitignore`에는 이 원본 데이터 디렉터리만 정확히 등록한다. `data/tts/` 전체를 제외하지 않으며 데이터 처리 코드, 평가 문장, 설정과 재현 가능한 요약 결과는 Git 추적 대상으로 유지한다. checkpoint와 생성 WAV처럼 추가로 제외할 대용량 생성물은 실제 출력 경로를 확정한 뒤 해당 경로만 별도로 등록한다.

`MALLO_TTS_DATA_ROOT`는 저장소의 `data/tts/` 절대 경로로 지정한다. 실행 코드가 환경 변수를 받지 못했거나 경로가 저장소 밖을 가리키면 데이터 처리와 학습을 시작하지 않는다. 원본 AI Hub ZIP과 그 내부 파일은 수정하지 않는다.

MeloTTS runtime은 `Python 3.11.9`의 `.venvs/runtime`과 `requirements/runtime.txt`를 사용한다. Qwen3-TTS처럼 학습·평가 전용인 실험은 `.venvs/dev`에 목적별 requirements를 추가 설치해 runtime과 분리한다. 다른 환경에서 얻은 결과는 호환성 참고 기록으로만 남기고 공식 Benchmark 수치에 합산하지 않는다. 설치 결과와 의존성 해석 결과는 모델별로 기록한다.

### 목표 스타일 및 확장 계약

- 이번 PoC의 유일한 지원 스타일은 `calm_friendly`다.
- `calm_friendly`는 안정된 억양, 과도하지 않은 감정 표현, 고령 사용자가 알아듣기 쉬운 명확한 발음을 목표로 한다. 속도를 일괄적으로 낮추는 것으로 스타일 달성을 대신하지 않는다.
- 향후 TTS 공통 계약을 변경할 때 사용할 수 있도록 `style` 개념과 이름만 예약한다. 현재 C-15 공통 계약 및 구현에는 임의로 필드를 추가하지 않는다.
- 복수 스타일을 구현할 때는 성격별 checkpoint, 화자 ID를 이용한 조건화, 별도 style embedding 중 하나를 별도 Spec과 비교 실험으로 결정한다.
- 이번 PoC 결과를 다른 성격을 선택할 수 있는 단일 모델로 표현하거나 검증되지 않은 스타일 이름을 지원한다고 표시하지 않는다.

### AI Hub 이용정책 및 결과물 공유

- 기준 정책: AI Hub `AI 허브 개방 데이터` 이용정책과 데이터셋 ID `71349`의 개별 안내를 적용한다.
- AI Hub 원본 WAV·JSON·ZIP은 다운로드 승인을 받은 이용자 범위에서만 보관하며 Git, 공개 저장소, 메신저 또는 승인받지 않은 제3자에게 제공하지 않는다.
- 코드, 직접 작성한 설정, 재현 절차와 원문을 복원할 수 없는 집계 통계만 Git 추적 대상으로 삼는다.
- 데이터셋 문장을 그대로 옮긴 예시, 원본 음성 일부와 원본을 재구성할 수 있는 중간 산출물은 공개 문서·PR에 포함하지 않는다.
- 연구 보고서와 이 데이터에 기반한 2차적 저작물에는 `과학기술정보통신부·한국지능정보사회진흥원 AI Hub 사업의 감성 및 발화스타일 동시 고려 음성합성 데이터(데이터셋 ID 71349)를 활용함`을 표시한다.
- 학습 checkpoint와 생성 WAV의 외부 배포 가능 범위는 일반 정책만으로 확정하지 않는다. AI Hub 또는 해당 데이터 수행기관의 서면 확인 전까지 로컬 비공개 산출물로 취급한다.
- 라이선스 문의는 Fine-tuning 실행을 차단하지 않는 후속 작업으로 기록하되, checkpoint·생성 WAV의 외부 공개 또는 제품 적용 전에는 반드시 완료한다. 문의·판정 계약은 `docs/specs/aihub-tts-license-inquiry.md`, 제출 문안과 상태는 `docs/aihub-tts-license-inquiry.md`에서 관리하고 문의 결과와 답변 일자는 `docs/worklogs/tts.md`에 남긴다.
- 향후 서면 문의에서는 학습 checkpoint 공개, 생성 음성 샘플 공개, 상업 제품에서의 모델·생성 음성 사용, 다운로드 승인 조직 내부의 checkpoint 공유 가능 범위를 각각 확인한다.
- 국외 소재 서비스 업로드, 국외 반출, 데이터셋 자체의 판매 또는 상업적 배포는 별도 합의 없이 수행하지 않는다.
- 개인정보나 재식별 가능 정보가 발견되면 사용을 중단하고 해당 파일을 삭제한 뒤 AI Hub에 신고한다.

### 데이터 검증 및 변환 계약

각 레코드에서 다음 값을 추출한다.

```text
audio_path
speaker_id
recording_group_id
language_code = KR
text
style
src_type
emotion
duration_seconds
sample_rate
channels
```

MeloTTS manifest는 UTF-8 텍스트로 생성한다.

```text
audio_path|speaker_id|KR|text
```

- `audio_path`는 존재하는 WAV의 절대 경로다.
- `speaker_id`는 AI Hub 원본 화자 식별자를 보존한다.
- `recording_group_id`는 문장 단위 WAV가 파생된 원본 녹음 세션 또는 원천 WAV 식별자를 보존한다. 원본에 해당 식별자가 없으면 파일명만으로 추측하지 않고 매핑 불가로 기록한다.
- `text`는 AI Hub 원문을 보존하며 앞뒤 공백만 제거한다.
- `|`, 줄바꿈 또는 빈 텍스트가 포함된 레코드는 제외하고 사유를 기록한다.
- WAV는 decode 가능, mono, 44.1 kHz 조건을 모두 만족해야 한다.
- 중복은 `speaker_id + normalized_text` 기준으로 제거한다.
- 모든 manifest에는 `MALLO_TTS_TARGET_SPEAKER_ID`와 일치하는 화자의 레코드만 포함한다.
- split은 `recording_group_id` 단위로 수행하고 같은 녹음 그룹이 둘 이상의 split에 나타나면 실패한다.
- split 비율은 총 음성 시간 기준 train 90%, validation 5%, test 5%에 가장 가깝게 배정하며 각 split에 최소 1개의 녹음 그룹을 둔다.
- 30분 adaptation package는 train split 안에서 녹음 그룹을 유지한 채 seed `42`로 선택한다.
- Qwen 학습용 `ref_audio`로 예약한 레코드는 MeloTTS manifest와 Qwen의 일반 학습 `audio` 행에서 모두 제외하며 validation/test에는 이동하거나 복제하지 않는다.

### Qwen3-TTS 데이터·학습 계약

Qwen3-TTS는 MeloTTS와 동일한 30분 adaptation package에서 예약 `ref_audio`를 제외한 paired training records 및 동일 validation/test split을 사용하되 [Qwen3-TTS 공식 Fine-tuning 문서](https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning)의 입력 형식으로 별도 변환한다.

```json
{"audio":"/absolute/path/to/train.wav","text":"학습 문장","ref_audio":"/absolute/path/to/reference.wav"}
```

- `audio`와 `text`는 MeloTTS manifest의 동일 레코드에서 가져오며 내용을 임의 보정하지 않는다.
- `ref_audio`는 목표 화자 10번의 30분 adaptation package에서 고른 3~10초 음성 한 개로 모든 Qwen 학습 행에 동일하게 사용한다.
- `ref_audio` 레코드는 두 모델의 paired training records와 validation/test 및 평가 문장 20개에 포함하지 않으며 ID·길이·선정 기준을 기록한다.
- 공식 `prepare_data.py`와 `Qwen/Qwen3-TTS-Tokenizer-12Hz`를 사용해 `audio_codes`가 포함된 JSONL을 생성한다.
- 본 학습 전에 레코드 2개로 데이터 준비, optimizer 1 step, checkpoint 저장·재로딩과 `generate_custom_voice` 합성을 수행한다.
- 스모크 테스트를 통과한 모델만 동일 조건 본 학습에 진입한다. 0.6B가 실패하면 원인과 commit SHA를 기록하고 위의 Qwen 대체 순서를 적용한다.
- Fine-tuned Qwen 추론은 공식 학습 절차의 `generate_custom_voice`를 사용하며 추가 참조 음성을 입력하지 않는다.

### 평가 문장 계약

평가 문장 20개는 다음 범주를 각각 4개 포함한다.

1. 메뉴명과 온도
2. 수량과 단위
3. 가격과 총액
4. 주문 수정·삭제 확인
5. 장바구니 요약과 결제 확인

평가 문장은 학습·검증 manifest의 문장과 정규화 후 완전히 일치하면 안 된다. 모든 모델은 동일 텍스트, device와 측정 코드로 비교한다. 합성 속도는 각 모델의 공식 기본 생성 설정을 사용하며 후처리 time-stretch로 속도를 맞추지 않는다. MeloTTS의 `speed=1.0`은 MeloTTS Baseline과 Fine-tuned 모델의 전후 비교에만 동일하게 적용한다. 모델별 속도 제어 지원 여부·설정값과 생성 음성 길이는 결과에 기록한다.

두 모델은 동일한 30분 adaptation package에서 예약 `ref_audio`를 제외한 paired training records와 동일 validation/test split을 사용한다. Fine-tuned 모델의 주 비교에서는 추론 참조 음성을 사용하지 않는다. Qwen의 학습용 `ref_audio`는 위 데이터 계약에 따라 모든 학습 행에 동일하게 사용하지만 평가 추론에는 전달하지 않는다. zero-shot voice clone은 적응 자원이 다른 보조 실험으로만 허용하며 최종 모델 점수에 포함하지 않는다. 비교 대상의 출력 샘플레이트가 다르면 원본 결과는 보존하고, MOS·SIM 비교용 사본만 동일한 mono 16 kHz로 변환한다.

### 측정 계약

```text
generation_latency_seconds = 합성 호출 직전부터 WAV 저장 완료까지
TTFB_seconds               = 합성 호출 직전부터 첫 재생 가능 오디오 chunk까지
audio_duration_seconds      = 생성 WAV의 전체 길이
RTF                         = generation_latency_seconds / audio_duration_seconds
```

- 스트리밍을 지원하지 않는 경로에서는 첫 재생 가능 WAV가 완성된 시점을 TTFB로 사용하고 `non_streaming`으로 표시한다.
- 스트리밍 경로에서는 첫 chunk의 바이트 수·음성 길이와 도착 시점을 함께 기록한다.
- 모든 비교 대상은 같은 장치에서 순차 측정한다. 모델별 필수 런타임이 달라 같은 Python 프로세스를 쓸 수 없는 경우에도 OS·장치·CUDA·측정 코드는 고정하고 환경 차이를 결과표에 표시한다.

결과에는 다음을 기록한다.

- 실험 ID와 실행 시각
- Git commit SHA와 MeloTTS commit SHA
- OS, CPU, RAM, GPU, VRAM, Python, PyTorch, CUDA
- 모델·checkpoint 식별자
- 문장 ID, 텍스트, 모델별 속도 설정 또는 기본값 사용 여부, 생성 음성 길이, cold/warm 구분
- 생성 지연, 음성 길이, RTF, Peak RAM, Peak VRAM
- TTFB와 streaming/non-streaming 구분
- SpeechBrain `speechbrain/spkrec-ecapa-voxceleb`의 고정 revision으로 계산한 화자 임베딩 cosine similarity(SIM)
- 실패 여부와 오류 메시지

개발 중 청취 평가는 TTS 담당자 1명이 빠른 반복 판단을 위해 수행한다. 최종 후보 비교는 작성자가 아닌 팀원을 포함한 최소 3명이 각 샘플에 1~5점으로 기록한다. 메뉴명·수량·단위·가격이 문장에 존재하지 않는 경우 해당 정보별 명료도는 `NA`로 기록하고 항목 평균에서 제외한다. 나머지 네 항목은 모든 문장에서 필수다.

- 자연스러움
- 전체 명료도
- 친절함
- 메뉴명 명료도
- 수량·단위 명료도
- 가격 명료도
- 매장 안내 음성으로서의 적합성

`자연스러움` 1~5점의 전체 평가자·문장 평균을 MOS로 보고한다. 이는 전문 청취실험이 아닌 프로젝트 내부 MOS임을 결과에 명시한다. SIM은 목표 화자의 test split 참조 음성 3개 각각과 생성 음성의 cosine similarity를 계산한 뒤 문장별 평균과 전체 평균을 보고하며, 절대 합격 기준이 아니라 모델 간 비교 지표로만 사용한다. SpeechBrain 모델이 영어 VoxCeleb 기반이라는 한계도 함께 기록한다.

Baseline과 학습 모델의 샘플 이름은 청취자에게 노출하지 않고 무작위 순서로 제시한다. 친절체 적용 여부는 `친절함`과 `매장 안내 음성으로서의 적합성` 점수 및 서술형 실패 사례로 판정한다.

평가자는 `calm_friendly`를 다음 기준으로 함께 판정한다.

- 안정된 억양이며 감정 표현이 과장되지 않는다.
- 고령 사용자가 메뉴명, 수량과 금액을 구분해 들을 수 있을 만큼 명확하다.
- 차분함을 만들기 위해 부자연스럽게 늘어지거나 응답성이 저하되지 않는다.

### 청취 평가 합격 계약

- 항목별 평균은 최종 평가자 전원과 평가 문장 20개의 유효 점수를 합산해 계산한다.
- 학습 모델의 `친절함`, `전체 명료도`, `매장 안내 음성으로서의 적합성`은 각각 평균 4.0/5 이상이어야 한다.
- 학습 모델의 `친절함` 평균은 동일 조건 Baseline보다 0.5점 이상 높아야 한다.
- 심각한 오독은 메뉴명·수량·단위·가격·부정 표현이 원문과 다른 의미로 들리는 경우다. 음성 깨짐은 무음, 잘림, 반복, 비정상 잡음 또는 합성 실패로 핵심 내용을 들을 수 없는 경우다.
- 심각한 오독·음성 깨짐은 최종 평가자 3명 중 2명 이상이 같은 문장에서 지적하면 1건으로 집계하며 허용 개수는 0개다.
- 핵심 주문 정보 전달 성공은 최종 평가자 3명 중 2명 이상이 해당 문장의 메뉴명·수량·단위·가격·수정 또는 결제 의도를 모두 올바르게 이해한 경우다. 20개 중 최소 18개가 성공해야 한다.
- 위 조건 중 하나라도 충족하지 못하면 Fine-tuning 실행 경로가 정상이어도 음질 PoC는 실패로 판정하고 실패 항목과 다음 실험 가설을 기록한다.

### 최종 모델 선택 계약

최종 후보는 먼저 다음 필수 조건을 모두 통과해야 한다.

- 심각한 오독·음성 깨짐 `0건`
- 핵심 주문 정보 전달 성공 `18/20개 이상`
- `친절함`, `전체 명료도`, `매장 안내 음성으로서의 적합성` 각각 `4.0/5 이상`
- 동일 조건 Benchmark 재실행 성공 및 이 Spec의 로컬 자원 한도 충족

필수 조건을 통과한 후보만 다음 100점 가중치로 평가한다.

| 영역 | 배점 | 산정 항목 |
|---|---:|---|
| 주문 정보 명료도 | 40 | 메뉴명 10, 수량·단위 15, 가격 15 |
| 차분한 친절체 품질 | 30 | 자연스러움 10, 친절함 10, 매장 안내 적합성 10 |
| 응답 성능 | 20 | warm TTFB p95 10, warm RTF p95 10 |
| 운영 적합성 | 10 | Peak RAM·VRAM 5, 재현성·통합 난이도 5 |

청취 항목은 5점 평균을 해당 배점으로 선형 환산한다. TTFB·RTF·Peak RAM·Peak VRAM처럼 낮을수록 좋은 지표는 `후보 중 최솟값 / 해당 후보 측정값 × 배점`으로 환산하며 0 또는 측정 실패 값은 유효 점수로 사용하지 않는다. Peak RAM·VRAM 5점은 각각 2.5점으로 나눈다.

재현성·통합 난이도 5점은 다음 각 1점 항목의 합계로 계산한다.

1. 잠금된 의존성과 실행 명령만으로 새 환경 설치에 성공한다.
2. checkpoint를 새 프로세스에서 3회 연속 정상 로딩한다.
3. 평가 문장 20개 반복 합성에서 실패·중단이 0건이다.
4. 공통 `TTS.synthesize()` Adapter에 모델 전용 수동 개입 없이 연결된다.
5. 공식 저장·로딩 경로를 사용하며 비공식 weight 수정이나 실행 중 파일 패치가 없다.

SIM은 영어 VoxCeleb 기반 encoder의 한국어 적용 한계가 있으므로 동점 참고 지표로만 사용하고 총점에는 넣지 않는다.

총점이 가장 높은 모델을 최종 후보로 선택한다. 점수 차이가 2점 이내면 warm TTFB p95가 낮은 모델, Peak VRAM이 낮은 모델, 통합 절차가 단순한 모델 순으로 결정한다. 어떤 후보도 필수 조건을 통과하지 못하면 최종 모델을 선택하지 않고 실패 원인과 다음 실험을 기록한다.

### 결과물

- 본 Spec을 만족하는 데이터 감사·변환 코드
- 주문 특화 평가 문장 20개
- Baseline 및 학습 모델 Benchmark 결과
- MeloTTS·Qwen3-TTS의 동일 30분 Fine-tuning 조건 비교 표·그래프와 발표용 재생 샘플
- MOS·SIM·TTFB·RTF 및 모델 선택 근거
- 데이터 필터링·검증·split 통계
- 실행 명령과 환경 정보
- checkpoint 학습 시작점이 사전학습 모델인지 확인한 근거
- `docs/worklogs/tts.md`의 PoC 결과 및 후속 결정
- 팀 공통 서비스에 전달할 TTS 오류 처리 목록: 빈 입력, 제한 초과 텍스트, 모델 오류, 자원 부족, 재생 실패
- 팀 공통 사용성 테스트에 전달할 TTS 관찰 항목: 첫 응답 대기, 주문 정보 이해, 재생 중단·재시도, 5초 이상 대기 안내. 상세 인계 계약과 기록 양식은 `docs/specs/tts-usability-handoff.md`와 `docs/tts-usability-test-handoff.md`를 따른다.

팀 공통 사용성 테스트에서는 팀 외부 최소 3명이 실제 주문 흐름을 사용해야 하며, 발견된 문제 중 최소 2개를 발표 전에 개선한다. 이 활동은 TTS 모델 청취 평가와 별도로 집계하고, TTS 관련 발견 사항과 개선 전후 결과를 본 worklog에 연결한다.

## AC (Given-When-Then)

### AC-01 · 한국어 Baseline 합성

- GIVEN: 팀 회의에서 확정한 Python 실험 환경에 MeloTTS와 한국어 사전학습 모델이 준비되어 있다.
- WHEN: 평가 문장 20개를 `KR`, speed `1.0`으로 합성한다.
- THEN: 20개 WAV가 생성되고 각 파일은 decode 가능하며 문장별 생성 결과가 기록된다.

### AC-02 · 재현 가능한 Baseline Benchmark

- GIVEN: 동일한 모델, 장치와 평가 문장 20개가 있다.
- WHEN: cold 1회와 warm 5회를 측정한다.
- THEN: 생성 지연과 TTFB의 평균·중앙값·p95, RTF, Peak RAM과 사용 가능한 경우 Peak VRAM이 계산되고 streaming 여부 및 환경 정보와 함께 저장된다.

### AC-03 · 친절체 데이터 선택

- GIVEN: AI Hub 데이터셋 ID 71349의 JSON과 WAV가 있다.
- WHEN: 데이터 변환기를 실행한다.
- THEN: `style.style=친절체`, `src_type=매장응대`, `style.emotion=기쁨` 조건을 모두 만족하는 레코드만 선택되고 선택 전후의 레코드 수·시간·화자 수가 기록된다.

### AC-04 · 잘못된 데이터 제외

- GIVEN: 정상 레코드와 누락 WAV, 손상 WAV, stereo, 비 44.1 kHz, 빈 텍스트 레코드가 섞여 있다.
- WHEN: 데이터 검증기를 실행한다.
- THEN: 정상 레코드만 manifest에 포함되고 제외된 레코드는 사유별로 집계되며 원본 파일은 변경되지 않는다.

### AC-05 · 단일 화자·녹음 세션 독립 split

- GIVEN: `MALLO_TTS_TARGET_SPEAKER_ID`와 녹음 그룹이 3개 이상 지정되어 있다.
- WHEN: seed `42`로 train/validation/test manifest를 생성한다.
- THEN: 모든 레코드는 목표 화자 한 명에 속하고 정확히 한 split에만 포함되며 어떤 녹음 그룹도 둘 이상의 split에 나타나지 않는다. train의 예약 `ref_audio`는 두 모델의 paired training records와 validation/test에서 제외된다.

### AC-06 · MeloTTS manifest 호환성

- GIVEN: 생성된 train/validation/test manifest가 있다.
- WHEN: MeloTTS 텍스트 전처리를 실행한다.
- THEN: 각 행이 `audio_path|speaker_id|KR|text`로 파싱되고 전처리가 오류 없이 완료된다.

### AC-07 · 단계별 학습과 checkpoint 추론

- GIVEN: 목표 화자의 30분 adaptation package에서 예약 `ref_audio`를 제외한 paired training manifest와 validation manifest가 있다.
- WHEN: 공식 학습용 G/D/DUR 가중치에서 학습을 시작하고 500 step마다 checkpoint와 평가 음성을 생성한다.
- THEN: 30분 단계에서 전처리·학습·checkpoint·추론이 모두 성공하고 실제 데이터 시간·batch size·학습 step이 기록된다. 1시간 이상 확장은 이 AC의 완료 조건이 아니다.

### AC-08 · Fine-tuning 여부 판정

- GIVEN: MeloTTS 학습 실행 기록과 checkpoint가 있다.
- WHEN: G/D/DUR 초기 가중치 로딩 로그, shape mismatch와 optimizer 시작 상태를 확인한다.
- THEN: 공식 학습용 G/D/DUR에서 모델 가중치를 이어받고 optimizer를 새로 시작한 근거가 있으면 Fine-tuning으로, 그렇지 않으면 신규 학습으로 명시되어 두 결과가 혼용되지 않는다.

### AC-09 · 동일 학습·평가 조건 다중 모델 비교

- GIVEN: MeloTTS와 Qwen3-TTS가 동일한 30분 adaptation package·paired training records·split·seed·학습 step 예산으로 Fine-tuning되어 추론 가능하다.
- WHEN: held-out 평가 문장 20개를 각 모델의 공식 기본 생성 설정, 같은 장치와 측정 코드로 생성하고 후처리 time-stretch 없이 블라인드 청취 평가를 진행한다.
- THEN: 최소 두 구조의 모델에 대한 MOS·SIM·TTFB·RTF·자원 사용량과 7개 청취 항목이 표·그래프로 정리되고, 친절함 및 숫자·금액·메뉴명 실패 사례와 최종 모델 선택 근거가 함께 기록된다.

### AC-10 · 저장소 데이터 보호

- GIVEN: AI Hub 원본, manifest, checkpoint, 생성 WAV와 측정 결과가 생성되었다.
- WHEN: Git 변경 목록을 확인한다.
- THEN: AI Hub 원본과 대용량 생성물은 포함되지 않고 코드, 평가 문장, 요약 결과 및 재현 절차만 커밋 대상으로 남는다.

### AC-11 · 차분한 친절체 블라인드 평가

- GIVEN: 모델 정보가 제거되고 무작위 순서로 배치된 Baseline과 학습 모델의 동일 문장 샘플이 있다.
- WHEN: 개발 중에는 TTS 담당자 1명이 평가하고 최종 후보 비교에는 최소 3명이 참여한다.
- THEN: 모든 평가자가 7개 청취 항목과 `calm_friendly`의 안정된 억양·과장되지 않은 감정·명료도·부자연스러운 지연 여부를 기록하며, 학습 모델이 3개 핵심 항목 평균 4.0/5 이상, Baseline 대비 친절함 0.5점 이상 향상, 심각한 오독·음성 깨짐 0개, 핵심 정보 전달 성공 18/20개 이상인지 판정된다.

### AC-12 · AI Hub 산출물 공개 제한

- GIVEN: 원본 데이터, 데이터셋 문장 예시, checkpoint, 생성 WAV, 코드와 집계 통계가 있다.
- WHEN: Git 변경 목록과 외부 공유 대상을 검토한다.
- THEN: 원본 및 원문을 복원할 수 있는 자료는 제외되고 checkpoint와 생성 WAV는 서면 허가 확인 전까지 비공개로 유지되며, 공개 결과물에는 AI Hub 데이터 활용 사실이 표시된다.

### AC-13 · AI Hub 라이선스 후속 문의

- GIVEN: checkpoint 또는 생성 WAV를 외부에 공개하거나 학습 결과를 제품에 적용하려 한다.
- WHEN: 공개 또는 제품 적용 승인 여부를 검토한다.
- THEN: AI Hub 또는 수행기관의 서면 답변과 답변 일자가 기록되어 있지 않으면 공개·제품 적용을 중단하고 로컬 비공개 상태를 유지한다.

### AC-14 · Qwen3-TTS 동일 조건 Fine-tuning 및 합성

- GIVEN: 팀 회의에서 확정한 Python 환경, `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, MeloTTS와 동일한 30분 adaptation package·paired training records·split·seed·학습 step 예산이 있다.
- WHEN: 공식 JSONL과 tokenizer로 2레코드 스모크 테스트를 통과한 뒤 Qwen3-TTS를 Fine-tuning하고 학습·검증 데이터와 중복되지 않는 평가 문장 20개를 `generate_custom_voice`로 합성한다.
- THEN: `audio_codes` JSONL, checkpoint와 20개 WAV, 실행 환경·모델 revision·학습 설정이 기록된다. 0.6B가 실패하면 자원 한도 안에서 1.7B를 시도하고, 둘 다 실패하면 동일 조건 모델 비교를 미충족으로 판정하며 zero-shot 결과로 대체하지 않는다.

### AC-15 · 최종 모델 선택

- GIVEN: 동일 조건으로 평가한 후보별 필수 조건, 청취 점수, warm TTFB p95, RTF, Peak RAM·VRAM과 재현성 기록이 있다.
- WHEN: 최종 모델 선택 계약의 필수 조건과 100점 가중치를 적용한다.
- THEN: 탈락 후보와 사유, 후보별 영역 점수·총점, 동점 처리 근거 및 최종 선택 모델이 기록되며 모든 후보가 필수 조건을 통과하지 못하면 선택 보류로 기록된다.

### AC-16 · MOS 및 SIM 산출

- GIVEN: MeloTTS Baseline과 동일 조건으로 Fine-tuning한 MeloTTS·Qwen3-TTS가 생성한 평가 음성, 목표 화자의 test split 참조 음성 3개가 있다.
- WHEN: 최소 3명의 블라인드 자연스러움 평가와 고정 SpeechBrain revision의 화자 임베딩 비교를 수행한다.
- THEN: 모델별 내부 MOS와 문장별·전체 SIM 평균이 산출되고, 평가 인원·척도·리샘플링·speaker encoder 및 한국어 적용 한계가 기록된다.

### AC-17 · 팀 공통 사용성 테스트 인계

- GIVEN: TTS가 통합된 실제 주문 흐름과 TTS 오류 처리 목록이 있다.
- WHEN: 팀 외부 사용자 최소 3명이 서비스를 사용한다.
- THEN: 청취 평가와 별도로 첫 응답 대기·주문 정보 이해·재생 중단·재시도·5초 이상 대기 안내를 관찰하고, 발견한 문제 중 최소 2개의 개선 전후 근거가 팀 결과물과 TTS worklog에 연결된다.
