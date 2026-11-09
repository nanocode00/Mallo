---
title: "Spec — 마이크·자동 Listening·수동 재입력 Fallback·VAD"
tags: [spec]
---

# Spec — 마이크·자동 Listening·수동 재입력 Fallback·VAD

> `MicrophoneRecorder`와 기존 구현 식별자 `TapToTalk`는 과거 구현 결과로 유지한다.
> 제품 Trigger의 기준은 **주문하기 1회 → 사용자 응답이 필요한 TTS 종료 후 자동
> Listening**이며, `TapToTalk` 클래스명은 매 발화마다 버튼을 누르는 제품 정책을 뜻하지
> 않는다. 현재 구현 gap은 `docs/notion-reconciliation-report.md`에 기록한다.

## Why

- **페르소나**: 시각·터치 기반 키오스크 이용에 부담을 느끼는 고령 사용자
- **상황**: 음성으로 카페 주문을 시도하지만, "언제 말해도 되는지"가 불명확해서 마이크 사용을 꺼린다. 키오스크 마이크는 항상 켜져 있으면 배경 소음이 STT로 전달된다.
- **문제**:
  1. 항상 녹음하면 배경 소음·발화 외 말이 STT로 넘어감
  2. 말하는 동안 UI가 "듣는 중"임을 알 수 없음
  3. 녹음 시작/종료 기준이 없어 고령 사용자가 말을 마쳤는데도 계속 녹음됨
- **측정 지표**: 데모에서 발화당 녹음 오류(잘림/과녹음) 0회, TTS Playback 종료 후 Listening 활성화 성공률, VAD 종료 정확도

## Goal

- **해결 목표**: 세션 안에서 사용자 응답이 필요한 TTS가 끝나면 버튼 조작 없이 녹음을 시작하고, VAD로 발화를 종료해 STT에 안전하게 전달한다. 수동 마이크는 같은 입력 경로를 재시작하는 Fallback으로 제공한다.
- **성공 기준**:
  - 대기 상태에서는 마이크가 비활성화된다.
  - `주문하기` 이후 매장/포장과 주문 질문 TTS의 실제 재생 종료 이벤트가 발생하면 자동 Listening이 시작된다.
- TTS 재생 중에는 Listening을 시작하지 않고 Barge-in을 받지 않는다.
- 음성 Command가 화면을 전환하면, 그 Command의 응답 TTS를 새 화면에서 재생한 뒤 실제 playback 종료 이벤트에만 `SYSTEM_PROMPTED` Listening을 재개한다. Touch 전환은 자동 Listening을 재개하지 않는다.
  - 자동 Listening Timeout·인식 실패 뒤 수동 마이크로 재입력할 수 있다.
  - 발화 감지 실패 없이 합성 오디오 기준 무음 감지 정확도 100% (단위 테스트)
  - 최대 녹음 시간 초과 시 안전 종료 (잘림 없이 버퍼 반환)
  - 반환 포맷은 STT 계약(`interfaces/stt.py`의 `transcribe(audio: bytes)`)과 호환되는 WAV bytes
  - `TapToTalk`과 recorder의 sample rate는 `record_from_mic()`에서 일치를 보장한다
- **Out of Scope**: 마이크 음질 보정, 노이즈 억제(S-06/07은 기존 전처리 파이프라인), 다중 마이크, 스트리밍 STT, 녹음 파일 보존 정책

## What

**Happy Path**
1. 사용자가 대기 화면의 `주문하기`를 한 번 눌러 세션을 시작한다.
2. 시스템이 사용자 응답이 필요한 안내를 재생하며 그동안 마이크를 비활성화한다.
3. 실제 TTS Playback 종료 이벤트가 발생하면 `SYSTEM_PROMPTED` Listening을 시작한다.
4. `MicrophoneRecorder`가 16kHz 모노 float32 프레임(30ms)을 스트리밍한다.
5. `VAD`가 첫 발화와 발화 후 무음을 감지해 입력을 종료한다.
6. `AudioBuffer`와 `to_wav_bytes()`가 PCM16 WAV bytes를 만들어 STT에 전달한다.
7. 인식 실패나 Timeout 뒤에는 사용자가 수동 마이크를 눌러 `USER_INITIATED_FALLBACK`으로 같은 4~6단계를 다시 실행할 수 있다.
8. 음성 Command가 화면을 전환한 경우 새 화면을 먼저 렌더링하고, 같은 응답 TTS 종료 뒤 새 화면의 `SYSTEM_PROMPTED` Listening을 시작한다.
   매장/포장 선택의 음성 응답은 선택 완료와 다음 주문 질문을 하나의 안내로 재생한다.
9. 음성 속도 변경 요청의 안내 TTS가 끝나면 같은 화면에서 `SYSTEM_PROMPTED` Listening을 재개한다. 터치 속도 조작과 재안내·기본 속도 요청은 자동 Listening을 시작하지 않는다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | Listening 후 최대 시간까지 발화 없음 | 질문·Cart를 유지하고 Listening 종료, 수동 재입력 제공 |
| EC-02 | 녹음 중 최대 시간(10초) 도달 | 즉시 종료, 지금까지 버퍼 반환 (잘림 없음) |
| EC-03 | 발화 중간의 1초 미만 잠깐 무음 | `silence_timeout`(1.0초)보다 짧으면 계속 녹음 |
| EC-04 | 마이크/장치 없음 또는 `sounddevice` 미설치 | `AudioInputError` 발생 (모듈 import 시점이 아니라 사용 시점에 오류) |
| EC-05 | 30ms 프레임보다 짧은 마지막 조각 | 버퍼에 정상 누적, 크기 보정 없이 그대로 반환 |
| EC-06 | `TapToTalk`과 recorder의 sample rate 불일치 | `record_from_mic()`에서 `AudioInputError` 발생 (녹음 시작 전 검증) |
| EC-07 | TTS 재생 중 Listening 시작 요청 | 마이크를 열지 않고 Playback 종료 이벤트까지 대기 |
| EC-08 | Listening 중 GUI 응답 | Audio Session을 종료하고 GUI 입력을 한 번만 처리 |
| EC-09 | 음성 전환 응답의 TTS 종료 전에 Touch 입력 또는 stale 응답 도착 | pending 자동 Listening을 취소하고 이전 화면/응답이 마이크를 열지 못하게 한다 |

## How

```
모듈 (패키지: src/adapters/audio/)

voice_input_controller.py
  class VoiceInputController:
      # desired orchestration contract
      # IDLE에서는 mic off
      # user_response_required + playback_end → SYSTEM_PROMPTED capture
      # manual mic → USER_INITIATED_FALLBACK capture
      # TTS_PLAYING 중 capture 금지

recorder.py
  class MicrophoneRecorder:
      def __init__(self, sample_rate: int = 16000, frame_ms: int = 30,
                   device: int | None = None)
      @property sample_rate: int
      @property frame_size: int            # sample_rate * frame_ms / 1000
      def stream_chunks(self) -> Iterator[np.ndarray]    # sounddevice InputStream lazy import
      # sounddevice 미설치/장치 없음 → AudioInputError (사용 시점)

tap_to_talk.py
  class TapToTalk:
      def __init__(self, vad: VAD, sample_rate: int = 16000,
                   max_duration: float = 10.0, silence_timeout: float = 1.0,
                   min_speech_duration: float = 0.3)
      def record(self, chunks: Iterable[np.ndarray]) -> np.ndarray
      # 발화 시작 후 silence_timeout 연속 무음 → 종료. 최대 10초 도달 → 즉시 반환.
      # 첫 발화 없이 max_duration 초과 → NoSpeechError
      # record()는 chunk iterable을 주입받아 마이크 없이도 단위 테스트 가능
      def record_from_mic(self, recorder: MicrophoneRecorder) -> np.ndarray
      # recorder.sample_rate와 TapToTalk.sample_rate가 다르면 AudioInputError
      # 마이크 스트림을 record()로 연결 — MicrophoneRecorder.stream_chunks() 사용
      def record_wav_from_mic(self, recorder: MicrophoneRecorder) -> bytes
      # record_from_mic() 결과를 to_wav_bytes()로 인코딩해 STT 계약 호환 WAV bytes 반환
```

`VoiceInputController`는 제품 Trigger를 소유하고, 기존 `TapToTalk`는 이름과 무관하게 한 번의 Audio Session에서 VAD 종료까지 프레임을 수집하는 하위 컴포넌트로 재사용한다.

- 마이크 샘플링: 모노 16kHz, float32, 30ms 프레임
- 기존 컴포넌트 테스트 기본값: 임계 -35dB, 발화 판정 비율 50%, 무음 종료 1.0초. 제품용 Silence Threshold는 고령 사용자 발화 테스트 후 확정한다.
- **sample rate 계약**: `record_from_mic()`·`record_wav_from_mic()`는 recorder와
  TapToTalk의 sample rate가 다르면 녹음 시작 전에 `AudioInputError`를 발생시킨다.
  무음 시간·최대 녹음 시간은 TapToTalk 기준, WAV 헤더는 recorder 기준으로
  계산되므로 이 불일치를 허용하면 실제 종료 시간이 설정값과 달라질 수 있다.
- 의존성: `sounddevice` (런타임 마이크 캡처에만, lazy import — 단위 테스트는 시스템 python에서 마이크 없이 통과해야 함)

## AC (Given-When-Then)

**AC-05 · TapToTalk 무음 종료**
- GIVEN: 0.5초 톤 + 1.5초 무음의 청크 스트림 (`silence_timeout=1.0`)
- WHEN: `record()` 호출
- THEN: 반환 배열 길이는 0.5초 발화(+최대 1초 무음)에 해당

**AC-06 · TapToTalk 발화 없음 오류**
- GIVEN: 11초 무음 청크 스트림 (`max_duration=10.0`)
- WHEN: `record()` 호출
- THEN: `NoSpeechError` 발생

**AC-07 · TapToTalk 최대 시간 반환**
- GIVEN: 11초 연속 톤 스트림 (`max_duration=10.0`)
- WHEN: `record()` 호출
- THEN: 반환 배열 길이는 10초 이하, 오류 없음

**AC-09 · Recorder 장치 부재 오류**
- GIVEN: `sounddevice` 미설치 또는 마이크 없는 환경
- WHEN: `MicrophoneRecorder().stream_chunks()` 사용
- THEN: `AudioInputError` 발생 (모듈 import 시점에는 오류 없음)

**AC-10 · chunk 스트림 형식**
- GIVEN: `sample_rate=16000, frame_ms=30` 설정
- WHEN: 스트림의 프레임 검사
- THEN: 각 프레임은 모노 float32, 길이 480

**AC-11 · TapToTalk/recorder sample rate 계약**
- GIVEN: `TapToTalk(sample_rate=16000)`과 `MicrophoneRecorder(sample_rate=48000)`
- WHEN: `record_from_mic()` 또는 `record_wav_from_mic()` 호출
- THEN: `AudioInputError` 발생 (녹음 시작 전)

**AC-12 · sample rate 일치 시 정상 녹음**
- GIVEN: 동일 sample rate(16000)의 `TapToTalk`과 `MicrophoneRecorder`
- WHEN: `record_from_mic()` 호출
- THEN: 오류 없이 발화 프레임 배열 반환

**AC-13 · TTS 종료 후 자동 Listening**
- GIVEN: 주문 세션에서 사용자 응답이 필요한 TTS가 재생 중이다.
- WHEN: 실제 Playback 종료 이벤트가 발생한다.
- THEN: 별도 마이크 버튼 입력 없이 `SYSTEM_PROMPTED LISTENING`이 한 번 시작된다.

**AC-14 · TTS와 마이크 상호배제**
- GIVEN: TTS Playback이 아직 끝나지 않았다.
- WHEN: 자동 Listening 시작 조건을 평가한다.
- THEN: 마이크는 비활성화 상태이고 Barge-in 입력을 수집하지 않는다.

**AC-15 · 수동 마이크 Fallback**
- GIVEN: 자동 Listening이 Timeout 또는 인식 실패로 끝났다.
- WHEN: 사용자가 수동 마이크 버튼을 누른다.
- THEN: Cart와 질문 Context를 유지한 채 `USER_INITIATED_FALLBACK LISTENING`이 시작된다.
