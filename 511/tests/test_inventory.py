import sys
from pathlib import Path
import tempfile
import unittest

import numpy as np
from obspy import Stream, Trace, UTCDateTime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import build_inventory, inspect_file


def trace(start, values):
    return Trace(np.array(values, dtype=np.int32), header={
        "network": "VN", "station": "TEST", "channel": "HLZ",
        "sampling_rate": 100.0, "starttime": UTCDateTime(start),
    })


class InventoryTests(unittest.TestCase):
    def test_preserves_gap_and_raw_statistics(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gap.mseed"
            Stream([trace(0, [1, 2, 3]), trace(1, [4, 5, 6])]).write(str(path), format="MSEED")
            result = inspect_file(path)
            self.assertEqual(len(result["traces"]), 2)
            self.assertEqual(result["discontinuities"][0]["kind"], "gap")
            self.assertAlmostEqual(result["discontinuities"][0]["duration_seconds"], .97)
            self.assertEqual(result["traces"][0]["mean_raw"], 2)

    def test_reports_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "overlap.mseed"
            Stream([trace(0, [1, 2, 3]), trace(.01, [4, 5, 6])]).write(str(path), format="MSEED")
            result = inspect_file(path)
            self.assertEqual(result["discontinuities"][0]["kind"], "overlap")

    def test_continues_after_corrupt_file(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "bad.mseed").write_bytes(b"not a waveform")
            Stream([trace(0, [7, 7, 7])]).write(str(directory / "good.mseed"), format="MSEED")
            report = build_inventory(directory)
            self.assertEqual(report["summary"]["error_count"], 1)
            self.assertEqual(report["summary"]["readable_file_count"], 1)
            self.assertEqual(report["summary"]["constant_trace_count"], 1)

    def test_empty_dataset_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "No .mseed files"):
                build_inventory(Path(folder))
