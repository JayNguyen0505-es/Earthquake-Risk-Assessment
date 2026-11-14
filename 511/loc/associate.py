"""REAL-style phase associator (Zhang et al. 2019, as used in LOC-FLOW).

For every candidate source node on a coarse 3-D grid and every P pick, the implied origin time
is t_P - tt_P(node, station). Picks whose implied origin times cluster (within ``tol_s``) are
counted; S picks are tested against the same origin time. The node/origin time with the most
consistent picks is declared an event if it has >= ``min_p`` P picks from distinct stations,
its picks are removed, and the search repeats.

Compact re-implementation for the 20-station network, not the C code of REAL. Complexity is
O(nodes x P-picks) per event, vectorised with numpy; a day of picks at this network size takes
seconds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .geometry import network_centre, to_local_km
from .locate import _as_table


class Associator:
    def __init__(self, stations, model=None, grid_step_km=10.0, depths_km=(5.0, 15.0, 25.0),
                 margin_km=60.0, tol_s=1.0, min_p=4, min_total=5, max_window_s=60.0):
        self.stations = stations.set_index("station")
        self.tt = _as_table(model)
        self.tol = tol_s
        self.min_p = min_p
        self.min_total = min_total
        self.max_window = max_window_s
        self.lat0, self.lon0 = network_centre(stations)
        sx, sy = to_local_km(self.stations["lat"], self.stations["lon"], self.lat0, self.lon0)
        self.sx = pd.Series(sx, index=self.stations.index)
        self.sy = pd.Series(sy, index=self.stations.index)
        xs = np.arange(sx.min() - margin_km, sx.max() + margin_km + 1e-9, grid_step_km)
        ys = np.arange(sy.min() - margin_km, sy.max() + margin_km + 1e-9, grid_step_km)
        gx, gy, gz = np.meshgrid(xs, ys, np.asarray(depths_km, float), indexing="ij")
        self.nodes = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
        self.sta_index = {s: j for j, s in enumerate(self.stations.index)}
        dist = np.hypot(self.nodes[:, :1] - sx[None, :], self.nodes[:, 1:2] - sy[None, :])  # nodes x stations
        z = np.repeat(self.nodes[:, 2:3], len(sx), axis=1)
        self.table = {ph: self.tt(dist, z, ph) for ph in ("P", "S")}

    def _candidates(self, p_picks):
        """Best (count, node, t0) over all nodes from implied P origin times."""
        js = p_picks["station"].map(self.sta_index).to_numpy()
        t0s = p_picks["time"].to_numpy()[None, :] - self.table["P"][:, js]        # nodes x P-picks
        t0s.sort(axis=1)
        # for each pick i, number of picks within [t0_i, t0_i + 2 tol]
        best_n, best_node, best_t0 = 0, None, None
        n_nodes, n_p = t0s.shape
        for i in range(n_p):
            right = t0s[:, i:i + 1] + 2 * self.tol
            counts = np.array([np.searchsorted(t0s[k], right[k, 0], side="right") for k in range(n_nodes)]) - i
            k = int(np.argmax(counts))
            if counts[k] > best_n:
                best_n, best_node = int(counts[k]), k
                best_t0 = float(np.mean(t0s[k, i:i + counts[k]]))
        return best_n, best_node, best_t0

    def _members(self, t0, node, picks):
        """Picks consistent with origin time t0 at node; one pick per station/phase."""
        js = picks["station"].map(self.sta_index).to_numpy()
        pred = np.where(picks["phase"].to_numpy() == "P", self.table["P"][node, js], self.table["S"][node, js])
        resid = picks["time"].to_numpy() - (t0 + pred)
        ok = np.abs(resid) <= self.tol
        sel = picks[ok].copy()
        sel["resid"] = resid[ok]
        if len(sel):
            sel = sel.loc[sel.groupby(["station", "phase"])["resid"].apply(lambda r: r.abs().idxmin())]
        return sel

    def associate(self, picks, max_events=1000):
        picks = picks[picks["station"].isin(self.stations.index)].sort_values("time").reset_index(drop=True)
        picks = picks.assign(pick_id=np.arange(len(picks)))
        events = []
        remaining = picks.copy()
        while len(remaining) >= self.min_total and len(events) < max_events:
            p_picks = remaining[remaining["phase"] == "P"]
            if len(p_picks) < self.min_p:
                break
            n, node, t0 = self._candidates(p_picks)
            if n < self.min_p:
                break
            window = remaining[(remaining["time"] >= t0 - self.tol) & (remaining["time"] <= t0 + self.max_window)]
            sel = self._members(t0, node, window)
            n_p = int((sel["phase"] == "P").sum())
            if n_p < self.min_p or len(sel) < self.min_total:
                # drop the earliest P pick that triggered an unusable cluster and continue
                remaining = remaining.drop(p_picks.index[0])
                continue
            x, y, z = self.nodes[node]
            events.append({"origin_time": float(t0 + sel["resid"].mean()), "x_km": float(x), "y_km": float(y),
                           "depth_km": float(z), "n_p": n_p, "n_picks": int(len(sel)),
                           "rms": float(np.sqrt(np.mean(sel["resid"] ** 2))), "pick_ids": sel["pick_id"].tolist()})
            remaining = remaining[~remaining["pick_id"].isin(sel["pick_id"])]
        return events, picks
