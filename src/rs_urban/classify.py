"""Random Forest training and windowed raster classification for rs-urban.

Implements P1-C contract from Section 4 and Section 6 of docs/03-contracts.md:
  - train_classifier: fits RandomForestClassifier strictly on train.csv using configured feature order
  - predict_raster_windowed: windowed prediction on 10-band features raster with colormap writing
  - train_predict: pipeline orchestrator returning ClassificationData(year, model, raw)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

import joblib
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from sklearn.ensemble import RandomForestClassifier

from rs_urban.contracts import ClassificationData, ProjectContext


def hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    """Convert hex color string (e.g., '#D95F02') to RGBA tuple."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (r, g, b, 255)


def build_colormap(
    classes_config: list[dict[str, Any]],
    nodata_code: int = 0,
) -> dict[int, tuple[int, int, int, int]]:
    """Build rasterio-compatible colormap from class configuration."""
    colormap: dict[int, tuple[int, int, int, int]] = {nodata_code: (0, 0, 0, 0)}
    for cls in classes_config:
        code = int(cls["code"])
        color_hex = cls["color"]
        colormap[code] = hex_to_rgba(color_hex)
    return colormap


def iter_windows(width: int, height: int, chunk_size: int = 512) -> Iterator[Window]:
    """Generate fixed-size rectangular windows covering a 2D raster extent."""
    for y in range(0, height, chunk_size):
        h = min(chunk_size, height - y)
        for x in range(0, width, chunk_size):
            w = min(chunk_size, width - x)
            yield Window(x, y, w, h)


def train_classifier(
    train_csv_path: Path,
    split_json_path: Path,
    config: dict[str, Any],
    year: int,
) -> tuple[RandomForestClassifier, dict[str, Any], dict[str, Any]]:
    """Train RandomForestClassifier on train.csv without reading holdout.

    Returns:
      (fitted_estimator, model_dict_to_save, training_report_dict)
    """
    if not train_csv_path.exists():
        raise FileNotFoundError(f"Training dataset not found: {train_csv_path}")
    if not split_json_path.exists():
        raise FileNotFoundError(f"Split metadata not found: {split_json_path}")

    # Read training samples
    train_df = pd.read_csv(train_csv_path)

    # Validate required columns
    if "class_id" not in train_df.columns:
        raise KeyError(f"Missing required 'class_id' column in {train_csv_path}")

    feature_order = list(config["features"]["order"])
    missing_features = [col for col in feature_order if col not in train_df.columns]
    if missing_features:
        raise KeyError(
            f"Training dataset {train_csv_path} is missing configured feature columns: {missing_features}"
        )

    # Extract feature matrix X and target labels y
    X = train_df[feature_order].to_numpy(dtype=np.float32)
    y = train_df["class_id"].to_numpy(dtype=np.int32)

    # Model configuration
    model_cfg = config.get("model", {})
    algorithm = model_cfg.get("algorithm", "random_forest")
    if algorithm != "random_forest":
        raise ValueError(
            f"Unsupported algorithm '{algorithm}' in config. Only 'random_forest' is supported."
        )

    random_seed = config.get("random_seed", 42)
    n_estimators = model_cfg.get("n_estimators", 300)
    min_samples_leaf = model_cfg.get("min_samples_leaf", 2)
    max_features = model_cfg.get("max_features", "sqrt")
    class_weight = model_cfg.get("class_weight", "balanced_subsample")
    n_jobs = model_cfg.get("n_jobs", -1)

    estimator = RandomForestClassifier(
        n_estimators=n_estimators,
        min_samples_leaf=min_samples_leaf,
        max_features=max_features,
        class_weight=class_weight,
        n_jobs=n_jobs,
        random_state=random_seed,
    )
    estimator.fit(X, y)

    # Checksums
    with open(split_json_path, "r", encoding="utf-8") as f:
        split_meta_obj = json.load(f)
    split_sha256 = split_meta_obj.get("split_sha256")
    if not split_sha256:
        split_bytes = split_json_path.read_bytes()
        split_sha256 = hashlib.sha256(split_bytes).hexdigest()

    train_bytes = train_csv_path.read_bytes()
    train_sha256 = hashlib.sha256(train_bytes).hexdigest()

    # Determine class codes
    configured_classes = [int(c["code"]) for c in config.get("classes", [])]
    class_codes = configured_classes if configured_classes else sorted(int(c) for c in np.unique(y))

    # Model dictionary conforming to Section 4 of docs/03-contracts.md
    model_dict: dict[str, Any] = {
        "estimator": estimator,
        "feature_names": feature_order,
        "class_codes": class_codes,
        "year": int(year),
        "config": model_cfg,
        "split_sha256": split_sha256,
    }

    # Group counts and pixel counts per class
    pixels_per_class = {
        int(k): int(v) for k, v in train_df["class_id"].value_counts().sort_index().items()
    }
    groups_per_class: dict[int, int] = {}
    if "group_id" in train_df.columns:
        for cls_code in sorted(train_df["class_id"].unique()):
            groups_per_class[int(cls_code)] = int(
                train_df[train_df["class_id"] == cls_code]["group_id"].nunique()
            )
        num_groups = int(train_df["group_id"].nunique())
    else:
        num_groups = 0

    # Training report metadata conforming to Section 4 of docs/03-contracts.md
    report_dict: dict[str, Any] = {
        "schema_version": 1,
        "year": int(year),
        "num_training_groups": num_groups,
        "num_training_pixels": int(len(train_df)),
        "pixels_per_class": pixels_per_class,
        "groups_per_class": groups_per_class,
        "feature_names": feature_order,
        "model_parameters": {
            "algorithm": algorithm,
            "n_estimators": n_estimators,
            "min_samples_leaf": min_samples_leaf,
            "max_features": max_features,
            "class_weight": class_weight,
            "n_jobs": n_jobs,
            "random_state": random_seed,
        },
        "split_sha256": split_sha256,
        "train_csv_sha256": train_sha256,
        "train_input_summary": {
            "train_csv": str(train_csv_path),
            "split_json": str(split_json_path),
        },
    }

    return estimator, model_dict, report_dict


def predict_raster_windowed(
    features_path: Path,
    valid_features_path: Path,
    output_raw_path: Path,
    estimator: RandomForestClassifier,
    feature_names: list[str],
    classes_config: list[dict[str, Any]],
    float_nodata: float = -9999.0,
    class_nodata: int = 0,
    chunk_size: int = 512,
) -> None:
    """Predict whole-scene LULC raster chunk by chunk, writing Byte raster and color table."""
    if not features_path.exists():
        raise FileNotFoundError(f"Features raster not found: {features_path}")
    if not valid_features_path.exists():
        raise FileNotFoundError(f"Valid features raster not found: {valid_features_path}")

    with rasterio.open(features_path) as feat_src, rasterio.open(valid_features_path) as valid_src:
        # Verify grid congruence
        if feat_src.crs != valid_src.crs:
            raise ValueError(
                f"CRS mismatch: features ({feat_src.crs}) vs valid_features ({valid_src.crs})"
            )
        if feat_src.transform != valid_src.transform:
            raise ValueError(
                f"Transform mismatch: features ({feat_src.transform}) vs valid_features ({valid_src.transform})"
            )
        if (feat_src.width, feat_src.height) != (valid_src.width, valid_src.height):
            raise ValueError(
                f"Dimension mismatch: features ({feat_src.width}x{feat_src.height}) "
                f"vs valid_features ({valid_src.width}x{valid_src.height})"
            )

        # Check feature order against raster band descriptions if present
        if feat_src.descriptions and all(feat_src.descriptions):
            descriptions_list = list(feat_src.descriptions)
            if descriptions_list != feature_names:
                raise ValueError(
                    f"Band descriptions {descriptions_list} in {features_path} "
                    f"do not match expected feature order {feature_names}"
                )

        if feat_src.count != len(feature_names):
            raise ValueError(
                f"Band count mismatch: features raster has {feat_src.count} bands, "
                f"expected {len(feature_names)} ({feature_names})"
            )

        output_raw_path.parent.mkdir(parents=True, exist_ok=True)

        profile = {
            "driver": "GTiff",
            "count": 1,
            "dtype": rasterio.uint8,
            "nodata": class_nodata,
            "crs": feat_src.crs,
            "transform": feat_src.transform,
            "width": feat_src.width,
            "height": feat_src.height,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }

        with rasterio.open(output_raw_path, "w", **profile) as out_dst:
            for window in iter_windows(feat_src.width, feat_src.height, chunk_size=chunk_size):
                feat_block = feat_src.read(window=window)  # shape: (count, win_h, win_w)
                valid_block = valid_src.read(1, window=window)  # shape: (win_h, win_w)

                # Valid condition: valid_features == 1 and all 10 feature values are finite and != float_nodata
                valid_mask = (valid_block == 1)
                for b_idx in range(feat_block.shape[0]):
                    band_slice = feat_block[b_idx]
                    valid_mask &= np.isfinite(band_slice) & (band_slice != float_nodata)

                out_block = np.full((window.height, window.width), class_nodata, dtype=np.uint8)

                if np.any(valid_mask):
                    # Transpose to (N_valid, num_features)
                    X_window = feat_block[:, valid_mask].T
                    preds = estimator.predict(X_window)
                    out_block[valid_mask] = preds.astype(np.uint8)

                out_dst.write(out_block, 1, window=window)

            # Write color table
            colormap = build_colormap(classes_config=classes_config, nodata_code=class_nodata)
            out_dst.write_colormap(1, colormap)


def train_predict(ctx: ProjectContext, year: int) -> ClassificationData:
    """Execute P1-C Random Forest training and whole-scene prediction for a given year."""
    if year not in ctx.config.get("years", [1992, 2021]):
        raise ValueError(
            f"Requested year {year} is not declared in project.toml years: {ctx.config.get('years')}"
        )

    # Standard input paths
    train_csv = ctx.data / "processed" / "samples" / str(year) / "train.csv"
    split_json = ctx.data / "processed" / "samples" / str(year) / "split.json"
    features_raster = ctx.data / "processed" / str(year) / "features_30m.tif"
    valid_features_raster = ctx.data / "processed" / str(year) / "valid_features_30m.tif"

    # Standard output paths
    model_path = ctx.outputs / "models" / str(year) / "rf.joblib"
    raw_raster = ctx.outputs / "rasters" / f"lulc_{year}_raw_30m.tif"
    report_json = ctx.reports / "accuracy" / f"training_{year}.json"

    # Train estimator strictly on train.csv
    estimator, model_dict, report_dict = train_classifier(
        train_csv_path=train_csv,
        split_json_path=split_json,
        config=ctx.config,
        year=year,
    )

    # Save model
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model_dict, model_path)

    # Update input summary with paths relative to ctx.root if possible
    def fmt_path(p: Path) -> str:
        try:
            return str(p.relative_to(ctx.root))
        except ValueError:
            return str(p)

    report_dict["train_input_summary"]["features_raster"] = fmt_path(features_raster)
    report_dict["train_input_summary"]["valid_features_raster"] = fmt_path(valid_features_raster)

    # Save training report
    report_json.parent.mkdir(parents=True, exist_ok=True)
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    # Execute windowed prediction
    feature_names = list(ctx.config["features"]["order"])
    classes_config = list(ctx.config.get("classes", []))
    float_nodata = float(ctx.config.get("float_nodata", -9999.0))
    class_nodata = int(ctx.config.get("class_nodata", 0))

    predict_raster_windowed(
        features_path=features_raster,
        valid_features_path=valid_features_raster,
        output_raw_path=raw_raster,
        estimator=estimator,
        feature_names=feature_names,
        classes_config=classes_config,
        float_nodata=float_nodata,
        class_nodata=class_nodata,
    )

    return ClassificationData(year=int(year), model=model_path, raw=raw_raster)
