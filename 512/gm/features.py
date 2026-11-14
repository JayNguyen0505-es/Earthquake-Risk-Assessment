"""Feature construction shared by the baseline and the ML models."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .vs30 import DEFAULT_VS30

MECHS = ["SS", "NM", "RV", "U"]
FEATURES = ["mag", "dist_km", "ln_dist", "depth_km", "ln_vs30", "mech_SS", "mech_NM", "mech_RV", "mech_U"]


def distance(df, metric="rhypo"):
    """Source-to-site distance in km. ``rjb`` falls back to epicentral distance when unknown
    (point-source approximation, fine for M < ~6)."""
    if metric == "rhypo":
        d = df["rhypo_km"].to_numpy(float)
    elif metric == "rjb":
        d = df["rjb_km"].to_numpy(float)
        d = np.where(np.isfinite(d), d, df["repi_km"].to_numpy(float))
    elif metric == "rrup":
        d = df["rrup_km"].to_numpy(float)
        d = np.where(np.isfinite(d), d, df["rhypo_km"].to_numpy(float))
    else:
        raise ValueError(metric)
    return np.maximum(d, 0.5)


def feature_frame(df, metric="rhypo"):
    X = pd.DataFrame(index=df.index)
    X["mag"] = df["mag"].to_numpy(float)
    X["dist_km"] = distance(df, metric)
    X["ln_dist"] = np.log(X["dist_km"])
    X["depth_km"] = df["depth_km"].fillna(10.0).to_numpy(float)
    vs = df["vs30_ms"].fillna(DEFAULT_VS30).to_numpy(float)
    X["ln_vs30"] = np.log(vs / DEFAULT_VS30)
    mech = df["mech"].fillna("U").astype(str)
    for m in MECHS:
        X[f"mech_{m}"] = (mech == m).astype(float)
    return X[FEATURES]


def target_vector(df, target_col):
    y = df[target_col].to_numpy(float)
    return np.log(y)
