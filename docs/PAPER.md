# Paper track: calibrated network-magnitude uncertainty

Working question: when a network has few stations, or the magnitude model is used in a new region,
is the reported magnitude uncertainty trustworthy? Short answer from the existing outputs: no.

## Evidence so far (from the 2026-11-23 DGX export, no retraining)

| data | DL MAE | slope (pred vs true) | 95% interval coverage (independent stations) |
|---|---|---|---|
| AQ2009GM test (in-domain) | 0.108 | 0.79 | 51% |
| Central Italy 2016, end-to-end | 0.254 | 0.30 | 16% |
| Central Italy HN, end-to-end | 0.215 | 0.38 | 26% |
| Ridgecrest 2019, end-to-end | 0.389 | 0.29 | 8% |

Wood-Anderson ML has slope ~1 in the same runs (constant regional offset only).
In-domain, ~70% of the residual variance is shared by all stations of an event (ICC), so
inverse-variance aggregation with 1/sum(w) is overconfident and gets worse as stations are added.

Pilot (`calibration_study.py --temporal-split 0.66` on AQ2009GM test predictions):

| k stations | naive | one global factor | shared error + conformal |
|---|---|---|---|
| 3 | 84% / 0.38 | 99% / 0.91 | 96% / 0.70 |
| 10 | 59% / 0.19 | 94% / 0.46 | 97% / 0.68 |
| all | 51% / 0.19 | 90% / 0.44 | 96% / 0.68 |

(coverage / mean width in magnitude units). Caveat: in-domain a fixed-width conformal interval
(`const_conf`) is about as good, because tau dominates. The shared-error model must beat it under
transfer, varying data quality, or few stations, or the method claim is weak.

## Method

Station residual r = b + eta_event + eps_station, eta ~ N(0, tau^2), eps ~ N(0, s^2 sd^2).
Event interval: (IVW mean - b) +- q * sqrt(tau^2 + s^2 / sum(1/sd^2)), q from split / Mondrian (by k) /
adaptive conformal. Training-time version: `train_magnitude.py --loss event` learns tau jointly
(Gaussian likelihood with covariance tau^2 11' + diag(sd^2), whole-event batches).

## Code map

| file | role |
|---|---|
| `511/calib/` | station tables, shared-error fit, conformal, dropout (random / one-sided), metrics |
| `511/calibration_study.py` | the comparison; in-domain, cross-region, `--few-shot N`, `--adaptive` |
| `511/train_magnitude.py` | `--loss event`; writes dev/test predictions with station metadata + split manifest |
| `511/e2e/magnitude.py`, `e2e/pipeline.py` | per-station ML / DL magnitudes -> `station_magnitudes.csv` |
| `scripts/dgx/run_paper.sh` | train -> e2e -> calib on the DGX |

## Run on the DGX

```
git fetch origin
git checkout feature/magnitude-calibration
bash scripts/dgx/setup_env.sh
source .venv-dgx/bin/activate
python -m unittest discover -s 511/tests
nohup bash scripts/dgx/run_paper.sh all > logs/paper_all.log 2>&1 &
```

The DGX is shared with other users' jobs: keep `WORKERS` small (default 4).

## Fixes made on this branch

- `picks.csv` checkpoint is reused only with the same picker and thresholds (`picks_config.json`),
  and only the requested `--max-hours` are returned.
- Event and pick matching are one-to-one (maximum matches, then minimum time difference) instead of greedy.
- `run_511.sh` uses an explicit `MAG_MODEL` and logs its hash, instead of the newest file.
- `train_magnitude.py` stops on empty splits and writes `split_manifest.csv` (fails if an event is in two splits).

## Not done yet

- Reference-location magnitude ablation (catalogue vs automatic location x analyst vs automatic P),
  to explain the DL slope of 0.3.
- A post-2020 test sequence outside INSTANCE (candidate: Marche offshore, Nov 2022).
- Second model (TEAM-LM) and an Mw subset to separate model error from catalogue-label error.
- Magnitude uncertainty -> BSSA14 exceedance probability (5.1.2 link).
