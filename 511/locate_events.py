"""Associate picks into events and locate them (stages 2-3 of 5.1.1).

    python 511/locate_events.py --picks 511/outputs/picks/picks.csv --stations data/stations.xlsx \
        --out 511/outputs/catalog/catalog.csv [--velocity 511/config/velocity_nw_vietnam.csv]

Input picks CSV must have columns station, phase (P/S), and either time_s (epoch seconds) or
time (UTC ISO). Output: one row per located event with hypocentre, origin time, RMS, number of
P/S picks, azimuthal gap and bootstrap errors, plus <out>_picks.csv listing the picks assigned
to each event.

Without the Institute's catalogue (B1-B3) the results can only be checked against public
catalogues (USGS/EMSC/ISC) for the larger events; without the regional velocity model (B5)
depths are poorly constrained.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loc.associate import Associator  # noqa: E402
from loc.geometry import read_stations  # noqa: E402
from loc.locate import Locator  # noqa: E402
from loc.velocity import TravelTimeTable, VelocityModel  # noqa: E402


def read_picks(path):
    df = pd.read_csv(path)
    df["station"] = df["station"].astype(str).str.strip()
    df["phase"] = df["phase"].astype(str).str.upper().str[0]
    if "time_s" not in df:
        df["time_s"] = pd.to_datetime(df["time"], utc=True).astype("int64") / 1e9
    df = df[df["phase"].isin(["P", "S"])]
    out = pd.DataFrame({"station": df["station"], "phase": df["phase"], "time": df["time_s"].astype(float)})
    for c in ("prob", "trace_id"):
        if c in df:
            out[c] = df[c]
    return out.reset_index(drop=True)


def run(picks_path, stations_path, out, velocity=None, tol_s=1.0, min_p=4, min_total=5, bootstrap=30):
    stations = read_stations(stations_path)
    model = VelocityModel.from_csv(velocity) if velocity else VelocityModel()
    table = TravelTimeTable(model)
    picks = read_picks(picks_path)
    print(f"{len(picks)} picks, {picks['station'].nunique()} stations")
    events, picks_out = Associator(stations, table, tol_s=tol_s, min_p=min_p, min_total=min_total).associate(picks)
    print(f"{len(events)} candidate events")
    locator = Locator(stations, table)
    rows, assigned = [], []
    for i, ev in enumerate(events):
        sub = picks_out.loc[ev["pick_ids"]]
        loc = locator.locate(sub, bootstrap=bootstrap)
        row = {"event_id": i, **loc.as_dict(), "origin_time_utc": pd.to_datetime(loc.origin_time, unit="s", utc=True),
               "assoc_n_p": ev["n_p"], "assoc_rms": ev["rms"]}
        rows.append(row)
        assigned.append(sub.assign(event_id=i))
        print(f"  {i:3d} {row['origin_time_utc']}  {loc.lat:.3f} {loc.lon:.3f}  z={loc.depth_km:.1f} km  "
              f"rms={loc.rms:.2f}s  nP={loc.n_p} nS={loc.n_s} gap={loc.gap_deg:.0f}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cat = pd.DataFrame(rows)
    cat.to_csv(out, index=False)
    if assigned:
        pd.concat(assigned).to_csv(out.with_name(out.stem + "_picks.csv"), index=False)
    print(f"wrote {len(cat)} events to {out}")
    return cat


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--picks", required=True)
    p.add_argument("--stations", required=True, help="data/stations.xlsx or CSV with station, lat, lon")
    p.add_argument("--out", default="511/outputs/catalog/catalog.csv")
    p.add_argument("--velocity", help="CSV depth_km,vp_kms for the regional 1-D model (default: generic crust)")
    p.add_argument("--tol", type=float, default=1.0)
    p.add_argument("--min-p", type=int, default=4)
    p.add_argument("--min-total", type=int, default=5)
    p.add_argument("--bootstrap", type=int, default=30)
    a = p.parse_args(argv)
    run(a.picks, a.stations, a.out, a.velocity, a.tol, a.min_p, a.min_total, a.bootstrap)


if __name__ == "__main__":
    main()
