"""Inventory and stage orchestration for the optional B/C/D workflow."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tomllib

import numpy as np
import pandas as pd
import rasterio

from rs_urban.enhance import (
    SPECTRAL, check_grid, classify_experiment, stable_transfer_candidates, write_json,
)
from rs_urban.spatial import analyze_advanced, source_maps


def load_settings(ctx, path):
    path = Path(path)
    if not path.is_absolute():
        path = ctx.root / path
    with path.open("rb") as stream:
        settings = tomllib.load(stream)
    valid_methods = {"svm", "rf", "stacking"}
    if not settings["classification"]["methods"] or set(settings["classification"]["methods"]) - valid_methods:
        raise ValueError("Methods must be a nonempty selection of svm, rf, stacking.")
    valid_sources = {"baseline", "svm", "rf", "stacking", "stacking_obia", "stacking_crf", "stacking_obia_crf"}
    if settings["analysis"]["source"] not in valid_sources:
        raise ValueError("Unknown analysis source.")
    if settings["classification"]["folds"] < 2 or settings["classification"]["chunk_size"] <= 0:
        raise ValueError("CV folds must be >=2 and chunk size positive.")
    if settings["analysis"]["permutations"] < 0 or settings["analysis"]["factor_bins"] < 2:
        raise ValueError("Invalid detector permutations or factor bins.")
    return settings


def inventory(ctx, settings, years=None, methods=None):
    tasks = []
    for year in years or ctx.config["years"]:
        sample = ctx.data / "processed" / "samples" / str(year)
        feature = ctx.data / "processed" / str(year)
        files = [sample / name for name in ["train.csv", "holdout.csv", "split.json"]]
        files += [feature / name for name in ["features_30m.tif", "valid_features_30m.tif"]]
        for method in methods or settings["classification"]["methods"]:
            dependencies = ["lightgbm", "catboost"] if method == "stacking" else []
            if method == "stacking" and settings["classification"]["object_smoothing"]:
                dependencies.append("skimage")
            if method == "stacking" and settings["classification"]["crf"]:
                dependencies.append("pydensecrf")
            missing = [str(path) for path in files if not path.exists()]
            missing += [f"dependency:{name}" for name in dependencies if importlib.util.find_spec(name) is None]
            tasks.append({"task": f"classify:{year}:{method}", "status": "pending" if missing else "ready",
                          "missing": missing})
    files = [*source_maps(ctx, settings["analysis"]["source"]),
             ctx.data / "processed" / "boundaries" / "xindu_2021.gpkg"]
    missing = [str(path) for path in files if not path.exists()]
    tasks.append({"task": "analyze", "status": "pending" if missing else "ready", "missing": missing})
    write_json(ctx.reports / "bcd" / "readiness.json", {
        "tasks": tasks,
        "optional_dependencies": {
            name: importlib.util.find_spec(name) is not None
            for name in ["lightgbm", "catboost", "skimage", "pydensecrf"]
        },
        "analysis_source": settings["analysis"]["source"],
        "terrain": str(ctx.data / ctx.config["feature_stack"]["dem_path"]),
        "external_factors": [
            {"name": item["name"], "path": str(ctx.data / item["path"]),
             "exists": (ctx.data / item["path"]).exists()}
            for item in settings.get("factors", [])
        ],
    })
    return tasks


def export_transfer(ctx, labels_first, labels_last, fraction=0.3):
    """Labels must already be mapped to project classes; exports review-only candidates."""
    years = ctx.config["years"]
    features, masks = [], []
    profile = None
    for year in years:
        source = ctx.data / "processed" / str(year)
        with rasterio.open(source / "features_30m.tif") as src, rasterio.open(source / "valid_features_30m.tif") as mask:
            check_grid(src, mask)
            indexes = [src.descriptions.index(name) + 1 for name in SPECTRAL]
            data = src.read(indexes, masked=True).astype(float).filled(np.nan)
            if profile is not None and (src.crs, src.transform, src.shape) != profile:
                raise ValueError("CVA input years must use the same grid.")
            profile = src.crs, src.transform, src.shape
            features.append(data)
            masks.append(mask.read(1) == 1)
    labels = []
    for path in [labels_first, labels_last]:
        with rasterio.open(path) as src:
            if (src.crs, src.transform, src.shape) != profile:
                raise ValueError("CVA labels must be aligned to the A grid.")
            labels.append(src.read(1))
            masks.append(src.read_masks(1) > 0)
    codes = [item["code"] for item in ctx.config["classes"]]
    if any((~np.isin(data, [0, *codes])).any() for data in labels):
        raise ValueError("Map external labels to project codes 1..4 with nodata=0 before CVA.")
    candidate, magnitude = stable_transfer_candidates(
        features[0], features[1], labels[0], labels[1], np.logical_and.reduce(masks), fraction
    )
    rows, cols = np.nonzero(candidate)
    frame = pd.DataFrame({
        "row": rows, "col": cols, "class_id": labels[0][candidate],
        "cva": magnitude[candidate], "status": "needs_manual_review",
    })
    target = ctx.outputs / "bcd" / "transfer"
    target.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target / "review_candidates.csv", index=False)
    write_json(target / "manifest.json", {
        "count": len(frame), "fraction": fraction, "years": years,
        "labels_first": str(labels_first), "labels_last": str(labels_last),
        "warning": "Candidates only. No training/holdout edits; review and spatial split audit required.",
        "method": "Lowest CVA magnitude among label-stable, jointly observed six-band reflectances.",
    })
    return len(frame)


def run(ctx, settings, step="all", years=None, methods=None, render=True):
    tasks = inventory(ctx, settings, years, methods)
    outcomes = []
    if step in ("classify", "all"):
        for task in tasks:
            if not task["task"].startswith("classify:"):
                continue
            if task["status"] != "ready":
                outcomes.append(task)
                continue
            _, year, method = task["task"].split(":")
            classify_experiment(ctx, int(year), method, settings["classification"])
            outcomes.append({"task": task["task"], "status": "computed"})
    if step in ("analyze", "all"):
        # Classification may just have created the selected source.
        needed = [*source_maps(ctx, settings["analysis"]["source"]),
                  ctx.data / "processed" / "boundaries" / "xindu_2021.gpkg"]
        missing = [str(path) for path in needed if not path.exists()]
        if missing:
            outcomes.append({"task": "analyze", "status": "pending", "missing": missing})
        else:
            analyze_advanced(ctx, settings)
            outcomes.append({"task": "analyze", "status": "computed"})
    from rs_urban.reporting import render_report
    final_tasks = inventory(ctx, settings, years, methods)
    result = render_report(ctx, settings, inventory=final_tasks, render=render and step in ("render", "all"))
    write_json(ctx.reports / "bcd" / "run.json", {"step": step, "tasks": outcomes, "figures": result["figures"]})
    if step == "check":
        return final_tasks
    if step == "render":
        return [{"task": row["figure"], "status": row["status"]} for row in result["figures"]]
    if step == "all":
        outcomes += [{"task": row["figure"], "status": row["status"]} for row in result["figures"]]
    return outcomes
