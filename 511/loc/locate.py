"""Single-event hypocentre location from P/S arrival times.

Origin time is eliminated analytically (for a trial hypocentre the best origin time is the
weighted mean of observed-minus-predicted travel times), so the search is over (x, y, z) only:

1. vectorised grid search over the network region and 0-40 km depth (robust, no starting point);
2. Nelder-Mead refinement from the best grid node;
3. optional bootstrap over picks for a crude uncertainty.

Misfit is weighted least squares (weight = 1/sigma^2 per pick; S picks get a larger sigma by
default). ``norm="l1"`` is more robust to a wrong pick.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .geometry import from_local_km, network_centre, to_local_km
from .velocity import TravelTimeTable, VelocityModel

PICK_COLUMNS = ["station", "phase", "time"]  # time in seconds (float); the CLI converts from UTC


@dataclass
class Location:
    lat: float
    lon: float
    depth_km: float
    origin_time: float
    rms: float
    n_p: int
    n_s: int
    gap_deg: float
    lat_err_km: float = float("nan")
    lon_err_km: float = float("nan")
    depth_err_km: float = float("nan")

    def as_dict(self):
        return self.__dict__.copy()


def _as_table(model):
    if model is None:
        return TravelTimeTable(VelocityModel())
    if isinstance(model, VelocityModel):
        return TravelTimeTable(model)
    return model


class Locator:
    def __init__(self, stations, model=None, sigma_p=0.1, sigma_s=0.2, norm="l2",
                 depth_range=(0.5, 40.0), grid_step_km=5.0, depth_step_km=5.0, margin_km=50.0):
        self.stations = stations.set_index("station")
        self.tt = _as_table(model)
        self.sigma = {"P": sigma_p, "S": sigma_s}
        self.norm = norm
        self.depth_range = depth_range
        self.grid_step = grid_step_km
        self.depth_step = depth_step_km
        self.margin = margin_km
        self.lat0, self.lon0 = network_centre(stations)
        sx, sy = to_local_km(self.stations["lat"], self.stations["lon"], self.lat0, self.lon0)
        self.sx = pd.Series(sx, index=self.stations.index)
        self.sy = pd.Series(sy, index=self.stations.index)

    # ---- forward model -------------------------------------------------------------------
    def _pick_arrays(self, picks):
        sx = self.sx.loc[picks["station"]].to_numpy()
        sy = self.sy.loc[picks["station"]].to_numpy()
        is_p = (picks["phase"].to_numpy() == "P")
        return sx, sy, is_p

    def predicted(self, x, y, z, picks):
        sx, sy, is_p = self._pick_arrays(picks)
        dist = np.hypot(sx - x, sy - y)
        return np.where(is_p, self.tt(dist, z, "P"), self.tt(dist, z, "S"))

    def _residuals(self, tt, t_obs, w):
        t0 = np.sum(w * (t_obs - tt), axis=-1, keepdims=True) / np.sum(w)
        return t_obs - tt - t0, np.squeeze(t0)

    def misfit(self, xyz, picks, t_obs, w):
        x, y, z = xyz
        if not (self.depth_range[0] <= z <= self.depth_range[1]):
            return 1e9
        r, _ = self._residuals(self.predicted(x, y, z, picks), t_obs, w)
        if self.norm == "l1":
            return float(np.sum(np.sqrt(w) * np.abs(r)))
        return float(np.sum(w * r ** 2))

    # ---- inversion -----------------------------------------------------------------------
    def _prepare(self, picks):
        picks = picks[picks["station"].isin(self.stations.index)].reset_index(drop=True)
        if len(picks) < 4:
            raise ValueError("need at least 4 picks")
        t_obs = picks["time"].to_numpy(float)
        w = np.array([1.0 / self.sigma[p] ** 2 for p in picks["phase"]])
        return picks, t_obs, w

    def grid_search(self, picks, t_obs, w):
        xs = np.arange(self.sx.min() - self.margin, self.sx.max() + self.margin + 1e-9, self.grid_step)
        ys = np.arange(self.sy.min() - self.margin, self.sy.max() + self.margin + 1e-9, self.grid_step)
        zs = np.arange(self.depth_range[0], self.depth_range[1] + 1e-9, self.depth_step)
        gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
        nodes = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
        sx, sy, is_p = self._pick_arrays(picks)
        dist = np.hypot(sx[None, :] - nodes[:, :1], sy[None, :] - nodes[:, 1:2])   # nodes x picks
        z = np.repeat(nodes[:, 2:3], len(picks), axis=1)
        tt = np.where(is_p[None, :], self.tt(dist, z, "P"), self.tt(dist, z, "S"))
        r, _ = self._residuals(tt, t_obs[None, :], w[None, :])
        f = np.sum(np.sqrt(w) * np.abs(r), axis=1) if self.norm == "l1" else np.sum(w * r ** 2, axis=1)
        return nodes[int(np.argmin(f))]

    def locate(self, picks, bootstrap=0, seed=0):
        picks, t_obs, w = self._prepare(picks)
        x0 = self.grid_search(picks, t_obs, w)
        res = minimize(self.misfit, x0, args=(picks, t_obs, w), method="Nelder-Mead",
                       options={"xatol": 0.05, "fatol": 1e-6, "maxiter": 2000})
        x, y, z = res.x
        z = float(np.clip(z, *self.depth_range))
        r, t0 = self._residuals(self.predicted(x, y, z, picks), t_obs, w)
        lat, lon = from_local_km(x, y, self.lat0, self.lon0)
        loc = Location(float(lat), float(lon), z, float(np.ravel(t0)[0]), float(np.sqrt(np.mean(r ** 2))),
                       int((picks["phase"] == "P").sum()), int((picks["phase"] == "S").sum()),
                       self.azimuthal_gap(x, y, picks))
        if bootstrap:
            rng = np.random.default_rng(seed)
            xyz = []
            for _ in range(bootstrap):
                idx = rng.integers(0, len(picks), len(picks))
                sub = picks.iloc[idx].reset_index(drop=True)
                if sub["station"].nunique() < 3:
                    continue
                rb = minimize(self.misfit, res.x, args=(sub, t_obs[idx], w[idx]), method="Nelder-Mead",
                              options={"xatol": 0.1, "fatol": 1e-5, "maxiter": 500})
                xyz.append(rb.x)
            if len(xyz) > 2:
                sd = np.std(np.array(xyz), axis=0)
                loc.lon_err_km, loc.lat_err_km, loc.depth_err_km = map(float, sd)
        return loc

    def azimuthal_gap(self, x, y, picks):
        stas = picks["station"].unique()
        az = np.sort(np.degrees(np.arctan2(self.sx.loc[stas].to_numpy() - x, self.sy.loc[stas].to_numpy() - y)) % 360)
        if len(az) < 2:
            return 360.0
        return float(np.diff(np.append(az, az[0] + 360)).max())
