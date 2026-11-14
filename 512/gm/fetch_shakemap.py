"""Build a ground-motion flatfile from USGS ShakeMap station lists (no registration needed).

Every USGS ShakeMap ships a ``stationlist.json`` (GeoJSON) with the observed PGA, PGV and
SA(0.3/1.0/3.0 s) at each seismic station plus rupture distances. Pulling it for every event
with a ShakeMap gives tens of thousands of recordings that can be used before the Vietnamese
network has recorded any earthquake. Vs30 is not in the station list; join it afterwards with
``gm.vs30.sample_points`` (ShakeMap itself uses the same USGS global grid).

Usage (from repository root, network required):

    python 512/fetch_shakemap.py --start 2015-01-01 --end 2025-12-31 --minmag 4.5 \
        --out data/gm/shakemap_flatfile.csv --cache data/gm/shakemap_cache

Stops politely on HTTP errors and can be re-run; already-downloaded events are read from the cache.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .flatfile import COLUMNS, clean, haversine_km, save

COMCAT = "https://earthquake.usgs.gov/fdsnws/event/1/query"
IM_NAMES = {"pga": "pga_g", "pgv": "pgv_cms", "sa(0.3)": "sa_0.3_g", "sa(1.0)": "sa_1.0_g", "sa(3.0)": "sa_3.0_g"}


def _num(v):
    try:
        if v is None or v == "null" or v == "":
            return np.nan
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _unflagged(flag):
    return flag in (None, "", "0", 0)


def parse_stationlist(geojson, event):
    """Convert one stationlist.json into unified rows.

    ``event`` is a dict with id, mag, depth_km, lat, lon. Only ``station_type == "seismic"``
    features are kept (DYFI/macroseismic points are not instrumental recordings). Amplitudes are
    the maximum over channels (horizontal components dominate); ShakeMap reports accelerations in
    %g and velocity in cm/s.
    """
    rows = []
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        if props.get("station_type", "seismic") != "seismic":
            continue
        if props.get("network") == "DYFI" or props.get("source") == "DYFI":
            continue
        lon, lat = feat["geometry"]["coordinates"][:2]
        ims = {v: np.nan for v in IM_NAMES.values()}
        for ch in props.get("channels", []) or []:
            for amp in ch.get("amplitudes", []) or []:
                name = str(amp.get("name", "")).lower()
                col = IM_NAMES.get(name)
                if col is None or not _unflagged(amp.get("flag")):
                    continue
                val = _num(amp.get("value"))
                if np.isnan(val):
                    continue
                units = str(amp.get("units", "")).lower()
                if col != "pgv_cms":
                    if units in ("%g", "pctg", "percent g", ""):
                        val = val / 100.0
                    elif units in ("m/s^2", "m/s2"):
                        val = val / 9.80665
                    elif units in ("cm/s^2", "cm/s2", "gal"):
                        val = val / 980.665
                ims[col] = np.nanmax([ims[col], val])
        # fall back to the top-level pga/pgv (already max over channels, %g and cm/s)
        if np.isnan(ims["pga_g"]):
            ims["pga_g"] = _num(props.get("pga")) / 100.0
        if np.isnan(ims["pgv_cms"]):
            ims["pgv_cms"] = _num(props.get("pgv"))
        if np.isnan(ims["pga_g"]) or ims["pga_g"] <= 0:
            continue
        dist = props.get("distances", {}) or {}
        repi = haversine_km(event["lat"], event["lon"], lat, lon)
        rhypo = _num(dist.get("rhypo"))
        if np.isnan(rhypo):
            rhypo = float(np.hypot(repi, event["depth_km"]))
        net = props.get("network") or props.get("source") or "XX"
        rows.append({
            "event_id": event["id"],
            "station_id": f"{net}.{props.get('code', feat.get('id', ''))}",
            "mag": event["mag"],
            "depth_km": event["depth_km"],
            "ev_lat": event["lat"], "ev_lon": event["lon"],
            "st_lat": lat, "st_lon": lon,
            "rhypo_km": rhypo,
            "repi_km": repi,
            "rjb_km": _num(dist.get("rjb")),
            "rrup_km": _num(dist.get("rrup", props.get("distance"))),
            "vs30_ms": _num(props.get("vs30")),
            "mech": "U",
            **ims,
            "source": "shakemap",
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def _get(session, url, retries=3, sleep=1.0):
    for attempt in range(retries):
        resp = session.get(url, timeout=60)
        if resp.status_code == 200:
            return resp
        if resp.status_code in (429, 503):
            time.sleep(sleep * (attempt + 1) * 5)
            continue
        resp.raise_for_status()
    resp.raise_for_status()


def query_events(session, start, end, minmag, bbox=None, limit=20000):
    params = {
        "format": "geojson", "starttime": start, "endtime": end, "minmagnitude": minmag,
        "producttype": "shakemap", "orderby": "time", "limit": limit,
    }
    if bbox:
        params.update(dict(zip(["minlongitude", "minlatitude", "maxlongitude", "maxlatitude"], bbox)))
    resp = session.get(COMCAT, params=params, timeout=120)
    resp.raise_for_status()
    return resp.json()["features"]


def fetch(start, end, minmag, out, cache, bbox=None, sleep=0.5, max_events=None):
    import requests

    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "vast-eq-512/0.1"
    events = query_events(session, start, end, minmag, bbox)
    if max_events:
        events = events[:max_events]
    print(f"{len(events)} events with a ShakeMap")
    frames = []
    for i, feat in enumerate(events):
        eid = feat["id"]
        lon, lat, depth = feat["geometry"]["coordinates"]
        event = {"id": eid, "mag": feat["properties"]["mag"], "depth_km": depth, "lat": lat, "lon": lon}
        cached = cache / f"{eid}.json"
        try:
            if cached.exists():
                station_json = json.loads(cached.read_text())
            else:
                detail = _get(session, feat["properties"]["detail"]).json()
                products = detail["properties"]["products"].get("shakemap", [])
                if not products:
                    continue
                contents = products[0]["contents"]
                key = next((k for k in contents if k.endswith("stationlist.json")), None)
                if key is None:
                    continue
                station_json = _get(session, contents[key]["url"]).json()
                cached.write_text(json.dumps(station_json))
                time.sleep(sleep)
        except Exception as exc:  # keep going; the run is resumable
            print(f"  {eid}: skipped ({type(exc).__name__}: {exc})")
            continue
        df = parse_stationlist(station_json, event)
        if len(df):
            frames.append(df)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(events)} events, {sum(len(f) for f in frames)} recordings")
    if not frames:
        raise SystemExit("no recordings collected")
    flat = clean(pd.concat(frames, ignore_index=True))
    save(flat, out)
    print(f"wrote {len(flat)} recordings from {flat['event_id'].nunique()} events to {out}")
    return flat


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--minmag", type=float, default=4.5)
    p.add_argument("--bbox", type=float, nargs=4, metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    p.add_argument("--out", default="data/gm/shakemap_flatfile.csv")
    p.add_argument("--cache", default="data/gm/shakemap_cache")
    p.add_argument("--max-events", type=int)
    a = p.parse_args(argv)
    fetch(a.start, a.end, a.minmag, a.out, a.cache, a.bbox, max_events=a.max_events)


if __name__ == "__main__":
    main()
