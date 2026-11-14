"""Tests for association and location on synthetic data. From repository root:

    python -m unittest discover -s 511/tests -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loc import synth  # noqa: E402
from loc.associate import Associator  # noqa: E402
from loc.geometry import from_local_km, to_local_km  # noqa: E402
from loc.locate import Locator  # noqa: E402
from loc.velocity import VelocityModel  # noqa: E402


class VelocityTests(unittest.TestCase):
    def test_halfspace_matches_analytic(self):
        m = VelocityModel.halfspace(6.0)
        for x, z in [(0, 10), (30, 5), (100, 20)]:
            self.assertAlmostEqual(m.travel_time(x, z, "P"), np.hypot(x, z) / 6.0, places=6)
            self.assertAlmostEqual(m.travel_time(x, z, "S"), np.hypot(x, z) / (6.0 / 1.73), places=6)

    def test_layered_direct_and_head_wave(self):
        m = VelocityModel([(0.0, 5.0), (10.0, 7.0)])
        # source at 2 km, receiver at 0 km distance: vertical ray in layer 0
        self.assertAlmostEqual(m.travel_time(0.0, 2.0, "P"), 2.0 / 5.0, places=6)
        # near: direct wave only. far: head wave (Pn-like) must be faster than the direct wave
        t_near = m.travel_time(5.0, 2.0, "P")
        self.assertAlmostEqual(t_near, np.hypot(5.0, 2.0) / 5.0, places=6)
        x = 150.0
        t_far = m.travel_time(x, 2.0, "P")
        t_direct = m._direct(x, 2.0, "P")
        self.assertLess(t_far, t_direct)
        # analytic head-wave time: x/v2 + (h_up + h_down) * sqrt(1/v1^2 - 1/v2^2)
        eta = np.sqrt(1 / 25 - 1 / 49)
        self.assertAlmostEqual(t_far, x / 7.0 + (10.0 + 8.0) * eta, places=6)

    def test_travel_time_monotonic_in_distance(self):
        m = VelocityModel()
        d = np.linspace(0, 300, 61)
        t = m.travel_time(d, 10.0, "P")
        self.assertTrue(np.all(np.diff(t) > 0))
        self.assertTrue(np.all(m.travel_time(d, 10.0, "S") > t))


class GeometryTests(unittest.TestCase):
    def test_roundtrip(self):
        lat, lon = 21.8, 103.5
        x, y = to_local_km(lat, lon, 21.5, 103.2)
        lat2, lon2 = from_local_km(x, y, 21.5, 103.2)
        self.assertAlmostEqual(lat, float(lat2), places=9)
        self.assertAlmostEqual(lon, float(lon2), places=9)
        self.assertAlmostEqual(float(y), 0.3 * 111.19, delta=0.1)


class LocateTests(unittest.TestCase):
    def setUp(self):
        self.stations = synth.random_stations(20, seed=1)
        self.model = VelocityModel()

    def test_recovers_synthetic_hypocentre(self):
        events = pd.DataFrame({"lat": [21.75], "lon": [103.45], "depth_km": [12.0], "origin_time": [1000.0]})
        picks = synth.synthetic_picks(self.stations, events, self.model, noise_p=0.05, noise_s=0.1, seed=2)
        loc = Locator(self.stations, self.model).locate(picks, bootstrap=20)
        self.assertAlmostEqual(loc.lat, 21.75, delta=0.03)      # ~3 km
        self.assertAlmostEqual(loc.lon, 103.45, delta=0.03)
        self.assertAlmostEqual(loc.depth_km, 12.0, delta=4.0)
        self.assertAlmostEqual(loc.origin_time, 1000.0, delta=0.5)
        self.assertLess(loc.rms, 0.25)
        self.assertTrue(np.isfinite(loc.depth_err_km))

    def test_l1_norm_survives_outlier_pick(self):
        events = pd.DataFrame({"lat": [21.6], "lon": [103.7], "depth_km": [8.0], "origin_time": [50.0]})
        picks = synth.synthetic_picks(self.stations, events, self.model, seed=3)
        picks.loc[0, "time"] += 5.0  # one badly wrong pick
        loc = Locator(self.stations, self.model, norm="l1").locate(picks)
        self.assertAlmostEqual(loc.lat, 21.6, delta=0.05)
        self.assertAlmostEqual(loc.lon, 103.7, delta=0.05)

    def test_wrong_velocity_model_biases_depth_not_epicentre_much(self):
        events = pd.DataFrame({"lat": [21.8], "lon": [103.3], "depth_km": [15.0], "origin_time": [0.0]})
        picks = synth.synthetic_picks(self.stations, events, self.model, seed=4)
        loc = Locator(self.stations, VelocityModel.halfspace(6.0)).locate(picks)
        self.assertAlmostEqual(loc.lat, 21.8, delta=0.08)
        self.assertAlmostEqual(loc.lon, 103.3, delta=0.08)


class AssociateTests(unittest.TestCase):
    def test_separates_events_and_ignores_false_picks(self):
        stations = synth.random_stations(20, seed=5)
        model = VelocityModel()
        events = synth.random_events(4, stations, seed=6, spacing_s=120.0)
        picks = synth.synthetic_picks(stations, events, model, false_picks=40, seed=7)
        assoc = Associator(stations, model, grid_step_km=10.0, tol_s=1.0, min_p=4)
        found, picks_out = assoc.associate(picks)
        self.assertEqual(len(found), 4)
        found = sorted(found, key=lambda e: e["origin_time"])
        for ev, (_, truth) in zip(found, events.sort_values("origin_time").iterrows()):
            self.assertAlmostEqual(ev["origin_time"], truth["origin_time"], delta=2.0)
            members = picks_out.loc[ev["pick_ids"], "event"]
            # at least 90 % of associated picks belong to the right event
            self.assertGreaterEqual((members == truth.name).mean(), 0.9)

    def test_association_then_location(self):
        stations = synth.random_stations(20, seed=8)
        model = VelocityModel()
        events = synth.random_events(2, stations, seed=9, spacing_s=200.0)
        picks = synth.synthetic_picks(stations, events, model, seed=10)
        found, picks_out = Associator(stations, model).associate(picks)
        locator = Locator(stations, model)
        for ev in found:
            loc = locator.locate(picks_out.loc[ev["pick_ids"]])
            truth = events.iloc[int(np.argmin(np.abs(events["origin_time"] - ev["origin_time"])))]
            self.assertAlmostEqual(loc.lat, truth["lat"], delta=0.05)
            self.assertAlmostEqual(loc.lon, truth["lon"], delta=0.05)


if __name__ == "__main__":
    unittest.main()
