"""FDSN download for the end-to-end benchmark.

Layout of a run directory (also the layout to use later for Vietnamese data):

    <run>/run.json            region, time window, provider, selected stations
    <run>/stations.csv        station (NET.STA), network, code, location, band, lat, lon, elev_km
    <run>/inventory.xml       StationXML with full responses for the selected channels
    <run>/events.csv          reference catalogue (event_id, time_s, lat, lon, depth_km, mag, mag_type)
    <run>/arrivals.csv        analyst P/S arrivals of the reference events (when the service provides them)
    <run>/catalog.xml         the same catalogue as QuakeML
    <run>/waveforms/YYYYMMDDTHH/NET.STA.mseed   one file per station and hour
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from loc.geometry import network_centre, to_local_km


def get_client(provider, timeout=180):
    from obspy.clients.fdsn import Client

    return Client(provider, timeout=timeout)


# ---- catalogue ------------------------------------------------------------------------------------
def _event_id(ev):
    rid = str(ev.resource_id)
    for key in ("eventId=", "eventid=", "evid="):
        if key in rid:
            return rid.split(key)[-1].split("&")[0]
    return rid.rstrip("/").split("/")[-1]


def catalog_to_frames(cat, provider=""):
    ev_rows, arr_rows = [], []
    for ev in cat:
        org = ev.preferred_origin() or (ev.origins[0] if ev.origins else None)
        if org is None or org.latitude is None:
            continue
        mag = ev.preferred_magnitude() or (ev.magnitudes[0] if ev.magnitudes else None)
        eid = _event_id(ev)
        ev_rows.append({
            "event_id": eid, "time": str(org.time), "time_s": float(org.time.timestamp),
            "lat": float(org.latitude), "lon": float(org.longitude),
            "depth_km": float(org.depth) / 1000.0 if org.depth is not None else np.nan,
            "mag": float(mag.mag) if mag is not None and mag.mag is not None else np.nan,
            "mag_type": (mag.magnitude_type or "") if mag is not None else "", "provider": provider,
        })
        picks = {str(p.resource_id): p for p in ev.picks}
        for arr in org.arrivals:
            pk = picks.get(str(arr.pick_id))
            if pk is None or pk.time is None:
                continue
            phase = (arr.phase or pk.phase_hint or "").strip().upper()[:1]
            if phase not in ("P", "S"):
                continue
            wid = pk.waveform_id
            arr_rows.append({"event_id": eid, "station": f"{wid.network_code}.{wid.station_code}",
                             "channel": wid.channel_code or "", "phase": phase,
                             "time_s": float(pk.time.timestamp)})
    events = pd.DataFrame(ev_rows, columns=["event_id", "time", "time_s", "lat", "lon", "depth_km", "mag",
                                            "mag_type", "provider"])
    arrivals = pd.DataFrame(arr_rows, columns=["event_id", "station", "channel", "phase", "time_s"])
    return events.sort_values("time_s").reset_index(drop=True), arrivals


def fetch_catalog(clients, region, start, end, minmag, out_dir, day_chunks=True):
    """Query the first provider that returns events, day by day, with arrivals when supported."""
    from obspy import Catalog, UTCDateTime
    from obspy.clients.fdsn.header import FDSNNoDataException

    minlon, minlat, maxlon, maxlat = region["bbox"]
    t, t_end = UTCDateTime(start), UTCDateTime(end)
    edges = []
    while t < t_end:
        nxt = min(t + 86400, t_end) if day_chunks else t_end
        edges.append((t, nxt))
        t = nxt
    used, cat = None, Catalog()
    for name, client in clients:
        cat = Catalog()
        for t1, t2 in edges:
            kw = dict(starttime=t1, endtime=t2, minlatitude=minlat, maxlatitude=maxlat, minlongitude=minlon,
                      maxlongitude=maxlon, minmagnitude=minmag, orderby="time-asc")
            try:
                part = client.get_events(includearrivals=True, **kw)
            except FDSNNoDataException:
                continue
            except Exception as exc:  # some services reject includearrivals; retry without
                print(f"  [{name}] get_events with arrivals failed ({type(exc).__name__}); retrying without")
                try:
                    part = client.get_events(**kw)
                except FDSNNoDataException:
                    continue
            cat.extend(part.events)
        if len(cat):
            used = name
            break
    events, arrivals = catalog_to_frames(cat, used or "")
    out_dir = Path(out_dir)
    events.to_csv(out_dir / "events.csv", index=False)
    arrivals.to_csv(out_dir / "arrivals.csv", index=False)
    if len(cat):
        cat.write(str(out_dir / "catalog.xml"), format="QUAKEML")
    print(f"catalogue ({used}): {len(events)} events, {len(arrivals)} analyst arrivals")
    return events, arrivals


# ---- stations -------------------------------------------------------------------------------------
def fetch_inventory(client, region, start, end, bands=None):
    from obspy import UTCDateTime

    minlon, minlat, maxlon, maxlat = region["bbox"]
    m = float(region.get("station_margin_deg", 0.1))
    bands = bands or region["channel_priority"]
    return client.get_stations(network=region.get("networks", "*"), channel=",".join(f"{b}?" for b in bands),
                               minlatitude=minlat - m, maxlatitude=maxlat + m, minlongitude=minlon - m,
                               maxlongitude=maxlon + m, starttime=UTCDateTime(start), endtime=UTCDateTime(end),
                               level="response")


def candidate_stations(inv, bands, start, end):
    """One row per station: the highest-priority band that has Z plus two horizontals open in the window."""
    from obspy import UTCDateTime

    t1, t2 = UTCDateTime(start), UTCDateTime(end)
    rows = []
    for net in inv:
        for sta in net:
            best = None
            for band in bands:
                by_loc = {}
                for ch in sta.channels:
                    if not ch.code.startswith(band):
                        continue
                    if ch.start_date and ch.start_date > t1:
                        continue
                    if ch.end_date and ch.end_date < t2:
                        continue
                    by_loc.setdefault(ch.location_code, set()).add(ch.code[-1])
                for loc, comps in sorted(by_loc.items()):
                    if "Z" in comps and len(comps & set("NE12")) >= 2:
                        best = (band, loc)
                        break
                if best:
                    break
            if best:
                lat = sta.latitude if sta.latitude is not None else sta.channels[0].latitude
                lon = sta.longitude if sta.longitude is not None else sta.channels[0].longitude
                elev = sta.elevation if sta.elevation is not None else 0.0
                rows.append({"station": f"{net.code}.{sta.code}", "network": net.code, "code": sta.code,
                             "location": best[1], "band": best[0], "lat": float(lat), "lon": float(lon),
                             "elev_km": float(elev) / 1000.0})
    return pd.DataFrame(rows, columns=["station", "network", "code", "location", "band", "lat", "lon", "elev_km"])


def select_stations(cands, n, bbox, min_spacing_km=0.0):
    """Farthest-point subset of ``n`` stations, seeded at the station nearest the region centre.

    Spreads stations over the region like a sparse regional network (the 20-station NW Vietnam
    layout) instead of keeping the densest cluster.
    """
    if len(cands) <= n:
        return cands.reset_index(drop=True)
    lat0 = (bbox[1] + bbox[3]) / 2
    lon0 = (bbox[0] + bbox[2]) / 2
    x, y = to_local_km(cands["lat"].to_numpy(), cands["lon"].to_numpy(), lat0, lon0)
    pts = np.column_stack([x, y])
    chosen = [int(np.argmin(np.hypot(x, y)))]
    dmin = np.hypot(*(pts - pts[chosen[0]]).T)
    while len(chosen) < n:
        k = int(np.argmax(dmin))
        if dmin[k] < min_spacing_km:
            break
        chosen.append(k)
        dmin = np.minimum(dmin, np.hypot(*(pts - pts[k]).T))
    return cands.iloc[chosen].reset_index(drop=True)


def subset_inventory(inv, stations):
    from obspy import Inventory

    out = Inventory(networks=[], source=inv.source)
    for _, r in stations.iterrows():
        out += inv.select(network=r["network"], station=r["code"], location=r["location"], channel=f"{r['band']}?")
    return out


# ---- waveforms ------------------------------------------------------------------------------------
def hour_key(t):
    return t.strftime("%Y%m%dT%H")


def fetch_waveforms(client, stations, start, end, out_dir, chunk_s=3600, retries=3, sleep=1.0):
    from obspy import Stream, UTCDateTime

    out_dir = Path(out_dir) / "waveforms"
    t, t_end = UTCDateTime(start), UTCDateTime(end)
    n_files, n_empty = 0, 0
    while t < t_end:
        t2 = min(t + chunk_s, t_end)
        folder = out_dir / hour_key(t)
        folder.mkdir(parents=True, exist_ok=True)
        todo = [r for _, r in stations.iterrows()
                if not (folder / f"{r['station']}.mseed").exists() and not (folder / f"{r['station']}.nodata").exists()]
        if todo:
            bulk = [(r["network"], r["code"], r["location"] or "", f"{r['band']}?", t, t2) for r in todo]
            st = None
            for attempt in range(retries):
                try:
                    st = client.get_waveforms_bulk(bulk)
                    break
                except Exception as exc:
                    if "No data" in str(exc) or type(exc).__name__ == "FDSNNoDataException":
                        st = Stream()
                        break
                    print(f"  {hour_key(t)} bulk request failed ({type(exc).__name__}: {exc}); retry {attempt + 1}")
                    time.sleep(sleep * (attempt + 1) * 5)
            if st is None:  # fall back to one request per station
                st = Stream()
                for r in todo:
                    try:
                        st += client.get_waveforms(r["network"], r["code"], r["location"] or "", f"{r['band']}?", t, t2)
                    except Exception:
                        pass
            for r in todo:
                sub = st.select(network=r["network"], station=r["code"])
                if len(sub):
                    sub.write(str(folder / f"{r['station']}.mseed"), format="MSEED")
                    n_files += 1
                else:
                    (folder / f"{r['station']}.nodata").touch()
                    n_empty += 1
            time.sleep(sleep)
        print(f"  {hour_key(t)}: {len(todo)} requested, {sum(1 for _ in folder.glob('*.mseed'))} stations with data")
        t = t2
    return n_files, n_empty


def run_fetch(region, start, end, out_dir, n_stations=None, bands=None, provider=None, catalog_minmag=None,
              clients=None, skip_waveforms=False, min_spacing_km=0.0):
    """Full download for one region; ``clients`` = {name: client} injects test doubles."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = provider or region["provider"]
    bands = bands or region["channel_priority"]
    n_stations = n_stations or region.get("n_stations", 20)
    clients = clients or {}

    def client(name):
        if name not in clients:
            clients[name] = get_client(name)
        return clients[name]

    print(f"[{region['id']}] {start} -> {end}, provider {provider}, bands {bands}, {n_stations} stations")
    inv = fetch_inventory(client(provider), region, start, end, bands)
    cands = candidate_stations(inv, bands, start, end)
    if cands.empty:
        raise SystemExit("no station with 3 components in the requested bands")
    stations = select_stations(cands, n_stations, region["bbox"], min_spacing_km)
    stations.to_csv(out_dir / "stations.csv", index=False)
    subset_inventory(inv, stations).write(str(out_dir / "inventory.xml"), format="STATIONXML")
    print(f"  {len(cands)} candidate stations -> {len(stations)} selected; bands used: "
          f"{stations['band'].value_counts().to_dict()}")
    cat_clients = [(name, client(name)) for name in region.get("catalog_providers", [provider])]
    fetch_catalog(cat_clients, region, start, end,
                  region.get("catalog_minmag", 0.5) if catalog_minmag is None else catalog_minmag, out_dir)
    meta = {"region": region["id"], "region_name": region.get("name", ""), "start": str(start), "end": str(end),
            "provider": provider, "bands": bands, "n_stations": int(len(stations)), "bbox": region["bbox"],
            "network_centre": network_centre(stations)}
    (out_dir / "run.json").write_text(json.dumps(meta, indent=2))
    if not skip_waveforms:
        n_files, n_empty = fetch_waveforms(client(provider), stations, start, end, out_dir)
        print(f"  waveforms: {n_files} station-hours written, {n_empty} without data")
    return out_dir
