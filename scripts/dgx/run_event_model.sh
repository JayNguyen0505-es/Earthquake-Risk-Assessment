#!/usr/bin/env bash
# Retrain the event-loss AQ2009GM model (first attempt hit CUDA OOM from other jobs), then its tables and calibration.
set -u
cd "$(dirname "$0")/../.."
source .venv/bin/activate
G="bash scripts/dgx/guard.sh"
m=AQ2009GM_event
MAG=511/outputs/magnitude; TAB=511/outputs/tables_final; CAL=511/outputs/calibration_final; W=4
for try in 1 2 3; do
  [ -f "$MAG/$m/model.pt" ] && [ -f "$MAG/$m/test_predictions.csv" ] && break
  MIN_FREE_GB=40 $G "train_${m}_try$try" python 511/train_magnitude.py --dataset AQ2009GM --epochs 40 --device cuda \
    --workers $W --loss event --events-per-batch 32 --stations-per-event 16 --out "$MAG/$m"
  sleep 600
done
for r in central_italy central_italy_hn ridgecrest marche_2022; do
  o=511/outputs/station_final/$m/$r
  [ -f "$o/station_magnitudes.csv" ] || $G "st_${m}_$r" python 511/e2e_magnitudes.py --run data/e2e/$r \
    --magnitude-model "$MAG/$m/model.pt" --loc-source ref --p-source analyst --workers $W --device cpu --out "$o"
  python 511/prep_tables.py --src "$o" --out-prefix "$TAB/$m/$r"
done
src=$MAG/$m/dev_predictions.csv
$G "cal_${m}_indomain" python 511/calibration_study.py --cal "$src" --test "$MAG/$m/test_predictions.csv" --adaptive --out "$CAL/$m/indomain"
for r in central_italy central_italy_hn ridgecrest marche_2022; do
  $G "cal_${m}_$r" python 511/calibration_study.py --cal "$src" --test "$TAB/$m/${r}_dl.csv" --out "$CAL/$m/transfer_$r"
  $G "curve_${m}_$r" python 511/local_data_curve.py --source "$src" --target "$TAB/$m/${r}_dl.csv" --estimator dl --workers $W --out "$CAL/$m/curve_dl_$r"
done
echo EVENT_MODEL_DONE
