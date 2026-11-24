"""Compare an automatic catalogue with the reference (agency) catalogue.

Matching: a detected event and a reference event are a candidate pair if their origin times differ by
at most ``max_dt`` seconds and their epicentres by at most ``max_km``. Pairs are assigned one-to-one,
first maximising the number of matched pairs, then minimising the time difference (linear assignment
per connected group of candidates). Picks are matched to analyst arrivals the same way. Reported: detection recall (overall and per magnitude
bin), precision, location errors, magnitude errors, and pick recall/residuals against the analyst
arrivals on the stations of the network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from loc.geometry import to_local_km

MAG_BINS = [-1, 1, 1.5, 2, 2.5, 3, 4, 10]


def one_to_one(i, j, cost):
    """Indices into the candidate pairs (i[k], j[k]) forming a maximum-cardinality, then minimum-cost,
    one-to-one matching. cost must lie in [0, 1]."""
    from scipy.optimize import linear_sum_assignment
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    i, j, cost = np.asarray(i), np.asarray(j), np.asarray(cost, float)
    if len(i) == 0:
        return np.array([], dtype=int)
    _, ii = np.unique(i, return_inverse=True)
    _, jj = np.unique(j, return_inverse=True)
    n1, n2 = ii.max() + 1, jj.max() + 1
    g = coo_matrix((np.ones(len(i)), (ii, n1 + jj)), shape=(n1 + n2, n1 + n2))
    _, lab = connected_components(g, directed=False)
    comp = lab[ii]
    order = np.argsort(comp, kind="stable")
    bounds = np.flatnonzero(np.diff(comp[order])) + 1
    keep = []
    for ks in np.split(order, bounds):
        if len(ks) == 1:
            keep.append(int(ks[0]))
            continue
        ri, rinv = np.unique(ii[ks], return_inverse=True)
        ci, cinv = np.unique(jj[ks], return_inverse=True)
        big = 2.0 * min(len(ri), len(ci)) + 10.0  # any extra valid pair outweighs all costs
        m = np.full((len(ri), len(ci)), big)
        idx = np.full((len(ri), len(ci)), -1)
        m[rinv, cinv] = cost[ks]
        idx[rinv, cinv] = ks
        r, c = linear_sum_assignment(m)
        sel = idx[r, c]
        keep.extend(int(k) for k in sel[sel >= 0])
    return np.sort(np.array(keep, dtype=int))


def match_events(det, ref, max_dt=3.0, max_km=25.0):
    if det.empty or ref.empty:
        return pd.DataFrame(columns=["det", "ref", "dt_s", "epi_err_km"])
    lat0, lon0 = float(ref["lat"].mean()), float(ref["lon"].mean())
    dx, dy = to_local_km(det["lat"].to_numpy(), det["lon"].to_numpy(), lat0, lon0)
    rx, ry = to_local_km(ref["lat"].to_numpy(), ref["lon"].to_numpy(), lat0, lon0)
    dt = det["time_s"].to_numpy()[:, None] - ref["time_s"].to_numpy()[None, :]
    dist = np.hypot(dx[:, None] - rx[None, :], dy[:, None] - ry[None, :])
    cand = np.argwhere((np.abs(dt) <= max_dt) & (dist <= max_km))
    if not len(cand):
        return pd.DataFrame(columns=["det", "ref", "dt_s", "epi_err_km"])
    ci, cj = cand[:, 0], cand[:, 1]
    cost = 0.999 * np.abs(dt[ci, cj]) / max_dt + 0.001 * dist[ci, cj] / max_km
    sel = one_to_one(ci, cj, cost)
    rows = [{"det": int(ci[k]), "ref": int(cj[k]), "dt_s": float(dt[ci[k], cj[k]]),
             "epi_err_km": float(dist[ci[k], cj[k]])} for k in sel]
    return pd.DataFrame(rows).sort_values("ref").reset_index(drop=True)


def _stats(x):
    x = pd.Series(x, dtype=float).dropna()
    if x.empty:
        return {"n": 0}
    return {"n": int(len(x)), "mean": float(x.mean()), "median": float(x.median()), "std": float(x.std()) if len(x) > 1 else 0.0,
            "mae": float(x.abs().mean()), "p90_abs": float(x.abs().quantile(0.9))}


def event_metrics(det, ref, matches):
    out = {"n_reference": int(len(ref)), "n_detected": int(len(det)), "n_matched": int(len(matches))}
    out["recall"] = len(matches) / max(len(ref), 1)
    out["precision"] = len(matches) / max(len(det), 1)
    if matches.empty:
        return out
    d = det.iloc[matches["det"]].reset_index(drop=True)
    r = ref.iloc[matches["ref"]].reset_index(drop=True)
    out["epicentre_error_km"] = _stats(matches["epi_err_km"])
    out["depth_error_km"] = _stats(d["depth_km"] - r["depth_km"])
    out["origin_time_error_s"] = _stats(matches["dt_s"])
    for col in ("ml", "m_dl"):
        if col in d:
            out[f"{col}_minus_reference"] = _stats(d[col] - r["mag"])
    return out


def in_bbox(df, bbox):
    minlon, minlat, maxlon, maxlat = bbox
    return ((df["lon"] >= minlon) & (df["lon"] <= maxlon) & (df["lat"] >= minlat) & (df["lat"] <= maxlat)).to_numpy()


def region_metrics(det, ref, matches, bbox, minmag=None):
    """Precision over the detections the reference catalogue could contain.

    The agency catalogue is requested for one bbox and a minimum magnitude, while the network also
    detects events outside the box and below that magnitude, so plain precision is biased low. Here
    precision counts only detections inside the bbox, and (when an ML is available) with ML at or above
    the catalogue's minimum magnitude. Unmatched detections inside the box are summarised by ML: if
    they are mostly small, they are likely real events missing from the agency catalogue.
    """
    if det.empty:
        return {}
    matched = np.zeros(len(det), dtype=bool)
    if not matches.empty:
        matched[matches["det"].to_numpy(int)] = True
    inside = in_bbox(det, bbox)
    out = {"bbox": [float(v) for v in bbox], "n_detected_in_bbox": int(inside.sum()),
           "n_detected_outside_bbox": int((~inside).sum()),
           "precision_in_bbox": float(matched[inside].sum() / max(inside.sum(), 1))}
    if minmag is not None and "ml" in det:
        ml = det["ml"].to_numpy(float)
        sel = inside & (np.isnan(ml) | (ml >= minmag))
        out.update({"minmag": float(minmag), "n_detected_in_bbox_above_minmag": int(sel.sum()),
                    "precision_in_bbox_above_minmag": float(matched[sel].sum() / max(sel.sum(), 1))})
        for name, m in (("unmatched_in_bbox_ml", inside & ~matched), ("matched_in_bbox_ml", inside & matched)):
            v = ml[m & ~np.isnan(ml)]
            if len(v):
                q = np.quantile(v, [0.1, 0.5, 0.9])
                out[name] = {"n": int(len(v)), "p10": float(q[0]), "median": float(q[1]), "p90": float(q[2]),
                             "n_ge_2": int((v >= 2).sum())}
    return out


def magnitude_error_by_bin(det, ref, matches, bins=MAG_BINS):
    """Bias and spread of ML and DL magnitude against the reference magnitude, per reference-magnitude bin."""
    if matches.empty:
        return pd.DataFrame()
    d = det.iloc[matches["det"].to_numpy(int)].reset_index(drop=True)
    r = ref.iloc[matches["ref"].to_numpy(int)].reset_index(drop=True)
    tab = pd.DataFrame({"bin": pd.cut(r["mag"], bins)})
    cols = [c for c in ("ml", "m_dl") if c in d]
    for c in cols:
        tab[c] = d[c].to_numpy(float) - r["mag"].to_numpy(float)
    g = tab.groupby("bin", observed=True)
    out = g.size().rename("n").to_frame()
    for c in cols:
        out[f"{c}_bias"] = g[c].mean()
        out[f"{c}_sd"] = g[c].std()
    return out.reset_index().astype({"bin": str})


def recall_by_magnitude(ref, matches, bins=MAG_BINS):
    found = np.zeros(len(ref), dtype=bool)
    if not matches.empty:
        found[matches["ref"].to_numpy()] = True
    cat = pd.cut(ref["mag"], bins)
    tab = pd.DataFrame({"bin": cat, "found": found}).groupby("bin", observed=False)["found"].agg(["size", "sum"])
    tab["recall"] = tab["sum"] / tab["size"].replace(0, np.nan)
    return tab.rename(columns={"size": "n_reference", "sum": "n_detected"}).reset_index().astype({"bin": str})


def pick_metrics(picks, arrivals, stations, tol=0.5):
    """Recall and residuals of automatic picks against analyst arrivals on our stations."""
    out = {}
    arr = arrivals[arrivals["station"].isin(stations)]
    for phase in ("P", "S"):
        a = arr[arr["phase"] == phase]
        p = picks[picks["phase"] == phase]
        resid = []
        by_sta = {s: np.sort(g["time"].to_numpy(float)) for s, g in p.groupby("station")}
        for sta, ga in a.groupby("station"):
            times = by_sta.get(sta)
            if times is None or not len(times):
                continue
            at = ga["time_s"].to_numpy(float)
            lo = np.searchsorted(times, at - tol, "left")
            hi = np.searchsorted(times, at + tol, "right")
            ci = np.repeat(np.arange(len(at)), hi - lo)
            cj = np.concatenate([np.arange(a0, b0) for a0, b0 in zip(lo, hi)]) if len(at) else np.array([], int)
            if not len(ci):
                continue
            d = times[cj] - at[ci]
            for k in one_to_one(ci, cj, np.abs(d) / tol):  # each pick explains at most one analyst arrival
                resid.append(float(d[k]))
        out[phase] = {"n_analyst": int(len(a)), "n_auto": int(len(p)), "matched": len(resid),
                      "recall": len(resid) / max(len(a), 1), **{f"resid_{k}": v for k, v in _stats(resid).items()}}
    return out


def plot_all(det, ref, matches, stations, by_mag, out_dir, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 6.5))
    if not ref.empty:
        ax.scatter(ref["lon"], ref["lat"], s=4 + 6 * np.clip(ref["mag"].fillna(1), 0, 5) ** 1.5, c="0.65",
                   label=f"reference ({len(ref)})", alpha=0.6)
    if not det.empty:
        ax.scatter(det["lon"], det["lat"], s=10, c="#c0392b", label=f"detected ({len(det)})", alpha=0.8)
    for _, m in matches.iterrows():
        d, r = det.iloc[int(m["det"])], ref.iloc[int(m["ref"])]
        ax.plot([d["lon"], r["lon"]], [d["lat"], r["lat"]], c="#c0392b", lw=0.4, alpha=0.5)
    ax.scatter(stations["lon"], stations["lat"], marker="^", s=70, c="#1f4e79", edgecolor="w", label="stations")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(out_dir / "map.png", dpi=130)
    plt.close(fig)

    if matches.empty:
        return
    d = det.iloc[matches["det"]].reset_index(drop=True)
    r = ref.iloc[matches["ref"]].reset_index(drop=True)
    panels = [("epicentre error (km)", matches["epi_err_km"], None),
              ("depth: auto - ref (km)", d["depth_km"] - r["depth_km"], None),
              ("origin time: auto - ref (s)", matches["dt_s"], None)]
    if "ml" in d:
        panels.append(("ML - reference M", d["ml"] - r["mag"], None))
    if "m_dl" in d and d["m_dl"].notna().any():
        panels.append(("DL M - reference M", d["m_dl"] - r["mag"], None))
    fig, axes = plt.subplots(1, len(panels) + 1, figsize=(3.4 * (len(panels) + 1), 3.2))
    for ax, (label, vals, _) in zip(axes, panels):
        v = pd.Series(vals, dtype=float).dropna()
        ax.hist(v, bins=30, color="#3b6ea5")
        ax.set_title(f"{label}\nmedian {v.median():+.2f}" if len(v) else label, fontsize=8)
    axes[-1].bar(range(len(by_mag)), by_mag["recall"].fillna(0), color="#2e7d32")
    axes[-1].set_xticks(range(len(by_mag)))
    axes[-1].set_xticklabels(by_mag["bin"], rotation=45, fontsize=7)
    axes[-1].set_ylim(0, 1)
    axes[-1].set_title("detection recall by magnitude", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "errors.png", dpi=130)
    plt.close(fig)
