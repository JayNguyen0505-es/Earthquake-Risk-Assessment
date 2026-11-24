"""Measure station magnitudes on reference events with controlled locations and P picks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from obspy import UTCDateTime, read_inventory

from dl.magnet import MagnitudePredictor, combine_station_estimates
from e2e.magnitude import station_dl_magnitudes, station_local_magnitudes
from e2e.pipeline import WaveformStore
from e2e.regions import get_region, velocity_model
from loc.geometry import network_centre, to_local_km
from loc.velocity import TravelTimeTable

STATION_COLUMNS = [
    "event_id", "time", "m_true", "mag_type", "station", "estimator", "m_pred", "sd",
    "logvar", "hyp_km", "azimuth", "snr", "p_time", "p_source_used", "loc_source",
    "log_amp_z", "log_amp_n", "log_amp_e", "logdist",
]
SUMMARY_COLUMNS = ["event_id", "estimator", "n_stations", "median", "ivw", "m_true"]
LOCATION_COLUMNS = ["time_s", "lat", "lon", "depth_km"]


def read_auto_csv(path, columns, dtype=None):
    # The pipeline writes a headerless CSV when there are no detections or matches.
    try:
        return pd.read_csv(path, dtype=dtype)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns)


def reference_events(args, hours):
    ref = pd.read_csv(args.run / "events.csv", dtype={"event_id": str})
    hours = set(hours)
    ref = ref.dropna(subset=["time_s"]).sort_values("time_s")
    ref = ref.assign(hour=ref["time_s"].map(lambda t: WaveformStore.key_of(UTCDateTime(t))))
    events = ref.loc[ref["hour"].isin(hours)].drop(columns="time", errors="ignore").rename(columns={"time_s": "time", "mag": "m_true"})
    metadata = ["event_id", "time", "m_true", "mag_type", "hour"]
    if args.loc_source == "ref":
        events = events.assign(time_s=events["time"])
    else:
        catalog = read_auto_csv(args.auto_dir / "catalog.csv", ["event_id", *LOCATION_COLUMNS],
                                dtype={"event_id": str})
        match_path = args.auto_dir / "matches.csv"
        if not match_path.exists():
            # run_pipeline omits matches.csv when there are no matches.
            return events.iloc[:0]
        matches = read_auto_csv(match_path, ["ref_id", "det_id"], dtype={"ref_id": str, "det_id": str})
        locations = matches[["ref_id", "det_id"]].merge(
            catalog[["event_id", *LOCATION_COLUMNS]].rename(columns={"event_id": "det_id"}), on="det_id")
        events = events[metadata].merge(locations, left_on="event_id", right_on="ref_id")
    events = events[metadata + LOCATION_COLUMNS].dropna(subset=LOCATION_COLUMNS)
    return events.iloc[:args.max_events]


class MagnitudeRun:
    def __init__(self, args, stations, max_depth):
        self.args = args
        self.centre = network_centre(stations)
        x, y = to_local_km(stations["lat"], stations["lon"], *self.centre)
        self.stations = stations.assign(x_km=x, y_km=y).set_index("station")
        self.store = WaveformStore(args.run, self.stations.index, cache_hours=3)
        region = get_region(json.loads((args.run / "run.json").read_text())["region"])
        self.coeffs = {k: region["ml"][k] for k in ("a", "b", "c")} if "ml" in region else {}
        self.tt = TravelTimeTable(velocity_model(region), max_dist_km=max(0.5, math.ceil(args.max_dist_km)),
                                  max_depth_km=max(60, math.ceil(max_depth)))
        self.predictor = None
        if args.magnitude_model:
            device = "cpu" if args.workers > 1 else args.device
            self.predictor = MagnitudePredictor(args.magnitude_model, device)
        self.inventory = None
        if not args.no_ml or (self.predictor and self.predictor.response_output):
            self.inventory = read_inventory(str(args.run / "inventory.xml"))
        self.analyst = {}
        self.auto = {}
        if self.predictor and args.p_source == "analyst":
            path = args.run / "arrivals.csv"
            if path.exists():
                arrivals = pd.read_csv(path, dtype={"event_id": str})
                arrivals = arrivals[arrivals["phase"] == "P"].dropna(subset=["time_s"])
                arrivals = arrivals.sort_values("time_s").drop_duplicates(["event_id", "station"])
                self.analyst = arrivals.set_index(["event_id", "station"])["time_s"].to_dict()
        if self.predictor and args.p_source == "auto":
            picks = read_auto_csv(args.auto_dir / "picks.csv", ["station", "phase", "time_s"])
            picks = picks[picks["phase"] == "P"].dropna(subset=["time_s"])
            self.auto = {sid: np.sort(rows["time_s"].to_numpy()) for sid, rows in picks.groupby("station")}

    def p_pick(self, event_id, station, theory):
        source = self.args.p_source
        if source == "auto":
            picks = self.auto.get(station)
            if picks is None:
                return None, None
            j = picks.searchsorted(theory)
            nearest = min(picks[max(0, j - 1):j + 1], key=lambda t: abs(t - theory))
            return (nearest, "auto") if abs(nearest - theory) <= 2 else (None, None)
        if source == "analyst":
            time = self.analyst.get((event_id, station))
            if time is not None:
                return time, "analyst"
        return theory, "theory"

    def event_rows(self, ref):
        x, y = to_local_km(ref.lat, ref.lon, *self.centre)
        origin = UTCDateTime(ref.time_s)
        ev = dict(x_km=float(x), y_km=float(y), depth_km=ref.depth_km, origin_time_utc=origin)
        epi = np.hypot(self.stations["x_km"] - x, self.stations["y_km"] - y)
        epi = epi[np.hypot(epi, ref.depth_km) <= self.args.max_dist_km]
        if epi.empty:
            return []

        lo, hi = origin, origin
        if not self.args.no_ml:
            tp = self.tt(epi, ref.depth_km, "P")
            ts = self.tt(epi, ref.depth_km, "S")
            # Keep both the noise and signal windows, including the WA processing pad.
            lo = origin + float(tp.min()) - 42
            hi = origin + float(np.max(ts + np.maximum(10, 1.5 * (ts - tp)))) + 30

        p_times, sources = {}, {}
        if self.predictor:
            theory = ref.time_s + self.tt(epi, ref.depth_km, "P")
            for sid, t in zip(epi.index, theory):
                pick, source = self.p_pick(ref.event_id, sid, t)
                if pick is not None:
                    p_times[sid], sources[sid] = UTCDateTime(pick), source
            if p_times:
                cfg = self.predictor.cfg
                lo = min(lo, min(p_times.values()) - cfg["pre"] / 100 - 30)
                hi = max(hi, max(p_times.values()) + (cfg["window"] - cfg["pre"]) / 100 + 30)

        if lo == hi:
            return []
        stream = self.store.span(lo, hi)
        available = {f"{tr.stats.network}.{tr.stats.station}" for tr in stream}
        station_ids = [sid for sid in epi.index if sid in available]
        rows = []
        if not self.args.no_ml:
            rows = station_local_magnitudes(stream, self.inventory, ev, station_ids, self.stations,
                                            self.tt, self.coeffs, self.args.max_dist_km)
        if p_times:
            snr = {r["station"]: r["snr"] for r in rows}
            # A station present elsewhere in the span may have no samples at this P.
            at_p = set()
            for tr in stream:
                sid = f"{tr.stats.network}.{tr.stats.station}"
                if sid in p_times and tr.stats.starttime <= p_times[sid] <= tr.stats.endtime:
                    at_p.add(sid)
            dl_rows = station_dl_magnitudes(self.predictor, stream, self.inventory, ev,
                                           {sid: t for sid, t in p_times.items() if sid in at_p},
                                           self.stations)
            rows.extend(dict(r, p_source_used=sources[r["station"]], snr=snr.get(r["station"], np.nan))
                        for r in dl_rows)
        return [dict(r, event_id=ref.event_id, time=ref.time, m_true=ref.m_true, mag_type=ref.mag_type,
                     loc_source=self.args.loc_source) for r in rows]

    def hour_rows(self, events):
        return [self.event_rows(ref) for ref in events]


def init_worker(*args):
    global worker, worker_args
    worker, worker_args = None, args


def process_hour(events):
    global worker
    if worker is None:
        worker = MagnitudeRun(*worker_args)
    return worker.hour_rows(events)


def collect_rows(hour_results, n_events):
    rows = []
    count = 0
    for hour in hour_results:
        for event_rows in hour:
            rows.extend(event_rows)
            count += 1
            if count % 50 == 0:
                print(f"Processed {count}/{n_events} events", flush=True)
    return pd.DataFrame(rows, columns=STATION_COLUMNS)


def event_summary(stations):
    rows = []
    for (event_id, estimator), group in stations.groupby(["event_id", "estimator"], sort=False):
        ivw = np.nan
        median = group["m_pred"].median()
        if estimator == "dl":
            ivw, _, median = combine_station_estimates(group["m_pred"], group["logvar"])
        rows.append(dict(event_id=event_id, estimator=estimator, n_stations=len(group), median=median,
                         ivw=ivw, m_true=group["m_true"].iloc[0]))
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--magnitude-model", type=Path)
    parser.add_argument("--loc-source", choices=["ref", "auto"], default="ref")
    parser.add_argument("--p-source", choices=["analyst", "theory", "auto"], default="analyst")
    parser.add_argument("--auto-dir", type=Path)
    parser.add_argument("--max-dist-km", type=float, default=300)
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-ml", action="store_true")
    args = parser.parse_args(argv)
    if (args.loc_source == "auto" or args.p_source == "auto") and args.auto_dir is None:
        parser.error("--auto-dir is required for auto locations or P picks")
    if args.workers < 1 or (args.max_events is not None and args.max_events < 0):
        parser.error("--workers must be positive and --max-events must be nonnegative")
    if not math.isfinite(args.max_dist_km) or args.max_dist_km <= 0:
        parser.error("--max-dist-km must be finite and positive")

    stations = pd.read_csv(args.run / "stations.csv", dtype={"station": str})
    store = WaveformStore(args.run, stations["station"])
    events = reference_events(args, store.hours)
    chunks = [[SimpleNamespace(**row) for row in group.to_dict("records")] for _, group in events.groupby("hour", sort=False)]
    if not chunks:
        rows = pd.DataFrame(columns=STATION_COLUMNS)
    else:
        init_args = (args, stations, events["depth_km"].max())
        if args.workers == 1:
            run = MagnitudeRun(*init_args)
            rows = collect_rows(map(run.hour_rows, chunks), len(events))
        else:
            with mp.get_context("spawn").Pool(min(args.workers, len(chunks)), init_worker, init_args) as pool:
                rows = collect_rows(pool.imap(process_hour, chunks), len(events))
    model_hash = None
    if args.magnitude_model:
        digest = hashlib.sha256()
        with args.magnitude_model.open("rb") as model:
            for block in iter(lambda: model.read(1024 * 1024), b""):
                digest.update(block)
        model_hash = digest.hexdigest()[:16]
    args.out.mkdir(parents=True, exist_ok=True)
    rows.to_csv(args.out / "station_magnitudes.csv", index=False)
    event_summary(rows).to_csv(args.out / "events_summary.csv", index=False)
    config = {"args": vars(args), "model_sha256": model_hash, "n_events": len(events)}
    (args.out / "config.json").write_text(json.dumps(config, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
