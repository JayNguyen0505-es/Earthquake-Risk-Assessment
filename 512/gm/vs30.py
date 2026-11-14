"""Vs30 from the USGS global mosaic (Heath et al. 2020; topographic-slope proxy with regional insets).

Until the Institute's measured Vs30 (work package 2) is available, this 30 arc-second (~900 m)
grid is the only site-condition layer for the three cities. ShakeMap uses the same grid, so the
training data (fetch_shakemap) and the scenario maps are consistent.

Download (631 MB, once):

    python 512/vs30.py download --dest data/gm/vs30

Sample at the 20 stations:

    python 512/vs30.py sample --grid data/gm/vs30/global_vs30.grd \
        --stations data/stations.xlsx --out data/gm/stations_vs30.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

VS30_URL = "https://apps.usgs.gov/shakemap_geodata/vs30/global_vs30.grd"
DEFAULT_VS30 = 760.0  # NEHRP B/C boundary used as reference rock in most GMPEs


def download(dest):
    import requests

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "global_vs30.grd"
    if target.exists():
        print(f"already present: {target}")
        return target
    with requests.get(VS30_URL, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = target.with_suffix(".part")
        done = 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if done % (50 << 20) < (1 << 20):
                    print(f"  {done / 1e6:.0f} MB")
        tmp.rename(target)
    print(f"saved {target}")
    return target


def sample_points(grid, lats, lons, default=DEFAULT_VS30):
    """Vs30 (m/s) at each (lat, lon). NaN/nodata cells get ``default``."""
    import rasterio

    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    with rasterio.open(grid) as src:
        vals = np.array([v[0] for v in src.sample(zip(lons, lats))], dtype=float)
        nodata = src.nodata
    if nodata is not None:
        vals[vals == nodata] = np.nan
    vals[~np.isfinite(vals) | (vals <= 0)] = default
    return vals


def grid_over_bbox(grid, bbox, step_deg):
    """Regular lat/lon grid over bbox=(minlon, minlat, maxlon, maxlat) with Vs30 sampled at nodes."""
    minlon, minlat, maxlon, maxlat = bbox
    lons = np.arange(minlon, maxlon + step_deg / 2, step_deg)
    lats = np.arange(minlat, maxlat + step_deg / 2, step_deg)
    glon, glat = np.meshgrid(lons, lats)
    vs = sample_points(grid, glat.ravel(), glon.ravel()) if grid else np.full(glon.size, DEFAULT_VS30)
    return pd.DataFrame({"lat": glat.ravel(), "lon": glon.ravel(), "vs30_ms": vs})


def read_stations(path):
    """Station table from data/stations.xlsx (Institute format) or a CSV with lat/lon columns."""
    path = Path(path)
    df = pd.read_excel(path) if path.suffix in {".xlsx", ".xls"} else pd.read_csv(path)
    rename = {}
    for c in df.columns:
        lc = str(c).strip().lower()
        if lc in {"vĩ độ", "vi do", "lat", "latitude"}:
            rename[c] = "lat"
        elif lc in {"kinh độ", "kinh do", "lon", "longitude"}:
            rename[c] = "lon"
        elif lc in {"mã trạm", "ma tram", "station", "station_code", "code"}:
            rename[c] = "station"
    df = df.rename(columns=rename)
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    return df.dropna(subset=["lat", "lon"]).reset_index(drop=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--dest", default="data/gm/vs30")
    s = sub.add_parser("sample")
    s.add_argument("--grid", required=True)
    s.add_argument("--stations", required=True)
    s.add_argument("--out", required=True)
    a = p.parse_args(argv)
    if a.cmd == "download":
        download(a.dest)
    else:
        st = read_stations(a.stations)
        st["vs30_ms"] = sample_points(a.grid, st["lat"], st["lon"])
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        st.to_csv(a.out, index=False)
        print(st[["station", "lat", "lon", "vs30_ms"]] if "station" in st else st)


if __name__ == "__main__":
    main()
