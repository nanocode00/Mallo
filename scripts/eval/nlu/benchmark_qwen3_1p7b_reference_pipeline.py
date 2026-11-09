"""Qwen3-1.7B legacy/reference NLU를 Mallo Pipeline에 연결한 MOCK_E2E benchmark.

REFERENCE ONLY: 이 스크립트는 PR #209의 Qwen3-0.6B 실서비스 통합 경로를 검증하지 않는다.
0.6B 서비스 검증은 qwen06b_nlu.py / HTTP NLU sidecar 경로를 사용해야 한다.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from adapters.nlu.qwen_nlu import QwenNLU
from adapters.stt.mock_stt import MockSTT
from adapters.tts.mock_tts import MockTTS
from app.service import MalloService
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.models import Cart
from utils.latency_aggregation import MOCK_E2E, nearest_rank_percentile, summarize_warm_turns


REFERENCE_MODEL = "Qwen3-1.7B-QLoRA-v1"
REFERENCE_SCOPE = "reference_only_not_qwen3_0p6b_service_validation"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def metric(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": nearest_rank_percentile(values, 95),
        "max": max(values),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import torch

    validation = read_jsonl(args.validation)
    predictions = {row["sample_id"]: row for row in read_jsonl(args.predictions)}
    selected = []
    for row in validation:
        if (
            len(selected) < 10
            and row["input"]["cart_before"] == []
            and row["metadata"]["label_group"] == "ADD_ITEM"
            and predictions[row["sample_id"]]["prediction"]
            == json.dumps(
                row["output"]["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        ):
            selected.append(row)
    if len(selected) != 10:
        raise RuntimeError("exact-match ADD_ITEM validation 문장 10개를 선택하지 못했습니다")

    nlu = QwenNLU(args.adapter)
    stt = MockSTT()
    service = MalloService(
        nlu=nlu,
        agent=ConversationAgent(load_menu()),
        tts=MockTTS(),
        stt=stt,
    )

    warmups = []
    for _ in range(3):
        stt.canned_text = selected[0]["input"]["utterance"]
        result = service.handle_audio(b"mock-audio", Cart())
        warmups.append(result.to_dict()["latency"])

    torch.cuda.reset_peak_memory_stats()
    turns = []
    for row in selected:
        for repetition in range(5):
            stt.canned_text = row["input"]["utterance"]
            result = service.handle_audio(b"mock-audio", Cart())
            turns.append(
                {
                    "sample_id": row["sample_id"],
                    "repetition": repetition + 1,
                    "success": result.order_result.success,
                    "input_tokens": nlu.last_input_tokens,
                    "output_tokens": nlu.last_output_tokens,
                    "latency": result.to_dict()["latency"],
                }
            )

    stage_keys = ("stt_ms", "nlu_ms", "agent_ms", "tts_ms", "total_e2e_ms")
    report = {
        "benchmark_scope": REFERENCE_SCOPE,
        "measurement_type": MOCK_E2E,
        "provider_set": f"MockSTT/{REFERENCE_MODEL}/ConversationAgent/MockTTS",
        "model_load_ms": nlu.load_latency_ms,
        "warmup_turns": warmups,
        "selected_validation_samples": [
            {"sample_id": row["sample_id"], "utterance": row["input"]["utterance"]}
            for row in selected
        ],
        "turn_count": len(turns),
        "input_tokens": metric([float(row["input_tokens"]) for row in turns]),
        "output_tokens": metric([float(row["output_tokens"]) for row in turns]),
        "latency_ms": {
            key: metric([float(row["latency"][key]) for row in turns]) for key in stage_keys
        },
        "e2e_classification": summarize_warm_turns(
            [float(row["latency"]["total_e2e_ms"]) for row in turns],
            [bool(row["success"]) for row in turns],
        ),
        "peak_vram_allocated": torch.cuda.max_memory_allocated(),
        "peak_vram_reserved": torch.cuda.max_memory_reserved(),
        "turns": turns,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "turns"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
