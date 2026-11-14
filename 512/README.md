# Work package 5.1.2: ground-motion (PGA / PSA) estimation

Machine-learning ground-motion models and scenario shaking maps for TP. Sơn La, TP. Điện Biên
Phủ and TP. Lai Châu. Everything here runs on **open data** so the work can start before the
Vietnamese network records earthquakes; the local recordings are added later for validation and
calibration (same flatfile schema).

## Pipeline

```
open recordings ──► unified flatfile ──► features ──► models ──► event-grouped CV ──► scenario maps
 (ShakeMap /         gm/flatfile.py     gm/features   baseline  gm/evaluate.py     gm/scenario.py
  NGA-West2 /                                         rf, gbm,                     + Vs30 grid
  20 stations later)                                  mlp                          (gm/vs30.py)
```

* `gm/flatfile.py` – one row per (event, station): magnitude, depth, distances, Vs30, mechanism,
  PGA, PGV, SA(0.3/1.0/3.0 s). Readers for the PEER NGA-West2 flatfile and for ShakeMap.
* `gm/fetch_shakemap.py` – downloads `stationlist.json` of every USGS ShakeMap (observed PGA/PGV/SA
  at seismic stations with rupture distances) → flatfile. No registration, resumable.
* `gm/vs30.py` – USGS global Vs30 mosaic (30″, slope-based with regional insets): sample at the
  20 stations or build a grid over a city. ShakeMap uses the same grid, so training and mapping
  are consistent. Replace with the Institute's measured Vs30 map (WP 2) when available.
* `gm/baseline.py` – GMPE-form regression (Boore–Atkinson 2008 shape, pseudo-depth by grid search)
  fitted on the same data: the "traditional" model the ML models must beat.
* `gm/models.py` – RandomForest, HistGradientBoosting, MLP (scikit-learn only).
* `gm/evaluate.py` – metrics in ln units with between-event τ, within-event φ, total σ; event-grouped
  K-fold so no test event leaks into training.
* `gm/scenario.py` – scenario PGA/PSA maps on a regular grid over a city (CSV, GeoTIFF for QGIS /
  WebGIS, PNG). Scenarios and city boxes in `config/scenarios.json`.
* `gm/synth.py` – synthetic flatfile with known truth (tests, smoke runs).

## Quick start (no data needed)

```bash
pip install -r 512/requirements.txt
python -m unittest discover -s 512/tests -v
python 512/make_synthetic.py --out data/gm/synthetic_flatfile.csv --events 300
python 512/train.py --flatfile data/gm/synthetic_flatfile.csv --out 512/outputs/synthetic --targets pga sa_1.0
python 512/scenario_map.py --model 512/outputs/synthetic/models/pga_gbm.joblib --scenario tuan_giao_1983 --city dien_bien
```

Synthetic numbers only prove the pipeline; absolute values are meaningless until a model is trained
on real recordings.

## With real open data

```bash
# 1. observed ground motions from USGS ShakeMaps (worldwide, M>=4.5, ~tens of thousands of rows)
python 512/fetch_shakemap.py --start 2015-01-01 --end 2025-12-31 --minmag 4.5 --out data/gm/shakemap_flatfile.csv
#    optional: restrict to a tectonically similar region, e.g. continental Asia
#    --bbox 60 5 125 45

# 2. Vs30 for every recording station (ShakeMap station lists carry no Vs30)
python 512/vs30.py download --dest data/gm/vs30
python - <<'EOF'
import pandas as pd, sys; sys.path.insert(0, "512")
from gm.vs30 import sample_points
df = pd.read_csv("data/gm/shakemap_flatfile.csv")
df["vs30_ms"] = sample_points("data/gm/vs30/global_vs30.grd", df["st_lat"], df["st_lon"])
df.to_csv("data/gm/shakemap_flatfile_vs30.csv", index=False)
EOF

# 3. train / evaluate / map
python 512/train.py --flatfile data/gm/shakemap_flatfile_vs30.csv --out 512/outputs/shakemap --targets pga pgv sa_0.3 sa_1.0 sa_3.0
python 512/vs30.py sample --grid data/gm/vs30/global_vs30.grd --stations data/stations.xlsx --out data/gm/stations_vs30.csv
python 512/scenario_map.py --model 512/outputs/shakemap/models/pga_gbm.joblib --scenario tuan_giao_1983 --city dien_bien --vs30-grid data/gm/vs30/global_vs30.grd
```

PEER NGA-West2 (the dataset named in the proposal) needs a free account; download the flatfile
and load it with `gm.flatfile.read_nga_west2(path)` — it has true Vs30, Rjb/Rrup and mechanism,
so it is the better training set; ShakeMap data is the no-registration fallback and the natural
source for Asian events.

## When the 20 stations record earthquakes

Compute PGA/PGV/SA from the accelerograms (needs the calibration in checklist A6), fill the same
flatfile schema with `source="vn_network"`, and (a) evaluate the open-data models on these rows
(residual bias = regional correction), (b) retrain with the rows added. The scripts need no change.

## Outputs

`512/outputs/` is git-ignored. `train.py` writes `metrics.csv` (CV and in-sample metrics per
target/model; baseline coefficients), `oof_residuals.csv`, residual plots, and
`models/<target>_<model>.joblib`. `scenario_map.py` writes `<city>_<scenario>_<target>.{csv,tif,png}`.

## Caveats to state in any report

* Point-source distances (Rjb ≈ Repi) in scenario maps: for M ≥ 6.5 a finite fault should be used.
* Scenario parameters in `config/scenarios.json` are placeholders (verified=false) until replaced
  with the Institute's catalogue values.
* Global slope-based Vs30 is ~900 m resolution; local site effects (basin in Điện Biên Phủ) will
  not appear until the WP 2 measurements are used.
