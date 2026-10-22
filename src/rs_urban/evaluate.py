"""Post-processing, vectorization, and independent accuracy evaluation module (P1-D).

Implements:
1. sieve_classification: Applies GDAL SieveFilter to remove isolated speckles (< 4 pixels)
   while preserving class boundaries and strictly retaining NoData (0).
2. vectorize_and_clip: Vectorizes final classification raster, clips to study_area geometry,
   and exports the complete Shapefile suite (.shp, .shx, .dbf, .prj, .cpg) with UTF-8 encoding.
3. calculate_confusion_matrix & calculate_class_metrics: Computes 5x5 confusion matrix, OA,
   precision, recall, and F1 score per class.
4. check_accuracy_threshold: Enforces strict threshold (OA > 0.75; 0.75 itself fails).
5. finalize_evaluate: Executes the end-to-end evaluation pipeline for a given year.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

# Automatically configure GDAL_DATA and PROJ_DATA if available in active environment
_prefix = Path(sys.prefix)
_gdal_share = _prefix / "Library" / "share" / "gdal"
if "GDAL_DATA" not in os.environ and _gdal_share.exists():
    os.environ["GDAL_DATA"] = str(_gdal_share)
_proj_share = _prefix / "Library" / "share" / "proj"
if "PROJ_DATA" not in os.environ and _proj_share.exists():
    os.environ["PROJ_DATA"] = str(_proj_share)

import geopandas as gpd
import numpy as np
import rasterio
from osgeo import gdal
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import shape

from rs_urban.contracts import EvaluationData, ProjectContext


# ---------------------------------------------------------------------------
# 1. Metric Calculations and Threshold Verification
# ---------------------------------------------------------------------------

def calculate_confusion_matrix(
    y_true: list[int] | np.ndarray,
    y_pred: list[int] | np.ndarray,
    class_order: list[int] = [1, 2, 3, 4, 5],
) -> tuple[list[list[int]], float]:
    """Calculate 5x5 confusion matrix and overall accuracy (OA).

    Rows: ground truth classes.
    Columns: predicted classes.
    """
    n_classes = len(class_order)
    class_to_idx = {c: i for i, c in enumerate(class_order)}
    matrix = [[0] * n_classes for _ in range(n_classes)]

    for t, p in zip(y_true, y_pred):
        if t in class_to_idx and p in class_to_idx:
            matrix[class_to_idx[t]][class_to_idx[p]] += 1

    total_samples = sum(sum(row) for row in matrix)
    correct_samples = sum(matrix[i][i] for i in range(n_classes))
    oa = correct_samples / total_samples if total_samples > 0 else 0.0

    return matrix, oa


def calculate_class_metrics(
    matrix: list[list[int]],
    class_order: list[int] = [1, 2, 3, 4, 5],
) -> list[dict[str, Any]]:
    """Compute per-class precision, recall, f1, and support from confusion matrix."""
    n_classes = len(class_order)
    metrics: list[dict[str, Any]] = []

    for i, class_id in enumerate(class_order):
        support = sum(matrix[i])
        pred_total = sum(matrix[r][i] for r in range(n_classes))
        tp = matrix[i][i]

        precision = tp / pred_total if pred_total > 0 else 0.0
        recall = tp / support if support > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        metrics.append({
            "class_id": class_id,
            "support": support,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        })

    return metrics


def check_accuracy_threshold(oa: float, threshold: float = 0.75) -> bool:
    """Enforce strict OA threshold: OA strictly greater than threshold.

    Contract Section 4: final.oa > 0.75 (0.75 itself does NOT pass).
    """
    return oa > threshold


# ---------------------------------------------------------------------------
# 2. Sieve Filtering (GDAL Sieve)
# ---------------------------------------------------------------------------

def sieve_classification(
    raw_arr: np.ndarray,
    threshold_pixels: int = 4,
    connectivity: int = 8,
    nodata_val: int = 0,
) -> np.ndarray:
    """Apply GDAL SieveFilter to remove speckles below threshold_pixels.

    Explicitly passes a binary mask where raw_arr != nodata_val.
    Strictly preserves NoData boundaries.
    """
    height, width = raw_arr.shape
    drv = gdal.GetDriverByName("MEM")

    ds_src = drv.Create("", width, height, 1, gdal.GDT_Byte)
    ds_src.GetRasterBand(1).WriteArray(raw_arr)

    # Explicit binary valid mask (1 for valid pixels, 0 for NoData)
    valid_mask = (raw_arr != nodata_val).astype(np.uint8)
    ds_mask = drv.Create("", width, height, 1, gdal.GDT_Byte)
    ds_mask.GetRasterBand(1).WriteArray(valid_mask)

    ds_dst = drv.Create("", width, height, 1, gdal.GDT_Byte)

    gdal.SieveFilter(
        ds_src.GetRasterBand(1),
        ds_mask.GetRasterBand(1),
        ds_dst.GetRasterBand(1),
        threshold_pixels,
        connectivity,
    )

    filtered_arr = ds_dst.GetRasterBand(1).ReadAsArray()

    # Guarantee NoData locations remain strictly nodata_val
    filtered_arr[raw_arr == nodata_val] = nodata_val

    return filtered_arr.astype(np.uint8)


# ---------------------------------------------------------------------------
# 3. Vectorization and Study Area Clipping
# ---------------------------------------------------------------------------

def vectorize_and_clip(
    raster_arr: np.ndarray,
    transform: Affine,
    crs: str,
    study_area_geom: Any,
    year: int,
    class_names: dict[int, str],
    output_shp: Path,
    nodata_val: int = 0,
) -> Path:
    """Vectorize raster classification, clip to study area, and write ESRI Shapefile suite."""
    mask = raster_arr != nodata_val
    records = []

    for geom_dict, val in shapes(raster_arr, mask=mask, transform=transform):
        class_id = int(val)
        if class_id == nodata_val:
            continue

        poly = shape(geom_dict)
        if study_area_geom is not None:
            poly = poly.intersection(study_area_geom)
            if poly.is_empty:
                continue

        area_km2 = poly.area / 1e6
        records.append({
            "class_id": class_id,
            "class_name": class_names.get(class_id, f"Class_{class_id}"),
            "year": int(year),
            "area_km2": float(area_km2),
            "geometry": poly,
        })

    output_shp.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        # Create empty GeoDataFrame with expected schema
        gdf = gpd.GeoDataFrame(
            columns=["class_id", "class_name", "year", "area_km2", "geometry"],
            crs=crs,
        )
    else:
        gdf = gpd.GeoDataFrame(records, crs=crs)

    # Save to Shapefile
    gdf.to_file(output_shp, driver="ESRI Shapefile", encoding="utf-8")

    # Ensure .cpg file exists with UTF-8 encoding
    cpg_path = output_shp.with_suffix(".cpg")
    cpg_path.write_text("UTF-8\n", encoding="utf-8")

    return output_shp


# ---------------------------------------------------------------------------
# 4. Report and Table Exporters
# ---------------------------------------------------------------------------

def export_confusion_matrix_csv(
    csv_path: Path,
    matrix: list[list[int]],
    class_order: list[int] = [1, 2, 3, 4, 5],
) -> Path:
    """Export confusion matrix CSV with true_class and pred_X headers."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["true_class"] + [f"pred_{c}" for c in class_order]

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i, c in enumerate(class_order):
            writer.writerow([c, *matrix[i]])

    return csv_path


def export_metrics_csv(
    csv_path: Path,
    metrics: list[dict[str, Any]],
) -> Path:
    """Export classification metrics CSV (precision, recall, f1, support)."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["class_id", "precision", "recall", "f1", "support"]

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in metrics:
            writer.writerow(row)

    return csv_path


# Enable GDAL exceptions
gdal.UseExceptions()


def generate_evaluation_report(
    json_path: Path,
    md_path: Path,
    year: int,
    oa_raw: float,
    oa_final: float,
    matrix_raw: list[list[int]],
    matrix_final: list[list[int]],
    metrics_raw: list[dict[str, Any]],
    metrics_final: list[dict[str, Any]],
    total_samples: int,
    total_groups: int,
    oa_threshold: float = 0.75,
    f1_target: float = 0.75,
) -> None:
    """Generate accuracy evaluation report in JSON and Markdown formats."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    passed_oa = check_accuracy_threshold(oa_final, oa_threshold)

    built_up_f1 = next((m["f1"] for m in metrics_final if m["class_id"] == 1), 0.0)
    passed_f1 = built_up_f1 >= f1_target

    # Contract Section 4: keep unrounded values in JSON, round in display/markdown
    report_dict = {
        "year": year,
        "total_samples": total_samples,
        "total_groups": total_groups,
        "oa_raw": float(oa_raw),
        "oa_final": float(oa_final),
        "oa_threshold": float(oa_threshold),
        "passed_oa_threshold": bool(passed_oa),
        "built_up_f1_target": float(f1_target),
        "built_up_f1_final": float(built_up_f1),
        "passed_f1_target": bool(passed_f1),
        "matrix_raw": matrix_raw,
        "matrix_final": matrix_final,
        "metrics_raw": metrics_raw,
        "metrics_final": metrics_final,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    md_lines = [
        f"# {year} 年土地覆盖分类独立精度评价报告",
        "",
        f"- **评价年份：** {year}",
        f"- **独立留出样本总数：** {total_samples} 像元",
        f"- **空间地块组数：** {total_groups} 组",
        f"- **原始分类总体精度 Overall Accuracy (OA) (Raw)：** {oa_raw:.4f}",
        f"- **最终分类总体精度 Overall Accuracy (OA) (Final)：** {oa_final:.4f}",
        f"- **硬性准入门槛 (OA > {oa_threshold})：** {'通过 (PASS)' if passed_oa else '未达标 (FAIL)'}",
        f"- **建设用地 F1 目标 (F1 ≥ {f1_target})：** {built_up_f1:.4f} ({'达标' if passed_f1 else '未达标'})",
        "",
        "## 1. 最终分类混淆矩阵 (Final Confusion Matrix)",
        "",
        "| 真实类别 \\ 预测类别 | 建设用地(1) | 耕地(2) | 其他植被(3) | 水域(4) | 裸地(5) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    class_names_map = {1: "建设用地(1)", 2: "耕地(2)", 3: "其他植被(3)", 4: "水域(4)", 5: "裸地(5)"}
    for i, row in enumerate(matrix_final):
        row_str = " | ".join(str(v) for v in row)
        md_lines.append(f"| {class_names_map[i+1]} | {row_str} |")

    md_lines.extend([
        "",
        "## 2. 最终分类各类指标 (Final Class Metrics)",
        "",
        "| 类别代码 | 类别名称 | Precision | Recall | F1-Score | Support |",
        "| :---: | :--- | :---: | :---: | :---: | :---: |",
    ])

    for m in metrics_final:
        cid = m["class_id"]
        cname = class_names_map.get(cid, str(cid))
        md_lines.append(f"| {cid} | {cname} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['support']} |")

    md_lines.append("")
    md_path.write_text("\n".join(md_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. Pipeline Entry Point: finalize_evaluate
# ---------------------------------------------------------------------------

def finalize_evaluate(ctx: ProjectContext, year: int) -> EvaluationData:
    """Execute P1-D postprocessing, vectorization, and independent accuracy evaluation.

    Returns EvaluationData.
    """
    raw_path = ctx.outputs / "rasters" / f"lulc_{year}_raw_30m.tif"
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw classification raster not found: {raw_path}")

    holdout_csv = ctx.data / "processed" / "samples" / str(year) / "holdout.csv"
    if not holdout_csv.exists():
        raise FileNotFoundError(f"Holdout samples CSV not found: {holdout_csv}")

    split_json_path = ctx.data / "processed" / "samples" / str(year) / "split.json"
    total_groups = 0
    if split_json_path.exists():
        with open(split_json_path, "r", encoding="utf-8") as f:
            split_meta = json.load(f)
            total_groups = len(split_meta.get("holdout_groups", []))

    # Read study area boundary for clipping
    ref_year = ctx.config.get("boundary_reference_year", 2021)
    bnd_path = ctx.data / "processed" / "boundaries" / f"xindu_{ref_year}.gpkg"
    study_area_geom = None
    if bnd_path.exists():
        gdf_study = gpd.read_file(bnd_path, layer="study_area")
        study_area_geom = gdf_study.union_all() if hasattr(gdf_study, "union_all") else gdf_study.unary_union
    else:
        raise FileNotFoundError(f"Study area boundary file not found: {bnd_path}")

    # Read raw raster
    with rasterio.open(raw_path) as src:
        raw_arr = src.read(1)
        meta = src.meta.copy()
        crs_str = src.crs.to_string() if src.crs else "EPSG:32648"
        transform = src.transform

    # Retrieve postprocessing parameters
    post_cfg = ctx.config.get("postprocess", {})
    sieve_thresh = int(post_cfg.get("sieve_threshold_pixels", 4))
    connectivity = int(post_cfg.get("connectivity", 8))

    # 1. GDAL Sieve post-processing
    final_arr = sieve_classification(
        raw_arr=raw_arr,
        threshold_pixels=sieve_thresh,
        connectivity=connectivity,
        nodata_val=0,
    )

    # Save final classification raster
    final_dir = ctx.outputs / "rasters"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / f"lulc_{year}_final_30m.tif"

    meta.update({
        "dtype": "uint8",
        "nodata": 0,
        "count": 1,
    })
    with rasterio.open(final_path, "w", **meta) as dst:
        dst.write(final_arr, 1)

    # 2. Vectorize and clip to study area
    class_map = {item["code"]: item["name"] for item in ctx.config.get("classes", [])}
    vector_dir = ctx.outputs / "vectors" / str(year)
    shp_path = vector_dir / f"lulc_{year}.shp"

    vectorize_and_clip(
        raster_arr=final_arr,
        transform=transform,
        crs=crs_str,
        study_area_geom=study_area_geom,
        year=year,
        class_names=class_map,
        output_shp=shp_path,
        nodata_val=0,
    )

    # 3. Read holdout samples and extract raw/final predictions
    holdout_samples: list[dict[str, Any]] = []
    with open(holdout_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            holdout_samples.append({
                "class_id": int(row["class_id"]),
                "row": int(row["row"]),
                "col": int(row["col"]),
                "group_id": row.get("group_id", ""),
            })

    if not holdout_samples:
        raise ValueError(f"Holdout CSV is empty: {holdout_csv}")

    y_true = [s["class_id"] for s in holdout_samples]
    y_raw = [int(raw_arr[s["row"], s["col"]]) for s in holdout_samples]
    y_final = [int(final_arr[s["row"], s["col"]]) for s in holdout_samples]

    eval_cfg = ctx.config.get("evaluation", {})
    class_order = eval_cfg.get("class_order", [1, 2, 3, 4, 5])
    oa_threshold = float(eval_cfg.get("overall_accuracy_strictly_greater_than", 0.75))
    f1_target = float(eval_cfg.get("built_up_f1_target", 0.75))

    matrix_raw, oa_raw = calculate_confusion_matrix(y_true, y_raw, class_order)
    matrix_final, oa_final = calculate_confusion_matrix(y_true, y_final, class_order)

    metrics_raw = calculate_class_metrics(matrix_raw, class_order)
    metrics_final = calculate_class_metrics(matrix_final, class_order)

    # 4. Export CSV tables
    tables_dir = ctx.outputs / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    export_confusion_matrix_csv(tables_dir / f"confusion_{year}_raw.csv", matrix_raw, class_order)
    export_confusion_matrix_csv(tables_dir / f"confusion_{year}_final.csv", matrix_final, class_order)
    export_metrics_csv(tables_dir / f"metrics_{year}_raw.csv", metrics_raw)
    export_metrics_csv(tables_dir / f"metrics_{year}_final.csv", metrics_final)

    # 5. Export evaluation JSON and Markdown reports
    rep_dir = ctx.reports / "accuracy"
    rep_dir.mkdir(parents=True, exist_ok=True)
    json_path = rep_dir / f"evaluation_{year}.json"
    md_path = rep_dir / f"evaluation_{year}.md"

    generate_evaluation_report(
        json_path=json_path,
        md_path=md_path,
        year=year,
        oa_raw=oa_raw,
        oa_final=oa_final,
        matrix_raw=matrix_raw,
        matrix_final=matrix_final,
        metrics_raw=metrics_raw,
        metrics_final=metrics_final,
        total_samples=len(y_true),
        total_groups=total_groups,
        oa_threshold=oa_threshold,
        f1_target=f1_target,
    )

    return EvaluationData(
        year=year,
        final=final_path,
        vectors=shp_path,
        report=md_path,
        oa_raw=oa_raw,
        oa_final=oa_final,
    )
