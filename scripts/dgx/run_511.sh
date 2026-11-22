#!/usr/bin/env bash
# All 5.1.1 experiments on open international data, step by step or all at once.
#
#   bash scripts/dgx/run_511.sh selftest     # unit tests + offline end-to-end self-test (~2 min)
#   bash scripts/dgx/run_511.sh picker       # Part A: picker benchmark (DL vs STA/LTA, cross-domain weights)
#   bash scripts/dgx/run_511.sh fetch        # Part B: download Central Italy + Ridgecrest (20 stations, 2 days each)
#   bash scripts/dgx/run_511.sh magnitude    # Part C: train the DL magnitude model
#   bash scripts/dgx/run_511.sh finetune     # Part A+: fine-tune PhaseNet on accelerometer (HN) traces
#   bash scripts/dgx/run_511.sh e2e          # Part B: full chain on every downloaded run, several pickers
#   bash scripts/dgx/run_511.sh all          # selftest -> picker -> fetch -> magnitude -> e2e
#
# Long runs: nohup bash scripts/dgx/run_511.sh all > logs/511_all.log 2>&1 &
# Settings (environment variables, defaults in brackets):
#   VENV [.venv-dgx]  DEVICE [cuda if available]  PICKER_DATASETS ["ETHZ"]  PICKER_N [2000]
#   MAG_DATASET [AQ2009GM]  MAG_CHANNELS [""]  MAG_EPOCHS [40]  FINETUNE_DATASET [AQ2009GM]  FINETUNE_CHANNELS [HN]
#   REGIONS ["central_italy ridgecrest"]  SEISBENCH_CACHE_ROOT [~/.seisbench]
set -uo pipefail
cd "$(dirname "$0")/../.."
VENV="${VENV:-.venv-dgx}"
# shellcheck disable=SC1091
[ -f "$VENV/bin/activate" ] && source "$VENV/bin/activate"
mkdir -p logs
DEVICE="${DEVICE:-$(python -c 'import torch; print("cuda" if torch.cuda.is_available() else "cpu")' 2>/dev/null || echo cpu)}"
PICKER_DATASETS="${PICKER_DATASETS:-ETHZ}"
PICKER_N="${PICKER_N:-2000}"
MAG_DATASET="${MAG_DATASET:-AQ2009GM}"
MAG_CHANNELS="${MAG_CHANNELS:-}"
MAG_EPOCHS="${MAG_EPOCHS:-40}"
FINETUNE_DATASET="${FINETUNE_DATASET:-AQ2009GM}"
FINETUNE_CHANNELS="${FINETUNE_CHANNELS:-HN}"
REGIONS="${REGIONS:-central_italy ridgecrest}"
FAILED=()

step() {  # step <name> <command...>: run, log, keep going on failure
  local name="$1"; shift
  echo "== $(date '+%F %T') $name: $*"
  if "$@" 2>&1 | tee -a "logs/511_${name}.log"; then
    echo "   ok"
  else
    echo "!! $name failed (see logs/511_${name}.log)"; FAILED+=("$name")
  fi
}

do_selftest() {
  step selftest python -m unittest discover -s 511/tests
  step selftest python 511/e2e_selftest.py
}

do_picker() {
  for ds in $PICKER_DATASETS; do
    step picker python 511/evaluate_picker.py --dataset "$ds" --model stalta --n "$PICKER_N"
    for w in ethz stead instance; do
      step picker python 511/evaluate_picker.py --dataset "$ds" --model phasenet --weights "$w" --n "$PICKER_N" --device "$DEVICE"
      step picker python 511/evaluate_picker.py --dataset "$ds" --model eqtransformer --weights "$w" --n "$PICKER_N" --device "$DEVICE"
    done
  done
  python - <<'EOF'
import glob, pandas as pd
files = sorted(glob.glob("511/outputs/picker_eval/*_summary.csv"))
if files:
    t = pd.concat(pd.read_csv(f).rename(columns={"Unnamed: 0": "phase"}) for f in files)
    t.to_csv("511/outputs/picker_eval/ALL_SUMMARIES.csv", index=False)
    print(t.pivot_table(index="run", columns="phase", values=["precision", "recall", "resid_std_s"]).round(3).to_string())
EOF
}

do_fetch() {
  for r in $REGIONS; do
    step fetch python 511/e2e_fetch.py --region "$r"
  done
  # accelerometer-only version of Central Italy: the instrument type of the 20 Palert stations
  step fetch python 511/e2e_fetch.py --region central_italy --bands HN --tag hn
}

do_magnitude() {
  local ch=()
  [ -n "$MAG_CHANNELS" ] && ch=(--channels $MAG_CHANNELS)
  step magnitude python 511/train_magnitude.py --dataset "$MAG_DATASET" "${ch[@]}" --epochs "$MAG_EPOCHS" \
    --device "$DEVICE" --out "511/outputs/magnitude/${MAG_DATASET}${MAG_CHANNELS:+_${MAG_CHANNELS// /-}}"
}

do_finetune() {
  local out="511/outputs/finetune/${FINETUNE_DATASET}_${FINETUNE_CHANNELS// /-}"
  step finetune python 511/finetune_picker.py --dataset "$FINETUNE_DATASET" --channels $FINETUNE_CHANNELS \
    --weights instance --epochs 20 --device "$DEVICE" --out "$out"
  for w in instance "$out/best"; do
    step finetune python 511/evaluate_picker.py --dataset "$FINETUNE_DATASET" --channels $FINETUNE_CHANNELS \
      --split-mode event --model phasenet --weights "$w" --n "$PICKER_N" --device "$DEVICE"
  done
}

do_e2e() {
  local mag=()
  local mm
  mm=$(ls -t 511/outputs/magnitude/*/model.pt 2>/dev/null | head -1)
  [ -n "$mm" ] && mag=(--magnitude-model "$mm") && echo "   using DL magnitude model $mm"
  for run in data/e2e/*/; do
    [ -f "$run/run.json" ] || continue
    step e2e python 511/e2e_run.py --run "$run" --picker stalta
    step e2e python 511/e2e_run.py --run "$run" --picker phasenet --weights instance --device "$DEVICE" "${mag[@]}"
    step e2e python 511/e2e_run.py --run "$run" --picker phasenet --weights stead --device "$DEVICE"
    step e2e python 511/e2e_run.py --run "$run" --picker eqtransformer --weights instance --device "$DEVICE"
  done
  python - <<'EOF'
import glob, json
rows = []
for f in sorted(glob.glob("511/outputs/e2e/*/*/metrics.json")):
    m = json.load(open(f)); e = m.get("events", {})
    g = lambda k: e.get(k, {}).get("median", float("nan")) if isinstance(e.get(k), dict) else float("nan")
    rows.append((f.split("/")[-3], f.split("/")[-2], e.get("n_reference"), e.get("n_matched"), e.get("recall"), e.get("precision"),
                 g("epicentre_error_km"), g("depth_error_km"), g("ml_minus_reference"), g("m_dl_minus_reference")))
print(f"{'run':22s} {'picker':32s} {'ref':>5s} {'hit':>5s} {'recall':>6s} {'prec':>6s} {'epi_km':>7s} {'dz_km':>6s} {'dML':>5s} {'dMdl':>5s}")
for r in rows:
    print(f"{r[0]:22s} {r[1]:32s} {r[2]!s:>5s} {r[3]!s:>5s} " + " ".join(f"{x:6.2f}" if isinstance(x, float) else f"{x!s:>6s}" for x in r[4:]))
EOF
}

case "${1:-all}" in
  selftest) do_selftest ;;
  picker) do_picker ;;
  fetch) do_fetch ;;
  magnitude) do_magnitude ;;
  finetune) do_finetune ;;
  e2e) do_e2e ;;
  all) do_selftest; do_picker; do_fetch; do_magnitude; do_e2e ;;
  *) echo "unknown step $1"; exit 2 ;;
esac
echo "== $(date '+%F %T') finished; device $DEVICE; failed steps: ${FAILED[*]:-none}"
