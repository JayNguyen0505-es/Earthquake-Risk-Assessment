"""Offline stand-in for an FDSN web service, for tests and the self-test.

Generates a station network, a catalogue with exact P/S arrivals, and waveforms whose amplitudes are
consistent with the IASPEI local-magnitude formula, so the full chain (fetch -> pick -> associate ->
locate -> ML -> evaluate) can be checked end to end without network access. It implements the
subset of obspy's FDSN Client API used by e2e.fetch.
"""

from __future__ import annotations

import zlib

import numpy as np

from loc.geometry import from_local_km, to_local_km
from loc.velocity import TravelTimeTable


class FakeFDSN:
    def __init__(self, region, vmodel, start, end, n_stations=14, n_events=8, seed=0, fs=100.0, gain=1e9,
                 noise=2e-8, mag_range=(1.8, 3.5), f_s=4.0):
        from obspy import UTCDateTime

        self.rng = np.random.default_rng(seed)
        self.region, self.fs, self.gain, self.noise, self.f_s = region, fs, gain, noise, f_s
        self.start, self.end = UTCDateTime(start), UTCDateTime(end)
        minlon, minlat, maxlon, maxlat = region["bbox"]
        self.lat0, self.lon0 = (minlat + maxlat) / 2, (minlon + maxlon) / 2
        w = to_local_km(self.lat0, maxlon, self.lat0, self.lon0)[0]
        h = to_local_km(maxlat, self.lon0, self.lat0, self.lon0)[1]
        sx, sy = self.rng.uniform(-w, w, n_stations), self.rng.uniform(-h, h, n_stations)
        slat, slon = from_local_km(sx, sy, self.lat0, self.lon0)
        self.stations = [{"code": f"S{i:02d}", "lat": float(a), "lon": float(b), "elev_m": float(self.rng.uniform(0, 1000)),
                          "x": float(x), "y": float(y)} for i, (a, b, x, y) in enumerate(zip(slat, slon, sx, sy))]
        span = self.end - self.start
        ex, ey = self.rng.uniform(-0.6 * w, 0.6 * w, n_events), self.rng.uniform(-0.6 * h, 0.6 * h, n_events)
        elat, elon = from_local_km(ex, ey, self.lat0, self.lon0)
        times = np.sort(self.rng.uniform(300, span - 300, n_events))
        self.events = [{"id": f"ev{k:03d}", "t": self.start + float(times[k]), "lat": float(elat[k]), "lon": float(elon[k]),
                        "x": float(ex[k]), "y": float(ey[k]), "depth": float(self.rng.uniform(4, 16)),
                        "mag": float(self.rng.uniform(*mag_range))} for k in range(n_events)]
        self.tt = TravelTimeTable(vmodel, max_dist_km=600.0)
        self.vp0, self.vs0 = vmodel.vp[0], vmodel.vs[0]
        for ev in self.events:
            ev["arr"] = {}
            for s in self.stations:
                epi = float(np.hypot(s["x"] - ev["x"], s["y"] - ev["y"]))
                hyp = float(np.hypot(epi, ev["depth"]))
                tp = float(self.tt(epi, ev["depth"], "P")) + s["elev_m"] / 1000 / self.vp0
                ts = float(self.tt(epi, ev["depth"], "S")) + s["elev_m"] / 1000 / self.vs0
                d_nm = 10 ** (ev["mag"] - 1.11 * np.log10(hyp) - 0.00189 * hyp + 2.09)  # IASPEI ML inverted
                ev["arr"][s["code"]] = (ev["t"] + tp, ev["t"] + ts, d_nm)

    # ---- obspy Client API subset -----------------------------------------------------------------
    def get_stations(self, **kwargs):
        from obspy.core.inventory import Channel, Inventory, Network, Response, Station

        resp = Response.from_paz(zeros=[], poles=[], stage_gain=self.gain, input_units="M/S", output_units="COUNTS")
        stas = []
        for s in self.stations:
            chans = [Channel(code=f"HH{c}", location_code="", latitude=s["lat"], longitude=s["lon"],
                             elevation=s["elev_m"], depth=0.0, azimuth=az, dip=dip, sample_rate=self.fs,
                             response=resp, start_date=self.start - 86400 * 365)
                     for c, az, dip in (("Z", 0.0, -90.0), ("N", 0.0, 0.0), ("E", 90.0, 0.0))]
            stas.append(Station(code=s["code"], latitude=s["lat"], longitude=s["lon"], elevation=s["elev_m"],
                                channels=chans, creation_date=self.start - 86400 * 365))
        return Inventory(networks=[Network(code="XX", stations=stas)], source="FakeFDSN")

    def get_events(self, starttime=None, endtime=None, includearrivals=False, **kwargs):
        from obspy.core.event import (Arrival, Catalog, Event, Magnitude, Origin, Pick, ResourceIdentifier,
                                      WaveformStreamID)
        from obspy.clients.fdsn.header import FDSNNoDataException

        evs = []
        for ev in self.events:
            if (starttime and ev["t"] < starttime) or (endtime and ev["t"] >= endtime):
                continue
            o = Origin(time=ev["t"], latitude=ev["lat"], longitude=ev["lon"], depth=ev["depth"] * 1000,
                       resource_id=ResourceIdentifier(f"smi:fake/origin/{ev['id']}"))
            e = Event(resource_id=ResourceIdentifier(f"smi:fake/event?eventId={ev['id']}"), origins=[o],
                      magnitudes=[Magnitude(mag=round(ev["mag"], 2), magnitude_type="ML")])
            e.preferred_origin_id = o.resource_id
            if includearrivals:
                for s in self.stations:
                    tp, ts, _ = ev["arr"][s["code"]]
                    for ph, t in (("P", tp), ("S", ts)):
                        pk = Pick(time=t, phase_hint=ph, waveform_id=WaveformStreamID("XX", s["code"], "", "HHZ"),
                                  resource_id=ResourceIdentifier(f"smi:fake/pick/{ev['id']}/{s['code']}/{ph}"))
                        e.picks.append(pk)
                        o.arrivals.append(Arrival(pick_id=pk.resource_id, phase=ph))
            evs.append(e)
        if not evs:
            raise FDSNNoDataException("No data available")
        return Catalog(events=evs)

    def _wavelet(self, n, t_rel, freq, dur, amp, rng):
        t = np.arange(n) / self.fs - t_rel
        tc = np.clip(t, 0.0, None)
        env = np.where(t >= 0, (1 - np.exp(-tc / 0.05)) * np.exp(-tc / dur), 0.0)
        return amp * env * np.sin(2 * np.pi * freq * t + rng.uniform(0, 2 * np.pi))

    def get_waveforms(self, network, station, location, channel, starttime, endtime, **kwargs):
        from obspy import Stream, Trace

        n = int(round((endtime - starttime) * self.fs))
        seed = zlib.crc32(f"{station}{int(starttime.timestamp)}".encode())
        rng = np.random.default_rng(seed)
        data = self.noise * rng.standard_normal((3, n))
        for ev in self.events:
            tp, ts, d_nm = ev["arr"][station]
            if ts < starttime - 60 or tp > endtime + 1:
                continue
            ev_rng = np.random.default_rng(zlib.crc32(f"{ev['id']}{station}".encode()))
            v_s = 2 * np.pi * self.f_s * d_nm * 1e-9          # S velocity amplitude giving the target WA amplitude
            dur = 0.4 + 0.5 * ev["mag"]
            data[0] += self._wavelet(n, tp - starttime, 8.0, 0.4 * dur, v_s / 3, ev_rng)
            data[0] += self._wavelet(n, ts - starttime, self.f_s, dur, 0.3 * v_s, ev_rng)
            for c in (1, 2):
                data[c] += self._wavelet(n, tp - starttime, 8.0, 0.4 * dur, v_s / 10, ev_rng)
                data[c] += self._wavelet(n, ts - starttime, self.f_s, dur, v_s, ev_rng)
        st = Stream()
        for c, comp in enumerate("ZNE"):
            tr = Trace((data[c] * self.gain).astype(np.float32))
            tr.stats.update({"network": "XX", "station": station, "location": "", "channel": f"HH{comp}",
                             "sampling_rate": self.fs, "starttime": starttime})
            st += tr
        return st

    def get_waveforms_bulk(self, bulk, **kwargs):
        from obspy import Stream

        st = Stream()
        for net, sta, loc, cha, t1, t2 in bulk:
            st += self.get_waveforms(net, sta, loc, cha, t1, t2)
        return st
