"""Tests for the calibration study (calib/) and the one-to-one matching. From the repository root:

    python -m unittest discover -s 511/tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from calib.aggregate import apply_station_terms, fit_shared_error, fit_station_terms, intraclass_correlation  # noqa: E402
from calib.conformal import adaptive_conformal, conformal_quantile  # noqa: E402
from calib.metrics import bootstrap_summary  # noqa: E402
from calib.study import run_study, split_by_time  # noqa: E402
from e2e.evaluate import match_events, one_to_one  # noqa: E402
from local_data_curve import main as local_data_curve  # noqa: E402


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
        ev, info = run_study(cal, test, ks=(2, "all"), modes=("random", "one_sided"), n_rep=1)
        self.assertFalse(info["has_station_sd"])
        self.assertAlmostEqual(info["shared_error_model"]["tau"], 0.15, delta=0.03)
        pairs = ev[(ev["k"] == "2") & (ev["method"] == "naive")]
        self.assertEqual(set(pairs["mode"]), {"random", "one_sided"})
        self.assertTrue((pairs["n_sta"] == 2).all())
        self.assertTrue(np.isfinite(pairs[["lo", "hi"]]).all().all())

    def test_station_terms_remove_injected_offset(self):
        table = synthetic_table(n_events=100, tau=0, scale=0)
        table["m_pred"] += 0.6 * (table["station"] == "s0")
        terms = fit_station_terms(table)
        self.assertAlmostEqual(terms["s0"], 0.6 * 100 / 105)
        test = table.iloc[:2].copy()
        test.loc[test.index[1], "station"] = "unseen"
        corrected = apply_station_terms(test, terms)
        self.assertAlmostEqual(corrected.iloc[0]["m_pred"] - corrected.iloc[0]["m_true"], 0.6 * 5 / 105)
        self.assertEqual(corrected.iloc[1]["m_pred"], test.iloc[1]["m_pred"])


class PhaseETests(unittest.TestCase):
    def test_bootstrap_resamples_events(self):
        events = synthetic_table(n_events=100).groupby("event_id").head(1)
        events = events.assign(method="synthetic", lo=events["m_pred"] - 0.15, hi=events["m_pred"] + 0.15)
        expected_coverage = events["m_true"].between(events["lo"], events["hi"]).mean()
        # Repeating the first event's rows must leave every event's weight unchanged.
        events = pd.concat([events, *([events.iloc[:1]] * 100)], ignore_index=True)
        ci = bootstrap_summary(events, ("method",), n_boot=500).iloc[0]
        self.assertAlmostEqual(ci["coverage"], expected_coverage)
        for metric in ("coverage", "mean_width", "interval_score"):
            self.assertLessEqual(ci[f"{metric}_lo"], ci[metric] + 1e-12)
            self.assertLessEqual(ci[metric], ci[f"{metric}_hi"] + 1e-12)

    def test_local_curve_improves_target_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target, out = root / "source.csv", root / "target.csv", root / "curve"
            synthetic_table(n_events=120, tau=0.08, seed=9).to_csv(source, index=False)
            synthetic_table(n_events=220, tau=0.28, bias=0.3, seed=11).to_csv(target, index=False)
            local_data_curve([
                "--source", str(source), "--target", str(target), "--estimator", "dl", "--out", str(out),
                "--ns", "0", "50", "999", "--reps", "2", "--ks", "3", "all", "--modes", "random", "--workers", "2",
            ])
            curve = pd.read_csv(out / "curve.csv")
            self.assertEqual(set(curve["n"]), {0, 50})
            shared = curve[(curve["method"] == "shared_conf") & (curve["k"] == "all")]
            coverage = shared.set_index("scheme")["coverage_mean"]
            self.assertGreater(coverage["target_only"], coverage["source_only"])
            self.assertEqual(set(pd.read_csv(out / "curve_raw.csv")["rep"]), {0, 1})
            self.assertTrue((out / "n_needed.csv").is_file())
            self.assertGreater((out / "curve.png").stat().st_size, 0)


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
