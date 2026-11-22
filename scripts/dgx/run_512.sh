#!/usr/bin/env bash
# 5.1.2 on open data: Vs30 grid -> California ShakeMap flatfile -> models -> scenario maps for the 3 cities.
#
#   nohup bash scripts/dgx/run_512.sh > logs/512.log 2>&1 &
#
# Re-running resumes the ShakeMap download from its cache (a re-run after a parser change only re-parses).
# CPU only (scikit-learn); set MODELS to drop slower models on a busy machine, e.g. MODELS="baseline hybrid gbm".
# Defaults (v2): larger horizontal component, magnitude-dependent distance cutoff; TAG names the outputs.
set -euo pipefail
cd "$(dirname "$0")/../.."
VENV="${VENV:-.venv-dgx}"
# shellcheck disable=SC1091
[ -f "$VENV/bin/activate" ] && source "$VENV/bin/activate"
MODELS="${MODELS:-baseline hybrid gbm rf mlp}"
START="${START:-2010-01-01}"
END="${END:-2025-12-31}"
COMPONENTS="${COMPONENTS:-horizontal}"
TAG="${TAG:-ca_v2}"
# model used for the scenario maps: the GMPE-form baseline extrapolates best to M6-7 (v2 run: sigma 0.74
# for PGA at M>=6 vs 0.90-0.98 for hybrid/gbm/mlp), and every scenario is M5.3-7
MAP_MODEL="${MAP_MODEL:-baseline}"
mkdir -p data/gm logs
echo "== $(date) vs30"
python 512/vs30.py download --dest data/gm/vs30
echo "== $(date) shakemap $START -> $END"
python 512/fetch_shakemap.py --start "$START" --end "$END" --minmag 4 --bbox -125 32 -114 42 \
  --vs30-grid data/gm/vs30/global_vs30.grd --components "$COMPONENTS" --out "data/gm/shakemap_${TAG}.csv"
echo "== $(date) train ($MODELS)"
# shellcheck disable=SC2086
python 512/train.py --flatfile "data/gm/shakemap_${TAG}.csv" --out "512/outputs/${TAG}" \
  --targets pga pgv sa_0.3 sa_1.0 sa_3.0 --distance rrup --max-dist 300 --mag-dist-cutoff --models $MODELS
echo "== $(date) scenario maps"
for s in tuan_giao_1983:dien_bien dien_bien_2001:dien_bien extreme_son_la:son_la extreme_lai_chau:lai_chau; do
  python 512/scenario_map.py --model "512/outputs/${TAG}/models/pga_${MAP_MODEL}.joblib" --scenario "${s%%:*}" --city "${s##*:}" \
    --vs30-grid data/gm/vs30/global_vs30.grd --out "512/outputs/${TAG}/maps_${MAP_MODEL}"
done
echo "== $(date) done"
