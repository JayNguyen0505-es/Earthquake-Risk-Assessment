"""Download a real-network benchmark for 5.1.1: catalogue, stations (20 by default), hourly waveforms.

    python 511/e2e_fetch.py --region central_italy                      # INGV, Nov 2016, 2 days
    python 511/e2e_fetch.py --region ridgecrest                         # SCEDC, Jul 2019, 2 days
    python 511/e2e_fetch.py --region central_italy --bands HN --tag hn  # accelerometers only, like the Palert stations
    python 511/e2e_fetch.py --region ridgecrest --start 2019-07-20 --end 2019-07-21 --stations 30

Regions, providers, default windows and velocity models live in 511/config/regions.json.
Output: data/e2e/<region>[_<tag>]/ (see e2e/fetch.py for the layout). Re-running resumes: hours
already on disk are skipped. A day of 20 stations at 100 Hz is roughly 0.5-1.5 GB of MiniSEED.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e.fetch import run_fetch  # noqa: E402
from e2e.regions import get_region, load_regions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--region", required=True, choices=[k for k, v in load_regions().items() if v.get("provider")])
    p.add_argument("--start", help="UTC start (default from regions.json)")
    p.add_argument("--end", help="UTC end (default from regions.json)")
    p.add_argument("--stations", type=int, help="number of stations to keep (default 20)")
    p.add_argument("--bands", nargs="+", help="instrument codes in priority order, e.g. HH EH HN, or HN only")
    p.add_argument("--min-spacing-km", type=float, default=0.0)
    p.add_argument("--catalog-minmag", type=float)
    p.add_argument("--skip-waveforms", action="store_true", help="catalogue and stations only (quick check)")
    p.add_argument("--tag", default="", help="suffix for the output folder")
    p.add_argument("--out", help="output folder (default data/e2e/<region>[_<tag>])")
    a = p.parse_args(argv)
    region = get_region(a.region)
    out = Path(a.out) if a.out else ROOT / "data" / "e2e" / (a.region + (f"_{a.tag}" if a.tag else ""))
    run_fetch(region, a.start or region["start"], a.end or region["end"], out, n_stations=a.stations,
              bands=a.bands, catalog_minmag=a.catalog_minmag, skip_waveforms=a.skip_waveforms,
              min_spacing_km=a.min_spacing_km)
    print(f"done: {out}")


if __name__ == "__main__":
    main()
