---
title: "Spec — Whisper 모델 크기 비교 (base/small/medium)"
tags: [spec]
---

# Spec — Whisper 모델 크기 비교 (base/small/medium)

## Why

- **페르소나**: 카페 키오스크에 음성으로 주문하는 고령 사용자 (음성 입력 → STT → 주문 처리)
- **상황**: S-20에서 `openai/whisper-medium` QLoRA 파인튜닝의 정확도를 확인했다. 최종 STT 모델 선정(S-14) 전에 medium이 유일한 선택인지, 더 작은 모델(base/small)로도 충분한지 판단 근거가 없다.
- **문제**:
  1. 모델 크기에 따른 정확도(CER/WER)·지연·자원(VRAM)의 정량 비교가 없음
  2. S-20의 150샘플 평가는 validation/test가 섞인 집계라 모델 선택에 test가 오염될 위험
  3. 문장별 평균 CER/WER는 짧은 문장과 긴 문장이 같은 비중 → 선택 편향
- **측정 지표**: base/small/medium의 validation CER/WER + latency + VRAM (모델 선택), 최종 선정 모델의 test 1회 성능 보고

## Goal

- **해결 목표**: 동일 데이터·동일 설정(BF16, 동일 샘플 수·시드)에서 모델 크기 3종을 비교해 S-14 최종 선정의 수치 근거를 만든다.
- **성공 기준**:
  - 모델 선택은 validation split에서만 수행 (test split 미사용)
  - CER/WER는 corpus-level(전체 목록 집계)로 계산하고 validation/test를 분리 보고
  - GPU 없는 단위 테스트로 데이터 선택·집계 로직 검증 (CI에서 실행)
- **Out of Scope**: QLoRA 파인튜닝 모델의 크기 비교, TTS, 실제 키오스크 배포, Whisper large 계열

## What

**Happy Path**
1. `compare_model_sizes.py --split validation --models base,small,medium` 실행
2. 각 모델 BF16으로 로드 → validation 샘플 전부 전사 → corpus-level CER/WER + latency + VRAM + 파라미터 수 산출
3. 출력 표에서 validation 기준으로 최적 모델 선택 (정확도 우선 → medium, 저지연 절충 → small)
4. 선정된 모델만 `--split test --models <선정>`으로 test 1회 평가 → 최종 보고
5. 결과 CSV를 `models/model-size-compare/`에 저장, worklog 갱신

**Edge Cases** (최소 5개 + 처리 방식)

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 오디오 파일이 누락됨 | 빈 텍스트 + latency NaN 기록, CER/WER 오류로 집계 |
| EC-02 | 멀티채널 오디오 | 채널 평균(mean axis=1)으로 모노 변환 |
| EC-03 | `--split test`에서 여러 모델 지정 | 허용하되 문서에서 "test는 최종 모델 1회 보고용"을 안내 |
| EC-04 | 잘못된 모델 키 | `ValueError` (허용 목록: base/small/medium) |
| EC-05 | split CSV가 없음 | `FileNotFoundError` |
| EC-06 | CUDA 사용 불가 | `require_cuda()`가 `RuntimeError`로 조기 종료 |

## How

- 실행 (GPU venv, `src/adapters/stt`에서):
  - 1단계(모델 선택): `python compare_model_sizes.py --split validation --models base,small,medium --samples 150 --seed 42`
  - 2단계(최종 보고): `python compare_model_sizes.py --split test --models medium --samples 150 --seed 42`
- 모델: `openai/whisper-base` / `openai/whisper-small` / `openai/whisper-medium`, dtype **bfloat16**, `language="ko"`, `task="transcribe"`, `max_new_tokens=440`
- 데이터: `common.VALIDATION_CSV`(validation split) / `common.TEST_CSV`(test split) — 화자 단위 분할, seed 42. `--samples`/`--seed`로 샘플링 제어(기본 150/42).
- 지표: `metrics.corpus_cer` / `metrics.corpus_wer` (문장별 평균 아님, 전체 목록을 한 번에 집계)
- latency: 샘플별 `perf_counter` 측정(모델 로딩 제외), NaN은 평균에서 제외
- VRAM: `torch.cuda.max_memory_allocated()` (모델 로딩 후 reset)
- 출력 CSV: `models/model-size-compare/compare_{split}_{n}_seed-{seed}.csv` (utf-8-sig)

## AC (Given-When-Then)

**AC-01 · validation split에서 모델 선택**
- GIVEN: validation.csv 존재
- WHEN: `--split validation --models base,small,medium` 실행
- THEN: 출력 표에 validation만 사용된 corpus-level CER/WER·latency·VRAM·params가 모델별로 출력되고 test 데이터는 포함되지 않는다.

**AC-02 · corpus-level 집계**
- GIVEN: 두 문장(짧은 1글자 + 긴 20글자)의 예측
- WHEN: `summarize_corpus`로 집계
- THEN: 문장별 평균이 아닌 전체 글자/단어 기준 오류율로 계산된다.

**AC-03 · split별 분리 보고**
- GIVEN: `--split both` 실행
- WHEN: `summarize_corpus` 호출
- THEN: validation/test 행이 각각 n·CER·WER을 따로 보고한다.

**AC-04 · 누락 오디오 처리**
- GIVEN: audio_path에 파일이 없는 샘플
- WHEN: 전사 루프 실행
- THEN: 빈 텍스트·NaN latency로 기록되고, corpus CER/WER에는 오류로 반영되며 latency 평균에서는 제외된다.

**AC-05 · 데이터 선택·집계 단위 테스트**
- GIVEN: CI 환경 (GPU 없음)
- WHEN: `pytest tests/unit/test_stt_model_size_compare.py`
- THEN: build_dataset(split 선택·샘플링·CSV 누락)과 summarize_corpus(split별·corpus·NaN) 테스트가 통과한다.

**AC-06 · 기본 split은 validation**
- GIVEN: `--split` 미지정
- WHEN: 스크립트 실행
- THEN: validation만 평가한다 (기본값 = validation, test는 최종 모델 1회 보고용).
