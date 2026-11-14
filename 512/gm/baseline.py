"""Classical GMPE-form regression fitted on the same data as the ML models.

ln Y = c0 + c1 (M-6) + c2 (M-6)^2 + [c3 + c4 (M-6)] ln R + c5 R + c6 ln(Vs30/760),
R = sqrt(dist^2 + h^2)

This is the functional form of Boore & Atkinson (2008) without the nonlinear site term. The
pseudo-depth ``h`` is chosen by grid search, the remaining coefficients by least squares. It is
the "traditional regression" that the proposal and refs/3_PGA_ML.pdf compare ML models against.
"""

from __future__ import annotations

import numpy as np

H_GRID = np.arange(1.0, 15.1, 1.0)
COEF_NAMES = ["c0", "c1", "c2", "c3", "c4", "c5", "c6"]


def design(mag, dist, ln_vs30, h):
    dm = mag - 6.0
    r = np.sqrt(dist ** 2 + h ** 2)
    lnr = np.log(r)
    return np.column_stack([np.ones_like(mag), dm, dm ** 2, lnr, dm * lnr, r, ln_vs30])


class BaselineGMPE:
    def __init__(self, h_grid=H_GRID):
        self.h_grid = np.asarray(h_grid, float)
        self.h = None
        self.coef = None

    def fit(self, X, y):
        mag = X["mag"].to_numpy(float)
        dist = X["dist_km"].to_numpy(float)
        lnv = X["ln_vs30"].to_numpy(float)
        best = None
        for h in self.h_grid:
            A = design(mag, dist, lnv, h)
            coef, *_ = np.linalg.lstsq(A, y, rcond=None)
            rmse = float(np.sqrt(np.mean((A @ coef - y) ** 2)))
            if best is None or rmse < best[0]:
                best = (rmse, h, coef)
        self.rmse_, self.h, self.coef = best
        return self

    def predict(self, X):
        A = design(X["mag"].to_numpy(float), X["dist_km"].to_numpy(float), X["ln_vs30"].to_numpy(float), self.h)
        return A @ self.coef

    def get_params(self, deep=False):
        return {"h_grid": self.h_grid}

    def set_params(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        return self

    def summary(self):
        return {"h_km": float(self.h), **{n: float(c) for n, c in zip(COEF_NAMES, self.coef)}}
