"""Synthetic flatfile with known truth, for tests and smoke runs before real data arrives.

The truth is a BA08-shaped attenuation with lognormal between-event (tau) and within-event (phi)
scatter. Coefficients are tuned so that M6 at 10 km on rock gives roughly 0.3 g, which is the
right order of magnitude; the point is only to exercise the pipeline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .flatfile import COLUMNS, haversine_km

TRUTH = {
    #            c0    c1    c2     c3    c4     c5      c6    h   tau   phi
    "pga_g":   (2.00, 1.20, -0.10, -1.30, 0.10, -0.004, -0.50, 6.0, 0.35, 0.55),
    "pgv_cms": (6.40, 1.50, -0.10, -1.20, 0.08, -0.003, -0.70, 6.0, 0.35, 0.55),
    "sa_0.3_g": (2.60, 1.10, -0.12, -1.25, 0.12, -0.004, -0.60, 6.0, 0.38, 0.60),
    "sa_1.0_g": (1.20, 1.60, -0.08, -1.10, 0.12, -0.002, -0.80, 6.0, 0.40, 0.62),
    "sa_3.0_g": (-0.60, 1.90, -0.05, -1.00, 0.10, -0.001, -0.80, 6.0, 0.42, 0.65),
}


def truth_ln(target, mag, dist, vs30):
    c0, c1, c2, c3, c4, c5, c6, h, _, _ = TRUTH[target]
    dm = mag - 6.0
    r = np.sqrt(dist ** 2 + h ** 2)
    return c0 + c1 * dm + c2 * dm ** 2 + (c3 + c4 * dm) * np.log(r) + c5 * r + c6 * np.log(vs30 / 760.0)


def make_flatfile(n_events=300, seed=0, center=(21.5, 103.5)):
    rng = np.random.default_rng(seed)
    rows = []
    for e in range(n_events):
        mag = rng.uniform(4.0, 7.5)
        depth = rng.uniform(3.0, 25.0)
        ev_lat = center[0] + rng.uniform(-1.5, 1.5)
        ev_lon = center[1] + rng.uniform(-1.5, 1.5)
        mech = rng.choice(["SS", "NM", "RV"], p=[0.5, 0.2, 0.3])
        n_sta = int(rng.integers(8, 40))
        event_terms = {t: rng.normal(0, TRUTH[t][8]) for t in TRUTH}
        for s in range(n_sta):
            repi = float(np.exp(rng.uniform(np.log(2.0), np.log(300.0))))
            az = rng.uniform(0, 2 * np.pi)
            st_lat = ev_lat + (repi / 111.0) * np.cos(az)
            st_lon = ev_lon + (repi / (111.0 * np.cos(np.radians(ev_lat)))) * np.sin(az)
            repi = float(haversine_km(ev_lat, ev_lon, st_lat, st_lon))
            rhypo = float(np.hypot(repi, depth))
            vs30 = float(np.exp(rng.normal(np.log(400.0), 0.4)))
            row = {
                "event_id": f"EV{e:04d}", "station_id": f"SY.S{s:03d}", "mag": mag, "depth_km": depth,
                "ev_lat": ev_lat, "ev_lon": ev_lon, "st_lat": st_lat, "st_lon": st_lon,
                "rhypo_km": rhypo, "repi_km": repi, "rjb_km": repi, "rrup_km": rhypo,
                "vs30_ms": vs30, "mech": mech, "source": "synthetic",
            }
            for t in TRUTH:
                ln_y = truth_ln(t, mag, rhypo, vs30) + event_terms[t] + rng.normal(0, TRUTH[t][9])
                row[t] = float(np.exp(ln_y))
            rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)
