"""Coverage of event-magnitude intervals under station dropout: naive vs shared-error vs conformal.

    # in-domain, existing outputs, no retraining: calibrate on the earliest 66% of test events
    python 511/calibration_study.py --cal 511/outputs/magnitude/AQ2009GM/test_predictions.csv \
        --temporal-split 0.66 --out 511/outputs/calibration/aq2009_temporal

    # proper split: calibrate on the dev set, test on the test set (train_magnitude.py writes both)
    python 511/calibration_study.py --cal 511/outputs/magnitude/AQ2009GM/dev_predictions.csv \
        --test 511/outputs/magnitude/AQ2009GM/test_predictions.csv --out 511/outputs/calibration/aq2009

    # cross-region: calibrate in Italy, test on Ridgecrest (station tables from e2e_magnitudes.py)
    python 511/calibration_study.py --cal .../central_italy/ref_loc/station_magnitudes.csv \
        --test .../ridgecrest/ref_loc/station_magnitudes.csv --estimator ml --out ...

    # few-shot recalibration in the new region: add its first 50 events to the calibration set
    python 511/calibration_study.py --cal ITALY --test RIDGECREST --few-shot 50 [--target-only] --adaptive ...

A spec is a train_magnitude.py predictions CSV, an e2e output folder, or a ready station table.
Outputs: summary.csv (per method), summary_by_k.csv (per method, k, dropout mode), info.json
(fitted tau / scale / bias, conformal factors, ICC), events.csv.gz, coverage_width_vs_k.png.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from calib.io import load_table  # noqa: E402
from calib.metrics import summarize  # noqa: E402
from calib.study import first_n_events, run_study, split_by_time  # noqa: E402


def _k(v):
    return v if v == "all" else int(v)


def plot(by_k, out, alpha):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    modes = [m for m in by_k["mode"].unique() if m != "all"] or ["all"]
    fig, axes = plt.subplots(len(modes), 2, figsize=(11, 3.6 * len(modes)), squeeze=False)
    order = sorted(by_k["k"].unique(), key=lambda k: 10 ** 6 if k == "all" else int(k))
    for r, mode in enumerate(modes):
        sub = by_k[(by_k["mode"] == mode) | (by_k["k"] == "all")]
        for method, g in sub.groupby("method"):
            g = g.set_index("k").reindex(order)
            axes[r, 0].plot(range(len(order)), g["coverage"], marker="o", label=method)
            axes[r, 1].plot(range(len(order)), g["mean_width"], marker="o", label=method)
        axes[r, 0].axhline(1 - alpha, color="k", lw=0.8, ls="--")
        for ax, lab in zip(axes[r], ("coverage", "mean interval width (magnitude units)")):
            ax.set_xticks(range(len(order)))
            ax.set_xticklabels(order)
            ax.set_xlabel(f"stations kept ({mode})")
            ax.set_ylabel(lab)
    axes[0, 0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "coverage_width_vs_k.png", dpi=130)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cal", nargs="+", required=True, help="calibration station table(s)")
    p.add_argument("--test", nargs="*", help="test station table(s); omit with --temporal-split")
    p.add_argument("--temporal-split", type=float, help="split --cal by time: this fraction calibrates")
    p.add_argument("--estimator", help="keep only this estimator (dl or ml) from e2e tables")
    p.add_argument("--few-shot", type=int, help="move the first N test events (time order) into calibration")
    p.add_argument("--target-only", action="store_true", help="with --few-shot: calibrate on those N events only")
    p.add_argument("--ks", nargs="+", default=["3", "5", "10", "all"])
    p.add_argument("--modes", nargs="+", default=["random", "one_sided"], choices=["random", "one_sided"])
    p.add_argument("--n-rep", type=int, default=3, help="random subsets per event and k")
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--no-bias", action="store_true", help="do not fit a global offset")
    p.add_argument("--adaptive", action="store_true", help="add adaptive conformal along the test sequence")
    p.add_argument("--aci-gamma", type=float, default=0.005)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)

    cal = pd.concat([load_table(s, a.estimator) for s in a.cal], ignore_index=True)
    if a.test:
        test = pd.concat([load_table(s, a.estimator) for s in a.test], ignore_index=True)
    elif a.temporal_split:
        cal, test = split_by_time(cal, a.temporal_split)
    else:
        raise SystemExit("give --test or --temporal-split")
    if a.few_shot:
        shot, test = first_n_events(test, a.few_shot)
        cal = shot if a.target_only else pd.concat([cal, shot], ignore_index=True)
    modes = list(a.modes)
    if "one_sided" in modes and not (cal["azimuth"].notna().all() and test["azimuth"].notna().all()):
        print("note: azimuths missing, one-sided dropout skipped")
        modes = [m for m in modes if m != "one_sided"] or ["random"]
    ks = [_k(k) for k in a.ks]
    events, info = run_study(cal, test, ks, modes, a.n_rep, a.alpha, a.seed, fit_bias=not a.no_bias,
                             adaptive=a.adaptive, aci_gamma=a.aci_gamma)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(events, ("method",), a.alpha)
    by_k = summarize(events, ("method", "k", "mode"), a.alpha)
    summary.to_csv(out / "summary.csv", index=False)
    by_k.to_csv(out / "summary_by_k.csv", index=False)
    events.to_csv(out / "events.csv.gz", index=False)
    info["args"] = vars(a)
    (out / "info.json").write_text(json.dumps(info, indent=2, default=str))
    plot(by_k, out, a.alpha)
    pd.set_option("display.width", 200)
    print(json.dumps({k: v for k, v in info.items() if k != "args"}, indent=1, default=str))
    print(by_k.pivot_table(index=["mode", "k"], columns="method", values="coverage").round(3).to_string())
    print(by_k.pivot_table(index=["mode", "k"], columns="method", values="mean_width").round(3).to_string())
    print(f"outputs in {out}")


if __name__ == "__main__":
    main()
