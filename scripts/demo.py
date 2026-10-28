"""Run the demo: uv run python scripts/demo.py (or `make demo`)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fmcg_forecast.demo import main

if __name__ == "__main__":
    raise SystemExit(main())
