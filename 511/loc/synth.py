"""Synthetic stations, events and picks for testing association and location."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .geometry import from_local_km, to_local_km
from .velocity import VelocityModel

NW_VIETNAM = (21.2, 22.4, 103.0, 104.0)  # lat min/max, lon min/max of the 20-station network


def random_stations(n=20, seed=0, bounds=NW_VIETNAM):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "station": [f"{4001 + i}" for i in range(n)],
        "lat": rng.uniform(bounds[0], bounds[1], n),
        "lon": rng.uniform(bounds[2], bounds[3], n),
        "elev_km": 0.0,
    })


def synthetic_picks(stations, events, model=None, noise_p=0.05, noise_s=0.1, p_detect=0.9,
                    s_detect=0.7, false_picks=0, seed=0):
    """events: DataFrame[lat, lon, depth_km, origin_time]. Returns picks DataFrame[station, phase, time, event]."""
    rng = np.random.default_rng(seed)
    model = model or VelocityModel()
    lat0, lon0 = float(stations["lat"].mean()), float(stations["lon"].mean())
    sx, sy = to_local_km(stations["lat"], stations["lon"], lat0, lon0)
    rows = []
    for k, ev in events.reset_index(drop=True).iterrows():
        ex, ey = to_local_km(ev["lat"], ev["lon"], lat0, lon0)
        dist = np.hypot(sx - ex, sy - ey)
        for j, sta in enumerate(stations["station"]):
            if rng.random() < p_detect:
                rows.append({"station": sta, "phase": "P",
                             "time": ev["origin_time"] + model.travel_time(dist[j], ev["depth_km"], "P")
                             + rng.normal(0, noise_p), "event": k})
            if rng.random() < s_detect:
                rows.append({"station": sta, "phase": "S",
                             "time": ev["origin_time"] + model.travel_time(dist[j], ev["depth_km"], "S")
                             + rng.normal(0, noise_s), "event": k})
    tmin = events["origin_time"].min() - 30
    tmax = events["origin_time"].max() + 120
    for _ in range(false_picks):
        rows.append({"station": str(rng.choice(stations["station"])), "phase": str(rng.choice(["P", "S"])),
                     "time": float(rng.uniform(tmin, tmax)), "event": -1})
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True)


def random_events(n, stations, seed=0, spacing_s=300.0):
    rng = np.random.default_rng(seed)
    lat0, lon0 = float(stations["lat"].mean()), float(stations["lon"].mean())
    x = rng.uniform(-80, 80, n)
    y = rng.uniform(-80, 80, n)
    lat, lon = from_local_km(x, y, lat0, lon0)
    return pd.DataFrame({"lat": lat, "lon": lon, "depth_km": rng.uniform(3, 25, n),
                         "origin_time": np.arange(n) * spacing_s + rng.uniform(0, 60, n)})
