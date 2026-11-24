"""Deep-learning magnitude estimation (Part C of 5.1.1).

Architecture follows MagNet (Mousavi & Beroza 2020): a convolutional encoder and a bidirectional
LSTM read a 3-component window that starts shortly before the P arrival. Two additions make it
usable in a network pipeline:

* scalar features: log10 of the peak amplitude of each component (lost by waveform normalisation)
  and log10 hypocentral distance (known once 5.1.1 has located the event). Magnitude is, to first
  order, log(amplitude) + attenuation(distance); giving the network both is what lets it transfer.
* Gaussian negative log-likelihood: the network predicts a mean and a variance, so each station
  estimate carries its own uncertainty; the event magnitude is the inverse-variance weighted mean.

Amplitude features are only meaningful in physical units (ground-motion datasets such as
InstanceGM, AQ2009GM); for count datasets (STEAD, ETHZ) train with ``use_amplitude=False``.
"""

from __future__ import annotations

import numpy as np

from .data import hypocentral_distance_km

DEFAULT_WINDOW = 3000   # 30 s at 100 Hz
DEFAULT_PRE = 100       # 1 s before P


def build_model(n_scalar, width=32, lstm=64, dropout=0.2):
    import torch
    from torch import nn

    class MagNet(nn.Module):
        def __init__(self):
            super().__init__()

            def block(cin, cout, k, pool):
                return nn.Sequential(nn.Conv1d(cin, cout, k, padding=k // 2), nn.BatchNorm1d(cout), nn.ReLU(),
                                     nn.MaxPool1d(pool))

            self.encoder = nn.Sequential(block(3, width, 7, 4), block(width, width, 5, 4),
                                         block(width, 2 * width, 5, 4), block(2 * width, 2 * width, 3, 2))
            self.lstm = nn.LSTM(2 * width, lstm, batch_first=True, bidirectional=True)
            self.head = nn.Sequential(nn.Linear(4 * lstm + n_scalar, 64), nn.ReLU(), nn.Dropout(dropout),
                                      nn.Linear(64, 2))
            self.n_scalar = n_scalar

        def forward(self, x, s):
            h = self.encoder(x).transpose(1, 2)        # (B, T, C)
            h, _ = self.lstm(h)
            h = torch.cat([h.mean(1), h.amax(1)], dim=1)
            if self.n_scalar:
                h = torch.cat([h, s], dim=1)
            out = self.head(h)
            return out[:, 0], out[:, 1].clamp(-7.0, 5.0)  # mean, log-variance

    return MagNet()


def gaussian_nll(mu, logvar, y):
    import torch

    return (0.5 * (torch.exp(-logvar) * (y - mu) ** 2 + logvar)).mean()


def event_nll(mu, logvar, y, event_idx, log_tau):
    """Gaussian NLL with an error shared by all stations of an event (mean per station).

    Residuals of one event r = y - mu have covariance tau^2 11' + diag(exp(logvar)). With tau -> 0 this
    is gaussian_nll; with tau > 0 the network is no longer pushed to explain the event-level error with
    small per-station variances, and tau is learned jointly. Closed form via Sherman-Morrison.
    """
    import torch

    r = y - mu
    w = torch.exp(-logvar)
    uniq, inv = torch.unique(event_idx, return_inverse=True)
    z = torch.zeros(len(uniq), dtype=mu.dtype, device=mu.device)
    A = z.index_add(0, inv, w)
    B = z.index_add(0, inv, w * r)
    C = z.index_add(0, inv, w * r * r)
    L = z.index_add(0, inv, logvar)
    tau2 = torch.exp(2 * log_tau)
    quad = C - tau2 * B * B / (1 + tau2 * A)
    logdet = L + torch.log1p(tau2 * A)
    return 0.5 * (quad + logdet).sum() / len(mu)


class EventBatchSampler:
    """Batches made of whole events: ``events_per_batch`` events, at most ``max_stations`` traces each.

    Needed by event_nll, which only sees the shared error when several stations of one event are in
    the same batch. ``groups`` is the event id of every sample (positional, as in the generator).
    """

    def __init__(self, groups, events_per_batch=32, max_stations=16, shuffle=True, seed=0):
        import pandas as pd

        codes, _ = pd.factorize(pd.Series(groups).astype(str))
        order = np.argsort(codes, kind="stable")
        bounds = np.flatnonzero(np.diff(codes[order])) + 1
        self.events = [g for g in np.split(order, bounds) if len(g)]
        self.epb, self.max_st, self.shuffle = events_per_batch, max_stations, shuffle
        self.rng = np.random.default_rng(seed)

    def __iter__(self):
        ev = list(self.events)
        if self.shuffle:
            self.rng.shuffle(ev)
        for i in range(0, len(ev), self.epb):
            batch = []
            for g in ev[i:i + self.epb]:
                if self.max_st and len(g) > self.max_st:
                    g = self.rng.choice(g, self.max_st, replace=False) if self.shuffle else g[:self.max_st]
                batch.extend(int(j) for j in g)
            yield batch

    def __len__(self):
        return (len(self.events) + self.epb - 1) // self.epb


# ---- SeisBench generator augmentations (callables on the state dict) ---------------------------------
class AmplitudeAndDistance:
    """Store log10 peak amplitude per component and log10 hypocentral distance before normalisation."""

    def __init__(self, key="X", eps=1e-12):
        self.key, self.eps = key, eps

    def __call__(self, state_dict):
        x, meta = state_dict[self.key]
        x = np.asarray(x, dtype=np.float64)
        x = x - x.mean(axis=-1, keepdims=True)
        amp = np.log10(np.abs(x).max(axis=-1) + self.eps).astype(np.float32)
        r = hypocentral_distance_km(meta)
        state_dict["amp"] = (amp, None)
        state_dict["logdist"] = (np.array([np.log10(r) if np.isfinite(r) else np.nan], dtype=np.float32), None)


class EventCode:
    """Integer event index per sample (for event_nll), from a {source_id: int} mapping."""

    def __init__(self, mapping, column="source_id"):
        self.mapping, self.column = mapping, column

    def __call__(self, state_dict):
        _, meta = state_dict["X"]
        state_dict["eid"] = (np.array(self.mapping.get(str(meta.get(self.column)), -1), dtype=np.int64), None)


class MagnitudeLabel:
    def __init__(self, column="source_magnitude"):
        self.column = column

    def __call__(self, state_dict):
        _, meta = state_dict["X"]
        state_dict["y"] = (np.array(float(meta[self.column]), dtype=np.float32), None)


def make_generator(dataset, window=DEFAULT_WINDOW, pre=DEFAULT_PRE, p_column="trace_p_arrival_sample"):
    import seisbench.generate as sbg

    ids = dataset.metadata["source_id"].astype(str) if "source_id" in dataset.metadata else None
    mapping = {} if ids is None else {sid: i for i, sid in enumerate(ids.unique())}
    gen = sbg.GenericGenerator(dataset)
    gen.add_augmentations([
        sbg.WindowAroundSample([p_column], samples_before=pre, windowlen=window, selection="first", strategy="pad"),
        AmplitudeAndDistance(),
        sbg.Normalize(demean_axis=-1, amp_norm_axis=-1, amp_norm_type="peak"),
        sbg.ChangeDtype(np.float32),
        MagnitudeLabel(),
        EventCode(mapping),
    ])
    return gen


def scalar_matrix(amp, logdist, use_amplitude=True):
    """(B, n_scalar) raw scalar features; NaN distances become NaN (filled by the scaler)."""
    cols = []
    if use_amplitude:
        cols.append(np.asarray(amp, dtype=np.float32).reshape(len(logdist), -1))
    cols.append(np.asarray(logdist, dtype=np.float32).reshape(-1, 1))
    return np.concatenate(cols, axis=1)


class ScalarScaler:
    def __init__(self, mean=None, std=None):
        self.mean = None if mean is None else np.asarray(mean, dtype=np.float32)
        self.std = None if std is None else np.asarray(std, dtype=np.float32)

    def fit(self, s):
        self.mean = np.nanmean(s, axis=0).astype(np.float32)
        self.std = (np.nanstd(s, axis=0) + 1e-6).astype(np.float32)
        return self

    def transform(self, s):
        z = (np.asarray(s, dtype=np.float32) - self.mean) / self.std
        return np.nan_to_num(z, nan=0.0).astype(np.float32)  # missing distance -> training mean


def combine_station_estimates(mu, logvar, tau=0.0):
    """Inverse-variance weighted event magnitude, its standard error and the station median.

    tau = 0 treats stations as independent (the standard error then shrinks like 1/sqrt(n), which is
    overconfident because station errors of one event are correlated). Pass the shared-error tau
    learned with --loss event (or fitted by calibration_study.py) to get sqrt(tau^2 + 1/sum w).
    """
    mu, var = np.asarray(mu, float), np.exp(np.asarray(logvar, float))
    w = 1.0 / var
    m = float(np.sum(w * mu) / np.sum(w))
    return m, float(np.sqrt(tau ** 2 + 1.0 / np.sum(w))), float(np.median(mu))


# ---- inference on raw obspy data (used by the end-to-end pipeline) ------------------------------------
class MagnitudePredictor:
    """Load a checkpoint written by train_magnitude.py and predict from obspy traces."""

    def __init__(self, checkpoint, device="cpu"):
        import torch

        ck = torch.load(checkpoint, map_location=device, weights_only=False)
        self.cfg = ck["config"]
        self.scaler = ScalarScaler(ck["scaler_mean"], ck["scaler_std"])
        self.model = build_model(len(ck["scaler_mean"]), **self.cfg.get("arch", {}))
        self.model.load_state_dict(ck["state_dict"])
        self.model.to(device).eval()
        self.device = device
        self.tau = float(ck.get("tau") or 0.0)  # shared event error learned with --loss event

    @property
    def response_output(self):
        """obspy remove_response output matching the training data units, or None for counts."""
        if not self.cfg.get("physical_units", False):
            return None
        return {"acceleration": "ACC", "velocity": "VEL", "displacement": "DISP"}.get(self.cfg.get("measurement"), "VEL")

    def station_window(self, st, p_time):
        """3 x window array (Z, N/1, E/2) at 100 Hz starting ``pre`` samples before p_time, or None."""
        fs = 100.0
        win, pre = self.cfg["window"], self.cfg["pre"]
        st = st.copy()
        for tr in st:
            if abs(tr.stats.sampling_rate - fs) > 1e-6:
                tr.resample(fs) if tr.stats.sampling_rate > fs else tr.interpolate(fs)
        t0 = p_time - pre / fs
        st.trim(t0, t0 + (win - 1) / fs, pad=True, fill_value=0.0)
        comps = []
        for codes in ("Z", "N1", "E2"):
            tr = [t for t in st if t.stats.channel[-1:] in codes]
            if not tr:
                return None
            d = np.asarray(tr[0].data, dtype=np.float64)[:win]
            comps.append(np.pad(d, (0, win - len(d))))
        return np.stack(comps)

    def predict(self, windows, distances_km):
        import torch

        x = np.stack(windows).astype(np.float64)
        x = x - x.mean(axis=-1, keepdims=True)
        amp = np.log10(np.abs(x).max(axis=-1) + 1e-12)
        x = x / (np.abs(x).max(axis=-1, keepdims=True) + 1e-10)
        logd = np.log10(np.maximum(np.asarray(distances_km, float), 0.1))
        s = self.scaler.transform(scalar_matrix(amp, logd, self.cfg.get("use_amplitude", True)))
        with torch.no_grad():
            mu, lv = self.model(torch.from_numpy(x.astype(np.float32)).to(self.device),
                                torch.from_numpy(s).to(self.device))
        self.last_features = np.column_stack([amp, logd])  # for train/deployment feature-shift checks
        return mu.cpu().numpy(), lv.cpu().numpy()
