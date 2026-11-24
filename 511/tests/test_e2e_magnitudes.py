"""Offline integration test for the reference-event magnitude and ablation CLIs."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from calib.io import load_table
from e2e.fake_fdsn import FakeFDSN
from e2e.fetch import run_fetch
from e2e.regions import get_region, velocity_model


class ReferenceMagnitudeTests(unittest.TestCase):
    def test_offline_ml_and_ablation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, out, summary = (root / name for name in ("run", "magnitudes", "summary"))
            start, end = "2020-01-01T00:00:00", "2020-01-01T02:00:00"
            region = get_region("central_italy")
            fake = FakeFDSN(region, velocity_model(region), start, end, n_events=8, seed=0)
            run_fetch(region, start, end, run, n_stations=12, bands=["HH"], clients={"INGV": fake})

            subprocess.run([sys.executable, str(HERE / "e2e_magnitudes.py"), "--run", str(run),
                            "--out", str(out), "--loc-source", "ref", "--p-source", "theory",
                            "--workers", "2"], check=True)
            stations = load_table(out)
            reference = pd.read_csv(run / "events.csv", dtype={"event_id": str}).set_index("event_id")
            self.assertEqual(set(stations["estimator"]), {"ml"})
            self.assertEqual(set(stations["event_id"]), set(reference.index))
            self.assertEqual(set(stations["loc_source"]), {"ref"})
            medians = stations.groupby("event_id")["m_pred"].median()
            for event_id, median in medians.items():
                self.assertAlmostEqual(median, reference.at[event_id, "mag"], delta=0.1, msg=event_id)
            config = json.loads((out / "config.json").read_text())
            self.assertEqual(config["n_events"], len(reference))
            events = pd.read_csv(out / "events_summary.csv", dtype={"event_id": str}).set_index("event_id")
            pd.testing.assert_series_equal(events["median"].sort_index(), medians, check_names=False)

            subprocess.run([sys.executable, str(HERE / "ablation_summary.py"), "--runs", f"fake={out}",
                            "--out", str(summary)], check=True)
            for name in ("ablation_events.csv", "ablation_by_bin.csv", "feature_shift.csv",
                         "ablation.md", "ablation_scatter.png"):
                self.assertGreater((summary / name).stat().st_size, 0)
            stats = pd.read_csv(summary / "ablation_events.csv").set_index("subset")
            self.assertEqual(stats.at["all", "n_events"], len(reference))
            self.assertLess(stats.at["all", "mae"], 0.1)


if __name__ == "__main__":
    unittest.main()
