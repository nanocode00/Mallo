from __future__ import annotations

import statistics

from app.service import build_mock_service
from domain.models import Cart


def measure_e2e_latency(iterations: int = 20) -> dict[str, dict[str, float]]:
    """PTT 종료(오디오 입력)부터 최종 음성 응답 시작까지의 지연을 측정한다.

    Mock STT/Order/TTS 환경에서 ``handle_audio``를 반복 호출해 모듈별 및
    전체 E2E 지연 분포(평균/최소/최대)를 수집한다. 실제 STT/오디오 길이는
    어댑터 교체 시 자연스럽게 반영된다.
    """
    service = build_mock_service()
    totals: list[float] = []
    stt: list[float] = []
    nlu: list[float] = []
    agent: list[float] = []
    tts: list[float] = []

    for _ in range(iterations):
        result = service.handle_audio(b"dummy-audio", Cart())
        totals.append(result.total_e2e_latency_ms)
        stt.append(result.stt_latency_ms)
        nlu.append(result.nlu_latency_ms)
        agent.append(result.agent_latency_ms)
        tts.append(result.tts_latency_ms)

    def summarize(values: list[float]) -> dict[str, float]:
        return {
            "mean_ms": round(statistics.mean(values), 2),
            "min_ms": round(min(values), 2),
            "max_ms": round(max(values), 2),
        }

    return {
        "total_e2e": summarize(totals),
        "stt": summarize(stt),
        "nlu": summarize(nlu),
        "agent": summarize(agent),
        "tts": summarize(tts),
    }


def main() -> None:
    report = measure_e2e_latency()
    print("Mallo E2E Latency Measurement (mock adapters, 20 iterations)")
    print("-" * 56)
    for stage, stats in report.items():
        print(
            f"{stage:<10} mean={stats['mean_ms']:>8.2f}ms "
            f"min={stats['min_ms']:>8.2f}ms max={stats['max_ms']:>8.2f}ms"
        )


if __name__ == "__main__":
    main()
