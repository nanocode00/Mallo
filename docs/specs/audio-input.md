---
title: "Spec — 음성 입력 오디오 유틸리티 (S-03 Audio Buffer · S-04 VAD · WAV 변환)"
tags: [spec]
---

# Spec — 음성 입력 오디오 유틸리티 (S-03 Audio Buffer · S-04 VAD · WAV 변환)

> 이 PR은 음성 입력 파이프라인을 두 PR로 분리한 **1/2**입니다.
> 여기서는 마이크 없이도 단위 테스트가 가능한 오디오 유틸리티
> (`AudioBuffer`, `EnergyVAD`, WAV 변환, 예외)만 다룹니다.
> `MicrophoneRecorder`와 기존 구현 식별자 `TapToTalk`는 `audio-input-mic.md`에서 다룹니다. `TapToTalk`라는 클래스명은 현재 제품의 매 턴 Tap 정책을 뜻하지 않습니다.

## Why

- **페르소나**: 시각·터치 기반 키오스크 이용에 부담을 느끼는 고령 사용자
- **상황**: 음성으로 카페 주문을 시도하지만, "언제 말해도 되는지"가 불명확해서 마이크 사용을 꺼린다. 키오스크 마이크는 항상 켜져 있으면 배경 소음이 STT로 전달된다.
- **문제**:
  1. 항상 녹음하면 배경 소음·발화 외 말이 STT로 넘어감
  2. 말하는 동안 UI가 "듣는 중"임을 알 수 없음
  3. 녹음 시작/종료 기준이 없어 고령 사용자가 말을 마쳤는데도 계속 녹음됨
- **측정 지표**: 데모에서 발화당 녹음 오류(잘림/과녹음) 0회, Listening 활성화 → STT 입력 준비까지의 오디오 처리 지연 300ms 이하

## Goal

- **해결 목표**: 자동 Listening과 수동 마이크 Fallback이 공유할 수 있도록, 마이크 캡처의 기반인 오디오 유틸리티(프레임 누적·발화 판정·WAV 인코딩)를 제공한다.
- **성공 기준**:
  - `AudioBuffer`가 모노 float32 프레임을 누적하고, 최대 시간 초과 시 안전하게 거부한다.
  - `EnergyVAD`가 프레임 단위로 무음/발화를 판정한다 (합성 오디오 기준 단위 테스트 통과).
  - `to_wav_bytes()`가 STT 계약(`interfaces/stt.py`의 `transcribe(audio: bytes)`)과 호환되는 PCM16 WAV bytes를 반환한다.
- **Out of Scope**: 마이크 캡처(`MicrophoneRecorder`)와 세션 Trigger orchestration은 분리 Spec(`audio-input-mic.md`)에서 관리, 마이크 음질 보정, 노이즈 억제(S-06/07은 기존 전처리 파이프라인), 다중 마이크, 스트리밍 STT, 녹음 파일 보존 정책

## What

**Happy Path**
1. STT 계약은 `audio: bytes`(PCM16 WAV)만 요구하므로, 프레임 누적 유틸리티가 이를 제공한다
2. `AudioBuffer`가 모노 float32 프레임(예: 30ms)을 순서대로 누적한다
3. `EnergyVAD`가 프레임 단위로 발화 여부를 판정한다
4. 누적분은 `to_wav_bytes()`로 PCM16 WAV bytes로 인코딩해 STT 계약과 호환된다

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 버퍼 최대 시간 초과 append | `BufferLimitError` 발생, 기존 누적분은 유지 |
| EC-02 | 모노 float32가 아닌 프레임 append | `ValueError` (지원: 모노 float32만) |
| EC-03 | 소음이 섞인 프레임(일부만 큰 진폭) | `min_speech_ratio` 미만이면 무음으로 판정 |
| EC-04 | STT 계약용 인코딩 | stdlib `wave` + PCM16으로 WAV bytes 생성 |

## How

```
패키지: src/adapters/audio/
모듈:

buffer.py
  class AudioBuffer:
      def __init__(self, sample_rate: int = 16000, max_duration: float = 10.0)
      def append(self, samples: np.ndarray) -> None      # 모노 float32만 허용
      def as_array(self) -> np.ndarray                   # (N,) float32 누적분
      def reset(self) -> None
      @property sample_count: int
      @property duration_seconds: float
      # max_duration 초과 append 시 BufferLimitError

vad.py
  class EnergyVAD:
      def __init__(self, sample_rate: int = 16000, frame_ms: int = 30,
                   threshold_db: float = -35.0, min_speech_ratio: float = 0.5)
      def is_speech(self, frame: np.ndarray) -> bool
      # 순수 numpy, 외부 의존성 없음. RMS(dB) >= threshold_db 인 샘플 비율 >= min_speech_ratio 면 발화
  VAD(Protocol):
      def is_speech(self, frame: np.ndarray) -> bool

wav.py
  def to_wav_bytes(samples: np.ndarray, sample_rate: int = 16000) -> bytes
  # stdlib wave + PCM16 변환. STT transcribe(audio: bytes) 계약과 호환

예외: audio/errors.py
  class AudioInputError(RuntimeError)
  class NoSpeechError(RuntimeError)
  class BufferLimitError(RuntimeError)
```

- 마이크 샘플링 규약(후속 PR에서 사용): 모노 16kHz, float32, 30ms 프레임
- VAD 구현 기본값: 임계 -35dB, 발화 판정 비율 50%, 무음 종료 1.0초. 제품 Threshold는 사용자 테스트 후 확정한다.
- 의존성: numpy (sounddevice는 후속 PR의 마이크 캡처에서만 lazy import)

## AC (Given-When-Then)

**AC-01 · AudioBuffer 누적/초기화**
- GIVEN: 빈 `AudioBuffer(sample_rate=16000, max_duration=10.0)`
- WHEN: 2개 프레임(각 480샘플)을 append 후 `as_array()`, 이어서 `reset()`
- THEN: `as_array()`는 길이 960, `reset()` 후 `sample_count == 0`

**AC-02 · AudioBuffer 최대 시간 제한**
- GIVEN: `max_duration=0.05`(약 800샘플)인 버퍼에 480샘플 2개 append
- WHEN: 두 번째 append 시도
- THEN: `BufferLimitError` 발생

**AC-03 · EnergyVAD 무음/발화 판정**
- GIVEN: 무음 프레임(전부 0)과 0.3 진폭 톤 프레임(1kHz)
- WHEN: 각각 `is_speech()` 호출
- THEN: 무음은 False, 톤은 True

**AC-04 · EnergyVAD 소음 혼입 판정**
- GIVEN: 80%가 0, 20%가 큰 진폭인 프레임 (`min_speech_ratio=0.5`)
- WHEN: `is_speech()` 호출
- THEN: False (임계 초과 샘플 비율 0.2 < 0.5)

**AC-08 · WAV 인코딩**
- GIVEN: 1초 16kHz 모노 샘플
- WHEN: `to_wav_bytes()` 호출 후 `wave`로 디코드
- THEN: PCM16, 16000Hz, 모노, 재생 시간 ≈ 1초

> 마이크·Trigger 관련 AC(AC-05~07, AC-09~10)는 `docs/specs/audio-input-mic.md`에 정의합니다.
