"""Re-score finished end-to-end runs without re-running picking, association or location.

    python 511/e2e_rescore.py                      # every run under 511/outputs/e2e/
    python 511/e2e_rescore.py --runs 511/outputs/e2e/ridgecrest/phasenet_instance_dlmag

Reads catalog.csv and matches.csv written by e2e_run.py and the reference catalogue of the run folder,
then adds to metrics.json:
  events_in_region        precision over detections inside the catalogue bbox (and ML >= the
                          catalogue minimum magnitude), plus the ML spread of unmatched detections
  magnitude_error_by_bin  ML and DL-magnitude bias/spread per reference-magnitude bin
and writes magnitude_error_by_bin.csv next to it.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e.evaluate import magnitude_error_by_bin, region_metrics  # noqa: E402
from e2e.regions import get_region  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def rescore(out_dir):
    out_dir = Path(out_dir)
    mpath = out_dir / "metrics.json"
    metrics = json.loads(mpath.read_text())
    run_dir = Path(metrics["run_dir"])
    run_dir = run_dir if run_dir.is_absolute() else ROOT / run_dir
    run = json.loads((run_dir / "run.json").read_text())
    region = get_region(run["region"])
    bbox = run.get("bbox") or region["bbox"]
    minmag = run.get("catalog_minmag", region.get("catalog_minmag"))
    det = pd.read_csv(out_dir / "catalog.csv")
    ref = pd.read_csv(run_dir / "events.csv")
    mfile = out_dir / "matches.csv"
    matches = pd.read_csv(mfile) if mfile.exists() else pd.DataFrame(columns=["det", "ref", "det_id", "ref_id"])
    if len(matches):
        det_pos = pd.Series(np.arange(len(det)), index=det["event_id"].astype(str))
        ref_pos = pd.Series(np.arange(len(ref)), index=ref["event_id"].astype(str))
        matches = matches.assign(det=det_pos.reindex(matches["det_id"].astype(str)).to_numpy(),
                                 ref=ref_pos.reindex(matches["ref_id"].astype(str)).to_numpy())
        matches = matches.dropna(subset=["det", "ref"]).astype({"det": int, "ref": int})
    metrics["events_in_region"] = region_metrics(det, ref, matches, bbox, minmag)
    tab = magnitude_error_by_bin(det, ref, matches)
    if len(tab):
        tab.to_csv(out_dir / "magnitude_error_by_bin.csv", index=False)
        metrics["magnitude_error_by_bin"] = tab.to_dict(orient="records")
    mpath.write_text(json.dumps(metrics, indent=2, default=str))
    return metrics


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", nargs="*", help="output folders (default: all under 511/outputs/e2e)")
    a = p.parse_args(argv)
    runs = a.runs or sorted(str(Path(f).parent) for f in glob.glob(str(ROOT / "511/outputs/e2e/*/*/catalog.csv")))
    print(f"{'run':18}{'picker':25}{'det':>6}{'in box':>7}{'prec':>6}{'prec box':>9}{'prec box,M':>11}"
          f"{'unmatched ML p50':>17}")
    for r in runs:
        try:
            m = rescore(r)
        except (FileNotFoundError, KeyError) as e:
            print(f"skip {r}: {e}")
            continue
        e, g = m.get("events", {}), m.get("events_in_region", {})
        um = g.get("unmatched_in_bbox_ml", {})
        print(f"{Path(r).parent.name:18}{Path(r).name:25}{e.get('n_detected', 0):6d}{g.get('n_detected_in_bbox', 0):7d}"
              f"{e.get('precision', float('nan')):6.2f}{g.get('precision_in_bbox', float('nan')):9.2f}"
              f"{g.get('precision_in_bbox_above_minmag', float('nan')):11.2f}{um.get('median', float('nan')):17.2f}")


if __name__ == "__main__":
    main()
