"""Conformal quantiles for normalised scores |m_event - m_true| / scale.

split       one quantile from a calibration set; finite-sample guarantee P(cover) >= 1 - alpha for
            exchangeable calibration/test events
mondrian    one quantile per group (here: number of stations k), falling back to the pooled one for
            small groups; gives coverage conditional on k
adaptive    adaptive conformal inference (Gibbs & Candes 2021) along an event sequence: the working
            miscoverage level is nudged after every event, so long-run coverage holds even when the
            test distribution drifts (a new region, an evolving aftershock sequence)
"""

from __future__ import annotations

import math

import numpy as np


def conformal_quantile(scores, alpha=0.05):
    """The ceil((n+1)(1-alpha))-th smallest score; inf if the calibration set is too small."""
    s = np.sort(np.asarray(scores, float)[np.isfinite(scores)])
    n = len(s)
    if n == 0:
        return np.inf
    k = math.ceil((n + 1) * (1 - alpha))
    return float(s[k - 1]) if k <= n else np.inf


class MondrianQuantiles:
    """Per-group conformal quantiles with a pooled fallback."""

    def __init__(self, alpha=0.05, min_group=50):
        self.alpha, self.min_group = alpha, min_group
        self.pooled, self.by_group = np.inf, {}

    def fit(self, scores, groups=None):
        scores = np.asarray(scores, float)
        self.pooled = conformal_quantile(scores, self.alpha)
        self.by_group = {}
        if groups is not None:
            groups = np.asarray(groups)
            for g in np.unique(groups):
                s = scores[groups == g]
                if np.isfinite(s).sum() >= self.min_group:
                    self.by_group[g] = conformal_quantile(s, self.alpha)
        return self

    def quantile(self, groups=None, n=None):
        if groups is None:
            return np.full(n or 1, self.pooled)
        return np.array([self.by_group.get(g, self.pooled) for g in np.asarray(groups)])


def adaptive_conformal(scores, alpha=0.05, gamma=0.005, warmup=None, window=None, init_scores=None):
    """Online quantiles q_t for a score sequence (time order) and the coverage indicators.

    q_t is the (1 - alpha_t) empirical quantile of the scores seen before t (plus optional
    calibration scores from elsewhere), and alpha_{t+1} = alpha_t + gamma * (alpha - err_t).
    Returns (q, covered) arrays; q is inf until there is enough history.
    """
    scores = np.asarray(scores, float)
    hist = list(np.asarray(init_scores, float)) if init_scores is not None else []
    a_t = alpha
    q, cov = np.full(len(scores), np.inf), np.zeros(len(scores), bool)
    warmup = warmup if warmup is not None else 0
    for t, s in enumerate(scores):
        h = np.asarray(hist[-window:] if window else hist)
        if len(h) >= max(warmup, 1):
            level = min(max(1 - a_t, 0.0), 1.0)
            q[t] = np.inf if a_t <= 0 else float(np.quantile(h, level, method="higher"))
        cov[t] = s <= q[t]
        a_t = a_t + gamma * (alpha - (0.0 if cov[t] else 1.0))
        hist.append(s)
    return q, cov
