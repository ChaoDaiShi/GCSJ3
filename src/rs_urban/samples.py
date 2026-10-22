"""Sample processing, 10-band feature extraction, and stratified group splitting.

Module owner: B (samples).
Public interface:
  build_samples(ctx: ProjectContext, year: int) -> SampleData
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.windows
from sklearn.model_selection import GroupShuffleSplit

from rs_urban.contracts import ProjectContext, SampleData

SAMPLE_CSV_FIELDNAMES = [
    "sample_id", "group_id", "year", "class_id",
    "row", "col", "x", "y",
    "blue", "green", "red", "nir", "swir1", "swir2",
    "ndvi", "ndbi", "mndwi", "bsi",
]

DEFAULT_FEATURE_ORDER = [
    "blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"
]


def calculate_indices(
    sr_arr: np.ndarray,
    valid_sr: np.ndarray,
    float_nodata: float = -9999.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Calculate 10 features (6 SR bands + 4 spectral indices) from a 6-band SR array.

    sr_arr shape: (6, H, W) in order: blue, green, red, nir, swir1, swir2
    valid_sr shape: (H, W), values: 1=valid, 0=in-area invalid, 255=outside area

    Formulas:
      NDVI  = (nir - red) / (nir + red)
      NDBI  = (swir1 - nir) / (swir1 + nir)
      MNDWI = (green - swir1) / (green + swir1)
      BSI   = ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue))

    Rule:
      When any denominator is 0, any input band is NoData/NaN/Inf, or valid_sr != 1,
      all 10 features for that pixel are marked as float_nodata (-9999.0).
      valid_features is 1 if valid, 0 if in-area invalid, and 255 if outside study area.
    """
    blue = sr_arr[0]
    green = sr_arr[1]
    red = sr_arr[2]
    nir = sr_arr[3]
    swir1 = sr_arr[4]
    swir2 = sr_arr[5]

    denom_ndvi = nir + red
    denom_ndbi = swir1 + nir
    denom_mndwi = green + swir1
    denom_bsi = (swir1 + red) + (nir + blue)

    # Check finite and non-nodata in all 6 input bands
    finite_mask = np.ones(valid_sr.shape, dtype=bool)
    for b in range(6):
        finite_mask &= np.isfinite(sr_arr[b]) & (sr_arr[b] != float_nodata)

    # Check non-zero denominators
    nonzero_denom = (
        (denom_ndvi != 0.0)
        & (denom_ndbi != 0.0)
        & (denom_mndwi != 0.0)
        & (denom_bsi != 0.0)
    )

    is_valid = (valid_sr == 1) & finite_mask & nonzero_denom

    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(is_valid, (nir - red) / denom_ndvi, float_nodata).astype(np.float32)
        ndbi = np.where(is_valid, (swir1 - nir) / denom_ndbi, float_nodata).astype(np.float32)
        mndwi = np.where(is_valid, (green - swir1) / denom_mndwi, float_nodata).astype(np.float32)
        bsi = np.where(
            is_valid,
            ((swir1 + red) - (nir + blue)) / denom_bsi,
            float_nodata,
        ).astype(np.float32)

    masked_sr = [
        np.where(is_valid, sr_arr[b], float_nodata).astype(np.float32)
        for b in range(6)
    ]

    features = np.stack(masked_sr + [ndvi, ndbi, mndwi, bsi], axis=0)

    valid_features = np.zeros(valid_sr.shape, dtype=np.uint8)
    valid_features[valid_sr == 255] = 255
    valid_features[is_valid] = 1

    return features, valid_features


def generate_features_raster(
    sr_path: Path,
    valid_sr_path: Path,
    out_features_path: Path,
    out_valid_features_path: Path,
    config: dict[str, Any],
) -> tuple[Path, Path]:
    """Generate 10-band Float32 features GeoTIFF and 1-band Byte valid_features GeoTIFF."""
    float_nodata = float(config.get("float_nodata", -9999.0))
    feature_order = config.get("features", {}).get("order", DEFAULT_FEATURE_ORDER)

    with rasterio.open(sr_path) as src_sr, rasterio.open(valid_sr_path) as src_valid:
        meta_features = src_sr.meta.copy()
        meta_features.update({
            "count": len(feature_order),
            "dtype": "float32",
            "nodata": float_nodata,
        })

        meta_valid = src_valid.meta.copy()
        meta_valid.update({
            "count": 1,
            "dtype": "uint8",
            "nodata": 255,
        })

        out_features_path.parent.mkdir(parents=True, exist_ok=True)
        out_valid_features_path.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(out_features_path, "w", **meta_features) as dst_f, \
             rasterio.open(out_valid_features_path, "w", **meta_valid) as dst_vf:
            dst_f.descriptions = tuple(feature_order)

            for _, window in src_sr.block_windows():
                sr_block = src_sr.read(window=window).astype(np.float32)
                valid_block = src_valid.read(1, window=window)

                f_block, vf_block = calculate_indices(
                    sr_block, valid_block, float_nodata=float_nodata
                )

                dst_f.write(f_block, window=window)
                dst_vf.write(vf_block, 1, window=window)

    return out_features_path, out_valid_features_path


def split_sample_groups(
    labels_gdf: gpd.GeoDataFrame,
    random_seed: int = 42,
    holdout_fraction: float = 0.25,
    min_labeled_groups: int = 8,
    min_holdout_groups: int = 2,
    existing_split_path: Path | None = None,
) -> dict[str, str]:
    """Perform stratified GroupShuffleSplit on unique group_ids by class_id.

    Returns a dict mapping group_id -> 'train' | 'holdout'.
    If existing_split_path exists, reloads and validates the frozen split.
    """
    if existing_split_path is not None and existing_split_path.exists():
        with open(existing_split_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            saved_groups = data.get("groups", {})
            gdf_groups = set(labels_gdf["group_id"].unique())
            if gdf_groups.issubset(saved_groups.keys()):
                return {g: saved_groups[g] for g in gdf_groups}

    # Verify that each group belongs to exactly one class
    group_classes = labels_gdf.groupby("group_id")["class_id"].unique()
    for g_id, c_ids in group_classes.items():
        if len(c_ids) > 1:
            raise ValueError(
                f"Group {g_id} is associated with multiple classes: {list(c_ids)}"
            )

    split_map: dict[str, str] = {}
    classes_present = sorted(labels_gdf["class_id"].unique())

    for class_id in classes_present:
        class_df = labels_gdf[labels_gdf["class_id"] == class_id]
        unique_groups = sorted(class_df["group_id"].unique())

        if len(unique_groups) < min_labeled_groups:
            raise ValueError(
                f"Class {class_id} has {len(unique_groups)} groups, which is less than "
                f"required minimum of {min_labeled_groups} groups."
            )

        gss = GroupShuffleSplit(
            n_splits=1,
            test_size=holdout_fraction,
            random_state=random_seed,
        )

        dummy_x = np.arange(len(unique_groups))
        train_idx, holdout_idx = next(gss.split(dummy_x, groups=unique_groups))

        train_groups = [unique_groups[i] for i in train_idx]
        holdout_groups = [unique_groups[i] for i in holdout_idx]

        if len(holdout_groups) < min_holdout_groups:
            raise ValueError(
                f"Class {class_id} resulted in {len(holdout_groups)} holdout groups, "
                f"less than required minimum of {min_holdout_groups} holdout groups."
            )

        for g in train_groups:
            split_map[g] = "train"
        for g in holdout_groups:
            split_map[g] = "holdout"

    return split_map


def extract_pixel_samples(
    features_path: Path,
    valid_features_path: Path,
    labels_gdf: gpd.GeoDataFrame,
    split_map: dict[str, str],
    year: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Extract valid pixel centers within sample polygons into train and holdout datasets.

    Returns:
      train_df, holdout_df, summary_dict
    """
    train_rows: list[dict[str, Any]] = []
    holdout_rows: list[dict[str, Any]] = []
    seen_pixels: dict[tuple[int, int], tuple[str, int]] = {}

    with rasterio.open(features_path) as src_f, rasterio.open(valid_features_path) as src_vf:
        transform = src_f.transform
        width = src_f.width
        height = src_f.height

        for _, row in labels_gdf.iterrows():
            geom = row.geometry
            if geom.is_empty:
                continue

            sample_id = str(row["sample_id"])
            group_id = str(row["group_id"])
            class_id = int(row["class_id"])
            split_type = split_map.get(group_id, "train")

            # Bounding box window for efficiency
            bounds = geom.bounds
            window = rasterio.windows.from_bounds(*bounds, transform=transform).round_offsets().round_lengths()
            r_start = max(0, int(window.row_off) - 1)
            c_start = max(0, int(window.col_off) - 1)
            r_stop = min(height, int(window.row_off + window.height) + 1)
            c_stop = min(width, int(window.col_off + window.width) + 1)

            if r_stop <= r_start or c_stop <= c_start:
                continue

            win = rasterio.windows.Window(c_start, r_start, c_stop - c_start, r_stop - r_start)
            win_transform = rasterio.windows.transform(win, transform)

            win_mask = rasterio.features.geometry_mask(
                [geom],
                out_shape=(int(win.height), int(win.width)),
                transform=win_transform,
                invert=True,
                all_touched=False,
            )

            vf_block = src_vf.read(1, window=win)
            f_block = src_f.read(window=win)

            # Find matching pixels
            matched_indices = np.argwhere(win_mask)
            for r_win, c_win in matched_indices:
                r_global = r_start + r_win
                c_global = c_start + c_win

                # Check duplicate pixel
                coord = (r_global, c_global)
                if coord in seen_pixels:
                    prev_group, prev_class = seen_pixels[coord]
                    if prev_group != group_id or prev_class != class_id:
                        raise ValueError(
                            f"Pixel row={r_global}, col={c_global} assigned to multiple groups "
                            f"({prev_group} vs {group_id}) or classes ({prev_class} vs {class_id})."
                        )
                    continue

                seen_pixels[coord] = (group_id, class_id)

                # Skip invalid or denominator-zero pixels
                if vf_block[r_win, c_win] != 1:
                    continue

                feat_vals = f_block[:, r_win, c_win]
                if not np.all(np.isfinite(feat_vals)) or np.any(feat_vals == -9999.0):
                    continue

                # Pixel center coordinates
                cx, cy = rasterio.transform.xy(transform, r_global, c_global, offset="center")

                record = {
                    "sample_id": sample_id,
                    "group_id": group_id,
                    "year": year,
                    "class_id": class_id,
                    "row": r_global,
                    "col": c_global,
                    "x": cx,
                    "y": cy,
                    "blue": float(feat_vals[0]),
                    "green": float(feat_vals[1]),
                    "red": float(feat_vals[2]),
                    "nir": float(feat_vals[3]),
                    "swir1": float(feat_vals[4]),
                    "swir2": float(feat_vals[5]),
                    "ndvi": float(feat_vals[6]),
                    "ndbi": float(feat_vals[7]),
                    "mndwi": float(feat_vals[8]),
                    "bsi": float(feat_vals[9]),
                }

                if split_type == "train":
                    train_rows.append(record)
                else:
                    holdout_rows.append(record)

    train_df = pd.DataFrame(train_rows, columns=SAMPLE_CSV_FIELDNAMES)
    holdout_df = pd.DataFrame(holdout_rows, columns=SAMPLE_CSV_FIELDNAMES)

    # Validate disjoint groups and pixel coordinates
    train_groups = set(train_df["group_id"].unique()) if not train_df.empty else set()
    holdout_groups = set(holdout_df["group_id"].unique()) if not holdout_df.empty else set()
    if train_groups.intersection(holdout_groups):
        raise ValueError(f"Train and holdout groups intersect: {train_groups.intersection(holdout_groups)}")

    train_coords = set(zip(train_df["row"], train_df["col"])) if not train_df.empty else set()
    holdout_coords = set(zip(holdout_df["row"], holdout_df["col"])) if not holdout_df.empty else set()
    if train_coords.intersection(holdout_coords):
        raise ValueError("Train and holdout pixel coordinates intersect.")

    # Class summary
    class_summary: dict[int, dict[str, int]] = {}
    classes_present = sorted(labels_gdf["class_id"].unique())
    for c in classes_present:
        class_summary[int(c)] = {
            "total_groups": int(len(labels_gdf[labels_gdf["class_id"] == c]["group_id"].unique())),
            "train_groups": int(len(train_df[train_df["class_id"] == c]["group_id"].unique())),
            "holdout_groups": int(len(holdout_df[holdout_df["class_id"] == c]["group_id"].unique())),
            "train_pixels": int((train_df["class_id"] == c).sum()),
            "holdout_pixels": int((holdout_df["class_id"] == c).sum()),
        }

    summary = {
        "total_train_samples": len(train_df),
        "total_holdout_samples": len(holdout_df),
        "class_summary": class_summary,
    }

    return train_df, holdout_df, summary


def build_samples(ctx: ProjectContext, year: int) -> SampleData:
    """Build 10-band features, freeze stratified sample split, and extract train/holdout datasets.

    Public contract:
      build_samples(ctx: ProjectContext, year: int) -> SampleData
    """
    sr_path = ctx.data / "processed" / str(year) / "sr_30m.tif"
    valid_sr_path = ctx.data / "processed" / str(year) / "valid_sr_30m.tif"
    labels_path = ctx.data / "samples" / str(year) / "labels.gpkg"

    if not sr_path.exists():
        raise FileNotFoundError(f"Required input SR raster not found: {sr_path}")
    if not valid_sr_path.exists():
        raise FileNotFoundError(f"Required input valid SR raster not found: {valid_sr_path}")
    if not labels_path.exists():
        raise FileNotFoundError(f"Required input labels vector not found: {labels_path}")

    # Output paths
    features_path = ctx.data / "processed" / str(year) / "features_30m.tif"
    valid_features_path = ctx.data / "processed" / str(year) / "valid_features_30m.tif"
    samples_dir = ctx.data / "processed" / "samples" / str(year)
    samples_dir.mkdir(parents=True, exist_ok=True)

    train_path = samples_dir / "train.csv"
    holdout_path = samples_dir / "holdout.csv"
    split_path = samples_dir / "split.json"

    # Step 1: Generate 10-band features raster and valid_features raster
    generate_features_raster(
        sr_path=sr_path,
        valid_sr_path=valid_sr_path,
        out_features_path=features_path,
        out_valid_features_path=valid_features_path,
        config=ctx.config,
    )

    # Step 2: Read labels GeoPackage
    labels_gdf = gpd.read_file(labels_path, layer="labels")
    target_crs = ctx.config.get("target_crs", "EPSG:32648")
    if labels_gdf.crs is None:
        labels_gdf = labels_gdf.set_crs(target_crs)
    elif labels_gdf.crs.to_string() != target_crs:
        labels_gdf = labels_gdf.to_crs(target_crs)

    # Step 3: Stratified GroupShuffleSplit
    sampling_cfg = ctx.config.get("sampling", {})
    random_seed = int(ctx.config.get("random_seed", 42))
    holdout_fraction = float(sampling_cfg.get("holdout_fraction", 0.25))
    min_labeled_groups = int(sampling_cfg.get("minimum_labeled_groups_per_class", 8))
    min_holdout_groups = int(sampling_cfg.get("minimum_holdout_groups_per_class", 2))

    split_map = split_sample_groups(
        labels_gdf=labels_gdf,
        random_seed=random_seed,
        holdout_fraction=holdout_fraction,
        min_labeled_groups=min_labeled_groups,
        min_holdout_groups=min_holdout_groups,
        existing_split_path=split_path,
    )

    # Step 4: Extract pixel samples
    train_df, holdout_df, summary = extract_pixel_samples(
        features_path=features_path,
        valid_features_path=valid_features_path,
        labels_gdf=labels_gdf,
        split_map=split_map,
        year=year,
    )

    # Step 5: Save train.csv and holdout.csv
    train_df.to_csv(train_path, index=False, encoding="utf-8")
    holdout_df.to_csv(holdout_path, index=False, encoding="utf-8")

    # Step 6: Compute sha256 hash of split and persist split.json
    split_payload = {
        "schema_version": 1,
        "year": year,
        "random_seed": random_seed,
        "holdout_fraction": holdout_fraction,
        "total_groups": len(split_map),
        "train_groups_count": len([g for g, s in split_map.items() if s == "train"]),
        "holdout_groups_count": len([g for g, s in split_map.items() if s == "holdout"]),
        "total_train_samples": len(train_df),
        "total_holdout_samples": len(holdout_df),
        "class_summary": summary["class_summary"],
        "groups": split_map,
    }
    split_canonical = json.dumps(split_map, sort_keys=True).encode("utf-8")
    split_sha256 = hashlib.sha256(split_canonical).hexdigest()
    split_payload["split_sha256"] = split_sha256

    with open(split_path, "w", encoding="utf-8") as f:
        json.dump(split_payload, f, indent=2, ensure_ascii=False)

    # Step 7: Write sampling report to reports/accuracy/sampling_{year}.md
    reports_acc_dir = ctx.reports / "accuracy"
    reports_acc_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_acc_dir / f"sampling_{year}.md"

    report_lines = [
        f"# 遥感样本采集与分组留出说明报告（{year} 年）",
        "",
        f"- **生成年份：** {year}",
        f"- **随机种子：** {random_seed}",
        f"- **留出比例：** {holdout_fraction * 100:.1f}%",
        f"- **总地块组数：** {len(split_map)}",
        f"- **训练样本数（Train）：** {len(train_df)} 像元",
        f"- **独立留出样本数（Holdout）：** {len(holdout_df)} 像元",
        f"- **划分 SHA256：** `{split_sha256}`",
        "",
        "## 各类别样本分布与分组留出统计",
        "",
        "| 类别编码 | 类别名称 | 总组数 | 训练组数 | 留出组数 (Holdout) | 训练像元数 | 留出像元数 |",
        "| :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    class_names = {c["code"]: c["name"] for c in ctx.config.get("classes", [])}
    for c_id, stats in sorted(summary["class_summary"].items()):
        c_name = class_names.get(c_id, f"类别_{c_id}")
        report_lines.append(
            f"| {c_id} | {c_name} | {stats['total_groups']} | {stats['train_groups']} | "
            f"{stats['holdout_groups']} | {stats['train_pixels']} | {stats['holdout_pixels']} |"
        )

    report_lines.extend([
        "",
        "## 独立性核查证据",
        "",
        "- [x] 训练组与留出组交集严格为空（已自动核验）。",
        "- [x] 训练像元坐标与留出像元坐标交集严格为空（已自动核验）。",
        f"- [x] 每类独立留出组均不小于 {min_holdout_groups} 组。",
        "- [x] 像元特征不包含缺失值或分母为 0 像元。",
        "",
    ])

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    return SampleData(
        year=year,
        features=features_path,
        valid_features=valid_features_path,
        train=train_path,
        holdout=holdout_path,
        split=split_path,
    )
