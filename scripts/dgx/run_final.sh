#!/usr/bin/env bash
# Final experiment queue (phases C-F). Waits for running jobs, then runs everything in order.
#   nohup bash scripts/dgx/run_final.sh > logs/final.log 2>&1 &   (normally inside tmux era, via guard.sh)
# Each heavy step goes through guard.sh, so memory checks apply per step.
set -u
cd "$(dirname "$0")/../.."
source .venv/bin/activate
G="bash scripts/dgx/guard.sh"
MAG=511/outputs/magnitude
TAB=511/outputs/tables_final
CAL=511/outputs/calibration_final
W="${WORKERS:-4}"
note() { echo "== $(date '+%F %T') $*"; }
wait_status() { while [ ! -f "logs/$1.status" ]; do sleep 300; done; note "$1 finished with status $(cat logs/$1.status)"; }

pip install -q --no-deps openquake.engine >/dev/null 2>&1
pip install -q shapely numba h3 alpha_shapes fiona toml >/dev/null 2>&1
python -c "from openquake.hazardlib.gsim.boore_2014 import BooreEtAl2014" && note "openquake ok" || note "openquake missing (phase F will fail)"

tables_for() {  # tables_for MODEL_TAG REGION...
  local m="$1"; shift
  for r in "$@"; do
    [ -d "data/e2e/$r" ] || continue
    local o=511/outputs/station_final/$m/$r
    [ -f "$o/station_magnitudes.csv" ] || $G "st_${m}_$r" python 511/e2e_magnitudes.py --run data/e2e/$r \
      --magnitude-model "$MAG/$m/model.pt" --loc-source ref --p-source analyst --workers "$W" --device cpu --out "$o"
    python 511/prep_tables.py --src "$o" --out-prefix "$TAB/$m/$r"
  done
}

calib_for() {  # calib_for MODEL_TAG REGION...
  local m="$1"; shift
  local src="$MAG/$m/dev_predictions.csv"
  $G "cal_${m}_indomain" python 511/calibration_study.py --cal "$src" --test "$MAG/$m/test_predictions.csv" \
    --adaptive --out "$CAL/$m/indomain"
  for r in "$@"; do
    [ -f "$TAB/$m/${r}_dl.csv" ] || continue
    $G "cal_${m}_$r" python 511/calibration_study.py --cal "$src" --test "$TAB/$m/${r}_dl.csv" --out "$CAL/$m/transfer_$r"
    $G "curve_${m}_$r" python 511/local_data_curve.py --source "$src" --target "$TAB/$m/${r}_dl.csv" --estimator dl \
      --workers "$W" --out "$CAL/$m/curve_dl_$r"
  done
}

# 1. AQ2009GM models (training started by run_paper.sh train)
wait_status paper_train
for m in AQ2009GM_gauss AQ2009GM_event; do
  [ -f "$MAG/$m/model.pt" ] || { note "missing $m"; continue; }
  tables_for "$m" central_italy central_italy_hn ridgecrest marche_2022
  calib_for "$m" central_italy central_italy_hn ridgecrest marche_2022
done
# classical ML: within each region (temporal) and Italy -> other regions with local-data curve
m=AQ2009GM_gauss
for r in central_italy central_italy_hn ridgecrest marche_2022; do
  [ -f "$TAB/$m/${r}_ml.csv" ] || continue
  $G "cal_ml_temporal_$r" python 511/calibration_study.py --cal "$TAB/$m/${r}_ml.csv" --temporal-split 0.5 \
    --station-terms --out "$CAL/ml/temporal_$r"
  [ "$r" = central_italy ] && continue
  $G "curve_ml_$r" python 511/local_data_curve.py --source "$TAB/$m/central_italy_ml.csv" --target "$TAB/$m/${r}_ml.csv" \
    --estimator ml --station-terms --workers "$W" --out "$CAL/ml/curve_$r"
done

# 2. phase F on the AQ2009GM_gauss in-domain and Ridgecrest events
for d in "$CAL/AQ2009GM_gauss/indomain" "$CAL/AQ2009GM_gauss/transfer_ridgecrest"; do
  [ -f "$d/events.csv.gz" ] && [ -f 512/magnitude_to_shaking.py ] && \
    $G "shake_$(basename $d)" python 512/magnitude_to_shaking.py --events "$d/events.csv.gz" --out "$d/shaking"
done

# 3. InstanceGM models (download must have finished; test only on ridgecrest + marche_2022)
wait_status dl_instancegm
if [ "$(cat logs/dl_instancegm.status)" = 0 ]; then
  for loss in gauss event; do
    m=InstanceGM_$loss
    [ -f "$MAG/$m/model.pt" ] || $G "train_$m" python 511/train_magnitude.py --dataset InstanceGM --epochs 30 \
      --device cuda --workers "$W" --loss $loss --events-per-batch 32 --stations-per-event 16 --out "$MAG/$m"
    [ -f "$MAG/$m/model.pt" ] || continue
    tables_for "$m" ridgecrest marche_2022
    calib_for "$m" ridgecrest marche_2022
  done
else
  note "InstanceGM download failed: fallback to AQ2009GM + Marche + Ridgecrest only"
fi

python - <<'PY'
import glob, pandas as pd
rows = []
for f in sorted(glob.glob("511/outputs/calibration_final/**/summary_by_k.csv", recursive=True)):
    t = pd.read_csv(f); t.insert(0, "study", f.split("calibration_final/")[1].rsplit("/", 1)[0]); rows.append(t)
if rows:
    pd.concat(rows).to_csv("511/outputs/calibration_final/ALL_BY_K.csv", index=False)
print("FINAL_QUEUE_DONE")
PY
