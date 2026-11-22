"""Benchmark P/S pickers on a labelled dataset: precision, recall, F1 and pick-time residuals.

    # deep-learning picker with pretrained weights (downloaded by SeisBench on first use)
    python 511/evaluate_picker.py --dataset ETHZ --model phasenet --weights instance --n 2000 --device cuda

    # classic STA/LTA baseline on the same traces
    python 511/evaluate_picker.py --dataset ETHZ --model stalta --n 2000

    # accelerometer traces only (closest to the HL? channels of the 20 Vietnamese stations)
    python 511/evaluate_picker.py --dataset InstanceGM --channels HN --model phasenet --weights instance

    # fine-tuned weights saved by finetune_picker.py
    python 511/evaluate_picker.py --dataset AQ2009GM --model phasenet --weights 511/outputs/finetune/aq2009/best

A labelled arrival counts as found (true positive) if a pick of the same phase lies within ``--tol``
seconds; picks farther than ``--tol`` from every labelled arrival of their phase are false
positives. Datasets: any seisbench.data class name or a local SeisBench-format folder.
Outputs (``--out`` stem): per-trace CSV, ``_summary.csv``, ``_summary.json``, residual histogram PNG.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dl.data import P_COLUMNS, S_COLUMNS, apply_filters, load_dataset, split_dataset  # noqa: E402
from dl.pickers import MODEL_NAMES, load_picker, pick_stream  # noqa: E402


def first_sample(meta, columns):
    vals = []
    for c in columns:
        v = meta.get(c, np.nan)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if np.isfinite(v):
            vals.append(v)
    return min(vals) if vals else np.nan


def sample_to_stream(waveform, meta, component_order, sampling_rate, min_samples=0):
    from obspy import Stream, Trace, UTCDateTime

    net = str(meta.get("station_network_code", "XX") or "XX")[:2]
    sta = str(meta.get("station_code", "STA") or "STA")[:5]
    band = str(meta.get("trace_channel", "HH") or "HH")[:2]
    data = np.asarray(waveform, dtype=np.float32)
    if data.shape[-1] < min_samples:  # pad short traces so the network sees a full window
        data = np.pad(data, ((0, 0), (0, min_samples - data.shape[-1])))
    st = Stream()
    for i, comp in enumerate(component_order[: data.shape[0]]):
        tr = Trace(data[i].copy())
        tr.stats.update({"network": net, "station": sta, "channel": band + comp,
                         "sampling_rate": sampling_rate, "starttime": UTCDateTime(0)})
        st += tr
    return st


def match_phase(truth_s, picks_s, tol):
    """Greedy one-to-one matching of picks to the labelled arrival. Returns (residual or nan, n_false)."""
    picks_s = sorted(picks_s)
    if not np.isfinite(truth_s):
        return np.nan, len(picks_s)
    if not picks_s:
        return np.nan, 0
    best = min(picks_s, key=lambda t: abs(t - truth_s))
    if abs(best - truth_s) <= tol:
        return best - truth_s, len(picks_s) - 1
    return np.nan, len(picks_s)


def summarize(res, tol):
    summary = {}
    for phase in ("P", "S"):
        g = res[res["phase"] == phase]
        labelled = g[np.isfinite(g["truth_s"])]
        tp = int(np.isfinite(labelled["resid_s"]).sum())
        fp = int(g["n_false"].sum())
        fn = int(len(labelled) - tp)
        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        hits = labelled["resid_s"].dropna()
        summary[phase] = {
            "n_traces": int(len(g)), "n_labelled": int(len(labelled)), "tp": tp, "fp": fp, "fn": fn,
            "precision": prec, "recall": rec, "f1": 2 * prec * rec / max(prec + rec, 1e-12),
            "resid_mean_s": float(hits.mean()) if len(hits) else np.nan,
            "resid_std_s": float(hits.std()) if len(hits) > 1 else np.nan,
            "resid_mae_s": float(hits.abs().mean()) if len(hits) else np.nan,
            "tol_s": tol,
        }
    return summary


def evaluate(dataset, model_name, weights, n=1000, tol=0.5, split="test", split_mode="dataset", channels=None,
             sampling_rate=100.0, device="cpu", seed=0, p_threshold=0.3, s_threshold=0.3, progress_every=200):
    ds = load_dataset(dataset, sampling_rate=sampling_rate, dimension_order="NCW")
    apply_filters(ds, channels=channels)
    subset = split_dataset(ds, mode=split_mode, seed=seed)[split] if split != "all" else ds
    if len(subset) == 0:
        raise SystemExit(f"no traces in split '{split}' (mode {split_mode}); try --split-mode event")
    idx = np.arange(len(subset))
    if n and n < len(idx):
        idx = np.sort(np.random.default_rng(seed).choice(idx, n, replace=False))
    picker = load_picker(model_name, weights, device)
    min_samples = int(getattr(picker, "in_samples", 0) or 0)
    comp_order = subset.component_order
    rows = []
    t0 = time.time()
    for k, i in enumerate(idx):
        wf, meta = subset.get_sample(int(i))
        fs = float(meta.get("trace_sampling_rate_hz", sampling_rate) or sampling_rate)
        st = sample_to_stream(wf, meta, comp_order, fs, min_samples)
        picks = pick_stream(picker, st, p_threshold, s_threshold)
        start = st[0].stats.starttime.timestamp
        for phase, cols in (("P", P_COLUMNS), ("S", S_COLUMNS)):
            truth = first_sample(meta, cols)
            truth_s = truth / fs if np.isfinite(truth) else np.nan
            cand = [r["time_s"] - start for r in picks if r["phase"] == phase]
            resid, n_false = match_phase(truth_s, cand, tol)
            rows.append({"index": int(i), "trace_name": meta.get("trace_name", ""), "phase": phase,
                         "truth_s": truth_s, "n_picks": len(cand), "resid_s": resid, "n_false": n_false,
                         "trace_channel": meta.get("trace_channel", ""),
                         "source_magnitude": meta.get("source_magnitude", np.nan)})
        if progress_every and (k + 1) % progress_every == 0:
            print(f"  {k + 1}/{len(idx)} traces, {time.time() - t0:.0f} s")
    res = pd.DataFrame(rows)
    return res, summarize(res, tol)


def plot_residuals(res, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
    for ax, phase in zip(axes, ("P", "S")):
        r = res[(res["phase"] == phase)]["resid_s"].dropna()
        ax.hist(r, bins=np.linspace(-0.5, 0.5, 51), color="#3b6ea5" if phase == "P" else "#b5523b")
        ax.set_title(f"{phase}: n={len(r)}, mean={r.mean():+.3f}s, std={r.std():.3f}s" if len(r) > 1 else phase)
        ax.set_xlabel("pick - analyst (s)")
    fig.suptitle(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default="ETHZ", help="seisbench.data class (ETHZ, STEAD, InstanceGM, AQ2009GM, ...) or local folder")
    p.add_argument("--model", default="phasenet", choices=MODEL_NAMES)
    p.add_argument("--weights", default="stead", help="pretrained name (stead, instance, ethz, original, ...) or saved path")
    p.add_argument("--n", type=int, default=1000, help="number of traces sampled from the split (0 = all)")
    p.add_argument("--tol", type=float, default=0.5)
    p.add_argument("--split", default="test", choices=["train", "dev", "test", "all"])
    p.add_argument("--split-mode", default="dataset", choices=["dataset", "event"])
    p.add_argument("--channels", nargs="*", help="instrument codes to keep, e.g. HN (accelerometers) or HH EH")
    p.add_argument("--p-threshold", type=float, default=0.3)
    p.add_argument("--s-threshold", type=float, default=0.3)
    p.add_argument("--device", default="cpu")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None, help="output CSV path (default 511/outputs/picker_eval/<dataset>_<model>_<weights>.csv)")
    a = p.parse_args(argv)
    tag = f"{Path(str(a.dataset)).name}_{a.model}_{Path(str(a.weights)).name if a.model != 'stalta' else 'classic'}"
    if a.channels:
        tag += "_" + "-".join(a.channels)
    out = Path(a.out or Path(__file__).resolve().parent / "outputs" / "picker_eval" / f"{tag}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    res, summary = evaluate(a.dataset, a.model, a.weights, a.n, a.tol, a.split, a.split_mode, a.channels,
                            device=a.device, seed=a.seed, p_threshold=a.p_threshold, s_threshold=a.s_threshold)
    res.to_csv(out, index=False)
    table = pd.DataFrame(summary).T
    table.insert(0, "run", tag)
    table.to_csv(out.with_name(out.stem + "_summary.csv"))
    out.with_name(out.stem + "_summary.json").write_text(json.dumps({"run": tag, "args": vars(a), "summary": summary},
                                                                   indent=2, default=str))
    plot_residuals(res, out.with_name(out.stem + "_residuals.png"), tag)
    print(table[["n_labelled", "precision", "recall", "f1", "resid_mean_s", "resid_std_s"]].round(3).to_string())
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
