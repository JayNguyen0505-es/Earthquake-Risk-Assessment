#!/usr/bin/env bash
# Phase A: magnitude ablation (catalogue vs automatic location x analyst/theory vs automatic P).
#   bash scripts/dgx/run_ablation.sh [MODEL]     (default: the old AQ2009GM checkpoint)
set -uo pipefail
cd "$(dirname "$0")/../.."
source .venv/bin/activate
MODEL="${1:-511/outputs/magnitude/old_AQ2009GM/model.pt}"
TAG="${TAG:-old}"
W="${WORKERS:-4}"
OUT=511/outputs/ablation/$TAG
for r in central_italy central_italy_hn ridgecrest; do
  auto=511/outputs/e2e_old/$r/phasenet_instance_dlmag
  [ -d "data/e2e/$r" ] || continue
  python 511/e2e_magnitudes.py --run data/e2e/$r --magnitude-model "$MODEL" --loc-source ref --p-source analyst --workers "$W" --device cpu --out $OUT/$r/ref_analyst
  python 511/e2e_magnitudes.py --run data/e2e/$r --magnitude-model "$MODEL" --loc-source ref --p-source auto --auto-dir $auto --no-ml --workers "$W" --device cpu --out $OUT/$r/ref_auto
  python 511/e2e_magnitudes.py --run data/e2e/$r --magnitude-model "$MODEL" --loc-source auto --p-source analyst --auto-dir $auto --workers "$W" --device cpu --out $OUT/$r/auto_analyst
  python 511/e2e_magnitudes.py --run data/e2e/$r --magnitude-model "$MODEL" --loc-source auto --p-source auto --auto-dir $auto --no-ml --workers "$W" --device cpu --out $OUT/$r/auto_auto
  python 511/ablation_summary.py --runs ref_analyst=$OUT/$r/ref_analyst ref_auto=$OUT/$r/ref_auto auto_analyst=$OUT/$r/auto_analyst auto_auto=$OUT/$r/auto_auto --out $OUT/$r/summary
done
