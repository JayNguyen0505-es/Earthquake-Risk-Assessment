"""End-to-end tests for Part B with an offline fake FDSN service. From the repository root:

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

from e2e.evaluate import match_events, pick_metrics, recall_by_magnitude  # noqa: E402
from e2e.fetch import candidate_stations, select_stations  # noqa: E402
from e2e.magnitude import ml_from_amplitude  # noqa: E402
from e2e.regions import get_region, load_regions, velocity_model  # noqa: E402
from loc import synth  # noqa: E402
from loc.associate import Associator, associate_windowed  # noqa: E402
from loc.velocity import TravelTimeTable, VelocityModel  # noqa: E402


class RegionTests(unittest.TestCase):
    def test_regions_and_velocity_models(self):
        regions = load_regions()
        for name in ("central_italy", "ridgecrest", "nw_vietnam"):
            self.assertIn(name, regions)
            vm = velocity_model(get_region(name))
            t = vm.travel_time(np.array([10.0, 50.0, 150.0]), 10.0, "P")
            self.assertTrue(np.all(np.diff(t) > 0))
        # Hadley-Kanamori: a vertical ray through 5.5 km of 5.5 km/s takes 1 s
        self.assertAlmostEqual(velocity_model(get_region("ridgecrest")).travel_time(0.0, 5.5, "P"), 1.0, places=6)

    def test_iaspei_ml(self):
        # 1 mm on a Wood-Anderson drum at 100 km is M3 by definition: A = 1 mm / 2080 = 480.8 nm
        self.assertAlmostEqual(ml_from_amplitude(1e6 / 2080, 100.0), 3.0, delta=0.01)


class SelectionTests(unittest.TestCase):
    def test_farthest_point_spreads_stations(self):
        rng = np.random.default_rng(0)
        dense = pd.DataFrame({"station": [f"XX.C{i}" for i in range(40)], "lat": 42.8 + rng.normal(0, 0.02, 40),
                              "lon": 13.2 + rng.normal(0, 0.02, 40)})
        spread = pd.DataFrame({"station": [f"XX.S{i}" for i in range(10)], "lat": rng.uniform(42.4, 43.2, 10),
                               "lon": rng.uniform(12.8, 13.7, 10)})
        sel = select_stations(pd.concat([dense, spread], ignore_index=True), 12, [12.75, 42.35, 13.75, 43.25])
        self.assertEqual(len(sel), 12)
        self.assertGreaterEqual(sel["station"].str.startswith("XX.S").sum(), 9)


class AssociationTests(unittest.TestCase):
    def test_windowed_association_over_hours(self):
        stations = synth.random_stations(20, seed=11)
        model = TravelTimeTable(VelocityModel())
        events = synth.random_events(30, stations, seed=12, spacing_s=240.0)
        picks = synth.synthetic_picks(stations, events, VelocityModel(), false_picks=300, seed=13)
        assoc = Associator(stations, model, tol_s=1.0)
        found, _ = associate_windowed(assoc, picks)
        times = np.array([e["origin_time"] for e in found])
        hits = sum(np.any(np.abs(times - t) < 2.0) for t in events["origin_time"])
        self.assertGreaterEqual(hits, 28)
        self.assertLessEqual(len(found), 33)  # few spurious events despite 300 false picks
        self.assertEqual(len(set(np.round(times, 1))), len(times))  # no duplicates across windows

    def test_s_mislabelled_as_p_does_not_create_ghost_event(self):
        stations = synth.random_stations(15, seed=21)
        vm = VelocityModel()
        events = synth.random_events(3, stations, seed=22, spacing_s=300.0)
        picks = synth.synthetic_picks(stations, events, vm, s_detect=1.0, seed=23)
        picks.loc[picks["phase"] == "S", "phase"] = "P"  # STA/LTA on the vertical often does this
        found, _ = associate_windowed(Associator(stations, TravelTimeTable(vm), tol_s=1.0), picks)
        self.assertEqual(len(found), 3)


class EvaluateTests(unittest.TestCase):
    def test_matching_and_recall(self):
        ref = pd.DataFrame({"event_id": ["a", "b", "c"], "time_s": [0.0, 100.0, 200.0], "lat": [42.0, 42.1, 42.2],
                            "lon": [13.0, 13.1, 13.2], "depth_km": [10, 10, 10], "mag": [1.2, 2.2, 3.2]})
        det = pd.DataFrame({"time_s": [0.5, 100.2, 500.0], "lat": [42.01, 42.4, 42.0], "lon": [13.0, 13.1, 13.0],
                            "depth_km": [9, 9, 9]})
        m = match_events(det, ref, max_dt=3, max_km=25)
        self.assertEqual(list(m["ref"]), [0])  # event b is 33 km away, c is not detected
        tab = recall_by_magnitude(ref, m)
        self.assertEqual(int(tab["n_detected"].sum()), 1)

    def test_pick_metrics(self):
        arr = pd.DataFrame({"event_id": ["a"] * 2, "station": ["XX.A", "XX.B"], "phase": ["P", "P"],
                            "time_s": [10.0, 20.0]})
        picks = pd.DataFrame({"station": ["XX.A", "XX.B", "XX.B"], "phase": ["P", "P", "S"],
                              "time": [10.1, 25.0, 20.0]})
        m = pick_metrics(picks, arr, {"XX.A", "XX.B"}, tol=0.5)
        self.assertEqual(m["P"]["matched"], 1)
        self.assertAlmostEqual(m["P"]["resid_mean"], 0.1, places=6)


class FetchFallbackTests(unittest.TestCase):
    def test_per_event_arrivals_and_per_station_waveforms(self):
        from e2e.fake_fdsn import FakeFDSN
        from e2e.fetch import run_fetch

        region = get_region("central_italy")
        vm = velocity_model(region)
        fake = FakeFDSN(region, vm, "2020-01-01T00:00:00", "2020-01-01T01:00:00", n_events=4, seed=3,
                        reject_search_arrivals=True, bulk_nodata=True)
        with tempfile.TemporaryDirectory() as d:
            run_fetch(region, "2020-01-01T00:00:00", "2020-01-01T01:00:00", d, n_stations=6, bands=["HH"],
                      clients={"INGV": fake})
            arr = pd.read_csv(Path(d) / "arrivals.csv")
            self.assertEqual(arr["event_id"].nunique(), 4)                  # arrivals recovered per event
            self.assertEqual(len(list(Path(d).glob("waveforms/*/*.mseed"))), 6)  # per-station fallback
            # waveforms-only re-run keeps the station selection and finds nothing left to do
            run_fetch(region, "2020-01-01T00:00:00", "2020-01-01T01:00:00", d, clients={"INGV": fake},
                      only="waveforms", retry_missing=True)
            self.assertEqual(len(pd.read_csv(Path(d) / "stations.csv")), 6)


class EndToEndTests(unittest.TestCase):
    def test_fake_network_full_chain(self):
        import e2e_selftest

        with tempfile.TemporaryDirectory() as d:
            det, m = e2e_selftest.run(d, "stalta", "none", "cpu", hours=2, n_events=8, seed=0)
            e = m["events"]
            self.assertGreaterEqual(e["recall"], 0.85)
            self.assertGreaterEqual(e["precision"], 0.85)
            self.assertLess(e["epicentre_error_km"]["median"], 2.0)
            self.assertLess(abs(e["depth_error_km"]["median"]), 2.0)
            self.assertLess(abs(e["ml_minus_reference"]["median"]), 0.3)
            self.assertGreater(m["picks_vs_analyst"]["P"]["recall"], 0.9)
            run = Path(d) / "run"
            for f in ("run.json", "stations.csv", "inventory.xml", "events.csv", "arrivals.csv", "catalog.xml"):
                self.assertTrue((run / f).exists(), f)
            from obspy import read_inventory

            inv = read_inventory(str(run / "inventory.xml"))
            self.assertEqual(len(candidate_stations(inv, ["HH"], "2020-01-01", "2020-01-01T02:00:00")), 12)


if __name__ == "__main__":
    unittest.main()
