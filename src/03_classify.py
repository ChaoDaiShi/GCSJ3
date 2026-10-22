"""Command-line entrypoint for Random Forest classification (03_classify.py).

Usage:
  python src/03_classify.py --config configs/project.toml --env-file .env --year 1992
  python src/03_classify.py --config configs/project.toml --env-file .env --year 2021
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
from rs_urban.classify import train_predict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train Random Forest classifier and predict whole-scene raw LULC raster."
    )
    add_common_args(parser)
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Target year to process (e.g. 1992, 2021)",
    )

    args = parser.parse_args(argv)

    ctx = load_context(config_path=args.config, env_file=args.env_file)
    result = train_predict(ctx=ctx, year=args.year)

    print(f"Classification completed successfully for year {result.year}")
    print(f"  Model saved to: {result.model}")
    print(f"  Raw raster saved to: {result.raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
