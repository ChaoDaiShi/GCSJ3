"""Command-line entry point for sample processing and feature extraction.

Step 02: Extracts 10-band features, generates stratified group split, and creates train/holdout datasets.
Usage:
  python src/02_samples.py --config configs/project.toml --env-file .env --year 1992
  python src/02_samples.py --config configs/project.toml --env-file .env --year 2021
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add src/ to sys.path if not running in installed mode
repo_root = Path(__file__).resolve().parents[1]
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rs_urban.config import add_common_args, load_context
from rs_urban.samples import build_samples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract 10-band features and extract stratified training/holdout samples."
    )
    add_common_args(parser)
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        choices=[1992, 2021],
        help="Target analysis year (1992 or 2021).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ctx = load_context(args.config, args.env_file)
    print(f"Executing sample processing pipeline for year {args.year}...")
    sample_data = build_samples(ctx, args.year)
    print(f"Sample processing completed successfully for year {args.year}:")
    print(f"  Features 30m raster:       {sample_data.features}")
    print(f"  Valid features raster:     {sample_data.valid_features}")
    print(f"  Training samples CSV:      {sample_data.train}")
    print(f"  Holdout samples CSV:       {sample_data.holdout}")
    print(f"  Split metadata:            {sample_data.split}")


if __name__ == "__main__":
    main()
