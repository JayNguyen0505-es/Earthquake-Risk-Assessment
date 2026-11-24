"""Interval quality: coverage, width and the interval (Winkler) score."""

from __future__ import annotations

import numpy as np
import pandas as pd


def interval_score(lo, hi, y, alpha=0.05):
    """Gneiting & Raftery (2007) interval score: width + 2/alpha * distance outside. Lower is better."""
    lo, hi, y = (np.asarray(v, float) for v in (lo, hi, y))
    return (hi - lo) + 2 / alpha * np.maximum(lo - y, 0) + 2 / alpha * np.maximum(y - hi, 0)


def summarize(events, by=("method",), alpha=0.05):
    """events: one row per (event, subset, method) with m_hat, lo, hi, m_true. Returns a summary table."""
    e = events.copy()
    e["covered"] = (e["m_true"] >= e["lo"]) & (e["m_true"] <= e["hi"])
    e["width"] = e["hi"] - e["lo"]
    e["iscore"] = interval_score(e["lo"], e["hi"], e["m_true"], alpha)
    e["abs_err"] = (e["m_hat"] - e["m_true"]).abs()
    finite = np.isfinite(e["width"])

    def agg(g):
        f = finite[g.index]
        return pd.Series({
            "n_events": int(g["event_id"].nunique()), "n_intervals": int(len(g)),
            "coverage": float(g["covered"].mean()),
            "mean_width": float(g.loc[f, "width"].mean()) if f.any() else np.inf,
            "median_width": float(g.loc[f, "width"].median()) if f.any() else np.inf,
            "interval_score": float(g.loc[f, "iscore"].mean()) if f.any() else np.inf,
            "mae": float(g["abs_err"].mean()), "bias": float((g["m_hat"] - g["m_true"]).mean()),
            "frac_infinite": float(1 - f.mean()),
        })

    return e.groupby(list(by), sort=True).apply(agg, include_groups=False).reset_index()
