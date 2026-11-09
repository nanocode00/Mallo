#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="$ROOT/.venvs/dev/bin/python"

ALLOW_DOWNLOAD="${ALLOW_DOWNLOAD:-1}"
SCRATCH="$ROOT/scratch/nlu-qwen06b/preflight"
REPORTS="$SCRATCH/reports"
MARKER="$SCRATCH/preflight.ok.json"
mkdir -p "$REPORTS"

DL=()
if [[ "$ALLOW_DOWNLOAD" == "1" ]]; then
  DL=(--allow-download)
fi

run_stage() {
  local name="$1"
  shift
  echo "[PREFLIGHT:$name] START"
  "$@"
  echo "[PREFLIGHT:$name] PASS"
}

run_stage DATASET \
  "$PYTHON" scripts/verify_nlu_qwen06b_dataset_contract.py \
  --report "$REPORTS/dataset.json"

run_stage TOKENIZER_PARITY \
  "$PYTHON" scripts/verify_nlu_qwen06b_tokenizer_parity.py \
  "${DL[@]}" \
  --report "$REPORTS/tokenizer-parity.json"

run_stage MODEL \
  "$PYTHON" scripts/verify_nlu_qwen06b_model_contract.py \
  "${DL[@]}" \
  --report "$REPORTS/model.json"

run_stage TRAIN_SMOKE \
  "$PYTHON" scripts/smoke_nlu_qwen06b_bf16_lora.py \
  "${DL[@]}" \
  --scratch "$SCRATCH/smoke" \
  --report "$REPORTS/smoke.json"

run_stage EVALUATOR \
  "$PYTHON" scripts/verify_nlu_qwen06b_evaluator.py \
  --report "$REPORTS/evaluator.json"

run_stage TRAIN_DRY_RUN \
  "$PYTHON" scripts/run_nlu_qwen06b_training.py \
  "${DL[@]}" \
  --dry-run

run_stage SWEEP_DRY_RUN \
  "$PYTHON" scripts/run_nlu_qwen06b_training.py \
  "${DL[@]}" \
  --epochs 4 \
  --learning-rate 1.5e-4 \
  --micro-batch-size 4 \
  --gradient-accumulation-steps 4 \
  --lora-r 32 \
  --lora-alpha 64 \
  --lora-dropout 0 \
  --seed 7 \
  --dry-run

run_stage PYTHON_SYNTAX \
  "$PYTHON" -m py_compile \
  src/adapters/nlu/qwen06b_config.py \
  scripts/verify_nlu_qwen06b_dataset_contract.py \
  scripts/verify_nlu_qwen06b_tokenizer_parity.py \
  scripts/verify_nlu_qwen06b_model_contract.py \
  scripts/smoke_nlu_qwen06b_bf16_lora.py \
  scripts/verify_nlu_qwen06b_evaluator.py \
  scripts/run_nlu_qwen06b_training.py \
  scripts/merge_nlu_qwen06b_adapter.py \
  scripts/run_nlu_qwen06b_prediction.py \
  scripts/run_nlu_qwen06b_overnight_sweep.py \
  scripts/run_nlu_qwen06b_overnight_max.py \
  scripts/run_nlu_qwen06b_resume.py

run_stage STARTUP_IMPORT \
  "$PYTHON" -c 'import adapters.nlu.qwen06b_config; import run_nlu_qwen06b_overnight_sweep; import run_nlu_qwen06b_overnight_max; import run_nlu_qwen06b_resume; print("overnight imports: PASS")'

run_stage SHELL_SYNTAX \
  bash -n \
  scripts/run_nlu_qwen06b_preflight.sh \
  scripts/run_nlu_qwen06b_bf16_baseline.sh \
  scripts/run_nlu_qwen06b_supervisor.sh \
  scripts/start_nlu_qwen06b_tmux.sh

run_stage UNIT_TESTS \
  "$PYTHON" -m pytest -q \
  tests/unit/test_qwen06b_config.py \
  tests/unit/test_qwen_nlu.py \
  tests/unit/test_qwen_prediction_runner.py

GIT_SHA="$(git rev-parse HEAD)"
export GIT_SHA MARKER REPORTS
"$PYTHON" - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from adapters.nlu.qwen06b_config import MODEL_ID, MODEL_REVISION

marker = Path(os.environ["MARKER"])
payload = {
    "status": "PASS",
    "git_sha": os.environ["GIT_SHA"],
    "model_id": MODEL_ID,
    "model_revision": MODEL_REVISION,
    "reports_dir": os.environ["REPORTS"],
    "test_split_opened": False,
    "completed_at": datetime.now(timezone.utc).isoformat(),
}
marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY

echo "[PREFLIGHT] ALL PASS"
echo "marker=$MARKER"
