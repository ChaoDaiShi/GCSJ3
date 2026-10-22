"""Command-line entrypoint for preprocessing tasks (P1-A).

Usage:
  python src/01_preprocess.py --config configs/project.toml --env-file .env --step boundaries
  python src/01_preprocess.py --config configs/project.toml --env-file .env --step surface --year 1992
  python src/01_preprocess.py --config configs/project.toml --env-file .env --step surface --year 2021
  python src/01_preprocess.py --config configs/project.toml --env-file .env --step pansharpen
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add src to sys.path if not present
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rs_urban.config import add_common_args, load_context
from rs_urban.preprocess import (
    pansharpen_2021,
    prepare_boundaries,
    preprocess_year,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preprocess remote sensing imagery and vector boundaries for Xindu urban expansion analysis."
    )
    add_common_args(parser)
    parser.add_argument(
        "--step",
        choices=["boundaries", "surface", "pansharpen"],
        required=True,
        help="Preprocessing step to execute: 'boundaries', 'surface', or 'pansharpen'.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Year to process (required when --step is 'surface', e.g. 1992 or 2021).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.step == "surface" and args.year is None:
        parser.error("--year is required when --step is 'surface'.")

    ctx = load_context(args.config, args.env_file)

    try:
        if args.step == "boundaries":
            print("[INFO] Preparing standard administrative boundaries and grids...")
            gpkg = prepare_boundaries(ctx)
            print(f"[SUCCESS] Boundaries and grids prepared: {gpkg}")

        elif args.step == "surface":
            print(f"[INFO] Preprocessing surface reflectance for year {args.year}...")
            prepared = preprocess_year(ctx, args.year)
            print(f"[SUCCESS] Surface reflectance preprocessed for {args.year}: {prepared.sr}")

        elif args.step == "pansharpen":
            print("[INFO] Performing 15m pansharpening for year 2021...")
            pan_path = pansharpen_2021(ctx)
            print(f"[SUCCESS] Pansharpened image produced: {pan_path}")

        return 0

    except Exception as e:
        print(f"[ERROR] Preprocessing failed on step '{args.step}': {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
