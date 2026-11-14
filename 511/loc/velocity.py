"""1-D layered velocity model with flat-earth P/S travel times.

Direct wave: two-point ray tracing on the ray parameter (vectorised bisection over distance).
Head waves: critically refracted along every interface below the source that is faster than all
layers above it. The travel time is the minimum of the two, as in HYPO71 / HYPOINVERSE.

``TravelTimeTable`` tabulates the model on a (depth, distance) grid once and interpolates
bilinearly; the locator and associator call it millions of times.

The default model is a generic crust for Northwest Vietnam and MUST be replaced by the
Institute's regional 1-D model (checklist item B5) when it is available: layer thicknesses and
velocities change locations by kilometres.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# depth-to-top (km), Vp (km/s); Vs = Vp / vp_vs. Generic crust; placeholder until B5 arrives.
DEFAULT_LAYERS = [(0.0, 5.0), (2.0, 5.8), (12.0, 6.3), (24.0, 6.9), (36.0, 8.0)]


@dataclass
class VelocityModel:
    layers: list = field(default_factory=lambda: list(DEFAULT_LAYERS))
    vp_vs: float = 1.73

    def __post_init__(self):
        self.tops = np.array([t for t, _ in self.layers], float)
        self.vp = np.array([v for _, v in self.layers], float)
        self.vs = self.vp / self.vp_vs
        self.bottoms = np.append(self.tops[1:], np.inf)

    @classmethod
    def halfspace(cls, vp=6.0, vp_vs=1.73):
        return cls([(0.0, vp)], vp_vs)

    @classmethod
    def from_csv(cls, path, vp_vs=1.73):
        """CSV with columns depth_km, vp_kms (one row per layer top)."""
        import pandas as pd

        df = pd.read_csv(path)
        return cls(list(zip(df["depth_km"].astype(float), df["vp_kms"].astype(float))), vp_vs)

    def velocities(self, phase):
        return self.vp if phase.upper() == "P" else self.vs

    def layer_index(self, depth):
        # a source exactly on an interface is treated as belonging to the layer above, so
        # travel times are continuous in depth
        return max(int(np.searchsorted(self.tops, depth, side="left") - 1), 0)

    def _segments(self, depth, phase):
        """Thickness and velocity of each layer segment between the surface and ``depth``."""
        v = self.velocities(phase)
        k = self.layer_index(depth)
        thick = (np.minimum(self.bottoms, depth) - self.tops)[: k + 1]
        v = v[: k + 1]
        keep = thick > 1e-9          # a source exactly on an interface has a zero-thickness segment
        return thick[keep], v[keep]

    def _direct(self, x, depth, phase, n_iter=60):
        """Direct-wave travel times for an array of epicentral distances (vectorised bisection)."""
        x = np.atleast_1d(np.asarray(x, float))
        thick, v = self._segments(depth, phase)
        total = thick.sum()
        if total <= 1e-9:                       # source at the surface
            return x / self.velocities(phase)[0]
        th = thick[:, None]
        vv = v[:, None]
        pmax = (1.0 / v.max()) * (1 - 1e-9)

        def xp(p):
            s = np.sqrt(np.maximum(1.0 - (p[None, :] * vv) ** 2, 1e-12))
            return np.sum(th * p[None, :] * vv / s, axis=0)

        lo = np.zeros_like(x)
        hi = np.full_like(x, pmax)
        for _ in range(n_iter):
            mid = 0.5 * (lo + hi)
            less = xp(mid) < x
            lo = np.where(less, mid, lo)
            hi = np.where(less, hi, mid)
        p = 0.5 * (lo + hi)
        s = np.sqrt(np.maximum(1.0 - (p[None, :] * vv) ** 2, 1e-12))
        t = np.sum(th / (vv * s), axis=0)
        # rays that could not reach x with p < pmax (grazing): straight line in the fastest layer
        unreachable = xp(np.full_like(x, pmax)) < x
        t = np.where(unreachable, np.hypot(x, total) / v.max(), t)
        return t

    def _head(self, x, depth, phase):
        """Minimum head-wave time over all faster interfaces below the source (inf where none)."""
        x = np.atleast_1d(np.asarray(x, float))
        v = self.velocities(phase)
        k = self.layer_index(depth)
        best = np.full_like(x, np.inf)
        for n in range(k + 1, len(v)):
            vn = v[n]
            if vn <= v[:n].max():
                continue
            t_vert, xcrit = 0.0, 0.0
            for i in range(n):
                h_up = self.bottoms[i] - self.tops[i]       # interface -> surface crosses every layer above n
                if i < k:
                    h_down = 0.0                            # source is below this layer
                elif i == k:
                    h_down = self.bottoms[i] - depth        # source -> bottom of its own layer
                else:
                    h_down = h_up
                eta = np.sqrt(1.0 / v[i] ** 2 - 1.0 / vn ** 2)
                t_vert += (h_up + h_down) * eta
                xcrit += (h_up + h_down) * (v[i] / vn) / np.sqrt(1 - (v[i] / vn) ** 2)
            t = x / vn + t_vert
            best = np.where(x >= xcrit, np.minimum(best, t), best)
        return best

    def travel_time(self, x_km, depth_km, phase="P"):
        """Travel time (s) for epicentral distance(s) x and one source depth (receiver at surface)."""
        x = np.atleast_1d(np.asarray(x_km, float))
        t = np.minimum(self._direct(x, depth_km, phase), self._head(x, depth_km, phase))
        return t if np.ndim(x_km) else float(t[0])


class TravelTimeTable:
    """Bilinear lookup of travel times on a (depth, distance) grid built from a VelocityModel."""

    def __init__(self, model=None, max_dist_km=500.0, dist_step_km=0.5, max_depth_km=60.0, depth_step_km=0.5):
        self.model = model or VelocityModel()
        self.dist = np.arange(0.0, max_dist_km + 1e-9, dist_step_km)
        self.depth = np.arange(0.0, max_depth_km + 1e-9, depth_step_km)
        self.table = {}
        for phase in ("P", "S"):
            tab = np.empty((len(self.depth), len(self.dist)))
            for i, z in enumerate(self.depth):
                tab[i] = self.model.travel_time(self.dist, z, phase)
            self.table[phase] = tab

    def __call__(self, dist_km, depth_km, phase="P"):
        tab = self.table[phase.upper()]
        d = np.clip(np.asarray(dist_km, float), self.dist[0], self.dist[-1])
        z = np.clip(np.asarray(depth_km, float), self.depth[0], self.depth[-1])
        fi = (z - self.depth[0]) / (self.depth[1] - self.depth[0])
        fj = (d - self.dist[0]) / (self.dist[1] - self.dist[0])
        i = np.clip(np.floor(fi).astype(int), 0, len(self.depth) - 2)
        j = np.clip(np.floor(fj).astype(int), 0, len(self.dist) - 2)
        wi, wj = fi - i, fj - j
        return ((1 - wi) * (1 - wj) * tab[i, j] + (1 - wi) * wj * tab[i, j + 1]
                + wi * (1 - wj) * tab[i + 1, j] + wi * wj * tab[i + 1, j + 1])

    travel_time = __call__
