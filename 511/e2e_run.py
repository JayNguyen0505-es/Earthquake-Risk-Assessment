"""Run the full 5.1.1 chain on a downloaded run directory and score it against the agency catalogue.

    # deep-learning picker, IASPEI local magnitude
    python 511/e2e_run.py --run data/e2e/central_italy --picker phasenet --weights instance --device cuda

    # classic baseline on the same data
    python 511/e2e_run.py --run data/e2e/central_italy --picker stalta

    # add the deep-learning magnitude model trained with train_magnitude.py
    python 511/e2e_run.py --run data/e2e/ridgecrest --picker phasenet --weights stead --device cuda \
        --magnitude-model 511/outputs/magnitude/instance_hh/model.pt

Steps: picks (hour by hour, checkpointed) -> REAL-style association on sliding windows -> location
(grid search + Nelder-Mead, station elevation correction, region 1-D model) -> ML (Wood-Anderson)
and optional DL magnitude -> matching with the reference catalogue.

Output (default 511/outputs/e2e/<run>/<picker>_<weights>/): picks.csv, catalog.csv, event_picks.csv,
matches.csv, recall_by_magnitude.csv, station_magnitudes.csv (per-station ML / DL magnitudes, for
calibration_study.py), metrics.json, map.png, errors.png. picks.csv is reused only if picks_config.json
shows the same picker and thresholds.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dl.pickers import MODEL_NAMES, load_picker  # noqa: E402
from e2e.pipeline import run_pipeline, summarize  # noqa: E402
from e2e.regions import get_region, velocity_model  # noqa: E402

HERE = Path(__file__).resolve().parent


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="run directory written by e2e_fetch.py")
    p.add_argument("--picker", default="phasenet", choices=MODEL_NAMES)
    p.add_argument("--weights", default="instance", help="pretrained weights name or path saved by finetune_picker.py")
    p.add_argument("--device", default="cpu")
    p.add_argument("--p-threshold", type=float, default=0.3)
    p.add_argument("--s-threshold", type=float, default=0.3)
    p.add_argument("--assoc-tol", type=float, default=1.5, help="association tolerance (s)")
    p.add_argument("--min-p", type=int, default=4)
    p.add_argument("--min-total", type=int, default=5)
    p.add_argument("--bootstrap", type=int, default=0, help="bootstrap resamples for location errors (slower)")
    p.add_argument("--velocity", help="CSV depth_km,vp_kms overriding the region model")
    p.add_argument("--magnitude-model", help="model.pt from train_magnitude.py")
    p.add_argument("--no-ml", action="store_true", help="skip Wood-Anderson local magnitude")
    p.add_argument("--max-hours", type=int, help="process only the first N hours (quick runs)")
    p.add_argument("--match-dt", type=float, default=3.0)
    p.add_argument("--match-km", type=float, default=25.0)
    p.add_argument("--out", help="output folder")
    a = p.parse_args(argv)

    run_dir = Path(a.run)
    meta = json.loads((run_dir / "run.json").read_text())
    region = get_region(meta["region"])
    vmodel = velocity_model(region, a.velocity)
    tag = a.picker if a.picker == "stalta" else f"{a.picker}_{Path(str(a.weights)).name}"
    if a.magnitude_model:
        tag += "_dlmag"
    out = Path(a.out) if a.out else HERE / "outputs" / "e2e" / run_dir.name / tag
    picker = load_picker(a.picker, a.weights, a.device)
    predictor = None
    if a.magnitude_model:
        from dl.magnet import MagnitudePredictor

        predictor = MagnitudePredictor(a.magnitude_model, a.device)
    print(f"[{region['id']}] {meta['start']} -> {meta['end']}, {meta['n_stations']} stations, picker {tag}")
    det, metrics = run_pipeline(run_dir, out, region, vmodel, picker, a.p_threshold, a.s_threshold, a.assoc_tol,
                                a.min_p, a.min_total, a.bootstrap, predictor, not a.no_ml, a.max_hours,
                                a.match_dt, a.match_km, picker_tag=tag.replace("_dlmag", ""))
    metrics["args"] = vars(a)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    print(summarize(metrics))
    print(f"outputs in {out}")


if __name__ == "__main__":
    main()
