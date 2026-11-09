#!/usr/bin/env bash
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="$ROOT/.venvs/dev/bin/python"

SWEEP_ID="${SWEEP_ID:?SWEEP_ID is required}"
MAX_RESTARTS="${MAX_RESTARTS:-5}"
RESTART_DELAY="${RESTART_DELAY:-3}"
SUMMARY="$ROOT/models/nlu/qwen3-0.6b-sweeps/$SWEEP_ID/final-summary.json"
STATUS="$ROOT/logs/nlu-qwen06b.status"

attempt=0
while true; do
  attempt=$((attempt + 1))
  echo "[SUPERVISOR] attempt=$attempt sweep_id=$SWEEP_ID"

  "$PYTHON" scripts/run_nlu_qwen06b_resume.py --sweep-id "$SWEEP_ID"
  rc=$?

  if [[ -f "$SUMMARY" ]]; then
    state="$("$PYTHON" - "$SUMMARY" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8')).get('state', 'UNKNOWN'))
PY
)"
    echo "[SUPERVISOR] final summary exists: state=$state rc=$rc"
    exit "$rc"
  fi

  if (( attempt > MAX_RESTARTS )); then
    cat > "$STATUS" <<EOF
stage=SUPERVISOR
state=FAILED
sweep_id=$SWEEP_ID
variant=
detail=runner exited without final summary after $attempt attempts; last_rc=$rc
EOF
    echo "[SUPERVISOR] giving up after $attempt attempts; last_rc=$rc" >&2
    exit "$rc"
  fi

  cat > "$STATUS" <<EOF
stage=SUPERVISOR
state=RESTARTING
sweep_id=$SWEEP_ID
variant=
detail=runner exited without final summary; attempt=$attempt rc=$rc
EOF
  echo "[SUPERVISOR] runner exited without final summary; restarting in ${RESTART_DELAY}s"
  sleep "$RESTART_DELAY"
done
