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
                 margin_km=60.0, tol_s=1.0, min_p=4, min_total=5, max_window_s=60.0, shadow_factor=2.0):
        self.stations = stations.set_index("station")
        self.tt = _as_table(model)
        self.tol = tol_s
        self.min_p = min_p
        self.min_total = min_total
        self.max_window = max_window_s
        # after an event is declared, picks of any label within shadow_factor * tol of its predicted
        # S time (or duplicate P picks) are consumed: an S arrival mislabelled as P must not seed a
        # second, ghost event a few seconds later
        self.shadow_tol = shadow_factor * tol_s
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

    def _candidates(self, p_picks, top=40):
        """Best (count, node, t0) per node from implied P origin times, for the ``top`` nodes (vectorised)."""
        js = p_picks["station"].map(self.sta_index).to_numpy()
        t = p_picks["time"].to_numpy(float)
        base = t.min()
        t0s = (t - base)[None, :] - self.table["P"][:, js]        # nodes x P-picks, relative seconds
        t0s.sort(axis=1)
        n_nodes, n_p = t0s.shape
        # count, for every node k and pick i, the implied origin times inside [t0s[k,i], t0s[k,i] + 2 tol]
        span = float(np.ptp(t0s)) + 4 * self.tol + 1.0
        offs = (np.arange(n_nodes) * span)[:, None]
        flat = (t0s + offs).ravel()
        right = np.searchsorted(flat, (t0s + offs + 2 * self.tol).ravel(), side="right").reshape(n_nodes, n_p)
        counts = right - (np.arange(n_nodes)[:, None] * n_p + np.arange(n_p)[None, :])
        best_i = counts.argmax(axis=1)
        best_n = counts[np.arange(n_nodes), best_i]
        order = np.argsort(-best_n, kind="stable")[:top]
        return [(int(best_n[k]), int(k), float(base + np.mean(t0s[k, best_i[k]:best_i[k] + best_n[k]])))
                for k in order if best_n[k] >= self.min_p]

    def _members(self, t0, node, picks):
        """Picks consistent with origin time t0 at node; one pick per station/phase."""
        js = picks["station"].map(self.sta_index).to_numpy()
        pred = np.where(picks["phase"].to_numpy() == "P", self.table["P"][node, js], self.table["S"][node, js])
        resid = picks["time"].to_numpy() - (t0 + pred)
        ok = np.abs(resid) <= self.tol
        sel = picks[ok].assign(resid=resid[ok], _abs=np.abs(resid[ok]))
        return sel.sort_values("_abs").drop_duplicates(["station", "phase"]).drop(columns="_abs")

    def _s_support(self, t0, node, picks):
        """Stations with a pick of any label at this node's predicted S time (S picks or S mislabelled as P)."""
        js = picks["station"].map(self.sta_index).to_numpy()
        near = np.abs(picks["time"].to_numpy() - (t0 + self.table["S"][node, js])) <= self.tol
        return int(picks.loc[near, "station"].nunique())

    def associate(self, picks, max_events=1000):
        picks = picks[picks["station"].isin(self.stations.index)].sort_values("time").reset_index(drop=True)
        picks = picks.assign(pick_id=np.arange(len(picks)))
        events = []
        remaining = picks.copy()
        while len(remaining) >= self.min_total and len(events) < max_events:
            p_picks = remaining[remaining["phase"] == "P"]
            if len(p_picks) < self.min_p:
                break
            # P-only counting proposes nodes; the full P+S fit chooses among them (an event at the edge
            # of the network trades location against origin time when only P is used)
            best = None
            for n, node, t0 in self._candidates(p_picks):
                window = remaining[(remaining["time"] >= t0 - self.tol) & (remaining["time"] <= t0 + self.max_window)]
                sel = self._members(t0, node, window)
                n_p = int((sel["phase"] == "P").sum())
                if n_p < self.min_p:
                    continue
                score = (n_p + self._s_support(t0, node, window), len(sel), -float(np.sqrt(np.mean(sel["resid"] ** 2))))
                if best is None or score > best[0]:
                    best = (score, node, t0, sel)
            if best is None or len(best[3]) < self.min_total:
                # drop the earliest P pick that could not seed a usable event and continue
                remaining = remaining.drop(p_picks.index[0])
                continue
            _, node, t0, sel = best
            x, y, z = self.nodes[node]
            n_p = int((sel["phase"] == "P").sum())
            t_origin = float(t0 + sel["resid"].mean())
            events.append({"origin_time": t_origin, "x_km": float(x), "y_km": float(y),
                           "depth_km": float(z), "n_p": n_p, "n_picks": int(len(sel)),
                           "rms": float(np.sqrt(np.mean(sel["resid"] ** 2))), "pick_ids": sel["pick_id"].tolist()})
            remaining = remaining[~remaining["pick_id"].isin(sel["pick_id"])]
            shadow = self._shadow(t_origin, node, remaining)["pick_id"]
            events[-1]["shadow_ids"] = shadow.tolist()
            remaining = remaining[~remaining["pick_id"].isin(shadow)]
        return events, picks

    def _shadow(self, t0, node, picks):
        """Unassociated picks that coincide with this event's predicted P or S arrivals."""
        if picks.empty:
            return picks
        js = picks["station"].map(self.sta_index).to_numpy()
        tp = t0 + self.table["P"][node, js]
        ts = t0 + self.table["S"][node, js]
        t = picks["time"].to_numpy()
        near = (np.abs(t - ts) <= self.shadow_tol) | (np.abs(t - tp) <= self.tol)
        return picks[near]


def associate_windowed(associator, picks, window_s=240.0, step_s=180.0, max_events_per_window=200):
    """Run the associator on overlapping time windows so a day of picks stays tractable.

    Each event is kept only by the window whose core [start, start + step) contains its origin
    time, so events in the overlap are not duplicated. Returns (events, picks) like ``associate``;
    event ``pick_ids`` index the returned picks frame.
    """
    picks = picks[picks["station"].isin(associator.stations.index)].sort_values("time").reset_index(drop=True)
    picks = picks.assign(pick_id=np.arange(len(picks)))
    if picks.empty:
        return [], picks
    events, used = [], set()
    t_first, t_last = float(picks["time"].min()), float(picks["time"].max())
    start = t_first - (window_s - step_s)
    while start <= t_last:
        win = picks[(picks["time"] >= start) & (picks["time"] < start + window_s) & ~picks["pick_id"].isin(used)]
        if (win["phase"] == "P").sum() >= associator.min_p:
            found, local = associator.associate(win.drop(columns=["pick_id"]).assign(_gid=win["pick_id"].to_numpy()),
                                                max_events=max_events_per_window)
            for ev in found:
                if start <= ev["origin_time"] < start + step_s:
                    gids = local.loc[ev["pick_ids"], "_gid"].astype(int).tolist()
                    used.update(gids)
                    # picks consumed as this event's S shadow must not seed events in later windows
                    used.update(local.loc[ev.get("shadow_ids", []), "_gid"].astype(int).tolist())
                    events.append({**ev, "pick_ids": gids})
        start += step_s
    events.sort(key=lambda e: e["origin_time"])
    return events, picks
