"""Picks -> association -> location -> magnitudes -> evaluation on a run directory written by fetch."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from loc.associate import Associator, associate_windowed
from loc.geometry import from_local_km, to_local_km
from loc.locate import Locator
from loc.velocity import TravelTimeTable

from .evaluate import (event_metrics, magnitude_error_by_bin, match_events, pick_metrics, plot_all,
                       recall_by_magnitude, region_metrics)
from .magnitude import event_dl_magnitude, event_local_magnitude


class WaveformStore:
    """Reads the hourly MiniSEED folders, with a small cache and padding across hour boundaries."""

    def __init__(self, run_dir, stations, cache_hours=4):
        self.root = Path(run_dir) / "waveforms"
        self.hours = sorted(p.name for p in self.root.iterdir() if p.is_dir()) if self.root.exists() else []
        self.stations = set(stations)
        self.cache, self.order, self.cache_hours = {}, [], cache_hours

    def _hour(self, key):
        from obspy import Stream, read

        if key in self.cache:
            return self.cache[key]
        st = Stream()
        folder = self.root / key
        if folder.exists():
            for f in sorted(folder.glob("*.mseed")):
                if f.stem in self.stations:
                    try:
                        st += read(str(f))
                    except Exception as exc:
                        print(f"  unreadable {f}: {exc}")
        self.cache[key] = st
        self.order.append(key)
        while len(self.order) > self.cache_hours:
            self.cache.pop(self.order.pop(0), None)
        return st

    @staticmethod
    def key_of(t):
        return t.strftime("%Y%m%dT%H")

    def span(self, t1, t2):
        from obspy import Stream

        st = Stream()
        t = t1 - (t1.minute * 60 + t1.second + t1.microsecond / 1e6)
        while t < t2:
            st += self._hour(self.key_of(t)).copy()
            t += 3600
        if not len(st):
            return st
        st.merge(method=1, fill_value="interpolate")
        st.trim(t1, t2)
        return st


def compute_picks(store, picker, out_csv, p_threshold, s_threshold, pad=60.0, max_hours=None):
    from obspy import UTCDateTime

    from dl.pickers import pick_stream

    out_csv = Path(out_csv)
    done = pd.read_csv(out_csv) if out_csv.exists() else pd.DataFrame()
    done_hours = set(done["hour"].astype(str)) if "hour" in done else set()
    frames = [done] if len(done) else []
    hours = store.hours[:max_hours] if max_hours else store.hours
    for i, key in enumerate(hours):
        if key in done_hours:
            continue
        t0 = time.time()
        h1 = UTCDateTime.strptime(key, "%Y%m%dT%H")
        st = store.span(h1 - pad, h1 + 3600 + pad)
        if not len(st):
            continue
        st.detrend("demean")
        rows = [r for r in pick_stream(picker, st, p_threshold, s_threshold, station_key="netsta")
                if h1.timestamp <= r["time_s"] < h1.timestamp + 3600]
        df = pd.DataFrame(rows, columns=["station", "network", "phase", "time", "time_s", "prob", "trace_id"])
        df["hour"] = key
        frames.append(df)
        pd.concat(frames, ignore_index=True).to_csv(out_csv, index=False)  # checkpoint after every hour
        print(f"  picks {key}: {len(df)} ({(df['phase'] == 'P').sum()} P, {(df['phase'] == 'S').sum()} S) "
              f"[{i + 1}/{len(hours)}, {time.time() - t0:.0f} s]")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["station", "network", "phase", "time", "time_s", "prob", "trace_id", "hour"])


def run_pipeline(run_dir, out_dir, region, vmodel, picker, p_threshold=0.3, s_threshold=0.3, assoc_tol=1.5,
                 min_p=4, min_total=5, bootstrap=0, magnitude_predictor=None, compute_ml=True, max_hours=None,
                 match_dt=3.0, match_km=25.0):
    from obspy import UTCDateTime, read_inventory

    run_dir, out_dir = Path(run_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stations = pd.read_csv(run_dir / "stations.csv", dtype={"location": str}).fillna({"location": ""})
    inventory = read_inventory(str(run_dir / "inventory.xml")) if (run_dir / "inventory.xml").exists() else None
    store = WaveformStore(run_dir, stations["station"])
    tt = TravelTimeTable(vmodel, max_dist_km=600.0)

    # 1. picks
    picks = compute_picks(store, picker, out_dir / "picks.csv", p_threshold, s_threshold, max_hours=max_hours)
    print(f"{len(picks)} picks on {picks['station'].nunique() if len(picks) else 0} stations")
    pk = picks.drop(columns=["time"], errors="ignore").rename(columns={"time_s": "time"})
    pk = pk[["station", "phase", "time", "prob"]].astype({"time": float}).copy()
    pk = pk[pk["phase"].isin(["P", "S"])]

    # 2. association
    t0 = time.time()
    assoc = Associator(stations, tt, tol_s=assoc_tol, min_p=min_p, min_total=min_total)
    events, pk_out = associate_windowed(assoc, pk)
    print(f"{len(events)} associated events ({time.time() - t0:.0f} s)")

    # 3. location + 4. magnitudes
    locator = Locator(stations, tt)
    lat0, lon0 = locator.lat0, locator.lon0
    sx, sy = to_local_km(stations["lat"].to_numpy(), stations["lon"].to_numpy(), lat0, lon0)
    st_tab = stations.assign(x_km=sx, y_km=sy).set_index("station")
    coeffs = {k: region["ml"][k] for k in ("a", "b", "c")} if "ml" in region else {}
    rows, ev_picks = [], []
    for k, ev in enumerate(events):
        sub = pk_out.loc[ev["pick_ids"]]
        try:
            loc = locator.locate(sub, bootstrap=bootstrap)
        except ValueError:
            continue
        x, y = to_local_km(loc.lat, loc.lon, lat0, lon0)
        row = {"event_id": f"auto{k:05d}", "time_s": loc.origin_time, "time": str(UTCDateTime(loc.origin_time)),
               "lat": loc.lat, "lon": loc.lon, "depth_km": loc.depth_km, "rms_s": loc.rms, "n_p": loc.n_p,
               "n_s": loc.n_s, "gap_deg": loc.gap_deg, "lat_err_km": loc.lat_err_km, "lon_err_km": loc.lon_err_km,
               "depth_err_km": loc.depth_err_km}
        evd = {"origin_time_utc": UTCDateTime(loc.origin_time), "x_km": float(x), "y_km": float(y),
               "depth_km": loc.depth_km}
        if compute_ml and inventory is not None and coeffs:
            ml, ml_sd, n_ml, _ = event_local_magnitude(store.span, inventory, st_tab, evd, sub, tt, coeffs)
            row.update({"ml": ml, "ml_sd": ml_sd, "n_ml": n_ml})
        if magnitude_predictor is not None:
            m, se, n = event_dl_magnitude(magnitude_predictor, store.span, inventory, st_tab, evd, sub)
            row.update({"m_dl": m, "m_dl_se": se, "n_dl": n})
        rows.append(row)
        ev_picks.append(sub.assign(event_id=row["event_id"]))
        if (k + 1) % 50 == 0:
            print(f"  located {k + 1}/{len(events)}")
    det = pd.DataFrame(rows)
    det.to_csv(out_dir / "catalog.csv", index=False)
    if ev_picks:
        pd.concat(ev_picks).to_csv(out_dir / "event_picks.csv", index=False)

    # 5. evaluation against the reference catalogue
    metrics = {"run_dir": str(run_dir), "region": region.get("id"), "n_picks": int(len(picks)),
               "n_associated": len(events), "n_located": int(len(det))}
    ref_path, arr_path = run_dir / "events.csv", run_dir / "arrivals.csv"
    if ref_path.exists():
        ref = pd.read_csv(ref_path)
        if max_hours and store.hours:
            t_end = UTCDateTime.strptime(store.hours[min(max_hours, len(store.hours)) - 1], "%Y%m%dT%H") + 3600
            ref = ref[ref["time_s"] < t_end.timestamp].reset_index(drop=True)
        if store.hours:
            t_start = UTCDateTime.strptime(store.hours[0], "%Y%m%dT%H").timestamp
            ref = ref[ref["time_s"] >= t_start].reset_index(drop=True)
        matches = match_events(det, ref, match_dt, match_km) if len(det) else pd.DataFrame(columns=["det", "ref"])
        metrics["events"] = event_metrics(det, ref, matches) if len(det) else {"n_reference": int(len(ref)),
                                                                                "n_detected": 0, "recall": 0.0}
        by_mag = recall_by_magnitude(ref, matches)
        by_mag.to_csv(out_dir / "recall_by_magnitude.csv", index=False)
        metrics["recall_by_magnitude"] = by_mag.to_dict(orient="records")
        if len(det) and "bbox" in region:
            metrics["events_in_region"] = region_metrics(det, ref, matches, region["bbox"],
                                                         region.get("catalog_minmag"))
            mag_bins = magnitude_error_by_bin(det, ref, matches)
            if len(mag_bins):
                mag_bins.to_csv(out_dir / "magnitude_error_by_bin.csv", index=False)
                metrics["magnitude_error_by_bin"] = mag_bins.to_dict(orient="records")
        if len(matches):
            m = matches.copy()
            m["det_id"] = det.iloc[m["det"]]["event_id"].to_numpy()
            m["ref_id"] = ref.iloc[m["ref"]]["event_id"].astype(str).to_numpy()
            m.to_csv(out_dir / "matches.csv", index=False)
        if arr_path.exists():
            arrivals = pd.read_csv(arr_path)
            if len(arrivals) and len(picks):
                metrics["picks_vs_analyst"] = pick_metrics(pk, arrivals[arrivals["event_id"].astype(str).isin(
                    ref["event_id"].astype(str))], set(stations["station"]))
        plot_all(det, ref, matches, stations, by_mag, out_dir, f"{region.get('name', '')}\n{out_dir.name}")
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    return det, metrics


def summarize(metrics):
    e = metrics.get("events", {})
    lines = [f"picks {metrics['n_picks']}, associated {metrics['n_associated']}, located {metrics['n_located']}"]
    if e:
        lines.append(f"reference {e.get('n_reference')}, matched {e.get('n_matched', 0)}: "
                     f"recall {e.get('recall', 0):.2f}, precision {e.get('precision', 0):.2f}")
        for key in ("epicentre_error_km", "depth_error_km", "origin_time_error_s", "ml_minus_reference",
                    "m_dl_minus_reference"):
            if key in e and e[key].get("n"):
                s = e[key]
                lines.append(f"  {key:22s} median {s['median']:+.2f}  MAE {s['mae']:.2f}  p90|.| {s['p90_abs']:.2f}  (n={s['n']})")
    if "picks_vs_analyst" in metrics:
        for ph, s in metrics["picks_vs_analyst"].items():
            lines.append(f"  {ph} picks vs analyst: recall {s['recall']:.2f} ({s['matched']}/{s['n_analyst']}), "
                         f"residual mean {s.get('resid_mean', float('nan')):+.3f}s std {s.get('resid_std', float('nan')):.3f}s")
    return "\n".join(lines)


__all__ = ["run_pipeline", "summarize", "WaveformStore", "from_local_km"]
