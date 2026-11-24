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


def bootstrap_summary(events, by, alpha=0.05, n_boot=1000, seed=0):
    """Return event-weighted point estimates and 95% event bootstrap intervals.

    As in summarize, width and score use finite-width intervals only. Events
    without any such interval contribute to coverage alone.
    """
    if n_boot < 1:
        raise ValueError("n_boot must be positive")
    by = list(by)
    metrics = ["coverage", "mean_width", "interval_score"]
    width = events["hi"] - events["lo"]
    finite = np.isfinite(width)
    values = events[[*by, "event_id"]].assign(
        coverage=events["m_true"].between(events["lo"], events["hi"]),
        mean_width=width.where(finite),
        interval_score=np.where(finite, interval_score(events["lo"], events["hi"], events["m_true"], alpha), np.nan),
    )
    event_means = values.groupby([*by, "event_id"], sort=True)[metrics].mean().reset_index()
    rng = np.random.default_rng(seed)
    rows = []
    for key, group in event_means.groupby(by, sort=True):
        row = dict(zip(by, key))
        data = group[metrics].to_numpy().T
        valid = ~np.isnan(data)
        sums = np.where(valid, data, 0.0)
        counts = valid.sum(axis=1)
        points = np.divide(sums.sum(axis=1), counts, out=np.full(len(metrics), np.inf), where=counts > 0)
        boot = np.full((len(metrics), n_boot), np.inf)
        batch_size = max(1, 1_000_000 // len(group))
        for start in range(0, n_boot, batch_size):
            stop = min(start + batch_size, n_boot)
            indices = rng.integers(len(group), size=(stop - start, len(group)), dtype=np.int32)
            for i in np.flatnonzero(counts):
                total = sums[i, indices].sum(axis=1)
                count = len(group) if counts[i] == len(group) else valid[i, indices].sum(axis=1)
                np.divide(total, count, out=boot[i, start:stop], where=count > 0)
        for metric, point, draws in zip(metrics, points, boot):
            row[metric] = point
            # Interpolate finite endpoints and handle infinite draws without inf - inf.
            draws.sort()
            for suffix, quantile in (("lo", 0.025), ("hi", 0.975)):
                rank = (len(draws) - 1) * quantile
                lower, upper = draws[int(rank)], draws[int(np.ceil(rank))]
                row[f"{metric}_{suffix}"] = (
                    lower + (rank % 1) * (upper - lower) if np.isfinite(upper) else np.inf
                )
        rows.append(row)
    columns = [*by, *(col for metric in metrics for col in (metric, f"{metric}_lo", f"{metric}_hi"))]
    return pd.DataFrame(rows, columns=columns)
