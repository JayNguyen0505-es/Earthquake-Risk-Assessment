"""Event magnitude from station estimates, with and without a shared (event-level) error term.

Model for station i of event e (r = m_pred - m_true):

    r_ei = b + eta_e + eps_ei,   eta_e ~ N(0, tau^2),   eps_ei ~ N(0, s^2 * sd_ei^2)

* b      global offset (regional bias of the estimator; 0 in-domain)
* eta_e  error shared by every station of the event: source effects, common path, a wrong
         catalogue label. Independent-station aggregation assumes tau = 0.
* eps_ei station-specific error. sd_ei is the estimator's own standard deviation (the DL model's
         predicted sigma); classical ML has no per-station sigma, so sd = 1 and s plays the role of phi.

Under this model the generalised-least-squares event estimate is still the inverse-variance mean, but
its variance is  tau^2 + s^2 / sum(1/sd_i^2) , which stops shrinking once stations are added. The
residual vector of one event is Gaussian with covariance tau^2 11' + D; its log-likelihood has a
closed form (Sherman-Morrison), so the fit only needs per-event sums.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

LOG2PI = float(np.log(2 * np.pi))


def fit_station_terms(cal_table, shrink=5.0):
    """Estimate station residual offsets with shrinkage toward zero."""
    residual = cal_table["m_pred"] - cal_table["m_true"]
    stats = residual.groupby(cal_table["station"]).agg(["sum", "count"])
    stats = stats[stats["count"] > 0]
    return (stats["sum"] / (stats["count"] + shrink)).to_dict()


def apply_station_terms(table, terms):
    """Subtract fitted offsets, leaving unseen stations uncorrected."""
    return table.assign(m_pred=table["m_pred"] - table["station"].map(terms).fillna(0.0))


def station_sd(df):
    """Per-row sd; rows without one (classical ML) get 1.0, i.e. equal weights."""
    sd = pd.to_numeric(df["sd"], errors="coerce") if "sd" in df else pd.Series(np.nan, index=df.index)
    return sd.fillna(1.0).clip(lower=1e-3).to_numpy(float)


def ivw(mu, sd):
    """Inverse-variance mean and its naive variance (stations independent)."""
    w = 1.0 / np.square(sd)
    return float(np.sum(w * mu) / np.sum(w)), float(1.0 / np.sum(w))


def naive_event(mu, sd, has_sd):
    """Interval centre and variance as usually reported.

    With per-station sigmas (DL): inverse-variance mean, variance 1/sum(w).
    Without (classical ML): mean of station magnitudes, variance std^2/n (NaN for one station).
    """
    if has_sd:
        return ivw(mu, sd)
    n = len(mu)
    var = float(np.var(mu, ddof=1) / n) if n > 1 else np.nan
    return float(np.mean(mu)), var


@dataclass
class SharedErrorModel:
    tau: float = 0.0     # sd of the shared event error
    scale: float = 1.0   # multiplies the per-station sd (phi when sd == 1)
    bias: float = 0.0    # mean of the residual m_pred - m_true

    def event(self, mu, sd):
        """(event estimate with the bias removed, variance of that estimate)."""
        m, v = ivw(mu, sd)
        return m - self.bias, self.tau ** 2 + self.scale ** 2 * v

    def to_dict(self):
        return {"tau": self.tau, "scale": self.scale, "bias": self.bias}


def _event_sums(df):
    """Per-event sums used by the likelihood: n, A=sum 1/sd^2, B=sum r/sd^2, C=sum r^2/sd^2, L=sum log sd^2."""
    r = (df["m_pred"] - df["m_true"]).to_numpy(float)
    v = np.square(station_sd(df))
    t = pd.DataFrame({"e": df["event_id"].to_numpy(), "n": 1.0, "A": 1 / v, "B": r / v, "C": r * r / v, "L": np.log(v)})
    s = t.groupby("e", sort=False).sum()
    return s["n"].to_numpy(), s["A"].to_numpy(), s["B"].to_numpy(), s["C"].to_numpy(), s["L"].to_numpy()


def shared_error_nll(params, sums, fit_bias=True):
    """Mean negative log-likelihood per station of the random-effects model (params in log space)."""
    n, A0, B0, C0, L0 = sums
    log_tau, log_s = params[0], params[1]
    b = params[2] if fit_bias else 0.0
    tau2, s2 = np.exp(2 * log_tau), np.exp(2 * log_s)
    B = B0 - b * A0
    C = C0 - 2 * b * B0 + b * b * A0
    A, B, C, L = A0 / s2, B / s2, C / s2, L0 + n * np.log(s2)
    quad = C - tau2 * B * B / (1 + tau2 * A)
    logdet = L + np.log1p(tau2 * A)
    return float(0.5 * np.sum(quad + logdet + n * LOG2PI) / np.sum(n))


def fit_shared_error(df, fit_bias=True, fit_scale=True):
    """Maximum-likelihood tau, scale and bias from a calibration station table."""
    from scipy.optimize import minimize

    sums = _event_sums(df)
    n, A0, B0, _, _ = sums
    b0 = float(np.sum(B0) / np.sum(A0)) if fit_bias else 0.0
    # method-of-moments start: within-event spread -> scale, spread of event means -> tau
    z = (df["m_pred"] - df["m_true"]).to_numpy(float) / station_sd(df)
    g = pd.Series(z).groupby(df["event_id"].to_numpy())
    within = float(np.nanmean(g.var(ddof=1))) if (g.size() > 1).any() else 1.0
    s0 = np.sqrt(max(within, 1e-6)) if fit_scale else 1.0
    r = pd.Series((df["m_pred"] - df["m_true"]).to_numpy(float)).groupby(df["event_id"].to_numpy())
    mean_sd2 = float(np.mean(np.square(station_sd(df))))
    tau0 = np.sqrt(max(float(r.mean().var(ddof=1)) - s0 ** 2 * mean_sd2 / float(np.mean(n)), 1e-4)) \
        if len(n) > 1 else 0.1
    x0 = [np.log(tau0), np.log(s0)] + ([b0] if fit_bias else [])
    bounds = [(np.log(1e-4), np.log(5.0)), (np.log(1e-3), np.log(100.0))] + ([(-5.0, 5.0)] if fit_bias else [])
    if not fit_scale:
        bounds[1] = (0.0, 0.0)
        x0[1] = 0.0

    res = minimize(lambda x: shared_error_nll(x, sums, fit_bias), np.array(x0), method="L-BFGS-B", bounds=bounds)
    x = res.x
    return SharedErrorModel(tau=float(np.exp(x[0])), scale=float(np.exp(x[1])) if fit_scale else 1.0,
                            bias=float(x[2]) if fit_bias else 0.0)


def intraclass_correlation(df):
    """Share of residual variance that is common to all stations of an event (one-way ANOVA estimate)."""
    r = df.assign(r=df["m_pred"] - df["m_true"]).groupby("event_id")["r"]
    n = r.size()
    n = n[n > 1]
    if n.empty:
        return np.nan
    g = df.assign(r=df["m_pred"] - df["m_true"])
    g = g[g["event_id"].isin(n.index)].groupby("event_id")["r"]
    within = float((g.var(ddof=1) * (g.size() - 1)).sum() / (g.size() - 1).sum())
    n0 = float((n.sum() - (n ** 2).sum() / n.sum()) / (len(n) - 1)) if len(n) > 1 else float(n.mean())
    between_ms = float((g.size() * (g.mean() - g.mean().mean()) ** 2).sum() / max(len(n) - 1, 1))
    tau2 = max((between_ms - within) / n0, 0.0)
    return tau2 / (tau2 + within) if tau2 + within > 0 else np.nan
