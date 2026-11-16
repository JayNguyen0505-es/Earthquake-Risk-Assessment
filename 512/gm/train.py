"""Train and evaluate ground-motion models on a unified flatfile.

    python 512/train.py --flatfile data/gm/shakemap_flatfile.csv --out 512/outputs/shakemap \
        --targets pga sa_1.0 --models baseline rf gbm mlp --distance rhypo

Writes per target/model: event-grouped CV metrics (metrics.csv), the final model fitted on all
rows (models/<target>_<model>.joblib), out-of-fold residuals, and diagnostic PNGs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import INTENSITY_MEASURES
from .evaluate import grouped_cv, metrics
from .features import feature_frame, target_vector
from .flatfile import TARGETS, load
from .models import MODEL_NAMES, make_model


def run(flatfile, out, targets, models, distance="rhypo", n_splits=5, seed=0, plots=True,
        max_dist=None, min_mag=None, require_vs30=False):
    out = Path(out)
    (out / "models").mkdir(parents=True, exist_ok=True)
    df = load(flatfile)
    n0 = len(df)
    if max_dist:
        df = df[df["rhypo_km"] <= max_dist]
    if min_mag:
        df = df[df["mag"] >= min_mag]
    if require_vs30:
        df = df[df["vs30_ms"].notna()]
    df = df.reset_index(drop=True)
    if len(df) != n0:
        print(f"filters kept {len(df)}/{n0} recordings, {df['event_id'].nunique()} events")
    rows, residuals = [], []
    for target in targets:
        col = TARGETS[target]
        sub = df[df[col] > 0].reset_index(drop=True)
        if len(sub) < 50:
            print(f"[{target}] only {len(sub)} rows, skipped")
            continue
        X = feature_frame(sub, distance)
        y = target_vector(sub, col)
        groups = sub["event_id"].to_numpy()
        print(f"[{target}] {len(sub)} recordings, {len(np.unique(groups))} events")
        for name in models:
            model = make_model(name, seed)
            oof, cv = grouped_cv(model, X, y, groups, n_splits)
            final = make_model(name, seed).fit(X, y)
            fit = metrics(y, final.predict(X), groups)
            row = {"target": target, "model": name, "distance": distance,
                   **{f"cv_{k}": v for k, v in cv.items()}, **{f"fit_{k}": v for k, v in fit.items()}}
            if name == "baseline":
                row.update({f"coef_{k}": v for k, v in final.summary().items()})
            rows.append(row)
            print(f"  {name:8s} CV rmse={cv['rmse']:.3f} r2={cv['r2']:.3f} tau={cv['tau']:.3f} phi={cv['phi']:.3f}")
            joblib.dump({"model": final, "target": target, "distance": distance, "features": list(X.columns)},
                        out / "models" / f"{target}_{name}.joblib")
            residuals.append(pd.DataFrame({"target": target, "model": name, "event_id": groups,
                                           "mag": X["mag"], "dist_km": X["dist_km"], "resid": y - oof}))
    table = pd.DataFrame(rows)
    table.to_csv(out / "metrics.csv", index=False)
    res = pd.concat(residuals, ignore_index=True) if residuals else pd.DataFrame()
    res.to_csv(out / "oof_residuals.csv", index=False)
    (out / "run.json").write_text(json.dumps({"flatfile": str(flatfile), "targets": targets, "models": models,
                                              "distance": distance, "n_rows": int(len(df))}, indent=2))
    if plots and len(res):
        plot_residuals(res, out)
    return table


def plot_residuals(res, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for target, grp in res.groupby("target"):
        models = sorted(grp["model"].unique())
        fig, axes = plt.subplots(2, len(models), figsize=(4 * len(models), 7), squeeze=False)
        for j, name in enumerate(models):
            g = grp[grp["model"] == name]
            for i, (xcol, label) in enumerate([("dist_km", "distance (km)"), ("mag", "magnitude")]):
                ax = axes[i, j]
                ax.scatter(g[xcol], g["resid"], s=4, alpha=0.3)
                ax.axhline(0, color="k", lw=0.8)
                if xcol == "dist_km":
                    ax.set_xscale("log")
                ax.set_xlabel(label)
                ax.set_ylabel("ln residual (obs - pred)")
                ax.set_title(f"{target} / {name}")
                ax.set_ylim(-3, 3)
        fig.tight_layout()
        fig.savefig(out / f"residuals_{target}.png", dpi=120)
        plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--flatfile", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--targets", nargs="+", default=["pga"], choices=INTENSITY_MEASURES)
    p.add_argument("--models", nargs="+", default=MODEL_NAMES, choices=MODEL_NAMES)
    p.add_argument("--distance", default="rhypo", choices=["rhypo", "rjb", "rrup"])
    p.add_argument("--splits", type=int, default=5)
    p.add_argument("--max-dist", type=float, help="drop recordings beyond this hypocentral distance (km)")
    p.add_argument("--min-mag", type=float)
    p.add_argument("--require-vs30", action="store_true", help="drop rows without Vs30 instead of assuming 760 m/s")
    p.add_argument("--no-plots", action="store_true")
    a = p.parse_args(argv)
    table = run(a.flatfile, a.out, a.targets, a.models, a.distance, a.splits, plots=not a.no_plots,
                max_dist=a.max_dist, min_mag=a.min_mag, require_vs30=a.require_vs30)
    cols = ["target", "model", "cv_rmse", "cv_r2", "cv_tau", "cv_phi", "cv_sigma"]
    print(table[cols].to_string(index=False))


if __name__ == "__main__":
    main()
