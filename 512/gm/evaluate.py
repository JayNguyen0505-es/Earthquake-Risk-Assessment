"""Metrics for ground-motion models, including the between/within-event split used in GMPE work."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.model_selection import GroupKFold


def residual_components(resid, groups):
    """tau = std of event terms, phi = std of within-event residuals, sigma = total.

    Event term = mean residual of the event (simple method-of-moments; a mixed-effects fit would
    weight by station count, which matters little once there are hundreds of events).
    """
    r = pd.Series(np.asarray(resid, float))
    g = pd.Series(np.asarray(groups))
    event_term = r.groupby(g.values).transform("mean")
    tau = float(r.groupby(g.values).mean().std(ddof=1)) if g.nunique() > 1 else float("nan")
    phi = float((r - event_term).std(ddof=1))
    return {"tau": tau, "phi": phi, "sigma": float(np.sqrt(np.nan_to_num(tau) ** 2 + phi ** 2))}


def metrics(y, yhat, groups=None):
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    resid = y - yhat
    out = {
        "n": int(len(y)),
        "bias": float(resid.mean()),
        "rmse": float(np.sqrt(np.mean(resid ** 2))),
        "mae": float(np.mean(np.abs(resid))),
        "r2": float(1 - np.sum(resid ** 2) / np.sum((y - y.mean()) ** 2)),
    }
    if groups is not None:
        out.update(residual_components(resid, groups))
    return out


def grouped_cv(model, X, y, groups, n_splits=5):
    """Event-grouped K-fold: a test event never appears in training (station overlap is allowed,
    as in standard GMPE practice). Returns out-of-fold predictions and pooled metrics."""
    gkf = GroupKFold(n_splits=min(n_splits, len(np.unique(groups))))
    oof = np.full(len(y), np.nan)
    for tr, te in gkf.split(X, y, groups):
        m = clone(model)
        m.fit(X.iloc[tr], y[tr])
        oof[te] = m.predict(X.iloc[te])
    return oof, metrics(y, oof, groups)
