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


def rupture_dimensions(mag):
    """Strike-slip subsurface rupture length and down-dip width (km), Wells & Coppersmith (1994)."""
    length = 10 ** (-2.57 + 0.62 * mag)
    width = 10 ** (-0.76 + 0.27 * mag)
    return float(length), float(width)


def finite_fault_distances(scn, lat, lon, seismogenic_depth_km=20.0):
    """Rjb and Rrup (km) to a vertical rectangular fault centred on the epicentre along ``strike_deg``.

    Length/width from Wells & Coppersmith (1994); the fault is centred on the hypocentre in depth,
    clipped to [0, seismogenic depth]. For a vertical fault Rjb is the distance to the surface
    projection (a line segment) and Rrup = sqrt(Rjb^2 + ztop^2).
    """
    length, width = rupture_dimensions(scn["mag"])
    width = min(width, seismogenic_depth_km)
    ztop = float(np.clip(scn["depth_km"] - width / 2, 0.0, seismogenic_depth_km - width))
    lat0, lon0 = scn["lat"], scn["lon"]
    x = np.radians(np.asarray(lon) - lon0) * 6371.0 * np.cos(np.radians(lat0))
    y = np.radians(np.asarray(lat) - lat0) * 6371.0
    th = np.radians(scn["strike_deg"])
    ux, uy = np.sin(th), np.cos(th)                      # unit vector along strike (east, north)
    t = np.clip(x * ux + y * uy, -length / 2, length / 2)  # projection on the trace, clipped to its ends
    rjb = np.hypot(x - t * ux, y - t * uy)
    rrup = np.hypot(rjb, ztop)
    return rjb, rrup, {"length_km": length, "width_km": width, "ztop_km": ztop}


def scenario_frame(scn, grid, finite_fault=None):
    """Pseudo-flatfile rows for every grid node of one scenario.

    Point source by default; a finite vertical fault when the scenario has ``strike_deg`` and
    M >= 6 (or ``finite_fault=True``). A point source puts every site at least one focal depth
    away and under-predicts near-fault shaking for large events.
    """
    repi = haversine_km(scn["lat"], scn["lon"], grid["lat"].to_numpy(), grid["lon"].to_numpy())
    rhypo = np.hypot(repi, scn["depth_km"])
    use_ff = finite_fault if finite_fault is not None else ("strike_deg" in scn and scn["mag"] >= 6.0)
    df = pd.DataFrame({c: np.nan for c in COLUMNS}, index=grid.index)
    df["event_id"] = scn.get("id", "scenario")
    df["station_id"] = [f"G{i}" for i in grid.index]
    df["mag"] = scn["mag"]
    df["depth_km"] = scn["depth_km"]
    df["ev_lat"], df["ev_lon"] = scn["lat"], scn["lon"]
    df["st_lat"], df["st_lon"] = grid["lat"].to_numpy(), grid["lon"].to_numpy()
    df["repi_km"], df["rhypo_km"] = repi, rhypo
    if use_ff:
        rjb, rrup, _ = finite_fault_distances(scn, grid["lat"].to_numpy(), grid["lon"].to_numpy())
        df["rjb_km"], df["rrup_km"] = rjb, rrup
    else:
        df["rjb_km"], df["rrup_km"] = repi, rhypo  # point-source approximation
    df["vs30_ms"] = grid["vs30_ms"].to_numpy()
    df["mech"] = scn.get("mech", "U")
    df["source"] = "scenario"
    return df


def predict_map(bundle, scn, grid, finite_fault=None):
    df = scenario_frame(scn, grid, finite_fault)
    X = feature_frame(df, bundle.get("distance", "rhypo"))
    ln_y = bundle["model"].predict(X)
    out = grid.copy()
    out["repi_km"] = df["repi_km"].to_numpy()
    out["rrup_km"] = df["rrup_km"].to_numpy()
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
    aspect = 1.0 / np.cos(np.radians(float(np.mean(lats))))  # equal km in both directions
    im = ax.imshow(arr, extent=[lons[0], lons[-1], lats[0], lats[-1]], origin="upper", cmap="YlOrRd", aspect=aspect)
    cs = ax.contour(lons, lats, arr[::-1], colors="k", linewidths=0.5)
    ax.clabel(cs, fontsize=7, fmt="%.2f")
    ax.plot(scn["lon"], scn["lat"], "k*", ms=12, label="epicentre")
    if "strike_deg" in scn and scn["mag"] >= 6.0:
        half = rupture_dimensions(scn["mag"])[0] / 2
        th = np.radians(scn["strike_deg"])
        dlat = half * np.cos(th) / 111.19
        dlon = half * np.sin(th) / (111.19 * np.cos(np.radians(scn["lat"])))
        ax.plot([scn["lon"] - dlon, scn["lon"] + dlon], [scn["lat"] - dlat, scn["lat"] + dlat], "k-", lw=2,
                label=f"rupture {2 * half:.0f} km (assumed strike {scn['strike_deg']:.0f}°)")
    ax.set_xlim(lons[0], lons[-1])
    ax.set_ylim(lats[0], lats[-1])
    ax.set_title(f"{scn.get('name', scn.get('id'))}  M{scn['mag']}  depth {scn['depth_km']} km  -  {target}")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.legend(loc="lower right")
    fig.colorbar(im, ax=ax, label=f"{target} (g)" if target != "pgv" else "pgv (cm/s)", shrink=0.75)
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
          f"min epicentral distance {table['repi_km'].min():.1f} km, min Rrup {table['rrup_km'].min():.1f} km "
          f"-> {stem}.{{csv,tif,png}}")
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
