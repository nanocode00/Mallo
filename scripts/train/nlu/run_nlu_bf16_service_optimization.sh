#!/usr/bin/env bash
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
STAMP="${MALLO_NLU_OPT_STAMP:-$(date +%Y%m%d-%H%M%S)}"
PYTHON="${MALLO_NLU_OPT_PYTHON:-$ROOT/.venvs/dev/bin/python}"
LOG="${MALLO_NLU_OPT_LOG:-$ROOT/logs/nlu-bf16-opt-$STAMP.log}"
STATUS="$ROOT/logs/nlu-bf16-opt.status"
OUT="$ROOT/models/nlu/service-optimization/$STAMP"
FINAL="$OUT/final-summary.json"
VALIDATION="$ROOT/data/nlu/processed/validation.jsonl"
BF16_RUN="$ROOT/models/nlu/qwen3-1.7b-lora/honorbear-20260824-qwen3-1p7b-bf16-native-lora-v1"
NF4_RUN="$ROOT/models/nlu/qwen3-1.7b-qlora/honorbear-20260824-qwen3-1p7b-qlora-v1"
BASELINE="$BF16_RUN/evaluations/validation-bf16-merged.jsonl"
FALLBACK="$NF4_RUN/evaluations/validation-fine-tuned.jsonl"
mkdir -p "$OUT" "$ROOT/logs"
exec > >(tee -a "$LOG") 2>&1

status() {
  printf 'stage=%s\nstate=%s\nlast_variant=%s\npeak_vram=%s\nmedian_p95=%s\nupdated_at=%s\n' \
    "$1" "$2" "${3:--}" "${4:--}" "${5:--}" "$(date --iso-8601=seconds)" > "$STATUS"
}
stage() { echo "[$1] $2"; status "$1" "$2" "${3:--}" "${4:--}" "${5:--}"; }
fail() { stage "$1" FAILED "${2:--}"; exit 1; }
trap 'fail INFRA "unexpected exit at line $LINENO"' ERR

for required in "$PYTHON" "$VALIDATION" "$BASELINE" "$FALLBACK" "$BF16_RUN/merged-bf16" "$NF4_RUN/final-adapter"; do
  [[ -e "$required" ]] || fail PREFLIGHT "missing:$required"
done
[[ "$VALIDATION $BASELINE $FALLBACK" != *test* ]] || fail PREFLIGHT test-path-detected
stage PREFLIGHT PASS validation-only

stage STAGE1 START prompt-lookup-8-gate64
PRED64="$OUT/stage1-validation64-prompt-lookup-8.jsonl"
PYTHONPATH=src "$PYTHON" -m adapters.nlu.qwen_prediction_runner \
  --split validation --variant fine-tuned --input "$VALIDATION" --output "$PRED64" \
  --precision bf16 --model-format merged --merged-model "$BF16_RUN/merged-bf16" \
  --max-new-tokens 96 --warmup-count 5 --batch-size 1 --attention-backend auto \
  --cache-implementation dynamic --output-profile canonical --prompt-lookup-num-tokens 8 --limit 64
PYTHONPATH=src "$PYTHON" scripts/analyze_nlu_service_optimization.py --gold "$VALIDATION" --baseline "$BASELINE" --candidate "$PRED64" --fallback "$FALLBACK" --output "$OUT/stage1-gate64-analysis.json"
if ! "$PYTHON" - "$OUT/stage1-gate64-analysis.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); m=r['candidate_metrics']; l=m['warm_latency_ms']
raise SystemExit(0 if m['exact_match']>=.90 and m['json_schema_valid_rate']>=.98 and m['invalid_menu_output_rate']==0 and l['median']<=1500 else 1)
PY
then
  stage STAGE1 REJECT prompt-lookup-8-gate64
else
  PRED300="$OUT/stage1-validation300-prompt-lookup-8.jsonl"
  PYTHONPATH=src "$PYTHON" -m adapters.nlu.qwen_prediction_runner \
    --split validation --variant fine-tuned --input "$VALIDATION" --output "$PRED300" \
    --precision bf16 --model-format merged --merged-model "$BF16_RUN/merged-bf16" \
    --max-new-tokens 96 --warmup-count 5 --batch-size 1 --attention-backend auto \
    --cache-implementation dynamic --output-profile canonical --prompt-lookup-num-tokens 8
  PYTHONPATH=src "$PYTHON" scripts/analyze_nlu_service_optimization.py --gold "$VALIDATION" --baseline "$BASELINE" --candidate "$PRED300" --fallback "$FALLBACK" --output "$OUT/stage1-analysis.json"
  stage STAGE1 PASS prompt-lookup-8-validation300
fi

stage STAGE2 START resident-cascade-validation300
CASCADE="$OUT/stage2-resident-cascade.jsonl"
CASCADE_SUMMARY="${CASCADE%.jsonl}.summary.json"
PYTHONPATH=src "$PYTHON" scripts/run_nlu_qwen3_1p7b_reference_cascade.py --validation "$VALIDATION" \
  --merged-model "$BF16_RUN/merged-bf16" --nf4-adapter "$NF4_RUN/final-adapter" \
  --output "$CASCADE" --limit 300 --max-new-tokens 96 --prompt-lookup-num-tokens 8
if "$PYTHON" - "$CASCADE_SUMMARY" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); m=r['metrics']; l=r['overall_latency_ms']
raise SystemExit(0 if m['exact_match']>=.90 and m['json_schema_valid_rate']>=.98 and m['invalid_menu_output_rate']==0 and l['median']<=1500 else 1)
PY
then
  stage STAGE2 PASS resident-cascade
  stage STAGE3 SKIPPED cascade-passed
  stage STAGE4 SKIPPED cascade-passed
else
  stage STAGE2 REJECT resident-cascade
  stage STAGE3 SKIPPED custom-decoder-not-implemented-minimal-transformers-path-unavailable
  stage STAGE4 SKIPPED augmentation-requires-reviewed-leakage-safe-data-before-training
fi

"$PYTHON" - "$OUT" "$FINAL" <<'PY'
import json,sys
from pathlib import Path
out, final = Path(sys.argv[1]), Path(sys.argv[2])
payload={"run_dir":str(out),"stage1":None,"stage2":None,"notes":["validation-only; test split/artifacts were not accessed","existing BF16/NF4 v1 artifacts were read-only"]}
for name,key in (("stage1-analysis.json","stage1"),("stage1-gate64-analysis.json","stage1_gate64"),("stage2-resident-cascade.summary.json","stage2")):
 p=out/name
 if p.exists(): payload[key]=json.loads(p.read_text())
final.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
PY
stage FINAL PASS service-optimization "$OUT" "$FINAL"
