"""Phase picking on MiniSEED with pretrained deep-learning pickers from SeisBench (PyTorch).

Replaces the TensorFlow-1 PhaseNet code in 511/phase1 for inference: the same PhaseNet
architecture (Zhu & Beroza 2019) plus EQTransformer are available with weights trained on
STEAD, INSTANCE, GEOFON, etc., and run on 3-component 100 Hz streams out of the box.

    python 511/pick.py --data-dir data/samples/4.0 --model phasenet --weights stead \
        --out 511/outputs/picks/picks_phasenet_stead.csv

Weights are downloaded on first use (~few MB) to ~/.seisbench. Output CSV columns:
station, phase, time (UTC ISO), time_s (epoch seconds, used by locate_events.py), prob,
trace_id, model, weights.

Important: the 20 stations are accelerometers (HL? channels) while most pretrained weights were
trained on broadband velocity records; check picks visually (``--plot``) and expect lower S
recall until the model is fine-tuned on local picks (checklist item B4).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dl.pickers import MODEL_NAMES, load_picker  # noqa: E402
from dl.pickers import pick_stream as _pick_stream  # noqa: E402


def load_model(name, weights, device="cpu"):
    return load_picker(name, weights, device)


def pick_stream(model, stream, p_threshold=0.3, s_threshold=0.3, batch_size=256, station_key="sta"):
    return _pick_stream(model, stream, p_threshold, s_threshold, batch_size, station_key)


def run(data_dir, out, model_name="phasenet", weights="stead", p_threshold=0.3, s_threshold=0.3,
        device="cpu", pattern="*.mseed", merge=True, plot=False):
    from obspy import read

    model = load_model(model_name, weights, device)
    data_dir = Path(data_dir)
    files = sorted(data_dir.rglob(pattern))
    if not files:
        raise SystemExit(f"no {pattern} files under {data_dir}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in files:
        st = read(str(path))
        if merge:
            st.merge(method=1, fill_value="interpolate")  # join segments, do not fabricate long gaps
        st.detrend("demean")
        for r in pick_stream(model, st, p_threshold, s_threshold):
            r.update({"file": path.name, "model": model_name, "weights": weights})
            rows.append(r)
        print(f"{path.name}: {sum(1 for r in rows if r['file'] == path.name)} picks")
        if plot and rows and hasattr(model, "annotate"):
            _plot(model, st, [r for r in rows if r["file"] == path.name], out.parent / f"{path.stem}.png")
    fields = ["station", "network", "phase", "time", "time_s", "prob", "start", "end", "trace_id", "file", "model", "weights"]
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["time_s"]))
    print(f"wrote {len(rows)} picks to {out}")
    return rows


def _plot(model, stream, rows, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from obspy import UTCDateTime

    ann = model.annotate(stream)
    fig, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    t0 = stream[0].stats.starttime
    for tr in stream.select(channel="*Z"):
        axes[0].plot(tr.times() + (tr.stats.starttime - t0), tr.data / (abs(tr.data).max() or 1), lw=0.4, label=tr.id)
    for tr in ann:
        if tr.stats.channel.endswith(("_P", "_S")):
            axes[1].plot(tr.times() + (tr.stats.starttime - t0), tr.data, lw=0.6, label=tr.stats.channel)
    for r in rows:
        axes[0].axvline(UTCDateTime(r["time"]) - t0, color="r" if r["phase"] == "P" else "b", lw=0.6)
    axes[0].legend(fontsize=6, loc="upper right")
    axes[1].legend(fontsize=6, loc="upper right")
    axes[1].set_xlabel(f"seconds after {t0}")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=str(ROOT / "data" / "samples" / "4.0"))
    p.add_argument("--out", default=str(ROOT / "511" / "outputs" / "picks" / "picks.csv"))
    p.add_argument("--model", default="phasenet", choices=MODEL_NAMES)
    p.add_argument("--weights", default="stead", help="pretrained weights name, e.g. stead, instance, original, geofon; "
                                                       "a path saved by finetune_picker.py; 'untrained' = random weights for a pipeline test")
    p.add_argument("--p-threshold", type=float, default=0.3)
    p.add_argument("--s-threshold", type=float, default=0.3)
    p.add_argument("--device", default="cpu")
    p.add_argument("--pattern", default="*.mseed")
    p.add_argument("--no-merge", action="store_true")
    p.add_argument("--plot", action="store_true", help="save one PNG per file with waveform, probabilities and picks")
    a = p.parse_args(argv)
    run(a.data_dir, a.out, a.model, a.weights, a.p_threshold, a.s_threshold, a.device, a.pattern, not a.no_merge, a.plot)


if __name__ == "__main__":
    main()
