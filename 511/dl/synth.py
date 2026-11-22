"""Synthetic SeisBench-format dataset with known P/S arrivals and magnitudes.

Used by the unit tests and by ``make_synthetic_dataset.py`` to smoke-test the picker benchmark,
picker fine-tuning and magnitude training on a new machine before downloading tens of GB.
Waveforms are ground velocity (m/s); amplitudes follow a Richter-type attenuation so that a
magnitude model has something physical to learn. The numbers are not realistic seismology.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _wavelet(n, start, freq, dur, amp, fs, rng):
    t = (np.arange(n) - start) / fs
    tc = np.clip(t, 0.0, None)
    env = np.where(t >= 0, np.exp(-tc / max(dur, 0.2)) * (1 - np.exp(-tc / 0.05)), 0.0)
    phase = rng.uniform(0, 2 * np.pi)
    return amp * env * np.sin(2 * np.pi * freq * t + phase)


def synthetic_trace(mag, dist_km, depth_km, fs=100.0, length_s=60.0, p_at_s=None, noise=2e-8, rng=None,
                    vp=6.0, vs=3.47):
    rng = rng or np.random.default_rng()
    n = int(length_s * fs)
    r = float(np.hypot(dist_km, depth_km))
    p_s = p_at_s if p_at_s is not None else rng.uniform(5.0, 15.0)
    s_s = p_s + r / vs - r / vp
    # peak ground velocity (m/s) from a Richter-like relation: log10 A = M - 1.11 log10 R - 0.00189 R - 5.3
    a_s = 10 ** (mag - 1.11 * np.log10(r) - 0.00189 * r - 5.3)
    a_p = a_s / 3.0
    dur = 0.5 + 0.6 * max(mag, 0.5)
    wf = noise * rng.standard_normal((3, n))
    p_i, s_i = int(p_s * fs), int(s_s * fs)
    wf[0] += _wavelet(n, p_i, 6.0, dur * 0.5, a_p, fs, rng)
    wf[1:] += 0.3 * _wavelet(n, p_i, 6.0, dur * 0.5, a_p, fs, rng)
    for c in (1, 2):
        wf[c] += _wavelet(n, s_i, 3.0, dur, a_s * rng.uniform(0.7, 1.0), fs, rng)
    wf[0] += 0.4 * _wavelet(n, s_i, 3.0, dur, a_s, fs, rng)
    return wf.astype(np.float32), p_i, (s_i if s_i < n else np.nan)


def write_dataset(path, n_events=60, stations_per_event=8, fs=100.0, length_s=60.0, seed=0,
                  channel="HH", measurement="velocity", noise_traces=0):
    import seisbench.data as sbd

    rng = np.random.default_rng(seed)
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    meta_path, wf_path = path / "metadata.csv", path / "waveforms.hdf5"
    for p in (meta_path, wf_path):
        if p.exists():
            p.unlink()
    with sbd.WaveformDataWriter(meta_path, wf_path) as writer:
        writer.data_format = {"dimension_order": "CW", "component_order": "ZNE", "measurement": measurement,
                              "unit": "mps", "instrument_response": "restituted"}
        for e in range(n_events):
            mag = rng.uniform(1.0, 5.0)
            depth = rng.uniform(3.0, 20.0)
            ev_lat, ev_lon = 21.5 + rng.uniform(-0.5, 0.5), 103.5 + rng.uniform(-0.5, 0.5)
            split = ["train", "dev", "test"][int(rng.choice(3, p=[0.7, 0.15, 0.15]))]
            for s in range(stations_per_event):
                dist = float(np.exp(rng.uniform(np.log(5.0), np.log(150.0))))
                wf, p_i, s_i = synthetic_trace(mag, dist, depth, fs, length_s, rng=rng)
                writer.add_trace({
                    "source_id": f"EV{e:05d}", "source_magnitude": round(mag, 2), "source_magnitude_type": "ML",
                    "source_latitude_deg": ev_lat, "source_longitude_deg": ev_lon, "source_depth_km": depth,
                    "station_network_code": "SY", "station_code": f"S{s:03d}",
                    "station_latitude_deg": ev_lat, "station_longitude_deg": ev_lon,
                    "path_ep_distance_km": dist, "trace_channel": channel, "trace_category": "earthquake_local",
                    "trace_sampling_rate_hz": fs, "trace_start_time": "2020-01-01T00:00:00",
                    "trace_p_arrival_sample": p_i, "trace_s_arrival_sample": s_i, "split": split,
                }, wf)
        for k in range(noise_traces):
            wf = (2e-8 * rng.standard_normal((3, int(length_s * fs)))).astype(np.float32)
            writer.add_trace({"source_id": None, "station_network_code": "SY", "station_code": f"N{k:03d}",
                              "trace_channel": channel, "trace_category": "noise", "trace_sampling_rate_hz": fs,
                              "trace_start_time": "2020-01-01T00:00:00", "split": "test"}, wf)
    return path
