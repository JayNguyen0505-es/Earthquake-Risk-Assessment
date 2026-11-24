"""Station subsets that mimic a degraded network.

random      k stations drawn uniformly from those that recorded the event
one_sided   a random direction is drawn and only stations within +-90 degrees of it (event-to-station
            azimuth) are eligible, then k of them are drawn: the event is seen from one side only, as
            for offshore events or a network edge
all         every station
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .aggregate import station_sd


@dataclass
class Event:
    event_id: str
    m_true: float
    time: float
    mu: np.ndarray
    sd: np.ndarray
    azimuth: np.ndarray


def events_from_table(df):
    """Station table -> list of Event (arrays per event), ordered by time when available."""
    df = df.copy()
    df["_sd"] = station_sd(df)
    if "azimuth" not in df:
        df["azimuth"] = np.nan
    if "time" not in df:
        df["time"] = np.nan
    out = []
    for eid, g in df.groupby("event_id", sort=False):
        out.append(Event(str(eid), float(g["m_true"].iloc[0]), float(pd.to_numeric(g["time"], errors="coerce").iloc[0]),
                         g["m_pred"].to_numpy(float), g["_sd"].to_numpy(float), g["azimuth"].to_numpy(float)))
    out.sort(key=lambda e: (np.inf if not np.isfinite(e.time) else e.time, e.event_id))
    return out


def choose(n, azimuth, k, mode, rng):
    """Positions of one subset of n stations, or None if the event cannot supply it."""
    if k == "all" or mode == "all":
        return np.arange(n)
    k = int(k)
    if mode == "random":
        return rng.choice(n, k, replace=False) if n >= k else None
    if mode == "one_sided":
        if not np.isfinite(azimuth).all():
            return None
        theta = rng.uniform(0, 360)
        idx = np.flatnonzero(np.cos(np.radians(azimuth - theta)) > 0)
        return rng.choice(idx, k, replace=False) if len(idx) >= k else None
    raise ValueError(f"unknown dropout mode {mode}")


def subsets(events, ks=(3, 5, 10, "all"), modes=("random",), n_rep=1, seed=0, min_stations=None):
    """Yield (event, k, mode, rep, positions) for every event, subset size, mode and repetition.

    Events with fewer than ``min_stations`` stations (default: the smallest numeric k) are skipped for
    every k, so all k are evaluated on the same events.
    """
    rng = np.random.default_rng(seed)
    num = [int(k) for k in ks if k != "all"]
    floor = min_stations if min_stations is not None else (min(num) if num else 1)
    for ev in events:
        n = len(ev.mu)
        if n < floor:
            continue
        if "all" in ks:
            yield ev, "all", "all", 0, np.arange(n)
        for mode in modes:
            for k in num:
                for rep in range(n_rep):
                    pos = choose(n, ev.azimuth, k, mode, rng)
                    if pos is not None:
                        yield ev, k, mode, rep, pos
