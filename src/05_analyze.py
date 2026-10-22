"""Command-line entrypoint for urban expansion and change analysis (05_analyze.py).

Usage:
  python src/05_analyze.py --config configs/project.toml --env-file .env
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is on sys.path when script is executed directly
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rs_urban.config import add_common_args, load_context
from rs_urban.analyze import analyze_change


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze urban expansion and land cover change between 1992 and 2021."
    )
    add_common_args(parser)

    args = parser.parse_args(argv)

    ctx = load_context(config_path=args.config, env_file=args.env_file)
    result = analyze_change(ctx=ctx)

    print("Urban change analysis completed successfully:")
    print(f"  Change raster: {result.raster}")
    print(f"  Change vectors: {result.vectors}")
    print(f"  Township statistics: {result.townships}")
    print(f"  District statistics: {result.district}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
