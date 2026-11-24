"""Event magnitudes for the end-to-end pipeline, with the station-level estimates kept.

Local magnitude (IASPEI standard): simulate a Wood-Anderson seismograph (static magnification
2080), take the largest horizontal amplitude A in the S window, convert to nm of ground
displacement (A / 2080) and apply  ML = log10(A_nm) + a log10(R) + b R + c  with R the
hypocentral distance in km (a=1.11, b=0.00189, c=-2.09 by default). Event ML = median of stations.
The same processing is applied to a pre-P noise window, so every station magnitude carries an SNR.

Deep-learning magnitude: dl.magnet.MagnitudePredictor on a window starting 1 s before each P time;
event value = inverse-variance weighted mean of the station estimates, standard error
sqrt(tau^2 + 1/sum w) with tau the shared event error stored in the checkpoint (0 for --loss gaussian).

Station rows (one dict per station and estimator) are what calibration_study.py consumes:
    station, estimator ("ml" | "dl"), m_pred, sd (DL only), hyp_km, azimuth, snr, p_time, + features
"""

from __future__ import annotations

import numpy as np

PAZ_WA = {"poles": [-6.283 + 4.7124j, -6.283 - 4.7124j], "zeros": [0j], "gain": 1.0, "sensitivity": 2080}


def wa_peaks_nm(st_station, inventory, windows, pad=30.0):
    """Peak horizontal Wood-Anderson amplitude (nm of ground displacement) in each (t1, t2) window."""
    t_lo = min(w[0] for w in windows) - pad
    t_hi = max(w[1] for w in windows) + pad
    st = st_station.copy()
    st.trim(t_lo, t_hi)
    horiz = [tr for tr in st if tr.stats.channel[-1:] in "NE12"]
    peaks = [0.0] * len(windows)
    if not horiz:
        return [np.nan] * len(windows)
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
            return [np.nan] * len(windows)
        tr.simulate(paz_remove=None, paz_simulate=PAZ_WA, water_level=60)
        for k, (t1, t2) in enumerate(windows):
            seg = tr.slice(t1, t2)
            if seg.stats.npts:
                peaks[k] = max(peaks[k], float(np.max(np.abs(seg.data))))
    return [p / PAZ_WA["sensitivity"] * 1e9 if p > 0 else np.nan for p in peaks]


def wa_amplitude_nm(st_station, inventory, t1, t2, pad=30.0):
    """Peak horizontal Wood-Anderson amplitude converted to nm of ground displacement, or NaN."""
    return wa_peaks_nm(st_station, inventory, [(t1, t2)], pad)[0]


def ml_from_amplitude(a_nm, r_km, a=1.11, b=0.00189, c=-2.09):
    return float(np.log10(a_nm) + a * np.log10(r_km) + b * r_km + c)


def station_geometry(stations, ev, sid):
    """(epicentral km, hypocentral km, event-to-station azimuth deg) in the local x/y frame."""
    r = stations.loc[sid]
    dx, dy = float(r["x_km"] - ev["x_km"]), float(r["y_km"] - ev["y_km"])
    epi = float(np.hypot(dx, dy))
    return epi, float(np.hypot(epi, ev["depth_km"])), float((np.degrees(np.arctan2(dx, dy)) + 360) % 360)


def station_local_magnitudes(st, inventory, ev, station_ids, stations, tt, coeffs, max_dist_km=300.0):
    """Station ML rows for one event (S-window amplitude, pre-P noise amplitude, SNR)."""
    rows = []
    for sid in station_ids:
        epi, hyp, az = station_geometry(stations, ev, sid)
        if hyp > max_dist_km:
            continue
        tp = float(tt(epi, ev["depth_km"], "P"))
        ts = float(tt(epi, ev["depth_km"], "S"))
        t_p = ev["origin_time_utc"] + tp
        w_sig = (t_p - 2.0, ev["origin_time_utc"] + ts + max(10.0, 1.5 * (ts - tp)))
        w_noise = (t_p - 12.0, t_p - 2.0)
        net, code = sid.split(".", 1)
        a_sig, a_noise = wa_peaks_nm(st.select(network=net, station=code), inventory, [w_sig, w_noise])
        if np.isfinite(a_sig) and a_sig > 0:
            rows.append({"station": sid, "estimator": "ml", "m_pred": ml_from_amplitude(a_sig, hyp, **coeffs),
                         "sd": np.nan, "hyp_km": hyp, "azimuth": az, "a_nm": a_sig,
                         "snr": a_sig / a_noise if np.isfinite(a_noise) and a_noise > 0 else np.nan})
    return rows


def event_local_magnitude(get_stream, inventory, stations, ev, picks, tt, coeffs, max_dist_km=300.0):
    """ML for one located event: (median, std, n, station rows).

    get_stream(t1, t2) -> obspy Stream for all stations; stations indexed by station id with
    x_km/y_km; ``picks`` are the event's associated picks; ``tt`` is a TravelTimeTable.
    """
    st = get_stream(ev["origin_time_utc"] - 20, ev["origin_time_utc"] + 150)
    rows = station_local_magnitudes(st, inventory, ev, sorted(set(picks["station"])), stations, tt, coeffs,
                                    max_dist_km)
    if not rows:
        return np.nan, np.nan, 0, rows
    ml = np.array([r["m_pred"] for r in rows])
    return float(np.median(ml)), float(np.std(ml)), len(rows), rows


def station_dl_magnitudes(predictor, st, inventory, ev, p_times, stations):
    """Station DL rows for one event. p_times: {station id: UTCDateTime of P}."""
    windows, meta = [], []
    out_units = predictor.response_output
    for sid, p_time in p_times.items():
        net, code = sid.split(".", 1)
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
        w = predictor.station_window(sub, p_time)
        if w is None:
            continue
        _, hyp, az = station_geometry(stations, ev, sid)
        windows.append(w)
        meta.append({"station": sid, "estimator": "dl", "hyp_km": hyp, "azimuth": az, "p_time": float(p_time.timestamp)})
    if not windows:
        return []
    mu, lv = predictor.predict(windows, [m["hyp_km"] for m in meta])
    feats = predictor.last_features
    names = ["log_amp_z", "log_amp_n", "log_amp_e", "logdist"]
    for k, m in enumerate(meta):
        m.update({"m_pred": float(mu[k]), "logvar": float(lv[k]), "sd": float(np.exp(0.5 * lv[k]))})
        m.update({n: float(feats[k, j]) for j, n in enumerate(names)})
    return meta


def event_dl_magnitude(predictor, get_stream, inventory, stations, ev, picks):
    """DL magnitude for one located event from its P picks: (m, se, n, station rows)."""
    from obspy import UTCDateTime

    from dl.magnet import combine_station_estimates

    p_picks = picks[picks["phase"] == "P"]
    if p_picks.empty:
        return np.nan, np.nan, 0, []
    st = get_stream(ev["origin_time_utc"] - 5, ev["origin_time_utc"] + 150)
    p_times = {}
    for _, pk in p_picks.sort_values("time").iterrows():
        p_times.setdefault(pk["station"], UTCDateTime(float(pk["time"])))
    rows = station_dl_magnitudes(predictor, st, inventory, ev, p_times, stations)
    if not rows:
        return np.nan, np.nan, 0, rows
    m, se, _ = combine_station_estimates([r["m_pred"] for r in rows], [r["logvar"] for r in rows],
                                         getattr(predictor, "tau", 0.0))
    return m, se, len(rows), rows
