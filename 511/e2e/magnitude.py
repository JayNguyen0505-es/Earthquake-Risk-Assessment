"""Event magnitudes for the end-to-end pipeline.

Local magnitude (IASPEI standard): simulate a Wood-Anderson seismograph (static magnification
2080), take the largest horizontal amplitude A in the S window, convert to nm of ground
displacement (A / 2080) and apply  ML = log10(A_nm) + a log10(R) + b R + c  with R the
hypocentral distance in km (a=1.11, b=0.00189, c=-2.09 by default). Event ML = median of stations.

Deep-learning magnitude: dl.magnet.MagnitudePredictor on a window starting 1 s before each P pick;
event value = inverse-variance weighted mean of the station estimates.
"""

from __future__ import annotations

import numpy as np

PAZ_WA = {"poles": [-6.283 + 4.7124j, -6.283 - 4.7124j], "zeros": [0j], "gain": 1.0, "sensitivity": 2080}


def wa_amplitude_nm(st_station, inventory, t1, t2, pad=30.0):
    """Peak horizontal Wood-Anderson amplitude converted to nm of ground displacement, or NaN."""
    st = st_station.copy()
    st.trim(t1 - pad, t2 + pad)
    horiz = [tr for tr in st if tr.stats.channel[-1:] in "NE12"]
    if not horiz:
        return np.nan
    peak = 0.0
    for tr in horiz:
        if tr.stats.npts < 10:
            continue
        fs = tr.stats.sampling_rate
        tr.detrend("demean")
        tr.taper(0.05)
        try:
            tr.remove_response(inventory=inventory, output="VEL", pre_filt=(0.1, 0.25, 0.4 * fs, 0.45 * fs),
                               water_level=60)
        except Exception:
            return np.nan
        tr.simulate(paz_remove=None, paz_simulate=PAZ_WA, water_level=60)
        tr.trim(t1, t2)
        if tr.stats.npts:
            peak = max(peak, float(np.max(np.abs(tr.data))))
    if peak <= 0:
        return np.nan
    return peak / PAZ_WA["sensitivity"] * 1e9  # m on the WA drum -> nm of ground displacement


def ml_from_amplitude(a_nm, r_km, a=1.11, b=0.00189, c=-2.09):
    return float(np.log10(a_nm) + a * np.log10(r_km) + b * r_km + c)


def event_local_magnitude(get_stream, inventory, stations, ev, picks, tt, coeffs, max_dist_km=300.0):
    """ML for one located event.

    get_stream(t1, t2) -> obspy Stream for all stations; stations indexed by station id with
    x_km/y_km; ``picks`` are the event's associated picks; ``tt`` is a TravelTimeTable.
    """
    t1 = ev["origin_time_utc"] - 5
    t2 = ev["origin_time_utc"] + 150
    st = get_stream(t1, t2)
    rows = []
    for sid in sorted(set(picks["station"])):
        r = stations.loc[sid]
        epi = float(np.hypot(r["x_km"] - ev["x_km"], r["y_km"] - ev["y_km"]))
        hyp = float(np.hypot(epi, ev["depth_km"]))
        if hyp > max_dist_km:
            continue
        tp = float(tt(epi, ev["depth_km"], "P"))
        ts = float(tt(epi, ev["depth_km"], "S"))
        w1 = ev["origin_time_utc"] + tp - 2.0
        w2 = ev["origin_time_utc"] + ts + max(10.0, 1.5 * (ts - tp))
        net, code = sid.split(".", 1)
        a_nm = wa_amplitude_nm(st.select(network=net, station=code), inventory, w1, w2)
        if np.isfinite(a_nm) and a_nm > 0:
            rows.append((sid, hyp, a_nm, ml_from_amplitude(a_nm, hyp, **coeffs)))
    if not rows:
        return np.nan, np.nan, 0, rows
    ml = np.array([r[3] for r in rows])
    return float(np.median(ml)), float(np.std(ml)), len(rows), rows


def event_dl_magnitude(predictor, get_stream, inventory, stations, ev, picks):
    from dl.magnet import combine_station_estimates

    p_picks = picks[picks["phase"] == "P"]
    if p_picks.empty:
        return np.nan, np.nan, 0
    t1 = ev["origin_time_utc"] - 5
    st = get_stream(t1, t1 + 150)
    windows, dists = [], []
    out_units = predictor.response_output
    for _, pk in p_picks.iterrows():
        from obspy import UTCDateTime

        net, code = pk["station"].split(".", 1)
        sub = st.select(network=net, station=code).copy()
        if not len(sub):
            continue
        if out_units:
            try:
                sub.detrend("demean")
                sub.taper(0.05)
                for tr in sub:
                    fs = tr.stats.sampling_rate
                    tr.remove_response(inventory=inventory, output=out_units,
                                       pre_filt=(0.05, 0.1, 0.4 * fs, 0.45 * fs), water_level=60)
            except Exception:
                continue
        w = predictor.station_window(sub, UTCDateTime(pk["time"]))
        if w is None:
            continue
        r = stations.loc[pk["station"]]
        epi = float(np.hypot(r["x_km"] - ev["x_km"], r["y_km"] - ev["y_km"]))
        windows.append(w)
        dists.append(float(np.hypot(epi, ev["depth_km"])))
    if not windows:
        return np.nan, np.nan, 0
    mu, lv = predictor.predict(windows, dists)
    m, se, _ = combine_station_estimates(mu, lv)
    return m, se, len(windows)
