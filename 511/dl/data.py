"""SeisBench dataset helpers shared by the picker benchmark, picker fine-tuning and magnitude training.

A dataset spec is either a SeisBench benchmark class name (``ETHZ``, ``STEAD``, ``InstanceGM``,
``AQ2009GM``, ``PNWAccelerometers``, ...), downloaded on first use into ``$SEISBENCH_CACHE_ROOT``
(default ``~/.seisbench``), or a path to a folder holding ``metadata.csv`` + ``waveforms.hdf5`` in
SeisBench format (how the Vietnamese data will be packaged later).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

P_COLUMNS = ["trace_p_arrival_sample", "trace_P_arrival_sample", "trace_P1_arrival_sample",
             "trace_Pg_arrival_sample", "trace_Pn_arrival_sample", "trace_Pb_arrival_sample"]
S_COLUMNS = ["trace_s_arrival_sample", "trace_S_arrival_sample", "trace_S1_arrival_sample",
             "trace_Sg_arrival_sample", "trace_Sn_arrival_sample", "trace_Sb_arrival_sample"]


def load_dataset(spec, sampling_rate=100.0, component_order="ZNE", **kwargs):
    import seisbench.data as sbd

    path = Path(str(spec)).expanduser()
    if path.exists():
        return sbd.WaveformDataset(path, sampling_rate=sampling_rate, component_order=component_order, **kwargs)
    if not hasattr(sbd, str(spec)):
        raise SystemExit(f"unknown dataset '{spec}': not a folder and not a seisbench.data class")
    return getattr(sbd, str(spec))(sampling_rate=sampling_rate, component_order=component_order, **kwargs)


def data_unit(ds):
    """(measurement, unit) from the dataset's data_format, e.g. ('velocity', 'counts') or ('acceleration', 'mps2')."""
    fmt = getattr(ds, "data_format", {}) or {}
    return str(fmt.get("measurement", "unknown")).lower(), str(fmt.get("unit", "unknown")).lower()


def is_physical_unit(ds):
    _, unit = data_unit(ds)
    return unit not in ("unknown", "", "none") and "count" not in unit


def phase_columns(metadata, phases=("P", "S")):
    """{column: phase} for the arrival-sample columns present in the metadata."""
    out = {}
    if "P" in phases:
        out.update({c: "P" for c in P_COLUMNS if c in metadata.columns})
    if "S" in phases:
        out.update({c: "S" for c in S_COLUMNS if c in metadata.columns})
    return out


def first_arrival(metadata, phase):
    cols = [c for c in (P_COLUMNS if phase == "P" else S_COLUMNS) if c in metadata.columns]
    if not cols:
        return pd.Series(np.nan, index=metadata.index)
    return metadata[cols].min(axis=1, skipna=True)


def channel_mask(metadata, prefixes):
    """Rows whose instrument code (first two letters of trace_channel, e.g. HH, EH, HN) is in prefixes."""
    if not prefixes:
        return np.ones(len(metadata), dtype=bool)
    col = next((c for c in ("trace_channel", "station_channel") if c in metadata.columns), None)
    if col is None:
        raise SystemExit("dataset has no trace_channel/station_channel column; cannot filter by channel")
    code = metadata[col].astype(str).str.upper().str[:2]
    return code.isin([p.upper()[:2] for p in prefixes]).to_numpy()


def earthquake_mask(metadata):
    """Drop pure-noise traces (STEAD/INSTANCE style ``trace_category``)."""
    if "trace_category" in metadata.columns:
        return ~metadata["trace_category"].astype(str).str.contains("noise", case=False).to_numpy()
    return np.ones(len(metadata), dtype=bool)


def event_split_labels(metadata, fractions=(0.8, 0.1, 0.1), key="source_id", seed=0):
    """Deterministic event-grouped split: every trace of one earthquake lands in the same set.

    Falls back to the dataset's own ``split`` column, then to a per-trace hash, if no event id exists.
    """
    if key in metadata.columns and metadata[key].notna().any():
        ids = metadata[key].astype(str)
    elif "split" in metadata.columns:
        return metadata["split"].astype(str).str.lower().replace({"val": "dev", "valid": "dev"}).to_numpy()
    else:
        ids = pd.Series(np.arange(len(metadata)).astype(str), index=metadata.index)
    h = pd.util.hash_pandas_object(ids + f"#{seed}", index=False).to_numpy() % 10_000 / 10_000.0
    a, b = fractions[0], fractions[0] + fractions[1]
    return np.where(h < a, "train", np.where(h < b, "dev", "test"))


def split_dataset(ds, mode="event", fractions=(0.8, 0.1, 0.1), seed=0):
    """Return {'train','dev','test'} -> filtered dataset copies.

    mode="event"   event-grouped hash split (recommended: no event leaks between sets)
    mode="dataset" the dataset's own split column (STEAD/ETHZ/INSTANCE ship one)
    """
    md = ds.metadata
    if mode == "dataset" and "split" in md.columns:
        labels = md["split"].astype(str).str.lower().replace({"val": "dev", "valid": "dev"}).to_numpy()
    else:
        labels = event_split_labels(md, fractions, seed=seed)
    return {name: ds.filter(labels == name, inplace=False) for name in ("train", "dev", "test")}


def apply_filters(ds, channels=None, earthquakes_only=False, require=None):
    mask = channel_mask(ds.metadata, channels)
    if channels and not mask.any():
        col = next(c for c in ("trace_channel", "station_channel") if c in ds.metadata.columns)
        have = sorted(ds.metadata[col].astype(str).str.upper().str[:2].unique())
        raise SystemExit(f"no traces with instrument code {' '.join(channels)}; this dataset has {' '.join(have)}")
    if earthquakes_only:
        mask &= earthquake_mask(ds.metadata)
    for col in require or []:
        if col not in ds.metadata.columns:
            raise SystemExit(f"dataset lacks required column {col}")
        mask &= ds.metadata[col].notna().to_numpy()
    if not mask.all():
        ds.filter(mask, inplace=True)
    return ds


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(np.asarray(lon2) - np.asarray(lon1)) / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def hypocentral_distance_km(meta):
    """Hypocentral distance from a metadata row/dict; NaN if coordinates are missing."""
    get = meta.get if hasattr(meta, "get") else (lambda k, d=None: meta[k] if k in meta else d)
    epi = get("path_ep_distance_km", np.nan)
    if epi is None or not np.isfinite(float(epi)):
        try:
            epi = float(haversine_km(float(get("source_latitude_deg")), float(get("source_longitude_deg")),
                                     float(get("station_latitude_deg")), float(get("station_longitude_deg"))))
        except (TypeError, ValueError):
            return np.nan
    depth = get("source_depth_km", np.nan)
    try:
        depth = float(depth)
    except (TypeError, ValueError):
        depth = np.nan
    if not np.isfinite(depth):
        depth = 10.0
    return float(np.hypot(float(epi), depth))


SNR_COLUMNS = [  # per-component SNR in dB, as named by AQ2009 (vel/counts) and INSTANCE / STEAD
    ("trace_z_snr_db_vel", "trace_n_snr_db_vel", "trace_e_snr_db_vel"),
    ("trace_Z_snr_db", "trace_N_snr_db", "trace_E_snr_db"),
    ("trace_z_snr_db_counts", "trace_n_snr_db_counts", "trace_e_snr_db_counts"),
    ("trace_snr_db",),
]


def snr_mask(metadata, min_db):
    """Keep traces whose every available component has SNR >= min_db (dead channels have NaN and are dropped)."""
    for cols in SNR_COLUMNS:
        if all(c in metadata.columns for c in cols):
            snr = metadata[list(cols)].apply(pd.to_numeric, errors="coerce")
            if cols == ("trace_snr_db",):  # STEAD stores "[z n e]" strings
                snr = metadata["trace_snr_db"].astype(str).str.strip("[]").str.split(expand=True).apply(
                    pd.to_numeric, errors="coerce")
            return (snr.min(axis=1, skipna=False) >= min_db).to_numpy(), list(cols)
    return None, []

