#!/usr/bin/env bash
# InstanceGM (Italy 2005-2020) magnitude model, per-trace Gaussian loss; tested only on post-2020 / non-Italian data.
set -u
cd "$(dirname "$0")/../.."
source .venv/bin/activate
G="bash scripts/dgx/guard.sh"
m=InstanceGM_gauss
MAG=511/outputs/magnitude; TAB=511/outputs/tables_final; CAL=511/outputs/calibration_final; W=4
for try in 1 2 3 4 5 6; do
  [ -f "$MAG/$m/test_predictions.csv" ] && break
  MIN_FREE_GB=40 $G "train_${m}_try$try" python 511/train_magnitude.py --dataset InstanceGM --epochs 30 --device cuda \
    --workers $W --loss gaussian --out "$MAG/$m"
  [ -f "$MAG/$m/test_predictions.csv" ] || sleep 900
done
[ -f "$MAG/$m/test_predictions.csv" ] || { echo "INSTANCE_FAILED"; exit 1; }
for r in ridgecrest marche_2022; do
  o=511/outputs/station_final/$m/$r
  [ -f "$o/station_magnitudes.csv" ] || $G "st_${m}_$r" python 511/e2e_magnitudes.py --run data/e2e/$r \
    --magnitude-model "$MAG/$m/model.pt" --loc-source ref --p-source analyst --workers $W --device cpu --out "$o"
  python 511/prep_tables.py --src "$o" --out-prefix "$TAB/$m/$r"
done
src=$MAG/$m/dev_predictions.csv
$G "cal_${m}_indomain" python 511/calibration_study.py --cal "$src" --test "$MAG/$m/test_predictions.csv" --out "$CAL/$m/indomain"
for r in ridgecrest marche_2022; do
  $G "cal_${m}_$r" python 511/calibration_study.py --cal "$src" --test "$TAB/$m/${r}_dl.csv" --out "$CAL/$m/transfer_$r"
  $G "curve_${m}_$r" python 511/local_data_curve.py --source "$src" --target "$TAB/$m/${r}_dl.csv" --estimator dl --workers $W --out "$CAL/$m/curve_dl_$r"
  $G "fewshot30_${m}_$r" python 511/calibration_study.py --cal "$src" --test "$TAB/$m/${r}_dl.csv" --few-shot 30 --target-only --out "$CAL/$m/fewshot30_$r"
done
echo INSTANCE_DONE
