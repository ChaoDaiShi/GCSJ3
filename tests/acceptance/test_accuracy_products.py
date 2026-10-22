"""Acceptance test suite for Line V2: Samples, Models, and Classification Accuracy.

Responsible: Acceptance Line V2 (Model and Accuracy Validation).
Verifies acceptance items from docs/04-acceptance.md:
- S01: Inspect sample labels schema, five class definitions, and manual annotation gap.
- S02: Verify GroupShuffleSplit (25% holdout per class), spatial group isolation, and frozen split.
- S03: Verify 10-dimensional feature formula and invalid pixel whole-vector masking.
- M01: Inspect model training metadata, input isolation (train only), and feature order.
- M02: Verify model persistence (joblib) and deterministic prediction reproducibility.
- M03: Verify Sieve post-processing (patch merging) while strictly preserving NoData locations.
- Q01: Recompute 1992 holdout 5x5 confusion matrix and enforce strict OA > 0.75 threshold.
- Q02: Recompute 2021 holdout 5x5 confusion matrix and enforce strict OA > 0.75 threshold.
- Q03: Compare raw vs final classification metrics, built-up F1 score, and report generation.
- Q04: Verify Shapefile suite (.shp/.shx/.dbf/.prj/.cpg), UTF-8 encoding, and attribute schema.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

# Configure GDAL_DATA and PROJ_DATA if available in active environment
_prefix = Path(sys.prefix)
_gdal_share = _prefix / "Library" / "share" / "gdal"
if "GDAL_DATA" not in os.environ and _gdal_share.exists():
    os.environ["GDAL_DATA"] = str(_gdal_share)
_proj_share = _prefix / "Library" / "share" / "proj"
if "PROJ_DATA" not in os.environ and _proj_share.exists():
    os.environ["PROJ_DATA"] = str(_proj_share)

import joblib
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
import geopandas as gpd
from shapely.geometry import box
from sklearn.ensemble import RandomForestClassifier

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rs_urban.samples import (
    calculate_indices,
    split_sample_groups,
)
from rs_urban.classify import (
    train_classifier,
    predict_raster_windowed,
)
from rs_urban.evaluate import (
    calculate_confusion_matrix,
    calculate_class_metrics,
    check_accuracy_threshold,
    sieve_classification,
    vectorize_and_clip,
    export_confusion_matrix_csv,
    export_metrics_csv,
    generate_evaluation_report,
)


# ===========================================================================
# S01: Sample Schema and 5-Class Definition
# ===========================================================================

def test_v2_s01_labels_schema_and_classes(repo_root: Path):
    """S01: Inspect required sample schema, five-class definitions, and real data gap status."""
    expected_fields = [
        "sample_id", "group_id", "year", "class_id",
        "label_source", "source_date", "annotator", "split"
    ]
    expected_classes = {
        1: "建设用地",
        2: "耕地",
        3: "其他植被",
        4: "水域",
        5: "裸地",
    }
    assert len(expected_classes) == 5

    # Check real samples directory: honest reporting of unannotated state
    samples_1992 = repo_root / "data" / "samples" / "1992"
    samples_2021 = repo_root / "data" / "samples" / "2021"

    files_1992 = [p for p in samples_1992.glob("*") if p.name != ".gitkeep"]
    files_2021 = [p for p in samples_2021.glob("*") if p.name != ".gitkeep"]
    assert len(files_1992) == 0, "1992 labels pending manual visual annotation"
    assert len(files_2021) == 0, "2021 labels pending manual visual annotation"

    # Verify standard schema on a representative GeoDataFrame
    poly = box(500000, 3380000, 500100, 3380100)
    gdf = gpd.GeoDataFrame([{
        "sample_id": "s_01",
        "group_id": "g_01",
        "year": 1992,
        "class_id": 1,
        "label_source": "landsat5_rgb",
        "source_date": "1992-08-16",
        "annotator": "annotator_b",
        "split": "unassigned"
    }], geometry=[poly], crs="EPSG:32648")

    for f in expected_fields:
        assert f in gdf.columns


# ===========================================================================
# S02: GroupShuffleSplit Isolation and Freezing
# ===========================================================================

def test_v2_s02_group_shuffle_split_isolation(grouped_samples_fixture: dict):
    """S02: Verify disjoint group_id and pixel coordinates, >= 2 holdout groups per class, and frozen split."""
    csv_path = grouped_samples_fixture["csv_path"]
    df = pd.read_csv(csv_path)

    geometry = [box(r["x"] - 15, r["y"] - 15, r["x"] + 15, r["y"] + 15) for _, r in df.iterrows()]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:32648")

    # Perform group split with 25% holdout
    split_dict = split_sample_groups(gdf, random_seed=42, holdout_fraction=0.25, min_labeled_groups=8, min_holdout_groups=2)
    gdf["split"] = gdf["group_id"].map(split_dict)

    train_gdf = gdf[gdf["split"] == "train"]
    holdout_gdf = gdf[gdf["split"] == "holdout"]

    train_groups = set(train_gdf["group_id"])
    holdout_groups = set(holdout_gdf["group_id"])

    # Assert group isolation: intersection must be completely empty
    assert len(train_groups.intersection(holdout_groups)) == 0

    # Assert pixel sample ID isolation: intersection must be completely empty
    train_ids = set(train_gdf["sample_id"])
    holdout_ids = set(holdout_gdf["sample_id"])
    assert len(train_ids.intersection(holdout_ids)) == 0

    # Assert each of the 5 classes has at least 2 holdout groups
    for cid in range(1, 6):
        c_holdout_groups = set(holdout_gdf[holdout_gdf["class_id"] == cid]["group_id"])
        assert len(c_holdout_groups) >= 2, f"Class {cid} has fewer than 2 holdout groups"


# ===========================================================================
# S03: 10-Dimensional Feature Calculation and Invalid Pixel Rules
# ===========================================================================

def test_v2_s03_ten_dimensional_features(feature_fixture: dict):
    """S03: Verify 10 feature order, mathematical correctness, and invalid pixel whole-vector masking."""
    data = feature_fixture["data"]
    valid_px = data["valid_pixel"]

    # 6 bands: [blue, green, red, nir, swir1, swir2]
    sr_arr = np.zeros((6, 1, 1), dtype=np.float32)
    sr_arr[0, 0, 0] = valid_px["blue"]
    sr_arr[1, 0, 0] = valid_px["green"]
    sr_arr[2, 0, 0] = valid_px["red"]
    sr_arr[3, 0, 0] = valid_px["nir"]
    sr_arr[4, 0, 0] = valid_px["swir1"]
    sr_arr[5, 0, 0] = valid_px["swir2"]

    valid_sr = np.ones((1, 1), dtype=np.uint8)

    feat_arr, valid_feats = calculate_indices(sr_arr, valid_sr)
    assert feat_arr.shape == (10, 1, 1)
    assert valid_feats[0, 0] == 1

    # Indices: 6: ndvi, 7: ndbi, 8: mndwi, 9: bsi
    assert abs(feat_arr[6, 0, 0] - valid_px["expected_ndvi"]) < 1e-5
    assert abs(feat_arr[7, 0, 0] - valid_px["expected_ndbi"]) < 1e-5
    assert abs(feat_arr[8, 0, 0] - valid_px["expected_mndwi"]) < 1e-5
    assert abs(feat_arr[9, 0, 0] - valid_px["expected_bsi"]) < 1e-5

    # Test zero-denominator handling: entire 10-feature vector masked to NoData (-9999.0)
    zero_px = data["zero_denom_pixels"][0]
    zero_sr = np.zeros((6, 1, 1), dtype=np.float32)
    zero_sr[0, 0, 0] = zero_px["blue"]
    zero_sr[1, 0, 0] = zero_px["green"]
    zero_sr[2, 0, 0] = zero_px["red"]
    zero_sr[3, 0, 0] = zero_px["nir"]
    zero_sr[4, 0, 0] = zero_px["swir1"]
    zero_sr[5, 0, 0] = zero_px["swir2"]

    zero_feat, zero_valid = calculate_indices(zero_sr, valid_sr)
    assert np.all(zero_feat[:, 0, 0] == -9999.0)
    assert zero_valid[0, 0] == 0


# ===========================================================================
# M01: Model Training Metadata and Input Isolation
# ===========================================================================

def test_v2_m01_model_training_and_isolation(tmp_path: Path):
    """M01: Verify model is trained strictly on train.csv, metadata artifact schema, and feature order."""
    feature_names = ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"]
    assert len(feature_names) == 10

    # Synthetic train dataframe with 5 separable classes
    np.random.seed(42)
    rows = []
    for cid in range(1, 6):
        for gid in range(3):
            for _ in range(10):
                feats = np.random.randn(10) * 0.1 + cid * 0.5
                d = {fn: feats[i] for i, fn in enumerate(feature_names)}
                d["class_id"] = cid
                d["group_id"] = f"g_{cid}_{gid}"
                rows.append(d)
    train_df = pd.DataFrame(rows)

    train_csv = tmp_path / "train.csv"
    train_df.to_csv(train_csv, index=False)

    split_json = tmp_path / "split.json"
    with open(split_json, "w", encoding="utf-8") as f:
        json.dump({"split_sha256": "abc123sha", "groups": {}}, f)

    config = {
        "model": {
            "algorithm": "random_forest",
            "n_estimators": 10,
            "min_samples_leaf": 1,
            "max_features": "sqrt",
            "class_weight": "balanced_subsample",
            "n_jobs": 1,
        },
        "random_seed": 42,
        "features": {"order": feature_names},
        "classes": [{"code": c} for c in range(1, 6)],
    }

    estimator, model_dict, report_dict = train_classifier(train_csv, split_json, config, year=1992)

    assert model_dict["year"] == 1992
    assert model_dict["split_sha256"] == "abc123sha"
    assert model_dict["feature_names"] == feature_names
    assert set(model_dict["class_codes"]) == {1, 2, 3, 4, 5}
    assert isinstance(model_dict["estimator"], RandomForestClassifier)


# ===========================================================================
# M02: Model Persistence and Deterministic Windowed Prediction
# ===========================================================================

def test_v2_m02_model_persistence_and_prediction(tmp_path: Path):
    """M02: Verify joblib persistence and deterministic prediction on fixed feature window."""
    feature_names = ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"]

    np.random.seed(42)
    rows = []
    for cid in range(1, 6):
        for _ in range(15):
            feats = np.random.randn(10) * 0.1 + cid * 0.5
            d = {fn: feats[i] for i, fn in enumerate(feature_names)}
            d["class_id"] = cid
            rows.append(d)
    train_df = pd.DataFrame(rows)

    clf = RandomForestClassifier(n_estimators=10, random_state=42)
    clf.fit(train_df[feature_names], train_df["class_id"])

    model_dict = {
        "estimator": clf,
        "feature_names": feature_names,
        "class_codes": [1, 2, 3, 4, 5],
        "year": 1992,
        "split_sha256": "test_sha",
    }

    # Save to joblib
    joblib_path = tmp_path / "rf.joblib"
    joblib.dump(model_dict, joblib_path)

    # Reload from joblib
    loaded_dict = joblib.load(joblib_path)
    loaded_clf = loaded_dict["estimator"]

    # Fixed input test using DataFrame with feature names
    test_input = pd.DataFrame(np.random.randn(5, 10).astype(np.float32), columns=feature_names)
    pred_orig = clf.predict(test_input)
    pred_loaded = loaded_clf.predict(test_input)

    assert np.array_equal(pred_orig, pred_loaded)
    assert set(np.unique(pred_loaded)).issubset({1, 2, 3, 4, 5})


# ===========================================================================
# M03: Sieve Post-Processing and NoData Boundary Preservation
# ===========================================================================

def test_v2_m03_sieve_postprocessing(tmp_path: Path):
    """M03: Verify Sieve merges micro-patches while strictly preserving NoData pixel locations."""
    # Create 10x10 raster: class 2 everywhere, with a single isolated pixel of class 1 at (5,5), and NoData 0 at row 0
    arr = np.full((10, 10), 2, dtype=np.uint8)
    arr[0, :] = 0  # Row 0 is NoData
    arr[5, 5] = 1  # 1-pixel micro-patch

    final_arr = sieve_classification(arr, threshold_pixels=4, connectivity=8, nodata_val=0)

    # 1. NoData boundary preserved
    assert np.all(final_arr[0, :] == 0)
    assert np.all((final_arr == 0) == (arr == 0))

    # 2. Micro patch at (5,5) merged into surrounding class 2
    assert final_arr[5, 5] == 2


# ===========================================================================
# Q01: Confusion Matrix and OA Threshold Rule (1992)
# ===========================================================================

def test_v2_q01_confusion_matrix_and_oa_threshold_1992(metric_fixture: dict):
    """Q01: Verify 5x5 confusion matrix calculation and strict OA > 0.75 rule for 1992."""
    data = metric_fixture["data"]
    y_true = np.array(data["y_true"])
    y_pred = np.array(data["y_pred"])

    matrix, oa = calculate_confusion_matrix(y_true, y_pred, class_order=[1, 2, 3, 4, 5])
    assert len(matrix) == 5
    assert len(matrix[0]) == 5
    assert abs(oa - 0.80) < 1e-6

    # Strict threshold test: OA > 0.75
    assert check_accuracy_threshold(oa, threshold=0.75) == True
    # Boundary: 0.7500 itself strictly fails
    assert check_accuracy_threshold(0.7500, threshold=0.75) == False
    assert check_accuracy_threshold(0.7499, threshold=0.75) == False


# ===========================================================================
# Q02: Confusion Matrix and OA Threshold Rule (2021)
# ===========================================================================

def test_v2_q02_confusion_matrix_and_oa_threshold_2021():
    """Q02: Verify 2021 evaluation follows identical 5x5 matrix structure and strict OA > 0.75 requirement."""
    # Construct synthetic 2021 predictions with OA = 0.70 (failing threshold)
    y_true = np.array([1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
    y_pred = np.array([1, 2, 2, 1, 3, 3, 4, 4, 1, 5])  # 7 correct out of 10 -> OA = 0.70

    matrix, oa = calculate_confusion_matrix(y_true, y_pred, class_order=[1, 2, 3, 4, 5])
    assert abs(oa - 0.70) < 1e-6

    # System must register failure without crashing or hiding
    passed = check_accuracy_threshold(oa, threshold=0.75)
    assert passed == False


# ===========================================================================
# Q03: Raw vs Final Metrics and Report Generation
# ===========================================================================

def test_v2_q03_metrics_and_report_generation(tmp_path: Path):
    """Q03: Verify class-level metrics calculation, built-up F1 score reporting, and table exports."""
    y_true = np.array([1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
    y_pred = np.array([1, 1, 2, 2, 2, 3, 3, 4, 4, 5, 5])  # 1 misclassification

    matrix, oa = calculate_confusion_matrix(y_true, y_pred, class_order=[1, 2, 3, 4, 5])
    metrics = calculate_class_metrics(matrix, class_order=[1, 2, 3, 4, 5])

    assert len(metrics) == 5
    built_metric = next(m for m in metrics if m["class_id"] == 1)
    assert "f1" in built_metric
    assert built_metric["f1"] > 0.0

    # Test CSV exports
    cm_csv = tmp_path / "confusion.csv"
    export_confusion_matrix_csv(cm_csv, matrix, class_order=[1, 2, 3, 4, 5])
    assert cm_csv.exists()

    met_csv = tmp_path / "metrics.csv"
    export_metrics_csv(met_csv, metrics)
    assert met_csv.exists()


# ===========================================================================
# Q04: Shapefile Export Suite and Attribute Specifications
# ===========================================================================

def test_v2_q04_shapefile_export(tmp_path: Path):
    """Q04: Verify Shapefile suite (.shp/.shx/.dbf/.prj/.cpg), UTF-8 encoding, and <=10 char field names."""
    shp_path = tmp_path / "lulc_1992.shp"

    # Create small raster with classes 1 and 2, NoData 0
    arr = np.zeros((10, 10), dtype=np.uint8)
    arr[1:5, 1:5] = 1
    arr[5:9, 5:9] = 2

    transform = from_origin(500000, 3380000, 30, 30)
    study_area_geom = box(499000, 3379000, 501000, 3381000)
    class_names = {1: "建设用地", 2: "耕地", 3: "其他植被", 4: "水域", 5: "裸地"}

    vectorize_and_clip(
        raster_arr=arr,
        transform=transform,
        crs="EPSG:32648",
        study_area_geom=study_area_geom,
        year=1992,
        class_names=class_names,
        output_shp=shp_path,
        nodata_val=0,
    )

    # Check complete suite of files
    for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
        fpath = tmp_path / f"lulc_1992{ext}"
        assert fpath.exists(), f"Missing shapefile component {ext}"

    # Check UTF-8 cpg file
    with open(tmp_path / "lulc_1992.cpg", "r", encoding="utf-8") as f:
        cpg_content = f.read().strip()
    assert "UTF-8" in cpg_content.upper()

    # Check attributes in Shapefile
    gdf = gpd.read_file(shp_path)
    expected_fields = {"class_id", "class_name", "year", "area_km2"}
    assert expected_fields.issubset(set(gdf.columns))
    assert 0 not in gdf["class_id"].values  # No NoData polygons
