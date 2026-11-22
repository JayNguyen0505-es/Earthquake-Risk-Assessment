"""Classic STA/LTA P/S picker, the baseline every deep-learning picker is compared against.

P: recursive STA/LTA on the band-passed vertical component; the pick is the trigger onset.
S: recursive STA/LTA on the band-passed horizontal envelope, first trigger between P + 0.5 s and
   P + ``s_max_after_p`` seconds (one S per P).
This is the logic of most network real-time detectors (e.g. Earthworm pick_ew) in simplified form.
"""

from __future__ import annotations

import numpy as np
from obspy.signal.filter import bandpass
from obspy.signal.trigger import recursive_sta_lta, trigger_onset


class STALTAPicker:
    name = "stalta"

    def __init__(self, sta=0.5, lta=10.0, p_on=3.5, p_off=1.0, s_on=3.0, s_off=1.0,
                 freqmin=2.0, freqmax=15.0, s_max_after_p=60.0, min_separation=2.0):
        self.sta, self.lta = sta, lta
        self.p_on, self.p_off, self.s_on, self.s_off = p_on, p_off, s_on, s_off
        self.freqmin, self.freqmax = freqmin, freqmax
        self.s_max_after_p = s_max_after_p
        self.min_separation = min_separation

    def _filt(self, x, fs):
        fmax = min(self.freqmax, 0.45 * fs)
        x = np.asarray(x, dtype=np.float64)
        x = x - x.mean()
        if fmax <= self.freqmin:
            return x
        return bandpass(x, self.freqmin, fmax, fs, corners=4, zerophase=False)

    def pick_arrays(self, z, n, e, fs):
        """Picks on one station given component arrays: list of (phase, sample, score)."""
        nsta, nlta = max(1, int(self.sta * fs)), max(2, int(self.lta * fs))
        if len(z) <= nlta + 1:
            return []
        cft = recursive_sta_lta(self._filt(z, fs), nsta, nlta)
        cft[: nlta] = 0.0  # LTA warm-up
        picks = []
        last = -np.inf
        for on, off in trigger_onset(cft, self.p_on, self.p_off):
            if (on - last) / fs < self.min_separation:
                continue
            picks.append(("P", int(on), float(cft[on: max(off, on + 1)].max())))
            last = on
        if n is None or e is None or not picks:
            return picks
        h = np.sqrt(self._filt(n, fs) ** 2 + self._filt(e, fs) ** 2)
        cft_s = recursive_sta_lta(h, nsta, max(nsta + 1, nlta // 2))
        cft_s[: nlta // 2] = 0.0
        s_trig = trigger_onset(cft_s, self.s_on, self.s_off)
        p_samples = [p[1] for p in picks]
        out = list(picks)
        for k, p in enumerate(p_samples):
            nxt = p_samples[k + 1] if k + 1 < len(p_samples) else np.inf
            lo, hi = p + int(0.5 * fs), min(p + int(self.s_max_after_p * fs), nxt)
            for on, off in s_trig:
                if lo <= on < hi:
                    out.append(("S", int(on), float(cft_s[on: max(off, on + 1)].max())))
                    break
        return out

    def pick(self, stream):
        """Picks for an obspy Stream with any number of stations -> list of dict rows."""
        rows = []
        for key in sorted({(tr.stats.network, tr.stats.station) for tr in stream}):
            st = stream.select(network=key[0], station=key[1])
            z = st.select(component="Z")
            if not len(z):
                continue
            z = z[0]
            h = [tr for tr in st if tr.stats.channel[-1:] in "NE12" and tr.stats.npts == z.stats.npts]
            n = h[0].data if len(h) >= 2 else None
            e = h[1].data if len(h) >= 2 else None
            fs = z.stats.sampling_rate
            for phase, sample, score in self.pick_arrays(z.data, n, e, fs):
                t = z.stats.starttime + sample / fs
                rows.append({"station": f"{key[0]}.{key[1]}", "network": key[0], "phase": phase,
                             "time": str(t), "time_s": float(t.timestamp), "prob": score,
                             "trace_id": z.id})
        return rows
