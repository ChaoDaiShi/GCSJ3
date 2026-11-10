"""Unit tests for P1-D: post-processing (sieve), vectorization, and independent accuracy evaluation.

Verifies:
1. metric_fixture verification: 4x4 confusion matrix and OA=0.8 calculation.
2. Threshold verification: OA strictly greater than 0.75 (0.75 itself fails).
3. Sieve filtering: isolated pixels (< 4 pixels) merged into surrounding class while
   retaining NoData (0) boundaries.
4. Vectorization and polygon clipping: outputs complete Shapefile suite (.shp, .shx, .dbf, .prj, .cpg)
   with required fields (class_id, class_name, year, area_km2).
5. Metric table exports (confusion matrix CSV and metrics CSV) and JSON/Markdown reports.
6. finalize_evaluate pipeline end-to-end execution.
7. CLI 04_evaluate.py argument parsing.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from pathlib import Path

# Automatically configure GDAL_DATA and PROJ_DATA if available
_prefix = Path(sys.prefix)
_gdal_share = _prefix / "Library" / "share" / "gdal"
if "GDAL_DATA" not in os.environ and _gdal_share.exists():
    os.environ["GDAL_DATA"] = str(_gdal_share)
_proj_share = _prefix / "Library" / "share" / "proj"
if "PROJ_DATA" not in os.environ and _proj_share.exists():
    os.environ["PROJ_DATA"] = str(_proj_share)

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine
import geopandas as gpd
from shapely.geometry import box

from rs_urban.contracts import EvaluationData, ProjectContext
from rs_urban.evaluate import (
    calculate_confusion_matrix,
    calculate_class_metrics,
    check_accuracy_threshold,
    sieve_classification,
    vectorize_and_clip,
    export_confusion_matrix_csv,
    export_metrics_csv,
    generate_evaluation_report,
    finalize_evaluate,
)


# ---------------------------------------------------------------------------
# Test 1: metric_fixture verification (4x4 matrix & OA=0.8)
# ---------------------------------------------------------------------------

def test_metric_fixture_evaluation(metric_fixture: dict):
    """Verify confusion matrix and metrics calculation on metric_fixture."""
    data = metric_fixture["data"]
    y_true = data["y_true"]
    y_pred = data["y_pred"]
    expected_oa = data["overall_accuracy"]
    expected_matrix = data["confusion_matrix"]
    class_order = [1, 2, 3, 4]

    matrix, oa = calculate_confusion_matrix(y_true, y_pred, class_order=class_order)
    assert oa == expected_oa
    assert math.isclose(oa, 0.8, abs_tol=1e-5)
    assert matrix == expected_matrix

    metrics = calculate_class_metrics(matrix, class_order=class_order)
    for exp_item, item in zip(data["class_metrics"], metrics):
        assert item["class_id"] == exp_item["class_id"]
        assert item["support"] == exp_item["support"]
        assert math.isclose(item["precision"], exp_item["precision"], abs_tol=1e-4)
        assert math.isclose(item["recall"], exp_item["recall"], abs_tol=1e-4)
        assert math.isclose(item["f1"], exp_item["f1"], abs_tol=1e-4)


# ---------------------------------------------------------------------------
# Test 2: Threshold verification: OA strictly greater than 0.75
# ---------------------------------------------------------------------------

def test_strict_oa_threshold():
    """Verify that OA must be strictly greater than 0.75 (0.75 is NOT passing)."""
    threshold = 0.75

    # 0.75 exactly -> FAILS
    assert check_accuracy_threshold(0.75, threshold) is False

    # Below 0.75 -> FAILS
    assert check_accuracy_threshold(0.7499, threshold) is False
    assert check_accuracy_threshold(0.60, threshold) is False

    # Strictly above 0.75 -> PASSES
    assert check_accuracy_threshold(0.7501, threshold) is True
    assert check_accuracy_threshold(0.80, threshold) is True


# ---------------------------------------------------------------------------
# Test 3: Sieve filtering of small patches and NoData preservation
# ---------------------------------------------------------------------------

def test_sieve_filter_removes_noise_and_preserves_nodata():
    """Verify GDAL Sieve: isolated 1-pixel patch is merged; NoData (0) remains 0."""
    # 5x5 grid:
    # 0 0 0 0 0
    # 0 1 1 1 0
    # 0 1 2 1 0  <- pixel (2, 2) is isolated class 2
    # 0 1 1 1 0
    # 0 0 0 0 0
    raw_arr = np.array([
        [0, 0, 0, 0, 0],
        [0, 1, 1, 1, 0],
        [0, 1, 2, 1, 0],
        [0, 1, 1, 1, 0],
        [0, 0, 0, 0, 0],
    ], dtype=np.uint8)

    final_arr = sieve_classification(
        raw_arr=raw_arr,
        threshold_pixels=4,
        connectivity=8,
        nodata_val=0,
    )

    # Isolated pixel (2, 2) should be merged into surrounding class 1
    assert final_arr[2, 2] == 1
    # All outer NoData pixels must stay 0 (NoData is preserved)
    assert np.all(final_arr[raw_arr == 0] == 0)
    # Class 1 interior is preserved
    assert final_arr[1, 1] == 1
    assert final_arr[1, 2] == 1
    assert final_arr[3, 3] == 1


# ---------------------------------------------------------------------------
# Test 4: Vectorization, study area clipping, and Shapefile creation
# ---------------------------------------------------------------------------

def test_vectorize_and_clip_to_study_area(tmp_path: Path):
    """Verify raster vectorization, study_area clipping, and full SHP suite generation."""
    out_dir = tmp_path / "vectors"
    out_dir.mkdir(parents=True, exist_ok=True)
    shp_path = out_dir / "lulc_2021.shp"

    # 3x3 classification raster:
    # 1 1 0
    # 1 2 2
    # 4 4 1
    transform = Affine(30.0, 0.0, 500000.0, 0.0, -30.0, 3380090.0)
    crs = "EPSG:32648"
    final_arr = np.array([
        [1, 1, 0],
        [1, 2, 2],
        [4, 4, 1],
    ], dtype=np.uint8)

    # Study area covering bounds [500000, 3380000, 500090, 3380090]
    study_area_poly = box(500000.0, 3380000.0, 500090.0, 3380090.0)
    gdf_study = gpd.GeoDataFrame([{"geometry": study_area_poly}], crs=crs)

    class_names = {
        1: "建设用地",
        2: "耕地",
        3: "其他植被",
        4: "水域",
        5: "裸地",
    }

    result_shp = vectorize_and_clip(
        raster_arr=final_arr,
        transform=transform,
        crs=crs,
        study_area_geom=study_area_poly,
        year=2021,
        class_names=class_names,
        output_shp=shp_path,
        nodata_val=0,
    )

    assert result_shp.exists()
    # Verify complete shapefile suite: .shp, .shx, .dbf, .prj, .cpg
    for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
        file_path = out_dir / f"lulc_2021{ext}"
        assert file_path.exists(), f"Missing required Shapefile component: {file_path}"

    # Read back shapefile and check fields and values
    gdf_res = gpd.read_file(result_shp)
    assert set(gdf_res.columns) >= {"class_id", "class_name", "year", "area_km2", "geometry"}
    assert len(gdf_res) > 0
    assert 0 not in gdf_res["class_id"].values  # NoData must not be vectorized
    assert set(gdf_res["year"].unique()) == {2021}
    assert all(gdf_res["area_km2"] > 0)


# ---------------------------------------------------------------------------
# Test 5: Metric CSV exports and report generation
# ---------------------------------------------------------------------------

def test_export_tables_and_reports(tmp_path: Path):
    """Verify confusion CSV, metrics CSV, and JSON/MD evaluation reports."""
    reports_dir = tmp_path / "reports"
    tables_dir = tmp_path / "tables"
    reports_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    matrix = [
        [10, 2, 0, 0],
        [1, 15, 0, 0],
        [0, 0, 8, 1],
        [0, 0, 0, 9],
    ]
    class_order = [1, 2, 3, 4]
    class_metrics = calculate_class_metrics(matrix, class_order)
    oa = sum(matrix[i][i] for i in range(4)) / sum(sum(r) for r in matrix)

    # 1. Confusion matrix CSV
    conf_csv = tables_dir / "confusion_2021_final.csv"
    export_confusion_matrix_csv(conf_csv, matrix, class_order)
    assert conf_csv.exists()
    with open(conf_csv, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert reader[0] == ["true_class", "pred_1", "pred_2", "pred_3", "pred_4"]
        assert len(reader) == 5

    # 2. Metrics CSV
    metrics_csv = tables_dir / "metrics_2021_final.csv"
    export_metrics_csv(metrics_csv, class_metrics)
    assert metrics_csv.exists()
    with open(metrics_csv, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert reader[0] == ["class_id", "precision", "recall", "f1", "support"]
        assert len(reader) == 5

    # 3. Reports
    json_path = reports_dir / "evaluation_2021.json"
    md_path = reports_dir / "evaluation_2021.md"
    generate_evaluation_report(
        json_path=json_path,
        md_path=md_path,
        year=2021,
        oa_raw=0.76,
        oa_final=oa,
        matrix_raw=matrix,
        matrix_final=matrix,
        metrics_raw=class_metrics,
        metrics_final=class_metrics,
        total_samples=sum(sum(r) for r in matrix),
        total_groups=10,
        oa_threshold=0.75,
        f1_target=0.75,
    )
    assert json_path.exists()
    assert md_path.exists()

    with open(json_path, "r", encoding="utf-8") as f:
        rep_json = json.load(f)
    assert rep_json["year"] == 2021
    assert rep_json["oa_final"] == oa
    assert rep_json["passed_oa_threshold"] is True

    md_content = md_path.read_text(encoding="utf-8")
    assert "# 2021 年土地覆盖分类独立精度评价报告" in md_content
    assert "Overall Accuracy (OA)" in md_content
    assert "通过" in md_content


# ---------------------------------------------------------------------------
# Test 6: finalize_evaluate end-to-end pipeline
# ---------------------------------------------------------------------------

def test_finalize_evaluate_pipeline(tmp_path: Path):
    """Verify finalize_evaluate loads raw, applies sieve, clips vectors, and evaluates holdout."""
    root = tmp_path / "project"
    data = root / "data"
    outputs = root / "outputs"
    reports = root / "reports"
    scratch = root / "scratch"

    year = 2021

    # Create raw classification raster (3x3)
    raw_dir = outputs / "rasters"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"lulc_{year}_raw_30m.tif"

    transform = Affine(30.0, 0.0, 500000.0, 0.0, -30.0, 3380090.0)
    crs = "EPSG:32648"

    raw_arr = np.array([
        [1, 1, 1],
        [2, 2, 3],
        [4, 4, 5],
    ], dtype=np.uint8)

    with rasterio.open(
        raw_path, "w", driver="GTiff", height=3, width=3, count=1,
        dtype="uint8", crs=crs, transform=transform, nodata=0,
    ) as dst:
        dst.write(raw_arr, 1)

    # Create study_area GPKG
    bnd_dir = data / "processed" / "boundaries"
    bnd_dir.mkdir(parents=True, exist_ok=True)
    bnd_gpkg = bnd_dir / "xindu_2021.gpkg"
    gdf_study = gpd.GeoDataFrame(
        [{"area_id": "510114", "name": "新都区", "reference_year": 2021, "geometry": box(500000, 3380000, 500090, 3380090)}],
        crs=crs,
    )
    gdf_study.to_file(bnd_gpkg, layer="study_area")

    # Create holdout.csv
    samples_dir = data / "processed" / "samples" / str(year)
    samples_dir.mkdir(parents=True, exist_ok=True)
    holdout_path = samples_dir / "holdout.csv"

    # 5 samples corresponding to each cell
    holdout_rows = [
        {"sample_id": "h1", "group_id": "g1", "year": year, "class_id": 1, "row": 0, "col": 0},
        {"sample_id": "h2", "group_id": "g2", "year": year, "class_id": 1, "row": 0, "col": 1},
        {"sample_id": "h3", "group_id": "g3", "year": year, "class_id": 2, "row": 1, "col": 0},
        {"sample_id": "h4", "group_id": "g4", "year": year, "class_id": 4, "row": 2, "col": 0},
        {"sample_id": "h5", "group_id": "g5", "year": year, "class_id": 5, "row": 2, "col": 2},
    ]
    with open(holdout_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_id", "group_id", "year", "class_id", "row", "col"])
        writer.writeheader()
        writer.writerows(holdout_rows)

    # Create split.json
    split_path = samples_dir / "split.json"
    split_info = {
        "year": year,
        "holdout_groups": ["g1", "g2", "g3", "g4", "g5"],
        "train_groups": ["t1", "t2"],
    }
    split_path.write_text(json.dumps(split_info), encoding="utf-8")

    ctx = ProjectContext(
        root=root,
        data=data,
        outputs=outputs,
        reports=reports,
        scratch=scratch,
        config={
            "target_crs": "EPSG:32648",
            "boundary_reference_year": 2021,
            "postprocess": {
                "sieve_threshold_pixels": 4,
                "connectivity": 8,
            },
            "evaluation": {
                "overall_accuracy_strictly_greater_than": 0.75,
                "built_up_f1_target": 0.75,
                "class_order": [1, 2, 3, 4, 5],
            },
            "classes": [
                {"code": 1, "name": "建设用地", "color": "#D95F02"},
                {"code": 2, "name": "耕地", "color": "#E6C84F"},
                {"code": 3, "name": "其他植被", "color": "#2E8B57"},
                {"code": 4, "name": "水域", "color": "#377EB8"},
                {"code": 5, "name": "裸地", "color": "#B69C7D"},
            ],
        },
    )

    eval_data: EvaluationData = finalize_evaluate(ctx, year=year)

    assert eval_data.year == year
    assert eval_data.final.exists()
    assert eval_data.vectors.exists()
    assert eval_data.report.exists()
    assert eval_data.oa_final > 0

    # Verify final raster properties
    with rasterio.open(eval_data.final) as src:
        assert src.dtypes[0] == "uint8"
        assert src.nodata == 0


# ---------------------------------------------------------------------------
# Test 7: CLI invocation of 04_evaluate.py
# ---------------------------------------------------------------------------

def test_cli_evaluate_invocation(tmp_path: Path):
    """Verify CLI error on missing year and help display."""
    import subprocess
    import sys

    # Missing --year
    cmd = [sys.executable, "src/04_evaluate.py"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "required" in res.stderr.lower() or "error" in res.stderr.lower()

    # Help
    cmd_help = [sys.executable, "src/04_evaluate.py", "--help"]
    res_help = subprocess.run(cmd_help, capture_output=True, text=True)
    assert res_help.returncode == 0
    assert "--year" in res_help.stdout
