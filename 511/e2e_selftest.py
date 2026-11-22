"""Offline self-test of the whole 5.1.1 chain (no internet, ~1 minute on CPU).

    python 511/e2e_selftest.py
    python 511/e2e_selftest.py --picker phasenet --weights instance --device cuda   # also exercises the DL picker

A fake FDSN service (e2e/fake_fdsn.py) produces 14 stations, 8 earthquakes with exact arrivals
and amplitudes consistent with the IASPEI ML formula. The real download code writes the run
directory and the real pipeline processes it. Expected with the STA/LTA picker: all events
detected, epicentre errors of ~1 km, |ML - truth| of a few tenths. Run this first on a new machine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dl.pickers import MODEL_NAMES, load_picker  # noqa: E402
from e2e.fake_fdsn import FakeFDSN  # noqa: E402
from e2e.fetch import run_fetch  # noqa: E402
from e2e.pipeline import run_pipeline, summarize  # noqa: E402
from e2e.regions import get_region, velocity_model  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def run(out, picker_name="stalta", weights="none", device="cpu", hours=2, n_events=8, seed=0):
    region = get_region("central_italy")
    vm = velocity_model(region)
    start, end = "2020-01-01T00:00:00", f"2020-01-01T{hours:02d}:00:00"
    fake = FakeFDSN(region, vm, start, end, n_events=n_events, seed=seed)
    run_dir = Path(out) / "run"
    run_fetch(region, start, end, run_dir, n_stations=12, bands=["HH"], clients={"INGV": fake})
    picker = load_picker(picker_name, weights, device)
    det, metrics = run_pipeline(run_dir, Path(out) / "result", region, vm, picker, assoc_tol=1.5, min_p=4)
    print(summarize(metrics))
    return det, metrics


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--picker", default="stalta", choices=MODEL_NAMES)
    p.add_argument("--weights", default="none")
    p.add_argument("--device", default="cpu")
    p.add_argument("--out", default=str(ROOT / "511" / "outputs" / "e2e_selftest"))
    a = p.parse_args(argv)
    _, m = run(a.out, a.picker, a.weights, a.device)
    e = m.get("events", {})
    ok = e.get("recall", 0) >= 0.75 and e.get("epicentre_error_km", {}).get("median", 99) < 5
    print(json.dumps({"selftest_passed": bool(ok)}))
    sys.exit(0 if ok or a.picker != "stalta" else 1)


if __name__ == "__main__":
    main()
