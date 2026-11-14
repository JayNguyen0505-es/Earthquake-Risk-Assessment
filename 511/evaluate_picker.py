"""Benchmark pretrained pickers on a labelled open dataset (precision/recall/residuals).

    python 511/evaluate_picker.py --dataset ETHZ --model phasenet --weights ethz --n 500 \
        --out 511/outputs/picker_eval/ethz_phasenet.csv

SeisBench downloads the dataset on first use (ETHZ ~1 GB; STEAD and INSTANCE are >70 GB, use
``--n`` and the ``test`` split). A pick is a hit if it is within ``--tol`` seconds of the analyst
arrival of the same phase. This reproduces the standard picker benchmark (Münchmeyer et al.
2022) and gives the numbers to report until local analyst picks (checklist B4) allow the same
evaluation on the 20 Vietnamese stations.

NOTE: written without network access to the SeisBench data servers; the SeisBench dataset API
(``get_waveforms``, ``metadata`` columns ``trace_p_arrival_sample`` / ``trace_s_arrival_sample``)
is as documented for seisbench 0.9-0.12. Please report any API mismatch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pick import load_model, pick_stream  # noqa: E402


def sample_to_stream(waveform, meta, sampling_rate):
    from obspy import Stream, Trace, UTCDateTime

    comps = str(meta.get("trace_component_order", "ZNE"))
    net = str(meta.get("station_network_code", "XX"))
    sta = str(meta.get("station_code", "STA"))
    base = str(meta.get("trace_channel", "HH"))[:2]
    st = Stream()
    for i, comp in enumerate(comps[: waveform.shape[0]]):
        tr = Trace(np.asarray(waveform[i], dtype=np.float32))
        tr.stats.update({"network": net, "station": sta, "channel": base + comp,
                         "sampling_rate": sampling_rate, "starttime": UTCDateTime(0)})
        st += tr
    return st


def evaluate(dataset, model_name, weights, n, tol, split="test", sampling_rate=100.0, device="cpu", seed=0):
    import seisbench.data as sbd

    data = getattr(sbd, dataset)(sampling_rate=sampling_rate)
    train, dev, test = data.train_dev_test()
    subset = {"train": train, "dev": dev, "test": test}[split]
    idx = np.arange(len(subset))
    if n and n < len(idx):
        idx = np.random.default_rng(seed).choice(idx, n, replace=False)
    model = load_model(model_name, weights, device)
    rows = []
    for i in idx:
        wf = subset.get_waveforms(int(i))
        meta = subset.metadata.iloc[int(i)]
        st = sample_to_stream(wf, meta, sampling_rate)
        picks = pick_stream(model, st)
        for phase in ("P", "S"):
            col = f"trace_{phase.lower()}_arrival_sample"
            truth = meta.get(col, np.nan)
            truth_s = float(truth) / sampling_rate if pd.notna(truth) else np.nan
            cand = [p["time_s"] for p in picks if p["phase"] == phase]
            best = min(cand, key=lambda t: abs(t - truth_s)) if cand and np.isfinite(truth_s) else np.nan
            rows.append({"index": int(i), "phase": phase, "truth_s": truth_s, "pick_s": best,
                         "n_picks": len(cand), "resid_s": best - truth_s if np.isfinite(best) else np.nan})
    res = pd.DataFrame(rows)
    summary = {}
    for phase, g in res.groupby("phase"):
        labelled = g[np.isfinite(g["truth_s"])]
        hit = labelled["resid_s"].abs() <= tol
        tp = int(hit.sum())
        fp = int((g["n_picks"].sum() - tp))
        fn = int(len(labelled) - tp)
        summary[phase] = {"n_labelled": int(len(labelled)), "precision": tp / max(tp + fp, 1),
                          "recall": tp / max(tp + fn, 1), "resid_mean_s": float(labelled.loc[hit, "resid_s"].mean()),
                          "resid_std_s": float(labelled.loc[hit, "resid_s"].std())}
    return res, summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default="ETHZ", help="SeisBench dataset class name: ETHZ, STEAD, INSTANCE, GEOFON, ...")
    p.add_argument("--model", default="phasenet", choices=["phasenet", "eqtransformer", "gpd"])
    p.add_argument("--weights", default="stead")
    p.add_argument("--n", type=int, default=500)
    p.add_argument("--tol", type=float, default=0.5)
    p.add_argument("--split", default="test", choices=["train", "dev", "test"])
    p.add_argument("--device", default="cpu")
    p.add_argument("--out", default="511/outputs/picker_eval/eval.csv")
    a = p.parse_args(argv)
    res, summary = evaluate(a.dataset, a.model, a.weights, a.n, a.tol, a.split, device=a.device)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out, index=False)
    pd.DataFrame(summary).T.to_csv(out.with_name(out.stem + "_summary.csv"))
    print(pd.DataFrame(summary).T.round(3))


if __name__ == "__main__":
    main()
