"""Tests for the calibration study (calib/) and the one-to-one matching. From the repository root:

    python -m unittest discover -s 511/tests -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from calib.aggregate import fit_shared_error, intraclass_correlation  # noqa: E402
from calib.conformal import adaptive_conformal, conformal_quantile  # noqa: E402
from calib.study import run_study, split_by_time  # noqa: E402
from e2e.evaluate import match_events, one_to_one  # noqa: E402


def synthetic_table(n_events=600, tau=0.2, sd=0.15, scale=1.0, bias=0.0, seed=0):
    """Station magnitudes with a shared event error tau and station error scale*sd."""
    rng = np.random.default_rng(seed)
    rows = []
    for e in range(n_events):
        m = rng.uniform(0.5, 3.5)
        n = rng.integers(3, 25)
        eta = rng.normal(0, tau)
        az = rng.uniform(0, 360, n)
        for i in range(n):
            rows.append({"event_id": f"e{e}", "station": f"s{i}", "m_true": m, "time": float(e), "azimuth": az[i],
                         "sd": sd, "m_pred": m + bias + eta + rng.normal(0, scale * sd), "estimator": "dl"})
    return pd.DataFrame(rows)


class SharedErrorTests(unittest.TestCase):
    def test_fit_recovers_parameters(self):
        t = synthetic_table(tau=0.2, sd=0.15, scale=0.5, bias=0.1)
        m = fit_shared_error(t)
        self.assertAlmostEqual(m.tau, 0.2, delta=0.02)
        self.assertAlmostEqual(m.scale, 0.5, delta=0.03)
        self.assertAlmostEqual(m.bias, 0.1, delta=0.03)
        self.assertGreater(intraclass_correlation(t), 0.6)

    def test_naive_undercovers_and_shared_recovers(self):
        cal, test = split_by_time(synthetic_table(tau=0.2, sd=0.15), 0.5)
        ev, info = run_study(cal, test, ks=(3, 10, "all"), modes=("random", "one_sided"), n_rep=1)
        cov = ev.assign(c=(ev["m_true"] >= ev["lo"]) & (ev["m_true"] <= ev["hi"])).groupby("method")["c"].mean()
        self.assertLess(cov["naive"], 0.8)
        for m in ("shared_gauss", "shared_conf", "shared_mondrian"):
            self.assertGreater(cov[m], 0.92, m)
        self.assertIn("one_sided", set(ev["mode"]))

    def test_classical_ml_without_sd(self):
        t = synthetic_table(tau=0.15, sd=0.2).assign(sd=np.nan, estimator="ml")
        cal, test = split_by_time(t, 0.5)
        ev, info = run_study(cal, test, ks=(3, "all"), n_rep=1)
        self.assertFalse(info["has_station_sd"])
        self.assertAlmostEqual(info["shared_error_model"]["tau"], 0.15, delta=0.03)


class ConformalTests(unittest.TestCase):
    def test_quantile_and_small_sample(self):
        self.assertEqual(conformal_quantile(np.arange(1, 20), 0.05), 19)
        self.assertEqual(conformal_quantile([1.0, 2.0], 0.05), np.inf)

    def test_adaptive_tracks_level(self):
        s = np.abs(np.random.default_rng(1).normal(size=4000))
        _, cov = adaptive_conformal(s, 0.1, 0.01, init_scores=s[:50])
        self.assertAlmostEqual(cov[200:].mean(), 0.9, delta=0.02)


class MatchingTests(unittest.TestCase):
    def test_one_to_one_maximises_pairs(self):
        # greedy on cost would take (0,0) first and leave detection 1 unmatched
        sel = one_to_one([0, 0, 1], [0, 1, 0], [0.1, 0.5, 0.2])
        self.assertEqual(len(sel), 2)
        self.assertEqual(set(sel), {1, 2})

    def test_match_events_two_pairs(self):
        det = pd.DataFrame({"time_s": [10.0, 11.0], "lat": [42.5, 42.5], "lon": [13.0, 13.0]})
        ref = pd.DataFrame({"time_s": [10.4, 13.5], "lat": [42.5, 42.5], "lon": [13.0, 13.0]})
        m = match_events(det, ref, max_dt=3.0, max_km=25.0)
        self.assertEqual(len(m), 2)


if __name__ == "__main__":
    unittest.main()
