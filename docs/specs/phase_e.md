# Spec: phase E tooling (calibration study extensions)

Read 511/calib/*.py and 511/calibration_study.py first. Keep existing CLI behaviour working.

## 1. k = 2 and default ks
Default --ks becomes 2 3 5 10 all. Check naive_event / dropout work with k=2 (ML naive var uses ddof=1).

## 2. Bootstrap confidence intervals
calib/metrics.py: add `bootstrap_summary(events, by, alpha=0.05, n_boot=1000, seed=0)` that resamples
EVENTS (event_id) with replacement within each group and returns, for coverage, mean_width and
interval_score, the point value plus 2.5/97.5 percentiles (columns coverage_lo, coverage_hi, ...).
Vectorise per group (precompute per-event means, then resample event indices); must handle 50k events
x 1000 boots in a few seconds. calibration_study.py writes summary_by_k_ci.csv with it (--n-boot, default 500).

## 3. Station corrections for classical ML (estimator variant)
calib/aggregate.py: `fit_station_terms(cal_table, shrink=5.0)` -> dict station -> mean residual
(m_pred - m_true) of that station on calibration events, shrunk toward 0 with n/(n+shrink);
`apply_station_terms(table, terms)` subtracts them (unknown station -> 0). calibration_study.py gets
`--station-terms` that fits on the calibration table and applies to both cal and test BEFORE the study
(record the number of corrected stations in info.json).

## 4. Local-data curve: 511/local_data_curve.py
    python 511/local_data_curve.py --source SRC_TABLE... --target TGT_TABLE... --estimator dl|ml
        [--ns 0 10 20 30 50 100 200] [--reps 20] [--ks 2 3 5 10 all] [--modes random one_sided]
        [--test-frac 0.5] [--station-terms] --out DIR
Target events sorted by time; the LAST test-frac of them is a fixed test set. For each N and rep, the
calibration set is: N=0 -> source only; N>0 -> either "target_only" (N target events) or
"source_plus_target" (source + N target events); the N target events are drawn from the first part:
rep 0 = the first N in time, reps >= 1 = random N (seeded). N larger than available -> skip.
Run calib.study.run_study for each (N, rep, scheme) with n_rep=1 and the given ks/modes, and collect the
per-(method, k, mode) coverage, mean_width, interval_score. Write DIR/curve_raw.csv (one row per
N, rep, scheme, method, k, mode), DIR/curve.csv (mean and 10/90 percentiles over reps), and
DIR/curve.png: coverage vs N and interval score vs N, one line per method, panels per scheme, for k=all
and k=3. Also DIR/n_needed.csv: smallest N whose mean coverage over reps >= 0.93 for each method/scheme/k.
Use multiprocessing over (N, rep) with --workers (default 4); keep memory small.

## 5. Tests
Extend 511/tests/test_calib.py with synthetic tables (helper synthetic_table exists): bootstrap CI
contains the point value; station terms remove an injected per-station offset; local_data_curve runs on
a small synthetic source/target pair (target has bias 0.3 and larger tau) and shows coverage at N=50 >
coverage at N=0 for shared_conf. All tests: `.venv-mac/bin/python -m unittest discover -s 511/tests`;
pyflakes clean on changed files. Do not commit. Update HANDOFF_STATE.md "Results so far" with one line.
