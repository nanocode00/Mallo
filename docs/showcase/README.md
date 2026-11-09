# 최종 제출용 오프라인 쇼케이스

생성 코드는 `scripts/showcase/`, 생성물은 Git 제외 대상인 `artifacts/showcase/`에 둔다. 두 HTML은 상대 WAV만 사용하므로 backend 없이 파일로 열 수 있다.

## TTS 재생성

```bash
HF_HUB_OFFLINE=1 PYTHONPATH=src .venvs/runtime/bin/python \
  scripts/showcase/build_tts_offline_showcase.py \
  --output-dir artifacts/showcase/tts-final-YYYYMMDD
```

- 모델 비교: MeloTTS baseline과 MeloTTS fine-tuned G_2800에 같은 `normalize_korean_text_for_tts()` 결과를 입력한다.
- Level 비교: 같은 정규화 결과에 기존 Adaptive Level 0/1/2 변환과 속도 정책을 적용한다.
- `results.json`에는 원문, 공통 normalized text, 모델/레벨, WAV, 시간 정보를 보존한다.

## STT 재생성

```bash
HF_HUB_OFFLINE=1 PYTHONPATH=src .venvs/runtime/bin/python \
  scripts/showcase/build_stt_offline_showcase.py \
  --input-wav path/to/representative-1.wav path/to/representative-2.wav \
  --output-dir artifacts/showcase/stt-final-YYYYMMDD
```

기본 모델은 `models/stt/final-train65-merged-bf16`이며, 하나의 모델 로드로 입력 WAV 전체를 처리한다. `results.json`과 `index.html`에는 파일명, 전사, 추론 시간, 입력 길이가 기록된다.

## 공개 경계

생성물은 최종 제출/내부 검토용 로컬 산출물이다. AI Hub 기반 음성은 별도 서면 허가와 표시 조건 확인 없이 외부에 공개하지 않는다. 기준은 `docs/aihub-tts-license-inquiry.md` (공개본에서 제외)를 따른다.

## 구버전 보관

이전 standalone HTML, raw WAV, 비공개 정적 사이트는 `artifacts/showcase/legacy/tts/`에 보관한다. 최신 최종 결과물인 `artifacts/showcase/stt-final-YYYYMMDD/` 및 `artifacts/showcase/tts-final-YYYYMMDD/`와 섞지 않는다.
