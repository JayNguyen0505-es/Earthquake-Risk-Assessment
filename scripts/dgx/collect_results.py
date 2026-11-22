"""Collect every result of 5.1.1 / 5.1.2 into one zip with a SUMMARY.md of the key tables.

    python scripts/dgx/collect_results.py                 # -> results_final_<MMDD_HHMM>.zip in the repo root
    python scripts/dgx/collect_results.py --name results_x.zip

Missing parts are skipped and reported in SUMMARY.md, so it can run at any time.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import time
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = [
    "logs/*.log",
    "512/outputs/*/metrics.csv", "512/outputs/*/residuals_*.png", "512/outputs/*/maps_final/*.png",
    "512/outputs/*/maps_final/*.csv",
    "511/outputs/picker_eval/*summar*.csv", "511/outputs/picker_eval/*.png",
    "511/outputs/magnitude/*/metrics.json", "511/outputs/magnitude/*/*.png", "511/outputs/magnitude/*/training_history.csv",
    "511/outputs/finetune/*/training.json",
    "511/outputs/e2e/*/*/metrics.json", "511/outputs/e2e/*/*/*.png", "511/outputs/e2e/*/*/recall_by_magnitude.csv",
    "data/e2e/*/run.json", "data/e2e/*/stations.csv",
]


def md_table(df, floatfmt=3):
    if df is None or df.empty:
        return "_no data_\n"
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(floatfmt)
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.tolist()) + " |")
    return "\n".join(lines) + "\n"


def section_512(root):
    out = ["## 5.1.2 ground motion (cross-validated sigma, ln units)\n"]
    for f in sorted(glob.glob(str(root / "512/outputs/*/metrics.csv"))):
        m = pd.read_csv(f)
        cols = ["target", "model", "cv_tau", "cv_phi", "cv_sigma"] + [c for c in m.columns if c.startswith("cv_sigma_M")]
        out.append(f"### {Path(f).parent.name}\n")
        out.append(md_table(m[[c for c in cols if c in m.columns]]))
    maps = sorted(glob.glob(str(root / "512/outputs/*/maps_final/*.csv")))
    if maps:
        rows = []
        for f in maps:
            d = pd.read_csv(f)
            ycol = [c for c in d.columns if c not in ("lat", "lon", "vs30_ms", "repi_km", "rrup_km")][0]
            rows.append({"map": Path(f).stem, "max": d[ycol].max(), "median": d[ycol].median(),
                         "min_rrup_km": d["rrup_km"].min() if "rrup_km" in d else float("nan")})
        out.append("### scenario maps (maps_final)\n")
        out.append(md_table(pd.DataFrame(rows)))
    return "\n".join(out)


def section_picker(root):
    files = sorted(glob.glob(str(root / "511/outputs/picker_eval/*_summary.csv")))
    out = ["## 5.1.1 Part A - phase picking\n"]
    if not files:
        return out[0] + "_not run yet_\n"
    t = pd.concat(pd.read_csv(f).rename(columns={"Unnamed: 0": "phase"}) for f in files)
    piv = t.pivot_table(index="run", columns="phase", values=["f1", "precision", "recall", "resid_std_s"])
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    out.append(md_table(piv.reset_index().sort_values("f1_P", ascending=False)))
    return "\n".join(out)


def section_e2e(root):
    files = sorted(glob.glob(str(root / "511/outputs/e2e/*/*/metrics.json")))
    out = ["## 5.1.1 Part B - end-to-end network benchmark\n"]
    if not files:
        return out[0] + "_not run yet_\n"
    rows = []
    for f in files:
        m = json.load(open(f))
        e = m.get("events", {})
        med = lambda k: (e.get(k) or {}).get("median") if isinstance(e.get(k), dict) else None  # noqa: E731
        pa = m.get("picks_vs_analyst", {})
        rows.append({"run": Path(f).parts[-3], "picker": Path(f).parts[-2], "picks": m.get("n_picks"),
                     "ref": e.get("n_reference"), "matched": e.get("n_matched"), "recall": e.get("recall"),
                     "precision": e.get("precision"), "epi_km_med": med("epicentre_error_km"),
                     "dz_km_med": med("depth_error_km"), "dML_med": med("ml_minus_reference"),
                     "dMdl_med": med("m_dl_minus_reference"),
                     "P_recall_vs_analyst": (pa.get("P") or {}).get("recall"),
                     "S_recall_vs_analyst": (pa.get("S") or {}).get("recall")})
    out.append(md_table(pd.DataFrame(rows)))
    for f in sorted(glob.glob(str(root / "511/outputs/e2e/*/*/recall_by_magnitude.csv"))):
        if "phasenet_instance" in f:
            out.append(f"recall by magnitude, {Path(f).parts[-3]} / {Path(f).parts[-2]}:\n")
            out.append(md_table(pd.read_csv(f)))
    return "\n".join(out)


def section_magnitude(root):
    files = sorted(glob.glob(str(root / "511/outputs/magnitude/*/metrics.json")))
    out = ["## 5.1.1 Part C - magnitude\n"]
    if not files:
        return out[0] + "_not run yet_\n"
    rows = []
    for f in files:
        m = json.load(open(f))
        for k in ("station_dl", "event_dl", "station_richter_baseline", "event_richter_baseline"):
            if k in m:
                rows.append({"model_dir": Path(f).parent.name, "estimate": k, **{x: m[k].get(x) for x in
                                                                                 ("n", "rmse", "mae", "bias", "r2")}})
        if "station_within_1sigma" in m:
            rows.append({"model_dir": Path(f).parent.name, "estimate": "fraction |resid| < 1 sigma (ideal 0.68)",
                         "rmse": m["station_within_1sigma"]})
    out.append(md_table(pd.DataFrame(rows)))
    return "\n".join(out)


def section_logs(root):
    out = ["## Download / job diagnostics\n```"]
    for f in sorted(glob.glob(str(root / "logs/*.log"))):
        txt = Path(f).read_text(errors="ignore")
        keep = [ln for ln in txt.splitlines()
                if re.search(r"request errors|analyst arrivals|waveforms:|failed steps|!! |Traceback|Error:", ln)]
        if keep:
            out.append(f"--- {Path(f).name}")
            out.extend(keep[-15:])
    out.append("```\n")
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(ROOT))
    p.add_argument("--name", default=time.strftime("results_final_%m%d_%H%M.zip"))
    a = p.parse_args(argv)
    root = Path(a.root)
    summary = "\n".join([f"# Results summary ({time.strftime('%Y-%m-%d %H:%M')})\n", section_512(root),
                         section_picker(root), section_e2e(root), section_magnitude(root), section_logs(root)])
    (root / "SUMMARY.md").write_text(summary)
    n = 0
    with zipfile.ZipFile(root / a.name, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(root / "SUMMARY.md", "SUMMARY.md")
        for pat in PATTERNS:
            for f in sorted(glob.glob(str(root / pat))):
                z.write(f, str(Path(f).relative_to(root)))
                n += 1
    print(f"{root / a.name}: SUMMARY.md + {n} files")


if __name__ == "__main__":
    main()
