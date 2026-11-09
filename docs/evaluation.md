# Mallo — 정량 결과와 검증 범위

## TTS 후보 실험

동일 **20문장 GPU 비교** 당시 기록:

| 후보 | 평균 생성 지연 |
|---|---:|
| Melo Base | 198.5ms |
| Melo Friendly | 204.1ms |
| Qwen Base | 6.91s |
| Qwen Friendly | 28.20s |

Melo Friendly의 생성 지연은 Base 대비 약 **5.6ms (+2.8%)** 증가했지만, 목표로 한 친절체 안내를 위해 선택했습니다.

별도 **production TTS checkpoint** 기록: **평균 0.38s · p95 0.53s · RTF 0.0894**.

## 최종 E2E

**Real Warm 50턴** 측정 결과:

- 전체 응답 지연: **p95 3.338s**
- 1.5초 목표 초과: **30/50턴**
- 따라서 최종 서비스가 1.5초 응답 요구사항을 충족했다고 주장할 수 없습니다.
- 이전에 보고된 **p95 312.2ms**는 실제 TTS·브라우저 첫 재생을 모두 포함하지 않는 별도 제한 측정이며 최종 E2E와 직접 비교하지 않습니다.

## 해석상의 주의

- TTS 모듈 단독, API 일부 흐름, 브라우저 사용자 전체 지연은 서로 다른 실험입니다.
- 특정 GPU·문장 세트·runtime·네트워크 조건의 결과를 모든 환경의 지연 보장으로 확대하지 않습니다.
- 사용성 탐색·모델 학습·음성 품질의 일부 검증이 이루어졌지만 최종 사용자 이해도 평가가 완료됐다고 주장하지 않습니다.

[프로젝트 개인 검증 원장](https://github.com/nanocode00/resume/blob/main/experiences/mallo-rework-checkpoint.md)
