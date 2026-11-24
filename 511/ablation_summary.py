"""Compare event magnitude errors and DL feature distributions across runs."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from dl.magnet import combine_station_estimates

FEATURES = ["log_amp_z", "log_amp_n", "log_amp_e", "logdist"]
BINS = [-1, 1, 1.5, 2, 2.5, 3, 4, 10]


def aggregate_events(stations, estimator):
    rows = []
    for event_id, group in stations.groupby("event_id", sort=False):
        if estimator == "ml":
            prediction = group["m_pred"].median()
        else:
            prediction, _, _ = combine_station_estimates(group["m_pred"], group["logvar"])
        rows.append((event_id, len(group), group["m_true"].iloc[0], prediction))
    events = pd.DataFrame(rows, columns=["event_id", "n_stations", "m_true", "m_pred"])
    return events.assign(error=events["m_pred"] - events["m_true"])


def summarize_events(events):
    slope = np.nan
    if events["m_true"].nunique() >= 2:
        slope = np.polyfit(events["m_true"], events["m_pred"], 1)[0]
    return dict(n_events=len(events), mae=events["error"].abs().mean(), bias=events["error"].mean(),
                slope=slope)


def feature_stats(values):
    values = values[np.isfinite(values)]
    if not len(values):
        return dict.fromkeys(["mean", "std", "p5", "p50", "p95"], np.nan)
    p5, p50, p95 = np.percentile(values, [5, 50, 95])
    return dict(mean=values.mean(), std=values.std(ddof=0), p5=p5, p50=p50, p95=p95)


def shift_rows(label, train, run):
    for feature in FEATURES:
        a = feature_stats(train[feature])
        b = feature_stats(run[feature])
        pooled = np.hypot(a["std"], b["std"]) / np.sqrt(2)
        yield dict(run=label, feature=feature, **{f"train_{k}": v for k, v in a.items()},
                   **{f"run_{k}": v for k, v in b.items()},
                   smd=(b["mean"] - a["mean"]) / pooled if pooled > 0 else np.nan)


def markdown_table(frame):
    def cell(value):
        if pd.isna(value):
            return "—"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value).replace("|", r"\|")

    def line(values):
        return "| " + " | ".join(map(cell, values)) + " |"

    return "\n".join([line(frame.columns), line(["---"] * len(frame.columns)),
                      *(line(row) for row in frame.itertuples(index=False, name=None))])


def plot_scatter(runs, path):
    fig, axes = plt.subplots(len(runs), 1, figsize=(5, 4 * len(runs)), squeeze=False,
                             layout="constrained")
    for (label, estimates), ax in zip(runs.items(), axes[:, 0]):
        bounds = []
        for estimator, events in estimates.items():
            if events.empty:
                continue
            ax.scatter(events["m_true"], events["m_pred"], s=12, alpha=0.6, label=estimator.upper())
            bounds.extend([events["m_true"].min(), events["m_true"].max(),
                           events["m_pred"].min(), events["m_pred"].max()])
        if bounds:
            ax.axline((min(bounds), min(bounds)), slope=1, ls="--", color="0.5", lw=1)
            ax.set(xlim=(min(bounds) - 0.2, max(bounds) + 0.2),
                   ylim=(min(bounds) - 0.2, max(bounds) + 0.2))
            ax.legend()
        ax.set(title=label, xlabel="Reference magnitude", ylabel="Event magnitude", aspect="equal")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True, metavar="LABEL=OUT_DIR")
    parser.add_argument("--train-pred", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    runs = {}
    for spec in args.runs:
        label, sep, folder = spec.partition("=")
        if not sep or not label or not folder or label in runs:
            parser.error("--runs requires unique LABEL=OUT_DIR pairs")
        runs[label] = Path(folder)

    train = pd.read_csv(args.train_pred, usecols=FEATURES, dtype=float) if args.train_pred else None
    numeric = ["m_true", "m_pred", "logvar", "snr", *FEATURES]
    dtypes = {"event_id": str, **dict.fromkeys(numeric, float)}
    summaries, by_bin, shifts, scatter = [], [], [], {}
    for label, folder in runs.items():
        stations = pd.read_csv(folder / "station_magnitudes.csv", dtype=dtypes)
        if train is not None:
            shifts.extend(shift_rows(label, train, stations[stations["estimator"] == "dl"]))
        stations = stations[np.isfinite(stations["m_true"]) & np.isfinite(stations["m_pred"])]
        scatter[label] = {}
        for estimator, group in stations.groupby("estimator", sort=False):
            if estimator == "dl":
                group = group[np.isfinite(group["logvar"])]
            for subset, rows in [("all", group), ("snr>=3", group[group["snr"] >= 3])]:
                events = aggregate_events(rows, estimator)
                key = dict(run=label, estimator=estimator, subset=subset)
                summaries.append(dict(**key, **summarize_events(events)))
                if subset == "all":
                    scatter[label][estimator] = events
                for lo, hi in zip(BINS, BINS[1:]):
                    in_bin = events[(events["m_true"] > lo) & (events["m_true"] <= hi)]
                    by_bin.append(dict(**key, mag_lo=lo, mag_hi=hi, n_events=len(in_bin),
                                       bias=in_bin["error"].mean()))

    key_columns = ["run", "estimator", "subset"]
    stats = pd.DataFrame(summaries, columns=key_columns + ["n_events", "mae", "bias", "slope"])
    bins = pd.DataFrame(by_bin, columns=key_columns + ["mag_lo", "mag_hi", "n_events", "bias"])
    shift_columns = [f"{src}_{stat}" for src in ("train", "run")
                     for stat in ("mean", "std", "p5", "p50", "p95")]
    shift = pd.DataFrame(shifts, columns=["run", "feature", *shift_columns, "smd"])
    args.out.mkdir(parents=True, exist_ok=True)
    stats.to_csv(args.out / "ablation_events.csv", index=False)
    bins.to_csv(args.out / "ablation_by_bin.csv", index=False)
    shift.to_csv(args.out / "feature_shift.csv", index=False)
    report = ["# Magnitude ablation", "## Event errors", markdown_table(stats),
              "## Bias by reference magnitude", markdown_table(bins[bins["n_events"] > 0])]
    if train is not None:
        report += ["## DL feature shift", markdown_table(shift[["run", "feature", "train_mean", "run_mean", "smd"]])]
    (args.out / "ablation.md").write_text("\n\n".join(report) + "\n", encoding="utf-8")
    plot_scatter(scatter, args.out / "ablation_scatter.png")


if __name__ == "__main__":
    main()
