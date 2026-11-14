"""Data-free demonstration of association + location on the real station geometry.

    python 511/synthetic_demo.py --stations data/stations.xlsx --events 10 --false-picks 60 \
        --out 511/outputs/synthetic_demo

Generates synthetic earthquakes around the 20-station network, synthetic P/S picks with noise,
missed detections and false picks, runs the associator and locator, and reports location errors.
This is the evaluation that can be done before the Institute delivers a reference catalogue.
Without --stations a random 20-station layout in the same region is used.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loc import synth  # noqa: E402
from loc.associate import Associator  # noqa: E402
from loc.geometry import read_stations  # noqa: E402
from loc.locate import Locator  # noqa: E402
from loc.velocity import TravelTimeTable, VelocityModel  # noqa: E402


def run(stations_path=None, n_events=10, false_picks=60, noise_p=0.1, noise_s=0.2, out=None, seed=0,
        wrong_model=False):
    stations = read_stations(stations_path) if stations_path else synth.random_stations(20, seed)
    truth_model = VelocityModel()
    events = synth.random_events(n_events, stations, seed=seed, spacing_s=180.0)
    picks = synth.synthetic_picks(stations, events, truth_model, noise_p, noise_s, false_picks=false_picks, seed=seed)
    # locate with a (possibly) different model to see the effect of an unknown velocity structure
    model = VelocityModel.halfspace(6.0) if wrong_model else truth_model
    table = TravelTimeTable(model)
    found, picks_out = Associator(stations, table).associate(picks)
    locator = Locator(stations, table)
    rows = []
    for ev in found:
        loc = locator.locate(picks_out.loc[ev["pick_ids"]], bootstrap=20)
        k = int(np.argmin(np.abs(events["origin_time"] - loc.origin_time)))
        t = events.iloc[k]
        err_km = synth.to_local_km(loc.lat, loc.lon, t["lat"], t["lon"])
        rows.append({"true_event": k, "lat": loc.lat, "lon": loc.lon, "depth_km": loc.depth_km,
                     "true_depth_km": t["depth_km"], "epi_err_km": float(np.hypot(*err_km)),
                     "depth_err_km": loc.depth_km - t["depth_km"], "ot_err_s": loc.origin_time - t["origin_time"],
                     "rms_s": loc.rms, "n_p": loc.n_p, "n_s": loc.n_s, "gap_deg": loc.gap_deg,
                     "boot_depth_err_km": loc.depth_err_km})
    res = pd.DataFrame(rows)
    print(f"{len(events)} true events, {len(found)} found, {false_picks} false picks injected")
    if len(res):
        print(res.round(2).to_string(index=False))
        print(f"median epicentre error {res['epi_err_km'].median():.1f} km, "
              f"median |depth error| {res['depth_err_km'].abs().median():.1f} km")
    if out:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        res.to_csv(out / "location_errors.csv", index=False)
        events.to_csv(out / "true_events.csv", index=False)
        picks.to_csv(out / "synthetic_picks.csv", index=False)
    return res


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stations")
    p.add_argument("--events", type=int, default=10)
    p.add_argument("--false-picks", type=int, default=60)
    p.add_argument("--noise-p", type=float, default=0.1)
    p.add_argument("--noise-s", type=float, default=0.2)
    p.add_argument("--wrong-model", action="store_true", help="locate with a 6 km/s half-space instead of the true model")
    p.add_argument("--out")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    run(a.stations, a.events, a.false_picks, a.noise_p, a.noise_s, a.out, a.seed, a.wrong_model)


if __name__ == "__main__":
    main()
