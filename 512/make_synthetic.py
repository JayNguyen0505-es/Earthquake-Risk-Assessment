"""Write a synthetic flatfile so the whole 5.1.2 pipeline can be exercised without real data.

    python 512/make_synthetic.py --out data/gm/synthetic_flatfile.csv --events 300
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gm.flatfile import save  # noqa: E402
from gm.synth import make_flatfile  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/gm/synthetic_flatfile.csv")
    p.add_argument("--events", type=int, default=300)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    df = make_flatfile(a.events, a.seed)
    save(df, a.out)
    print(f"wrote {len(df)} synthetic recordings from {a.events} events to {a.out}")
