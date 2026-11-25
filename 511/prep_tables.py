"""Split station_magnitudes.csv (from e2e_magnitudes.py) into per-estimator tables with one magnitude type.

    python 511/prep_tables.py --src OUT_DIR_OR_CSV --out-prefix tables/ridgecrest [--mag-types ML]

Writes <prefix>_dl.csv and <prefix>_ml.csv (only estimators present), keeping only events whose
reference magnitude type is in --mag-types (case-insensitive), so labels are on one scale.
"""

import argparse
from pathlib import Path

import pandas as pd


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", required=True)
    p.add_argument("--out-prefix", required=True)
    p.add_argument("--mag-types", nargs="+", default=["ML"])
    a = p.parse_args(argv)
    src = Path(a.src)
    t = pd.read_csv(src / "station_magnitudes.csv" if src.is_dir() else src, dtype={"event_id": str})
    if "mag_type" in t:
        t = t[t["mag_type"].astype(str).str.upper().isin([m.upper() for m in a.mag_types])]
    Path(a.out_prefix).parent.mkdir(parents=True, exist_ok=True)
    for est, g in t.groupby("estimator"):
        g.to_csv(f"{a.out_prefix}_{est}.csv", index=False)
        print(f"{a.out_prefix}_{est}.csv: {g['event_id'].nunique()} events, {len(g)} rows")


if __name__ == "__main__":
    main()
