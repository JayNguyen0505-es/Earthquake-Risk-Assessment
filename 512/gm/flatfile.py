"""Unified ground-motion flatfile.

One row = one (event, station) recording. Columns (all SI except where noted):

    event_id      str   provider event id
    station_id    str   NET.STA
    mag           float moment/local magnitude as given by the provider
    depth_km      float hypocentral depth
    ev_lat, ev_lon
    st_lat, st_lon
    rhypo_km      float hypocentral distance
    repi_km       float epicentral distance
    rjb_km        float Joyner-Boore distance (NaN if unknown; scenario code falls back to repi)
    rrup_km       float closest distance to rupture (NaN if unknown)
    vs30_ms       float time-averaged shear-wave velocity in top 30 m
    mech          str   SS, NM, RV, U (unknown)
    pga_g         float peak ground acceleration in g
    pgv_cms       float peak ground velocity in cm/s
    sa_0.3_g, sa_1.0_g, sa_3.0_g   pseudo-spectral acceleration (5% damping) in g
    source        str   "nga_west2" | "shakemap" | "synthetic" | ...

Targets are modelled in natural log space (ln of g, ln of cm/s).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = [
    "event_id", "station_id", "mag", "depth_km", "ev_lat", "ev_lon", "st_lat", "st_lon",
    "rhypo_km", "repi_km", "rjb_km", "rrup_km", "vs30_ms", "mech",
    "pga_g", "pgv_cms", "sa_0.3_g", "sa_1.0_g", "sa_3.0_g", "source",
]

TARGETS = {
    "pga": "pga_g",
    "pgv": "pgv_cms",
    "sa_0.3": "sa_0.3_g",
    "sa_1.0": "sa_1.0_g",
    "sa_3.0": "sa_3.0_g",
}

# NGA-West2 public flatfile (Ancheta et al. 2014). Column headers differ slightly between the
# xlsx releases, so each field has a list of regexes tried in order against the header names.
NGA_WEST2_PATTERNS = {
    "event_id": [r"^EQID$"],
    "station_id": [r"^Station Sequence Number$", r"^Station Name$"],
    "mag": [r"^Earthquake Magnitude$"],
    "depth_km": [r"^Hypocenter Depth \(km\)$"],
    "ev_lat": [r"^Hypocenter Latitude \(deg\)$"],
    "ev_lon": [r"^Hypocenter Longitude \(deg\)$"],
    "st_lat": [r"^Station Latitude$"],
    "st_lon": [r"^Station Longitude$"],
    "rhypo_km": [r"^HypD \(km\)$"],
    "repi_km": [r"^EpiD \(km\)$"],
    "rjb_km": [r"^Joyner-Boore Dist\. \(km\)$"],
    "rrup_km": [r"^ClstD \(km\)$"],
    "vs30_ms": [r"^Vs30 \(m/s\) selected for analysis$", r"^Vs30.*selected", r"^Vs30"],
    "mech": [r"^Mechanism Based on Rake Angle$"],
    "pga_g": [r"^PGA \(g\)$"],
    "pgv_cms": [r"^PGV \(cm/sec\)$"],
    "sa_0.3_g": [r"^T0\.300S$"],
    "sa_1.0_g": [r"^T1\.000S$"],
    "sa_3.0_g": [r"^T3\.000S$"],
}

# NGA-West2 mechanism codes: 0 strike-slip, 1 normal, 2 reverse, 3 reverse-oblique, 4 normal-oblique
NGA_MECH = {0: "SS", 1: "NM", 2: "RV", 3: "RV", 4: "NM"}


def _match_column(columns, patterns):
    for pattern in patterns:
        rx = re.compile(pattern, re.IGNORECASE)
        for col in columns:
            if rx.search(str(col).strip()):
                return col
    return None


def read_nga_west2(path, sheet_name=0, column_overrides=None):
    """Read the PEER NGA-West2 flatfile (xlsx or csv) into the unified schema.

    The flatfile must be downloaded manually from https://peer.berkeley.edu/research/
    data-sciences/databases (free registration). Pass ``column_overrides`` as
    {unified_name: source_column} when headers differ from the defaults.
    """
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        raw = pd.read_excel(path, sheet_name=sheet_name)
    else:
        raw = pd.read_csv(path, low_memory=False)
    overrides = dict(column_overrides or {})
    out = pd.DataFrame(index=raw.index)
    missing = []
    for field, patterns in NGA_WEST2_PATTERNS.items():
        src = overrides.get(field) or _match_column(raw.columns, patterns)
        if src is None:
            missing.append(field)
            out[field] = np.nan
        else:
            out[field] = raw[src]
    if missing:
        print(f"[nga_west2] columns not found, left NaN: {missing}")
    out["event_id"] = out["event_id"].astype(str)
    out["station_id"] = out["station_id"].astype(str)
    out["mech"] = out["mech"].map(lambda v: NGA_MECH.get(int(v), "U") if pd.notna(v) else "U")
    out["source"] = "nga_west2"
    # NGA uses -999 for unknown values
    for c in COLUMNS:
        if out[c].dtype.kind in "fi":
            out.loc[out[c] <= -900, c] = np.nan
    return clean(out[COLUMNS])


def clean(df, min_mag=3.0, max_rhypo_km=400.0, min_vs30=100.0):
    """Drop rows unusable for regression and enforce dtypes."""
    df = df.copy()
    num = [c for c in COLUMNS if c not in {"event_id", "station_id", "mech", "source"}]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["mag"] >= min_mag]
    df = df[(df["rhypo_km"] > 0) & (df["rhypo_km"] <= max_rhypo_km)]
    df = df[df["pga_g"] > 0]
    df.loc[df["vs30_ms"] < min_vs30, "vs30_ms"] = np.nan
    df["mech"] = df["mech"].fillna("U").astype(str)
    return df.reset_index(drop=True)


def load(path):
    """Load a unified flatfile saved by this package (csv or parquet)."""
    path = Path(path)
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    return df[COLUMNS]


def save(df, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
    return path


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))
