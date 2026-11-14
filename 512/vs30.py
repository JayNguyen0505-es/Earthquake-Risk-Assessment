"""Entry point: see gm.vs30 for documentation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gm.vs30 import main  # noqa: E402

if __name__ == "__main__":
    main()
