"""One picking interface over SeisBench deep-learning models and the STA/LTA baseline.

    picker = load_picker("phasenet", "instance", device="cuda")   # pretrained weights name
    picker = load_picker("phasenet", "511/outputs/finetune/best")  # fine-tuned weights saved by finetune_picker.py
    picker = load_picker("stalta")                                 # classic baseline, no weights
    rows = pick_stream(picker, stream)                             # list of dicts, one per pick
"""

from __future__ import annotations

from pathlib import Path

from .stalta import STALTAPicker

MODEL_NAMES = ["phasenet", "eqtransformer", "gpd", "stalta"]


def _model_class(name):
    import seisbench.models as sbm

    return {"phasenet": sbm.PhaseNet, "eqtransformer": sbm.EQTransformer, "gpd": sbm.GPD}[name]


def load_picker(name, weights="stead", device="cpu"):
    if name == "stalta":
        return STALTAPicker()
    cls = _model_class(name)
    w = Path(str(weights)).expanduser()
    if str(weights) in ("untrained", "none"):
        model = cls()  # random weights: only for pipeline tests / training from scratch
    elif w.with_suffix(".json").exists() or w.with_suffix(".pt").exists():
        model = cls.load(str(w))  # saved by model.save(path) -> path.json + path.pt
    else:
        model = cls.from_pretrained(str(weights))
    model.to(device)
    model.eval()
    return model


def pick_stream(model, stream, p_threshold=0.3, s_threshold=0.3, batch_size=256, station_key="netsta"):
    """Run a picker on an obspy Stream. ``station_key`` = "netsta" gives NET.STA ids, "sta" gives STA only."""
    if isinstance(model, STALTAPicker):
        rows = model.pick(stream)
    else:
        out = model.classify(stream, batch_size=batch_size, P_threshold=p_threshold, S_threshold=s_threshold)
        rows = []
        for p in out.picks:
            parts = (p.trace_id.split(".") + ["", "", ""])[:3]
            net, sta = parts[0], parts[1]
            rows.append({
                "station": f"{net}.{sta}", "network": net, "phase": p.phase,
                "time": str(p.peak_time), "time_s": float(p.peak_time.timestamp),
                "prob": float(p.peak_value) if p.peak_value is not None else float("nan"),
                "trace_id": p.trace_id,
            })
    if station_key == "sta":
        for r in rows:
            r["station"] = r["station"].split(".", 1)[-1]
    return rows
