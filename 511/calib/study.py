"""Compare interval methods for the event magnitude under station dropout.

Methods (alpha = 0.05 unless set):

    naive           the usual interval: inverse-variance mean +- 1.96 sqrt(1/sum w) for DL, or
                    mean +- 1.96 std/sqrt(n) for classical ML (stations independent)
    naive_conf      naive interval rescaled by ONE conformal factor (global recalibration baseline)
    const_conf      fixed half-width = conformal quantile of |m_hat - m_true| (ignores k and sigmas)
    shared_gauss    shared-error model fitted by maximum likelihood: (m - b) +- 1.96 sqrt(tau^2 + s^2/sum w)
    shared_conf     shared-error variance, conformal factor pooled over k
    shared_mondrian shared-error variance, conformal factor per k (conditional coverage per k)
    shared_aci      shared-error variance, adaptive conformal along the test sequence (online; optional)

Calibration scores are computed on calibration events subsampled with the same k / dropout modes as
the test events, so the conformal quantiles see the same mix of network sizes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from .aggregate import SharedErrorModel, fit_shared_error, intraclass_correlation, ivw, naive_event
from .conformal import MondrianQuantiles, adaptive_conformal, conformal_quantile
from .dropout import events_from_table, subsets

METHODS = ["naive", "naive_conf", "const_conf", "shared_gauss", "shared_conf", "shared_mondrian"]


def _has_sd(table):
    return "sd" in table and pd.to_numeric(table["sd"], errors="coerce").notna().any()


def subset_rows(events, has_sd, model, ks, modes, n_rep, seed):
    """One row per subset: naive and shared-error centres/variances."""
    rows = []
    for ev, k, mode, rep, pos in subsets(events, ks, modes, n_rep, seed):
        mu, sd = ev.mu[pos], ev.sd[pos]
        m_n, v_n = naive_event(mu, sd, has_sd)
        m_s, v_s = model.event(mu, sd)
        rows.append({"event_id": ev.event_id, "time": ev.time, "m_true": ev.m_true, "k": str(k), "mode": mode,
                     "rep": rep, "n_sta": len(pos), "m_naive": m_n, "v_naive": v_n, "m_shared": m_s, "v_shared": v_s,
                     "m_median": float(np.median(mu))})
    return pd.DataFrame(rows)


def run_study(cal, test, ks=(3, 5, 10, "all"), modes=("random",), n_rep=3, alpha=0.05, seed=0,
              fit_bias=True, adaptive=False, aci_gamma=0.005, min_group=50):
    """Returns (events, info): one row per (subset, method) with lo/hi, and the fitted parameters."""
    has_sd = _has_sd(cal) and _has_sd(test)
    if not has_sd:  # classical ML: equal weights everywhere
        cal, test = cal.assign(sd=np.nan), test.assign(sd=np.nan)
    model = fit_shared_error(cal, fit_bias=fit_bias)
    cal_ev, test_ev = events_from_table(cal), events_from_table(test)
    c = subset_rows(cal_ev, has_sd, model, ks, modes, n_rep, seed)
    t = subset_rows(test_ev, has_sd, model, ks, modes, n_rep, seed + 1)
    if c.empty or t.empty:
        raise ValueError("no calibration or test subsets: too few stations per event for the requested k")
    z = norm.ppf(1 - alpha / 2)
    c_naive = np.abs(c["m_naive"] - c["m_true"]) / np.sqrt(c["v_naive"])
    c_shared = np.abs(c["m_shared"] - c["m_true"]) / np.sqrt(c["v_shared"])
    q_naive = conformal_quantile(c_naive, alpha)
    q_const = conformal_quantile(np.abs(c["m_naive"] - c["m_true"]), alpha)
    q_shared = conformal_quantile(c_shared, alpha)
    mond = MondrianQuantiles(alpha, min_group).fit(c_shared, c["k"])

    out = []

    def add(name, centre, half):
        out.append(t[["event_id", "time", "m_true", "k", "mode", "rep", "n_sta"]].assign(
            method=name, m_hat=centre, lo=centre - half, hi=centre + half))

    sn, ss = np.sqrt(t["v_naive"]), np.sqrt(t["v_shared"])
    add("naive", t["m_naive"], z * sn)
    add("naive_conf", t["m_naive"], q_naive * sn)
    add("const_conf", t["m_naive"], np.full(len(t), q_const))
    add("shared_gauss", t["m_shared"], z * ss)
    add("shared_conf", t["m_shared"], q_shared * ss)
    add("shared_mondrian", t["m_shared"], mond.quantile(t["k"]) * ss)
    if adaptive:
        half = np.full(len(t), np.inf)
        for (_, _), g in t.sort_values("time").groupby(["k", "mode"], sort=False):
            score = (np.abs(g["m_shared"] - g["m_true"]) / np.sqrt(g["v_shared"])).to_numpy()
            init = c_shared[(c["k"] == g["k"].iloc[0]).to_numpy()].to_numpy()
            q, _ = adaptive_conformal(score, alpha, aci_gamma, init_scores=init)
            half[t.index.get_indexer(g.index)] = q * np.sqrt(g["v_shared"].to_numpy())
        add("shared_aci", t["m_shared"], half)
    events = pd.concat(out, ignore_index=True)
    info = {"has_station_sd": bool(has_sd), "shared_error_model": model.to_dict(), "alpha": alpha,
            "q_naive_conf": q_naive, "q_const_conf": q_const, "q_shared_conf": q_shared,
            "q_shared_mondrian": {str(k): v for k, v in mond.by_group.items()},
            "icc_calibration": intraclass_correlation(cal), "icc_test": intraclass_correlation(test),
            "n_cal_events": len(cal_ev), "n_test_events": len(test_ev),
            "point_mae_test_all": {
                "ivw": float((t.loc[t["k"] == "all", "m_naive"] - t.loc[t["k"] == "all", "m_true"]).abs().mean()),
                "median": float((t.loc[t["k"] == "all", "m_median"] - t.loc[t["k"] == "all", "m_true"]).abs().mean())}}
    return events, info


def split_by_time(table, frac=0.66):
    """Calibration = earliest ``frac`` of events, test = the rest (no event in both)."""
    ev = table.groupby("event_id")["time"].first().sort_values(kind="stable")
    cut = int(len(ev) * frac)
    cal_ids = set(ev.index[:cut])
    m = table["event_id"].isin(cal_ids)
    return table[m].copy(), table[~m].copy()


def first_n_events(table, n):
    """(first n events in time, the rest)."""
    ev = table.groupby("event_id")["time"].first().sort_values(kind="stable")
    ids = set(ev.index[:n])
    m = table["event_id"].isin(ids)
    return table[m].copy(), table[~m].copy()


__all__ = ["METHODS", "run_study", "split_by_time", "first_n_events", "ivw", "SharedErrorModel"]
