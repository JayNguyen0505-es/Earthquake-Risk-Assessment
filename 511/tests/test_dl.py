"""Tests for Part A (picker benchmark, fine-tuning) and Part C (magnitude model) on a synthetic
SeisBench dataset. Needs seisbench + torch (511/requirements.txt). From the repository root:

    python -m unittest discover -s 511/tests -v
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

HAVE_DL = all(importlib.util.find_spec(m) for m in ("seisbench", "torch"))


class STALTATests(unittest.TestCase):
    def test_picks_synthetic_arrivals(self):
        from dl.stalta import STALTAPicker
        from dl.synth import synthetic_trace

        rng = np.random.default_rng(0)
        hits_p, hits_s = 0, 0
        for k in range(10):
            wf, p_i, s_i = synthetic_trace(3.0, 30.0, 10.0, p_at_s=20.0, rng=rng)
            picks = STALTAPicker().pick_arrays(wf[0], wf[1], wf[2], 100.0)
            hits_p += any(ph == "P" and abs(s - p_i) <= 50 for ph, s, _ in picks)
            hits_s += any(ph == "S" and abs(s - s_i) <= 50 for ph, s, _ in picks)
        self.assertGreaterEqual(hits_p, 9)
        self.assertGreaterEqual(hits_s, 7)

    def test_short_trace_returns_nothing(self):
        from dl.stalta import STALTAPicker

        self.assertEqual(STALTAPicker().pick_arrays(np.zeros(100), None, None, 100.0), [])


@unittest.skipUnless(HAVE_DL, "seisbench/torch not installed")
class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dl.synth import write_dataset

        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = write_dataset(Path(cls.tmp.name) / "ds", n_events=40, stations_per_event=6, noise_traces=5, seed=3)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_event_split_keeps_events_together(self):
        from dl.data import load_dataset, split_dataset

        ds = load_dataset(self.path, dimension_order="NCW")
        sp = split_dataset(ds, mode="event")
        ids = {k: set(v.metadata["source_id"].dropna()) for k, v in sp.items()}
        self.assertFalse(ids["train"] & ids["test"])
        self.assertFalse(ids["train"] & ids["dev"])
        self.assertEqual(sum(len(v) for v in sp.values()), len(ds))

    def test_resampling_moves_arrival_samples(self):
        from dl.data import load_dataset

        a = load_dataset(self.path, sampling_rate=100.0, dimension_order="NCW").get_sample(0)
        b = load_dataset(self.path, sampling_rate=50.0, dimension_order="NCW").get_sample(0)
        self.assertEqual(a[0].shape[-1], 2 * b[0].shape[-1])
        self.assertAlmostEqual(a[1]["trace_p_arrival_sample"] / 2, b[1]["trace_p_arrival_sample"], delta=1)

    def test_evaluate_picker_stalta(self):
        import evaluate_picker

        res, summary = evaluate_picker.evaluate(self.path, "stalta", "none", n=0, split="all")
        self.assertEqual(set(res["phase"]), {"P", "S"})
        self.assertGreater(summary["P"]["recall"], 0.4)
        self.assertLess(abs(summary["P"]["resid_mean_s"]), 0.3)
        # noise traces produce no labelled arrival
        self.assertEqual(summary["P"]["n_labelled"], 240)

    def test_finetune_saves_loadable_weights(self):
        import finetune_picker
        from dl.pickers import load_picker

        with tempfile.TemporaryDirectory() as d:
            finetune_picker.main(["--dataset", str(self.path), "--weights", "none", "--epochs", "1",
                                  "--batch-size", "16", "--workers", "0", "--device", "cpu", "--out", d])
            info = json.loads((Path(d) / "training.json").read_text())
            self.assertEqual(len(info["history"]), 1)
            model = load_picker("phasenet", str(Path(d) / "best"))
            self.assertEqual(model.in_samples, 3001)

    def test_magnitude_training_and_predictor(self):
        import train_magnitude
        from dl.magnet import MagnitudePredictor

        with tempfile.TemporaryDirectory() as d:
            train_magnitude.main(["--dataset", str(self.path), "--epochs", "2", "--batch-size", "32",
                                  "--workers", "0", "--device", "cpu", "--width", "8", "--lstm", "8", "--out", d])
            m = json.loads((Path(d) / "metrics.json").read_text())
            self.assertIn("station_dl", m)
            self.assertIn("event_richter_baseline", m)
            # the Richter-type baseline recovers the synthetic attenuation law almost exactly
            self.assertLess(m["station_richter_baseline"]["rmse"], 0.2)
            pred = MagnitudePredictor(Path(d) / "model.pt")
            self.assertEqual(pred.response_output, "VEL")
            mu, lv = pred.predict([np.random.default_rng(0).standard_normal((3, 3000)) * 1e-6] * 2, [20.0, 80.0])
            self.assertEqual(mu.shape, (2,))
            self.assertTrue(np.all(np.isfinite(mu)) and np.all(np.isfinite(lv)))


if __name__ == "__main__":
    unittest.main()
