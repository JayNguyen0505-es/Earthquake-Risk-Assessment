"""Converters from the pipeline outputs into station tables (see calib/__init__.py)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

STD_COLUMNS = ["event_id", "station", "m_true", "m_pred", "sd", "time", "azimuth", "estimator"]


def _time_from_source_id(sid):
    """AQ2009 ids look like 'AQ.20090406003543' -> UNIX seconds; NaN otherwise."""
    m = re.search(r"(\d{14})", str(sid))
    if not m:
        return np.nan
    return pd.Timestamp(m.group(1)).tz_localize("UTC").timestamp()


def azimuth_deg(ev_lat, ev_lon, st_lat, st_lon):
    """Initial great-circle bearing from event to station, degrees clockwise from north."""
    p1, p2 = np.radians(ev_lat), np.radians(st_lat)
    dl = np.radians(np.asarray(st_lon, float) - np.asarray(ev_lon, float))
    x = np.sin(dl) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(x, y)) + 360.0) % 360.0


def from_train_predictions(path, estimator="dl"):
    """test_predictions.csv / dev_predictions.csv written by train_magnitude.py (old or new format)."""
    df = pd.read_csv(path, low_memory=False)
    out = pd.DataFrame({"event_id": df["source_id"].astype(str), "m_true": df["m_true"].astype(float),
                        "m_pred": df["m_pred"].astype(float), "sd": np.exp(0.5 * df["logvar"].astype(float))})
    out["station"] = (df["station_code"].astype(str) if "station_code" in df else
                      df.groupby("source_id").cumcount().astype(str))
    if "source_time" in df:
        out["time"] = pd.to_datetime(df["source_time"], utc=True, errors="coerce").map(
            lambda t: t.timestamp() if pd.notna(t) else np.nan)
    else:
        out["time"] = out["event_id"].map(_time_from_source_id)
    if "azimuth" in df:
        out["azimuth"] = df["azimuth"].astype(float)
    elif {"source_lat", "source_lon", "station_lat", "station_lon"} <= set(df.columns):
        out["azimuth"] = azimuth_deg(df["source_lat"], df["source_lon"], df["station_lat"], df["station_lon"])
    else:
        out["azimuth"] = np.nan
    out["estimator"] = estimator
    for c in ("dist_km", "log_amp_z", "log_amp_n", "log_amp_e", "channel", "mag_type"):
        if c in df:
            out[c] = df[c]
    return out[STD_COLUMNS + [c for c in out.columns if c not in STD_COLUMNS]]


def from_e2e(out_dir, run_dir=None, estimator=None):
    """station_magnitudes.csv of an e2e_run.py / e2e_magnitudes.py output folder, labelled with the
    reference magnitude through matches.csv (e2e_run) or directly (e2e_magnitudes, which works on
    reference events)."""
    out_dir = Path(out_dir)
    sm = pd.read_csv(out_dir / "station_magnitudes.csv")
    if estimator:
        sm = sm[sm["estimator"] == estimator]
    if "m_true" not in sm:
        import json

        matches = pd.read_csv(out_dir / "matches.csv")
        run_dir = Path(run_dir or json.loads((out_dir / "metrics.json").read_text())["run_dir"])
        ref = pd.read_csv(run_dir / "events.csv")
        ref["event_id"] = ref["event_id"].astype(str)
        mm = matches.assign(ref_id=matches["ref_id"].astype(str)).merge(
            ref[["event_id", "mag", "time_s"]].rename(columns={"event_id": "ref_id"}), on="ref_id")
        sm = sm.merge(mm[["det_id", "ref_id", "mag", "time_s"]], left_on="event_id", right_on="det_id")
        sm = sm.assign(event_id=sm["ref_id"], m_true=sm["mag"], time=sm["time_s"])
    for c in STD_COLUMNS:
        if c not in sm:
            sm[c] = np.nan
    sm = sm.dropna(subset=["m_pred", "m_true"])
    sm["event_id"] = sm["event_id"].astype(str)
    return sm[STD_COLUMNS + [c for c in sm.columns if c not in STD_COLUMNS]].reset_index(drop=True)


def load_table(spec, estimator=None):
    """A station table from a CSV path: train_magnitude predictions, an e2e folder, or a ready table."""
    p = Path(spec)
    if p.is_dir():
        return from_e2e(p, estimator=estimator)
    head = pd.read_csv(p, nrows=2)
    if "source_id" in head and "logvar" in head:
        return from_train_predictions(p, estimator or "dl")
    df = pd.read_csv(p)
    if estimator and "estimator" in df:
        df = df[df["estimator"] == estimator]
    df["event_id"] = df["event_id"].astype(str)
    return df
