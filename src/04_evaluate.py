"""Command-line entrypoint for postprocessing, vectorization, and evaluation (P1-D).

Usage:
  python src/04_evaluate.py --config configs/project.toml --env-file .env --year 1992
  python src/04_evaluate.py --config configs/project.toml --env-file .env --year 2021
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
from rs_urban.evaluate import finalize_evaluate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply sieve post-processing, vectorization, and independent accuracy evaluation for Xindu LULC classification."
    )
    add_common_args(parser)
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Year to evaluate (e.g. 1992 or 2021).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ctx = load_context(args.config, args.env_file)

    try:
        print(f"[INFO] Finalizing and evaluating classification for year {args.year}...")
        eval_data = finalize_evaluate(ctx, args.year)
        print(f"[SUCCESS] Final raster: {eval_data.final}")
        print(f"[SUCCESS] Shapefile: {eval_data.vectors}")
        print(f"[SUCCESS] Accuracy report: {eval_data.report}")
        print(f"[METRIC] Raw OA: {eval_data.oa_raw:.4f}, Final OA: {eval_data.oa_final:.4f}")
        return 0

    except Exception as e:
        print(f"[ERROR] Evaluation failed for year {args.year}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
