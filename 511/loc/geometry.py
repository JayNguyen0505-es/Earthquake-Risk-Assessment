"""Local coordinates and station tables."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

R_EARTH = 6371.0


def to_local_km(lat, lon, lat0, lon0):
    """Equirectangular projection around (lat0, lon0): adequate for a ~300 km network."""
    x = np.radians(np.asarray(lon, float) - lon0) * R_EARTH * np.cos(np.radians(lat0))
    y = np.radians(np.asarray(lat, float) - lat0) * R_EARTH
    return x, y


def from_local_km(x, y, lat0, lon0):
    lat = lat0 + np.degrees(np.asarray(y, float) / R_EARTH)
    lon = lon0 + np.degrees(np.asarray(x, float) / (R_EARTH * np.cos(np.radians(lat0))))
    return lat, lon


def read_stations(path):
    """Station table -> DataFrame[station, lat, lon, elev_km].

    Accepts data/stations.xlsx (Institute headers: Mã trạm / Vĩ độ / Kinh độ) or any CSV with
    station, lat, lon columns. Station codes are strings ("4001").
    """
    path = Path(path)
    df = pd.read_excel(path) if path.suffix in {".xlsx", ".xls"} else pd.read_csv(path)
    rename = {}
    for c in df.columns:
        lc = str(c).strip().lower()
        if lc in {"vĩ độ", "vi do", "lat", "latitude"}:
            rename[c] = "lat"
        elif lc in {"kinh độ", "kinh do", "lon", "longitude"}:
            rename[c] = "lon"
        elif lc in {"mã trạm", "ma tram", "station", "station_code", "code", "sta"}:
            rename[c] = "station"
        elif lc in {"elev_km", "elevation_km"}:
            rename[c] = "elev_km"
    df = df.rename(columns=rename)
    df["station"] = df["station"].astype(str).str.strip()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    if "elev_km" not in df:
        df["elev_km"] = 0.0
    return df.dropna(subset=["lat", "lon"])[["station", "lat", "lon", "elev_km"]].reset_index(drop=True)


def network_centre(stations):
    return float(stations["lat"].mean()), float(stations["lon"].mean())
