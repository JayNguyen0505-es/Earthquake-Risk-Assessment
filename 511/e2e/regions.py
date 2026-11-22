"""Region definitions for the end-to-end benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from loc.velocity import VelocityModel

CONFIG = Path(__file__).resolve().parents[1] / "config" / "regions.json"


def load_regions(path=CONFIG):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: v for k, v in cfg.items() if not k.startswith("_")}


def get_region(name, path=CONFIG):
    regions = load_regions(path)
    if name not in regions:
        raise SystemExit(f"unknown region '{name}'; available: {', '.join(regions)}")
    return dict(regions[name], id=name)


def velocity_model(region, csv_override=None):
    if csv_override:
        return VelocityModel.from_csv(csv_override, vp_vs=region.get("velocity", {}).get("vp_vs", 1.73))
    v = region["velocity"]
    return VelocityModel([tuple(layer) for layer in v["layers"]], vp_vs=v.get("vp_vs", 1.73))
