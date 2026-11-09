#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="$ROOT/.venvs/dev/bin/python"
SESSION="${SESSION_NAME:-nlu-qwen06b}"
STATUS="$ROOT/logs/nlu-qwen06b.status"
RUNNER="${NLU_QWEN06B_RUNNER:-overnight}"
SWEEP_ID="${SWEEP_ID:-honorbear-$(date +%Y%m%d-%H%M%S)-qwen3-0p6b-overnight}"
LOG="$ROOT/logs/nlu-qwen06b-${SWEEP_ID}.log"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "ERROR: tmux session이 이미 존재합니다: $SESSION" >&2
  echo "확인: tmux attach -t $SESSION" >&2
  exit 2
fi

PREFLIGHT="$ROOT/scratch/nlu-qwen06b/preflight/preflight.ok.json"
if [[ ! -f "$PREFLIGHT" ]]; then
  echo "ERROR: preflight marker가 없습니다." >&2
  echo "먼저 실행: ALLOW_DOWNLOAD=1 bash scripts/run_nlu_qwen06b_preflight.sh" >&2
  exit 2
fi

# tmux를 띄우기 전에 실제 startup import를 foreground에서 검증한다.
if [[ "$RUNNER" == "overnight" ]]; then
  "$PYTHON" - <<'PY'
import adapters.nlu.qwen06b_config
import run_nlu_qwen06b_overnight_max
import run_nlu_qwen06b_resume
print("startup_import=PASS")
PY
fi

mkdir -p "$ROOT/logs"
if [[ "$RUNNER" == "baseline" ]]; then
  COMMAND="cd '$ROOT' && export PYTHONPATH='$ROOT/src:$ROOT/scripts'\${PYTHONPATH:+:\$PYTHONPATH} && set -o pipefail && bash scripts/run_nlu_qwen06b_bf16_baseline.sh 2>&1 | tee -a '$LOG'"
elif [[ "$RUNNER" == "overnight" ]]; then
  COMMAND="cd '$ROOT' && export PYTHONPATH='$ROOT/src:$ROOT/scripts'\${PYTHONPATH:+:\$PYTHONPATH} && export SWEEP_ID='$SWEEP_ID' && set -o pipefail && bash scripts/run_nlu_qwen06b_supervisor.sh 2>&1 | tee -a '$LOG'"
else
  echo "ERROR: NLU_QWEN06B_RUNNER는 baseline 또는 overnight여야 합니다: $RUNNER" >&2
  exit 2
fi

tmux new-session -d -s "$SESSION" "$COMMAND"

sleep 1
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "ERROR: tmux runner가 시작 직후 종료됐습니다." >&2
  echo "log=$LOG" >&2
  tail -n 80 "$LOG" >&2 || true
  exit 3
fi

echo "started=1"
echo "runner=$RUNNER"
echo "session=$SESSION"
echo "sweep_id=$SWEEP_ID"
echo "status=$STATUS"
echo "log=$LOG"
echo "attach: tmux attach -t $SESSION"
echo "status: cat $STATUS"
echo "gpu: watch -n 2 nvidia-smi"
echo "log: tail -f '$LOG'"
