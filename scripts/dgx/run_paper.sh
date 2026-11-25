#!/usr/bin/env bash
# Paper track: calibrated network-magnitude uncertainty. Steps can be run one at a time.
#
#   bash scripts/dgx/run_paper.sh train      # AQ2009GM magnitude model, per-trace loss and event loss
#   bash scripts/dgx/run_paper.sh e2e        # rerun the full chain with each model -> station_magnitudes.csv
#   bash scripts/dgx/run_paper.sh calib      # calibration studies (in-domain, cross-region, few-shot)
#   bash scripts/dgx/run_paper.sh all
#
# Long runs: nohup bash scripts/dgx/run_paper.sh all > logs/paper_all.log 2>&1 &
# Settings: VENV [.venv-dgx] DEVICE [cuda] MAG_DATASET [AQ2009GM] MAG_EPOCHS [40] WORKERS [4]
#           REGIONS ["central_italy central_italy_hn ridgecrest"] FEW_SHOT [50]
# The DGX is shared: WORKERS and the batch sizes are kept modest on purpose.
set -uo pipefail
cd "$(dirname "$0")/../.."
VENV="${VENV:-.venv-dgx}"
# shellcheck disable=SC1091
[ -f "$VENV/bin/activate" ] && source "$VENV/bin/activate"
mkdir -p logs
DEVICE="${DEVICE:-$(python -c 'import torch; print("cuda" if torch.cuda.is_available() else "cpu")' 2>/dev/null || echo cpu)}"
MAG_DATASET="${MAG_DATASET:-AQ2009GM}"
MAG_EPOCHS="${MAG_EPOCHS:-40}"
WORKERS="${WORKERS:-4}"
REGIONS="${REGIONS:-central_italy central_italy_hn ridgecrest}"
FEW_SHOT="${FEW_SHOT:-50}"
MAG_ROOT=511/outputs/magnitude
E2E_ROOT=511/outputs/paper_e2e
CAL_ROOT=511/outputs/calibration
FAILED=()

step() {
  local name="$1"; shift
  echo "== $(date '+%F %T') $name: $*"
  if "$@" 2>&1 | tee -a "logs/paper_${name}.log"; then echo "   ok"; else echo "!! $name failed"; FAILED+=("$name"); fi
}

do_train() {
  step train python 511/train_magnitude.py --dataset "$MAG_DATASET" --epochs "$MAG_EPOCHS" --device "$DEVICE" \
    --workers "$WORKERS" --loss gaussian --out "$MAG_ROOT/${MAG_DATASET}_gauss"
  step train python 511/train_magnitude.py --dataset "$MAG_DATASET" --epochs "$MAG_EPOCHS" --device "$DEVICE" \
    --workers "$WORKERS" --loss event --events-per-batch 32 --stations-per-event 16 --out "$MAG_ROOT/${MAG_DATASET}_event"
}

do_e2e() {
  for r in $REGIONS; do
    [ -f "data/e2e/$r/run.json" ] || { echo "   skip $r: data/e2e/$r missing (run scripts/dgx/run_511.sh fetch)"; continue; }
    for loss in gauss event; do
      local mm="$MAG_ROOT/${MAG_DATASET}_${loss}/model.pt"
      [ -f "$mm" ] || { echo "   skip $loss: $mm missing"; continue; }
      local out="$E2E_ROOT/$r/phasenet_instance_${loss}"
      local old
      for old in "511/outputs/e2e_old/$r/phasenet_instance_dlmag/picks.csv" "511/outputs/e2e/$r/phasenet_instance_dlmag/picks.csv" "511/outputs/e2e/$r/phasenet_instance/picks.csv" \
                 "$E2E_ROOT/$r/phasenet_instance_gauss/picks.csv"; do
        if [ ! -f "$out/picks.csv" ] && [ -f "$old" ]; then
          mkdir -p "$out"
          cp "$old" "$out/picks.csv"
          printf '{"picker": "phasenet_instance", "p_threshold": 0.3, "s_threshold": 0.3, "pad_s": 60.0}\n' > "$out/picks_config.json"
          echo "   reusing picks from $old (PhaseNet INSTANCE, thresholds 0.3/0.3)"
        fi
      done
      step e2e python 511/e2e_run.py --run "data/e2e/$r" --picker phasenet --weights instance --device "$DEVICE" \
        --magnitude-model "$mm" --out "$out"
    done
  done
}

do_calib() {
  for loss in gauss event; do
    local d="$MAG_ROOT/${MAG_DATASET}_${loss}"
    [ -f "$d/dev_predictions.csv" ] || continue
    step calib python 511/calibration_study.py --cal "$d/dev_predictions.csv" --test "$d/test_predictions.csv" \
      --adaptive --out "$CAL_ROOT/indomain_${loss}"
    for r in $REGIONS; do
      local e="$E2E_ROOT/$r/phasenet_instance_${loss}"
      [ -f "$e/station_magnitudes.csv" ] || continue
      step calib python 511/calibration_study.py --cal "$d/dev_predictions.csv" --test "$e" --estimator dl \
        --modes random one_sided --out "$CAL_ROOT/transfer_${loss}_${r}_dl"
      step calib python 511/calibration_study.py --cal "$d/dev_predictions.csv" --test "$e" --estimator dl \
        --few-shot "$FEW_SHOT" --target-only --adaptive --out "$CAL_ROOT/fewshot_${loss}_${r}_dl"
    done
  done
  local base="$E2E_ROOT/central_italy/phasenet_instance_gauss"
  for r in $REGIONS; do
    local e="$E2E_ROOT/$r/phasenet_instance_gauss"
    [ -f "$e/station_magnitudes.csv" ] || continue
    step calib python 511/calibration_study.py --cal "$e" --temporal-split 0.5 --estimator ml \
      --modes random one_sided --out "$CAL_ROOT/temporal_${r}_ml"
    if [ "$r" != central_italy ] && [ -f "$base/station_magnitudes.csv" ]; then
      step calib python 511/calibration_study.py --cal "$base" --test "$e" --estimator ml \
        --modes random one_sided --out "$CAL_ROOT/transfer_central_italy_to_${r}_ml"
      step calib python 511/calibration_study.py --cal "$base" --test "$e" --estimator ml \
        --few-shot "$FEW_SHOT" --adaptive --out "$CAL_ROOT/fewshot_central_italy_to_${r}_ml"
    fi
  done
  python - <<'PY'
import glob, pandas as pd
rows = []
for f in sorted(glob.glob("511/outputs/calibration/*/summary.csv")):
    t = pd.read_csv(f); t.insert(0, "study", f.split("/")[-2]); rows.append(t)
if rows:
    t = pd.concat(rows)
    t.to_csv("511/outputs/calibration/ALL_SUMMARIES.csv", index=False)
    print(t.pivot_table(index="study", columns="method", values="coverage").round(3).to_string())
    print(t.pivot_table(index="study", columns="method", values="mean_width").round(3).to_string())
PY
}

case "${1:-all}" in
  train) do_train ;;
  e2e) do_e2e ;;
  calib) do_calib ;;
  all) do_train; do_e2e; do_calib ;;
  *) echo "unknown step $1"; exit 2 ;;
esac
echo "== $(date '+%F %T') finished; device $DEVICE; failed steps: ${FAILED[*]:-none}"
