"""Tests for Phase F magnitude-to-PGA propagation."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from magnitude_to_shaking import (
    DISTANCES,
    GroundMotionGrid,
    bssa14_ln_pga,
    conditional_probability,
    evaluate,
    integrated_probability,
)


class ExceedanceTests(unittest.TestCase):
    def test_bssa14_matches_openquake_contexts_and_is_monotonic(self):
        from openquake.hazardlib.contexts import RuptureContext, get_mean_stds
        from openquake.hazardlib.gsim.boore_2014 import BooreEtAl2014
        from openquake.hazardlib.imt import PGA

        magnitudes = [4.0, 5.0, 6.0]
        distances = np.array([5.0, 20.0, 80.0])
        mean, sigma = bssa14_ln_pga(np.array(magnitudes)[:, None], distances)
        self.assertTrue((np.diff(mean, axis=0) > 0).all())
        self.assertTrue((np.diff(mean, axis=1) < 0).all())
        self.assertTrue((sigma > 0).all())

        for i, magnitude in enumerate(magnitudes):
            ctx = RuptureContext([
                ("mag", magnitude), ("rake", 0.0), ("rjb", distances),
                ("vs30", np.full(distances.size, 400.0)), ("sids", np.arange(distances.size)),
            ])
            ref_mean, ref_sigma, _, _ = get_mean_stds(BooreEtAl2014(), ctx, [PGA()])
            np.testing.assert_allclose(mean[i], ref_mean[0])
            np.testing.assert_allclose(sigma[i], ref_sigma[0])

    def test_small_sigma_recovers_reference(self):
        magnitudes = np.array([4.0, 5.0, 6.0])
        grid = GroundMotionGrid(3.9, 6.1)
        reference = conditional_probability(*bssa14_ln_pga(magnitudes[:, None], DISTANCES))
        for sigma in (0.0, 1e-8):
            with self.subTest(sigma=sigma):
                estimate = integrated_probability(magnitudes, np.full(3, sigma), grid)
                np.testing.assert_allclose(estimate, reference, atol=1e-10, rtol=0)

    def test_underestimated_intervals_have_worse_brier(self):
        rng = np.random.default_rng(10)
        events = pd.DataFrame({
            "event_id": np.arange(1500),
            "m_true": rng.normal(5.5, 0.65, 1500),
            "m_hat": 5.5,
            "k": "3",
            "mode": "random",
        })
        events = events[events["m_true"] >= 3.0]
        events = pd.concat([
            events.assign(method="naive", sigma_m=0.65 / 4),
            events.assign(method="shared_conf", sigma_m=0.65),
        ], ignore_index=True)
        summary, reliability = evaluate(events, "observed", seed=21)
        scores = summary.groupby("method")["brier"].mean()
        self.assertGreater(scores["naive"], scores["shared_conf"])
        floor = summary.pivot(index="threshold", columns="method", values="brier_ref")
        np.testing.assert_array_equal(floor["naive"], floor["shared_conf"])
        counts = reliability.groupby(["method", "threshold"])["n_cases"].sum()
        np.testing.assert_array_equal(counts.to_numpy(), summary["n_cases"].to_numpy())
