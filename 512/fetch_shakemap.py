"""Entry point: see gm.fetch_shakemap for documentation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gm.fetch_shakemap import main  # noqa: E402

if __name__ == "__main__":
    main()
