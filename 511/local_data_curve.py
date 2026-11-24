"""Measure cross-region calibration as more early target events become available."""

from __future__ import annotations

import argparse
import multiprocessing as mp
from pathlib import Path

import numpy as np
import pandas as pd

from calib.aggregate import apply_station_terms, fit_station_terms
from calib.io import STD_COLUMNS, load_table
from calib.metrics import summarize
from calib.study import run_study, split_by_time

METRICS = ["coverage", "mean_width", "interval_score"]
GROUPS = ["n", "scheme", "method", "k", "mode"]
SCHEMES = ("source_only", "target_only", "source_plus_target")


def _init_worker(source, early, test, early_ids, options):
    global _worker_data
    _worker_data = source, early, test, early_ids, options


def _run_trial(trial):
    n, rep = trial
    source, early, test, early_ids, options = _worker_data
    if n:
        ids = early_ids[:n] if rep == 0 else np.random.default_rng(
            [options.seed, n, rep]).choice(early_ids, size=n, replace=False)
        shot = early[early["event_id"].isin(ids)]
        schemes = ((SCHEMES[1], shot), (SCHEMES[2], pd.concat([source, shot], ignore_index=True)))
    else:
        schemes = ((SCHEMES[0], source),)
    results = []
    for scheme, cal in schemes:
        evaluation = test
        if options.station_terms:
            terms = fit_station_terms(cal)
            cal, evaluation = apply_station_terms(cal, terms), apply_station_terms(test, terms)
        events, _ = run_study(cal, evaluation, options.ks, options.modes, n_rep=1, seed=options.seed)
        results.append(summarize(events, ("method", "k", "mode"))[["method", "k", "mode", *METRICS]]
                       .assign(n=n, rep=rep, scheme=scheme))
    return pd.concat(results, ignore_index=True)


def _percentile(values, q):
    ordered = np.sort(values.dropna().to_numpy())
    if not len(ordered):
        return np.nan
    rank = (len(ordered) - 1) * q
    lower, upper = ordered[int(rank)], ordered[int(np.ceil(rank))]
    return lower + (rank % 1) * (upper - lower) if np.isfinite(upper) else np.inf


def _plot(curve, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = [("all", "all"), *(("3", mode) for mode in curve.loc[curve["k"] == "3", "mode"].unique())]
    if not any(k == "3" for k, _ in panels):
        panels.append(("3", "random"))
    fig, axes = plt.subplots(len(panels) * 2, len(SCHEMES), squeeze=False,
                             figsize=(12, 4.2 * len(panels)), sharex="col")
    methods = sorted(curve["method"].unique())
    handles = {}
    for i, (k, mode) in enumerate(panels):
        subset = curve[(curve["k"] == k) & (curve["mode"] == mode)]
        for col, scheme in enumerate(SCHEMES):
            data = subset[subset["scheme"] == scheme]
            for offset, metric in enumerate(("coverage", "interval_score")):
                ax = axes[2 * i + offset, col]
                for color, method in enumerate(methods):
                    rows = data[data["method"] == method]
                    if not rows.empty:
                        line, = ax.plot(rows["n"], rows[f"{metric}_mean"].replace(np.inf, np.nan),
                                        color=f"C{color}", marker="o", label=method)
                        handles[method] = line
                if i == 0 and offset == 0:
                    ax.set_title(scheme.replace("_", " "))
                if col == 0:
                    ax.set_ylabel(f"{metric.replace('_', ' ')}\nk={k}, {mode}")
                if metric == "coverage":
                    ax.axhline(0.93, color="0.5", lw=0.8, ls="--")
            axes[-1, col].set_xlabel("Target calibration events (N)")
    fig.legend(handles.values(), handles.keys(), loc="lower center", ncol=len(methods), fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "curve.png", dpi=130)
    plt.close(fig)


def _load_region(paths, estimator, region):
    table = pd.concat([load_table(path, estimator).reindex(columns=STD_COLUMNS) for path in paths],
                      ignore_index=True)
    # Event identifiers may be local to each catalog. Keep regions distinct when pooling.
    return table.assign(event_id=region + ":" + table["event_id"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", nargs="+", required=True)
    parser.add_argument("--target", nargs="+", required=True)
    parser.add_argument("--estimator", choices=("dl", "ml"), required=True)
    parser.add_argument("--ns", nargs="+", type=int, default=[0, 10, 20, 30, 50, 100, 200])
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("--ks", nargs="+", default=["2", "3", "5", "10", "all"])
    parser.add_argument("--modes", nargs="+", choices=("random", "one_sided"), default=["random", "one_sided"])
    parser.add_argument("--test-frac", type=float, default=0.5)
    parser.add_argument("--station-terms", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 0 < args.test_frac < 1:
        parser.error("--test-frac must be between 0 and 1")
    if min(args.reps, args.workers) < 1 or min(args.ns) < 0 or args.seed < 0:
        parser.error("--reps and --workers must be positive; --ns and --seed must be nonnegative")
    source = _load_region(args.source, args.estimator, "source")
    target = _load_region(args.target, args.estimator, "target")
    early, test = split_by_time(target, 1 - args.test_frac)
    if source.empty or test.empty:
        parser.error("source and target test tables must contain events")
    early_ids = early.groupby("event_id")["time"].first().sort_values(kind="stable").index.to_numpy()
    trials = [(n, rep) for n in sorted(set(args.ns)) if n <= len(early_ids) for rep in range(args.reps)]
    if not trials:
        parser.error("no requested N fits the early target set")
    worker_args = (source, early, test, early_ids, args)
    if args.workers == 1:
        _init_worker(*worker_args)
        raw = pd.concat(map(_run_trial, trials), ignore_index=True)
    else:
        with mp.Pool(min(args.workers, len(trials)), initializer=_init_worker, initargs=worker_args) as pool:
            raw = pd.concat(pool.imap(_run_trial, trials), ignore_index=True)
    raw = raw[[*GROUPS[:1], "rep", *GROUPS[1:], *METRICS]]
    aggregations = {}
    for metric in METRICS:
        aggregations[f"{metric}_mean"] = (metric, "mean")
        aggregations[f"{metric}_p10"] = (metric, lambda v: _percentile(v, 0.1))
        aggregations[f"{metric}_p90"] = (metric, lambda v: _percentile(v, 0.9))
    curve = raw.groupby(GROUPS).agg(**aggregations).reset_index()
    # Each repetition contributes one coverage value per k, averaging modes where available.
    keys = ["method", "scheme", "k"]
    per_rep = raw.groupby([*keys, "n", "rep"])["coverage"].mean()
    coverage = per_rep.groupby(level=[*keys, "n"]).mean().reset_index()
    needed = coverage[coverage["coverage"] >= 0.93].groupby(keys)["n"].min().rename("n_needed")
    needed = raw[keys].drop_duplicates().sort_values(keys).join(needed, on=keys)
    needed["n_needed"] = needed["n_needed"].astype("Int64")
    args.out.mkdir(parents=True, exist_ok=True)
    raw.to_csv(args.out / "curve_raw.csv", index=False)
    curve.to_csv(args.out / "curve.csv", index=False)
    needed.to_csv(args.out / "n_needed.csv", index=False)
    _plot(curve, args.out)


if __name__ == "__main__":
    main()
