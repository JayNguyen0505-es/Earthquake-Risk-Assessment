"""Scenario ground-motion maps for the three cities (the GIS deliverable of work package 5).

For a scenario earthquake (historical or extreme), predict PGA/PSA on a regular grid over a city
with a trained model + Vs30 grid, and write CSV, GeoTIFF (for QGIS / WebGIS tiles) and PNG.

    python 512/scenario_map.py --model 512/outputs/synthetic/models/pga_gbm.joblib \
        --scenario tuan_giao_1983 --city lai_chau --vs30-grid data/gm/vs30/global_vs30.grd \
        --out 512/outputs/maps

Scenario parameters live in 512/config/scenarios.json; replace the placeholders with the
Institute's catalogue values before using the maps for anything official.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .features import feature_frame
from .flatfile import COLUMNS, haversine_km
from .vs30 import DEFAULT_VS30, grid_over_bbox

CONFIG = Path(__file__).resolve().parents[1] / "config" / "scenarios.json"


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def scenario_frame(scn, grid):
    """Pseudo-flatfile rows for every grid node of one scenario (point source)."""
    repi = haversine_km(scn["lat"], scn["lon"], grid["lat"].to_numpy(), grid["lon"].to_numpy())
    rhypo = np.hypot(repi, scn["depth_km"])
    df = pd.DataFrame({c: np.nan for c in COLUMNS}, index=grid.index)
    df["event_id"] = scn.get("id", "scenario")
    df["station_id"] = [f"G{i}" for i in grid.index]
    df["mag"] = scn["mag"]
    df["depth_km"] = scn["depth_km"]
    df["ev_lat"], df["ev_lon"] = scn["lat"], scn["lon"]
    df["st_lat"], df["st_lon"] = grid["lat"].to_numpy(), grid["lon"].to_numpy()
    df["repi_km"], df["rhypo_km"] = repi, rhypo
    df["rjb_km"], df["rrup_km"] = repi, rhypo  # point-source approximation
    df["vs30_ms"] = grid["vs30_ms"].to_numpy()
    df["mech"] = scn.get("mech", "U")
    df["source"] = "scenario"
    return df


def predict_map(bundle, scn, grid):
    df = scenario_frame(scn, grid)
    X = feature_frame(df, bundle.get("distance", "rhypo"))
    ln_y = bundle["model"].predict(X)
    out = grid.copy()
    out["repi_km"] = df["repi_km"].to_numpy()
    out[bundle["target"]] = np.exp(ln_y)
    return out


def write_outputs(table, target, out_dir, name, step_deg, scn):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / name
    table.to_csv(stem.with_suffix(".csv"), index=False)
    lats = np.sort(table["lat"].unique())
    lons = np.sort(table["lon"].unique())
    arr = table.pivot(index="lat", columns="lon", values=target).reindex(index=lats, columns=lons).to_numpy()
    arr = arr[::-1]  # north up
    try:
        import rasterio
        from rasterio.transform import from_origin

        transform = from_origin(lons[0] - step_deg / 2, lats[-1] + step_deg / 2, step_deg, step_deg)
        with rasterio.open(stem.with_suffix(".tif"), "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                           count=1, dtype="float32", crs="EPSG:4326", transform=transform, nodata=-9999) as dst:
            dst.write(np.nan_to_num(arr, nan=-9999).astype("float32"), 1)
    except ImportError:
        print("rasterio not installed; GeoTIFF skipped")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(arr, extent=[lons[0], lons[-1], lats[0], lats[-1]], origin="upper", cmap="YlOrRd", aspect="auto")
    cs = ax.contour(lons, lats, arr[::-1], colors="k", linewidths=0.5)
    ax.clabel(cs, fontsize=7, fmt="%.2f")
    ax.plot(scn["lon"], scn["lat"], "k*", ms=12, label="epicentre")
    ax.set_title(f"{scn.get('name', scn.get('id'))}  M{scn['mag']}  depth {scn['depth_km']} km  -  {target}")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.legend(loc="lower right")
    fig.colorbar(im, ax=ax, label=target)
    fig.tight_layout()
    fig.savefig(stem.with_suffix(".png"), dpi=130)
    plt.close(fig)
    return stem


def run(model_path, scenario_id, city_id, out_dir, vs30_grid=None, step_deg=None, config=CONFIG):
    cfg = load_config(config)
    scn = dict(cfg["scenarios"][scenario_id], id=scenario_id)
    city = cfg["cities"][city_id]
    step = step_deg or cfg.get("grid_step_deg", 0.005)
    bundle = joblib.load(model_path)
    grid = grid_over_bbox(vs30_grid, city["bbox"], step)
    if vs30_grid is None:
        print(f"no Vs30 grid given: using {DEFAULT_VS30} m/s everywhere")
    table = predict_map(bundle, scn, grid)
    name = f"{city_id}_{scenario_id}_{bundle['target']}"
    stem = write_outputs(table, bundle["target"], out_dir, name, step, scn)
    print(f"{name}: max {bundle['target']} = {table[bundle['target']].max():.3f}, "
          f"min epicentral distance {table['repi_km'].min():.1f} km -> {stem}.{{csv,tif,png}}")
    return table


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True, help="joblib bundle written by train.py")
    p.add_argument("--scenario", required=True)
    p.add_argument("--city", required=True)
    p.add_argument("--out", default="512/outputs/maps")
    p.add_argument("--vs30-grid", help="USGS global_vs30.grd / GeoTIFF; omitted = 760 m/s")
    p.add_argument("--step", type=float, help="grid spacing in degrees (default from config)")
    p.add_argument("--config", default=str(CONFIG))
    a = p.parse_args(argv)
    run(a.model, a.scenario, a.city, a.out, a.vs30_grid, a.step, a.config)


if __name__ == "__main__":
    main()
