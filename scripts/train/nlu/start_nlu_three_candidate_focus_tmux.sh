#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

SESSION="${MALLO_NLU_FOCUS_SESSION:-nlu-focus3}"
RUN_ID="${RUN_ID:-focus3-$(date +%Y%m%d-%H%M%S)}"
PYTHON="${MALLO_NLU_FOCUS_PYTHON:-$ROOT/.venvs/dev/bin/python}"
LOG="${MALLO_NLU_FOCUS_LOG:-$ROOT/logs/nlu-focus3-${RUN_ID}.log}"
export PYTHONPATH="$ROOT/src:$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$ROOT/logs"

[[ -x "$PYTHON" ]] || { echo "python missing: $PYTHON" >&2; exit 1; }
command -v tmux >/dev/null || { echo "tmux missing" >&2; exit 1; }

"$PYTHON" - <<'PY'
import adapters.nlu.model_evaluator
import adapters.nlu.qwen_training_data
print("[STARTUP_IMPORT] PASS")
PY

# Build/freeze or verify the challenge before entering tmux so data identity is visible.
"$PYTHON" scripts/build_nlu_focused_challenge_v1.py

# Verify all model paths and commands without touching the GPU.
"$PYTHON" scripts/run_nlu_three_candidate_focus.py --run-id "$RUN_ID" --dry-run >/tmp/nlu-focus3-dry-run.txt
cat /tmp/nlu-focus3-dry-run.txt

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already exists: $SESSION" >&2
  echo "attach: tmux attach -t $SESSION" >&2
  exit 1
fi

CMD="cd '$ROOT' && export PYTHONPATH='$PYTHONPATH' && '$PYTHON' scripts/run_nlu_three_candidate_focus.py --run-id '$RUN_ID' 2>&1 | tee -a '$LOG'; rc=\${PIPESTATUS[0]}; echo '[TMUX] runner rc='\$rc; exec bash"
tmux new-session -d -s "$SESSION" "$CMD"
sleep 1

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "focused benchmark died during startup" >&2
  echo "===== LOG TAIL =====" >&2
  tail -n 100 "$LOG" >&2 || true
  exit 1
fi

echo "started=1"
echo "session=$SESSION"
echo "run_id=$RUN_ID"
echo "log=$LOG"
echo "status=$ROOT/logs/nlu-three-candidate-focus.status"
echo "attach: tmux attach -t $SESSION"
echo "resume after interruption: RUN_ID=$RUN_ID bash scripts/start_nlu_three_candidate_focus_tmux.sh"
