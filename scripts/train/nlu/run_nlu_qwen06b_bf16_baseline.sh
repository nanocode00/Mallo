#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
PYTHON="$ROOT/.venvs/dev/bin/python"

EXPERIMENT_ID="${EXPERIMENT_ID:-honorbear-20260825-qwen3-0p6b-bf16-lora-v1}"
RUN_DIR="$ROOT/models/nlu/qwen3-0.6b-lora/$EXPERIMENT_ID"
EVAL_DIR="$RUN_DIR/evaluations"
LOG_DIR="$ROOT/logs"
STATUS="$LOG_DIR/nlu-qwen06b.status"
LOG="$LOG_DIR/nlu-qwen06b-$(date +%Y%m%d-%H%M%S).log"
SUMMARY="$RUN_DIR/final-summary.json"
PREFLIGHT="$ROOT/scratch/nlu-qwen06b/preflight/preflight.ok.json"
CURRENT_STAGE="BOOT"
mkdir -p "$LOG_DIR"

write_status() {
  local stage="$1"
  local state="$2"
  local detail="${3:-}"
  CURRENT_STAGE="$stage"
  cat > "$STATUS" <<EOF
stage=$stage
state=$state
experiment_id=$EXPERIMENT_ID
log=$LOG
run_dir=$RUN_DIR
summary=$SUMMARY
detail=$detail
EOF
}

on_error() {
  local code="$?"
  local line="${1:-unknown}"
  trap - ERR
  write_status "${CURRENT_STAGE:-UNKNOWN}" FAILED "exit_code=$code line=$line"
  echo "[FAILED] stage=${CURRENT_STAGE:-UNKNOWN} exit_code=$code line=$line" >&2
  exit "$code"
}
trap 'on_error "$LINENO"' ERR

write_status PRECHECK RUNNING
exec > >(tee -a "$LOG") 2>&1

echo "[RUN] Qwen3-0.6B BF16-native LoRA baseline"
echo "experiment_id=$EXPERIMENT_ID"
echo "run_dir=$RUN_DIR"
echo "log=$LOG"

if [[ ! -f "$PREFLIGHT" ]]; then
  write_status PRECHECK FAILED "preflight marker missing"
  echo "ERROR: preflight marker가 없습니다. 먼저 bash scripts/run_nlu_qwen06b_preflight.sh 를 실행하세요."
  exit 2
fi

CURRENT_SHA="$(git rev-parse HEAD)"
MARKER_SHA="$("$PYTHON" - "$PREFLIGHT" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["git_sha"])
PY
)"
if [[ "$CURRENT_SHA" != "$MARKER_SHA" ]]; then
  write_status PRECHECK FAILED "git sha changed after preflight"
  echo "ERROR: preflight 이후 Git SHA가 바뀌었습니다: $MARKER_SHA -> $CURRENT_SHA"
  exit 2
fi

if [[ -d "$RUN_DIR" && -n "$(find "$RUN_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  write_status PRECHECK FAILED "non-empty run dir"
  echo "ERROR: 기존 experiment 디렉터리를 덮어쓰지 않습니다: $RUN_DIR"
  exit 2
fi
mkdir -p "$EVAL_DIR"

write_status TRAINING RUNNING
TRAIN_STARTED="$(date +%s)"
echo "[TRAINING] START"
"$PYTHON" scripts/run_nlu_qwen06b_training.py \
  --output-dir "$RUN_DIR" \
  --epochs 3 \
  --learning-rate 2e-4 \
  --micro-batch-size 2 \
  --gradient-accumulation-steps 8
TRAIN_ENDED="$(date +%s)"
echo "[TRAINING] PASS elapsed=$((TRAIN_ENDED-TRAIN_STARTED))s"

ADAPTER="$RUN_DIR/final-adapter"
if [[ ! -d "$ADAPTER" ]]; then
  write_status TRAINING FAILED "final adapter missing"
  echo "ERROR: final adapter가 없습니다: $ADAPTER"
  exit 3
fi

write_status MERGE RUNNING
echo "[MERGE] START"
"$PYTHON" scripts/merge_nlu_qwen06b_adapter.py \
  --adapter "$ADAPTER" \
  --output "$RUN_DIR/merged-bf16"
echo "[MERGE] PASS"

write_status VALIDATION_PEFT RUNNING
echo "[VALIDATION_PEFT] START"
"$PYTHON" scripts/run_nlu_qwen06b_prediction.py \
  --model-format peft \
  --adapter "$ADAPTER" \
  --experiment-id "$EXPERIMENT_ID-peft" \
  --output "$EVAL_DIR/validation-bf16-peft.jsonl"
"$PYTHON" -m adapters.nlu.model_evaluator \
  --gold data/nlu/processed/validation.jsonl \
  --predictions "$EVAL_DIR/validation-bf16-peft.jsonl" \
  --summary "$EVAL_DIR/validation-bf16-peft-summary.json"
echo "[VALIDATION_PEFT] PASS"

write_status VALIDATION_MERGED RUNNING
echo "[VALIDATION_MERGED] START"
"$PYTHON" scripts/run_nlu_qwen06b_prediction.py \
  --model-format merged \
  --merged-model "$RUN_DIR/merged-bf16" \
  --experiment-id "$EXPERIMENT_ID-merged" \
  --output "$EVAL_DIR/validation-bf16-merged.jsonl"
"$PYTHON" -m adapters.nlu.model_evaluator \
  --gold data/nlu/processed/validation.jsonl \
  --predictions "$EVAL_DIR/validation-bf16-merged.jsonl" \
  --summary "$EVAL_DIR/validation-bf16-merged-summary.json"
echo "[VALIDATION_MERGED] PASS"

write_status SUMMARY RUNNING
export ROOT RUN_DIR EVAL_DIR SUMMARY EXPERIMENT_ID TRAIN_STARTED TRAIN_ENDED
"$PYTHON" - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

from adapters.nlu.model_evaluator import evaluate_files
from adapters.nlu.qwen06b_config import MODEL_ID, MODEL_REVISION

root = Path(os.environ["ROOT"])
run_dir = Path(os.environ["RUN_DIR"])
eval_dir = Path(os.environ["EVAL_DIR"])
summary_path = Path(os.environ["SUMMARY"])
experiment_id = os.environ["EXPERIMENT_ID"]
gold_path = root / "data/nlu/processed/validation.jsonl"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def prediction_sha(path: Path) -> str:
    digest = hashlib.sha256()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        payload = json.dumps(
            {"sample_id": row["sample_id"], "prediction": row["prediction"]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()

peft_pred = eval_dir / "validation-bf16-peft.jsonl"
merged_pred = eval_dir / "validation-bf16-merged.jsonl"
peft_summary = load(eval_dir / "validation-bf16-peft-summary.json")
merged_summary = load(eval_dir / "validation-bf16-merged-summary.json")
peft_manifest = load(peft_pred.with_suffix(".manifest.json"))
merged_manifest = load(merged_pred.with_suffix(".manifest.json"))
training_manifest = load(run_dir / "training-manifest.json")

peft_rows = {row["sample_id"]: row for row in map(json.loads, peft_pred.read_text(encoding="utf-8").splitlines())}
merged_rows = {row["sample_id"]: row for row in map(json.loads, merged_pred.read_text(encoding="utf-8").splitlines())}
changed = sorted(
    sample_id for sample_id in peft_rows
    if peft_rows[sample_id]["prediction"] != merged_rows[sample_id]["prediction"]
)

results, _ = evaluate_files(gold_path, merged_pred)
per_group = defaultdict(lambda: {"count": 0, "exact": 0, "schema": 0})
for row in results:
    group = row["label_group"]
    per_group[group]["count"] += 1
    per_group[group]["exact"] += int(row["exact_match"])
    per_group[group]["schema"] += int(row["schema_valid"])
per_group_report = {
    group: {
        "count": values["count"],
        "exact_match": values["exact"] / values["count"],
        "schema_valid": values["schema"] / values["count"],
    }
    for group, values in sorted(per_group.items())
}

service_gate = {
    "exact_match_gte_0_90": (merged_summary.get("exact_match") or 0) >= 0.90,
    "schema_valid_gte_0_98": (merged_summary.get("json_schema_valid_rate") or 0) >= 0.98,
    "invalid_menu_eq_0": merged_summary.get("invalid_menu_output_rate") == 0,
    "median_latency_lt_1s": (
        merged_summary.get("warm_latency_ms", {}).get("median") is not None
        and merged_summary["warm_latency_ms"]["median"] < 1000
    ),
}
service_candidate = all(service_gate.values())

payload = {
    "status": "PASS",
    "experiment_id": experiment_id,
    "model_id": MODEL_ID,
    "revision": MODEL_REVISION,
    "test_split_opened": False,
    "training": {
        "elapsed_seconds": int(os.environ["TRAIN_ENDED"]) - int(os.environ["TRAIN_STARTED"]),
        "best_model_checkpoint": training_manifest.get("best_model_checkpoint"),
        "best_metric": training_manifest.get("best_metric"),
        "train_metrics": training_manifest.get("train_metrics"),
    },
    "peft": {
        "summary": peft_summary,
        "prediction_sha256": prediction_sha(peft_pred),
        "peak_vram_allocated": peft_manifest.get("peak_vram_allocated"),
        "peak_vram_reserved": peft_manifest.get("peak_vram_reserved"),
    },
    "merged": {
        "summary": merged_summary,
        "prediction_sha256": prediction_sha(merged_pred),
        "peak_vram_allocated": merged_manifest.get("peak_vram_allocated"),
        "peak_vram_reserved": merged_manifest.get("peak_vram_reserved"),
        "per_label_group": per_group_report,
    },
    "peft_vs_merged": {
        "byte_exact_equal_count": len(peft_rows) - len(changed),
        "changed_count": len(changed),
        "changed_sample_ids": changed,
    },
    "service_gate": service_gate,
    "service_candidate": service_candidate,
    "baseline_goal": {
        "exact_match": ">= 0.90",
        "schema_valid": ">= 0.98",
        "invalid_menu": "0",
        "median_latency_ms": "< 1000",
    },
}
summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY

write_status FINAL PASS "baseline completed; inspect final-summary.json for service gate"
echo "[FINAL] PASS"
echo "summary=$SUMMARY"
