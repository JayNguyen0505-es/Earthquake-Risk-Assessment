#!/usr/bin/env bash
# Phase F under transfer: PGA exceedance with N=0 vs N=30 local calibration events (AQ2009GM_gauss).
# Waits until run_final.sh has produced the AQ2009GM_gauss calibration outputs.
set -u
cd "$(dirname "$0")/../.."
source .venv/bin/activate
G="bash scripts/dgx/guard.sh"
m=AQ2009GM_gauss
SRC=511/outputs/magnitude/$m/dev_predictions.csv
TAB=511/outputs/tables_final/$m
CAL=511/outputs/calibration_final/$m
while [ ! -f "$CAL/curve_dl_marche_2022/curve.csv" ] && [ ! -f logs/curve_${m}_marche_2022.status ]; do sleep 300; done
for r in central_italy central_italy_hn ridgecrest marche_2022; do
  [ -f "$TAB/${r}_dl.csv" ] || continue
  $G "fewshot30_$r" python 511/calibration_study.py --cal "$SRC" --test "$TAB/${r}_dl.csv" --few-shot 30 --target-only \
    --out "$CAL/fewshot30_$r"
  for d in "$CAL/transfer_$r" "$CAL/fewshot30_$r"; do
    [ -f "$d/events.csv.gz" ] && $G "shake_${m}_$(basename $d)" python 512/magnitude_to_shaking.py \
      --events "$d/events.csv.gz" --out "$d/shaking"
  done
done
echo PHASE_F_DONE
