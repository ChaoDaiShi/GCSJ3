"""Optional B/C/D experiments, analysis, figures and readiness reporting."""

from __future__ import annotations

import argparse
from pathlib import Path

from rs_urban.bcd import export_transfer, load_settings, run
from rs_urban.config import add_common_args, load_context


def main(argv=None):
    parser = argparse.ArgumentParser(description="B/C/D optimization and auditable offline analysis")
    add_common_args(parser)
    parser.add_argument("--bcd-config", type=Path, default=Path("configs/bcd.toml"))
    parser.add_argument("--step", choices=["check", "classify", "transfer", "analyze", "render", "all"], default="check")
    parser.add_argument("--year", type=int, nargs="+")
    parser.add_argument("--methods", nargs="+", choices=["svm", "rf", "stacking"])
    parser.add_argument("--source", choices=["baseline", "svm", "rf", "stacking",
                                           "stacking_obia", "stacking_crf", "stacking_obia_crf"])
    parser.add_argument("--labels-first", type=Path)
    parser.add_argument("--labels-last", type=Path)
    parser.add_argument("--transfer-fraction", type=float, default=0.3)
    args = parser.parse_args(argv)
    ctx = load_context(args.config, args.env_file)
    settings = load_settings(ctx, args.bcd_config)
    if args.source:
        settings["analysis"]["source"] = args.source
    if args.year and set(args.year) - set(ctx.config["years"]):
        parser.error("--year must be declared in project.toml")
    if args.methods:
        settings["classification"]["methods"] = args.methods
    if args.step == "transfer":
        if not args.labels_first or not args.labels_last:
            parser.error("transfer requires --labels-first and --labels-last")
        count = export_transfer(ctx, args.labels_first, args.labels_last, args.transfer_fraction)
        print(f"Exported {count} review-only transfer candidates; no samples modified.")
        return 0
    outcomes = run(ctx, settings, args.step, args.year, args.methods)
    for item in outcomes:
        print(f"{item['task']}: {item['status']}")
    print(f"Report: {ctx.reports / 'bcd' / 'report.md'}")
    return 2 if any(item["status"] == "pending" for item in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
