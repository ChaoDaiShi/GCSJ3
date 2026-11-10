"""Integration tests for rs-urban multi-stage processing pipeline (P2).

Maintained by: Role I (Integration).
Validates:
1. P2-G1 (A -> B):
   - Handover from PreparedData (SR 30m, valid_sr, grid, AOI mask) to SampleData.
   - 10-band feature raster generation (band order, public grid, CRS EPSG:32648).
   - Valid features mask generation (1=valid, 0=in-area invalid, 255=outside AOI).
   - Pixel coordinate alignment: row/col to geographic coordinate center.
   - Mask exclusion: invalid pixels (fill, cloud, shadow, zero-denominator, nodata) excluded.
   - Stratified group splitting: disjoint train/holdout groups, disjoint pixel coordinates.
   - Deterministic split freezing and persistence in split.json.
   - Sampling explanation report generation in reports/accuracy/sampling_{year}.md.
   - Command-line interface execution (01_preprocess.py -> 02_samples.py).
   - Real small-window integration using unpacked Landsat 5 Level-2 scene.
2. Full multi-stage pipeline integration across all five modules (A -> B -> C -> D -> E).
"""

from __future__ import annotations

import csv
import json
import math
import os
import subprocess
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

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
import pytest

from tests.conftest import write_ten_dim_config
import rasterio
from rasterio.transform import Affine, from_origin
from shapely.geometry import Polygon, box

from rs_urban.analyze import (
    CHANGE_COLORMAP,
    TABLE_FIELDNAMES,
    analyze_change,
)
from rs_urban.classify import train_predict
from rs_urban.config import load_context
from rs_urban.contracts import (
    ChangeData,
    ClassificationData,
    EvaluationData,
    PreparedData,
    ProjectContext,
    SampleData,
)
from rs_urban.evaluate import finalize_evaluate
from rs_urban.preprocess import (
    mask_and_scale_surface_reflectance,
    mask_qa_pixel,
    mask_qa_radsat,
    parse_mtl_metadata,
    prepare_boundaries,
    preprocess_year,
)
from rs_urban.samples import build_samples


# ---------------------------------------------------------------------------
# Helper: Setup Synthetic Test Workspace for A -> B Integration
# ---------------------------------------------------------------------------

def _setup_g1_test_environment(tmp_path: Path) -> tuple[ProjectContext, Path, Path]:
    """Create a self-contained temporary workspace with realistic configurations and data."""
    root = tmp_path / "workspace"
    data = root / "data"
    outputs = root / "outputs"
    reports = root / "reports"
    scratch = root / "scratch"

    for d in [data, outputs, reports, scratch]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. Project config
    config_dict = {
        "project_slug": "rs-urban-expansion",
        "study_area": "成都市新都区",
        "years": [1992, 2021],
        "boundary_reference_year": 2021,
        "expected_township_count": 9,
        "target_crs": "EPSG:32648",
        "analysis_resolution_m": 30,
        "display_resolution_m": 15,
        "float_nodata": -9999.0,
        "class_nodata": 0,
        "mask_nodata": 255,
        "random_seed": 42,
        "imagery": {
            "requested_date_1992": "1992-08-16",
            "requested_date_2021": "2021-02-05",
            "surface_reflectance_scale": 0.0000275,
            "surface_reflectance_offset": -0.2,
            "band_order": ["blue", "green", "red", "nir", "swir1", "swir2"],
            "landsat5_bands": [1, 2, 3, 4, 5, 7],
            "landsat8_bands": [2, 3, 4, 5, 6, 7],
            "reflectance_resampling": "bilinear",
            "categorical_resampling": "nearest",
        },
        "features": {
            "order": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"],
        },
        "sampling": {
            "split_group": "group_id",
            "holdout_fraction": 0.25,
            "minimum_labeled_groups_per_class": 8,
            "minimum_holdout_groups_per_class": 2,
        },
        "model": {
            "algorithm": "random_forest",
            "n_estimators": 50,
            "min_samples_leaf": 2,
            "max_features": "sqrt",
            "class_weight": "balanced_subsample",
            "n_jobs": 1,
        },
        "postprocess": {
            "sieve_threshold_pixels": 4,
            "connectivity": 8,
        },
        "evaluation": {
            "overall_accuracy_strictly_greater_than": 0.75,
            "built_up_f1_target": 0.75,
            "class_order": [1, 2, 3, 4],
        },
        "analysis": {
            "elapsed_years": 29,
            "comparison_mask": "intersection_of_valid_pixels",
            "area_unit": "km2",
        },
        "classes": [
            {"code": 1, "name": "城镇及建设用地", "color": "#D95F02"},
            {"code": 2, "name": "耕地", "color": "#E6C84F"},
            {"code": 3, "name": "林草植被", "color": "#2E8B57"},
            {"code": 4, "name": "水体", "color": "#377EB8"},
        ],
    }

    config_path = root / "project.toml"
    with open(config_path, "wb") as f:
        import tomllib
        # Write as TOML string
        lines = [
            'schema_version = 1',
            f'project_slug = "{config_dict["project_slug"]}"',
            f'study_area = "{config_dict["study_area"]}"',
            f'years = [1992, 2021]',
            'boundary_reference_year = 2021',
            'expected_township_count = 9',
            f'target_crs = "{config_dict["target_crs"]}"',
            'analysis_resolution_m = 30',
            'display_resolution_m = 15',
            'float_nodata = -9999.0',
            'class_nodata = 0',
            'mask_nodata = 255',
            'random_seed = 42',
            '',
            '[imagery]',
            'surface_reflectance_scale = 0.0000275',
            'surface_reflectance_offset = -0.2',
            'band_order = ["blue", "green", "red", "nir", "swir1", "swir2"]',
            'landsat5_bands = [1, 2, 3, 4, 5, 7]',
            'landsat8_bands = [2, 3, 4, 5, 6, 7]',
            'reflectance_resampling = "bilinear"',
            'categorical_resampling = "nearest"',
            '',
            '[features]',
            'order = ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"]',
            '',
            '[sampling]',
            'split_group = "group_id"',
            'holdout_fraction = 0.25',
            'minimum_labeled_groups_per_class = 8',
            'minimum_holdout_groups_per_class = 2',
            '',
            '[model]',
            'algorithm = "random_forest"',
            'n_estimators = 50',
            'min_samples_leaf = 2',
            'max_features = "sqrt"',
            'class_weight = "balanced_subsample"',
            'n_jobs = 1',
            '',
            '[postprocess]',
            'sieve_threshold_pixels = 4',
            'connectivity = 8',
            '',
            '[evaluation]',
            'overall_accuracy_strictly_greater_than = 0.75',
            'built_up_f1_target = 0.75',
            'class_order = [1, 2, 3, 4]',
            '',
            '[analysis]',
            'elapsed_years = 29',
            'comparison_mask = "intersection_of_valid_pixels"',
            'area_unit = "km2"',
            '',
        ]
        for c in config_dict["classes"]:
            lines.extend([
                '[[classes]]',
                f'code = {c["code"]}',
                f'name = "{c["name"]}"',
                f'color = "{c["color"]}"',
                '',
            ])
        f.write("\n".join(lines).encode("utf-8"))

    # 2. .env file
    for k in ["RS_DATA_ROOT", "RS_OUTPUT_ROOT", "RS_REPORT_ROOT", "RS_SCRATCH_ROOT", "GDAL_CACHEMAX"]:
        if k in os.environ:
            del os.environ[k]

    env_path = root / ".env"
    env_path.write_text(
        f"RS_DATA_ROOT={data.resolve().as_posix()}\n"
        f"RS_OUTPUT_ROOT={outputs.resolve().as_posix()}\n"
        f"RS_REPORT_ROOT={reports.resolve().as_posix()}\n"
        f"RS_SCRATCH_ROOT={scratch.resolve().as_posix()}\n"
        "GDAL_CACHEMAX=256\n",
        encoding="utf-8",
    )

    # 3. Create boundaries vector
    # 30m grid of 60x60 pixels: bounds [499980, 3379980, 501780, 3381780]
    crs = "EPSG:32648"
    county_geom = box(499980, 3379980, 501780, 3381780)
    gdf_county = gpd.GeoDataFrame(
        [{"area_id": "510114", "name": "新都区", "reference_year": 2021, "geometry": county_geom}],
        crs=crs,
    )
    raw_bnd_dir = data / "raw" / "boundaries" / "county" / "2021"
    raw_bnd_dir.mkdir(parents=True, exist_ok=True)
    county_shp = raw_bnd_dir / "xindu_county.shp"
    gdf_county.to_file(county_shp)

    townships_data = []
    # 9 townships tiled inside county
    for i in range(3):
        for j in range(3):
            idx = i * 3 + j + 1
            t_geom = box(499980 + j * 600, 3379980 + i * 600, 499980 + (j + 1) * 600, 3379980 + (i + 1) * 600)
            u_type = "town" if idx in (8, 9) else "street"
            townships_data.append({
                "unit_id": f"51011400{idx}",
                "name": f"街镇_{idx}",
                "unit_type": u_type,
                "reference_year": 2021,
                "geometry": t_geom,
            })
    gdf_townships = gpd.GeoDataFrame(townships_data, crs=crs)
    raw_t_dir = data / "raw" / "boundaries" / "townships" / "2021"
    raw_t_dir.mkdir(parents=True, exist_ok=True)
    townships_shp = raw_t_dir / "xindu_townships.shp"
    gdf_townships.to_file(townships_shp)

    cat_dir = data / "catalog"
    cat_dir.mkdir(parents=True, exist_ok=True)
    (cat_dir / "boundaries.csv").write_text(
        "dataset_id,reference_year,admin_level,file_path,layer_name,source_crs,source_url,acquired_at,license_note,verification_status\n"
        f"xindu_2021,2021,county,{county_shp.relative_to(data).as_posix()},xindu_county,EPSG:32648,,2026-10-15,,verified\n"
        f"townships_2021,2021,township,{townships_shp.relative_to(data).as_posix()},xindu_townships,EPSG:32648,,2026-10-15,,verified\n",
        encoding="utf-8",
    )

    # 4. Create synthetic 1992 Landsat 5 Level-2 scene
    scene_dir_1992 = data / "raw" / "landsat" / "1992" / "level2" / "LT05_L2SP_129039_19920816_02_T1"
    scene_dir_1992.mkdir(parents=True, exist_ok=True)
    mtl_1992 = scene_dir_1992 / "LT05_L2SP_129039_19920816_02_T1_MTL.txt"
    mtl_1992.write_text("""GROUP = L1_METADATA_FILE
  GROUP = METADATA_FILE_INFO
    LANDSAT_PRODUCT_ID = "LT05_L2SP_129039_19920816_02_T1"
    PROCESSING_LEVEL = "L2SP"
  END_GROUP = METADATA_FILE_INFO
  GROUP = IMAGE_ATTRIBUTES
    SPACECRAFT_ID = "LANDSAT_5"
    DATE_ACQUIRED = 1992-08-16
  END_GROUP = IMAGE_ATTRIBUTES
END_GROUP = L1_METADATA_FILE
END
""", encoding="utf-8")

    transform_30 = Affine(30.0, 0.0, 499980.0, 0.0, -30.0, 3381780.0)
    # 60 rows, 60 cols
    height, width = 60, 60

    # Write 6 bands
    for b in [1, 2, 3, 4, 5, 7]:
        bpath = scene_dir_1992 / f"LT05_L2SP_129039_19920816_02_T1_SR_B{b}.TIF"
        # DN=10000 -> SR = 10000 * 0.0000275 - 0.2 = 0.075
        arr = np.full((height, width), 10000, dtype=np.uint16)
        # Add special test pixels:
        # (row=0, col=0): fill DN=0
        arr[0, 0] = 0
        # (row=0, col=1): high reflectance (DN=20000 -> SR = 0.35)
        arr[0, 1] = 20000
        with rasterio.open(
            bpath, "w", driver="GTiff", height=height, width=width, count=1,
            dtype="uint16", crs=crs, transform=transform_30, nodata=0,
        ) as dst:
            dst.write(arr, 1)

    # QA bands
    qa_path_1992 = scene_dir_1992 / "LT05_L2SP_129039_19920816_02_T1_QA_PIXEL.TIF"
    qa_arr = np.zeros((height, width), dtype=np.uint16)
    qa_arr[0, 0] = 1   # Fill bit 0
    qa_arr[0, 2] = 8   # Cloud bit 3
    qa_arr[0, 3] = 16  # Cloud shadow bit 4
    qa_arr[0, 4] = 128 # Water bit 7 (retained)
    with rasterio.open(
        qa_path_1992, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint16", crs=crs, transform=transform_30,
    ) as dst:
        dst.write(qa_arr, 1)

    radsat_path_1992 = scene_dir_1992 / "LT05_L2SP_129039_19920816_02_T1_QA_RADSAT.TIF"
    with rasterio.open(
        radsat_path_1992, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint16", crs=crs, transform=transform_30,
    ) as dst:
        dst.write(np.zeros((height, width), dtype=np.uint16), 1)

    # Register in scenes.csv
    (cat_dir / "scenes.csv").write_text(
        "year,sensor,processing_level,product_id,acquisition_date,wrs_path,wrs_row,scene_dir,mtl_path,paired_product_id,source_url,downloaded_at,selection_status\n"
        f"1992,LANDSAT_5,L2SP,LT05_L2SP_129039_19920816_02_T1,1992-08-16,129,039,{scene_dir_1992.relative_to(data).as_posix()},{mtl_1992.relative_to(data).as_posix()},,,2026-10-15,selected\n",
        encoding="utf-8",
    )

    ctx = load_context(config_path, env_path, root_dir=root)
    return ctx, config_path, env_path


def _generate_realistic_sample_polygons(
    out_gpkg_path: Path,
    crs: str = "EPSG:32648",
    xmin: float = 500100.0,
    ymin: float = 3380100.0,
) -> Path:
    """Generate sample polygons with 5 classes and 8 spatial groups per class."""
    out_gpkg_path.parent.mkdir(parents=True, exist_ok=True)
    records = []

    # 5 classes, 8 groups per class = 40 groups
    for class_id in range(1, 6):
        for g_idx in range(1, 9):
            group_id = f"cls_{class_id}_grp_{g_idx:02d}"
            # Create a 60m x 60m polygon (covering 2x2 30m pixels)
            gx = xmin + (g_idx - 1) * 180.0
            gy = ymin + (class_id - 1) * 180.0
            poly = Polygon([
                (gx, gy),
                (gx + 60.0, gy),
                (gx + 60.0, gy + 60.0),
                (gx, gy + 60.0),
                (gx, gy),
            ])
            records.append({
                "sample_id": f"s_{class_id}_{g_idx:02d}",
                "group_id": group_id,
                "year": 1992,
                "class_id": class_id,
                "label_source": "historical_tm_interpretation",
                "source_date": "1992-08-16",
                "annotator": "annotator_B",
                "split": "unassigned",
                "geometry": poly,
            })

    gdf = gpd.GeoDataFrame(records, crs=crs)
    if out_gpkg_path.exists():
        out_gpkg_path.unlink()
    gdf.to_file(out_gpkg_path, layer="labels", driver="GPKG")
    return out_gpkg_path


# ---------------------------------------------------------------------------
# Test 1: P2-G1 Micro-Pipeline Data Handover (A -> B)
# ---------------------------------------------------------------------------

def test_p2_g1_micro_pipeline(tmp_path: Path):
    """Verify data handover from Preprocessing (A) to Samples (B) on micro-grid.

    Contracts verified:
    1. A outputs PreparedData (sr_30m, valid_sr_30m, grid_30m, xindu_2021.gpkg).
    2. B consumes PreparedData and produces SampleData.
    3. 10-band features raster generated with correct order and CRS EPSG:32648.
    4. valid_features raster values strictly within {0, 1, 255}.
    5. Pixel alignment: extracted sample coordinates (x, y) strictly match pixel center.
    6. Mask exclusion: fill and cloud pixels (row=0, col=0..3) are not extracted.
    7. Group separation: train and holdout groups have zero intersection.
    8. Coordinate separation: train and holdout pixel centers have zero intersection.
    9. Stratified holdout: 25% holdout per class, >=2 holdout groups per class.
    10. Split freeze: repeated execution reuses split.json and produces identical sha256.
    11. Sampling report generated in reports/accuracy/sampling_1992.md.
    """
    ctx, _, _ = _setup_g1_test_environment(tmp_path)

    # Step A1: Prepare boundaries
    bnd_path = prepare_boundaries(ctx)
    assert bnd_path.exists()

    # Step A2: Preprocess year 1992
    prepared: PreparedData = preprocess_year(ctx, year=1992)
    assert prepared.year == 1992
    assert prepared.sr.exists()
    assert prepared.valid_sr.exists()

    # Verify SR raster properties from A
    with rasterio.open(prepared.sr) as src:
        assert src.count == 6
        assert src.dtypes[0] == "float32"
        assert src.nodata == -9999.0
        assert src.crs.to_string() == "EPSG:32648"
        assert src.descriptions == ("blue", "green", "red", "nir", "swir1", "swir2")
        sr_transform = src.transform

    # Provide sample polygons (B input)
    labels_path = ctx.data / "samples" / "1992" / "labels.gpkg"
    _generate_realistic_sample_polygons(labels_path)
    assert labels_path.exists()

    # Step B: Build samples
    sample_data: SampleData = build_samples(ctx, year=1992)
    assert sample_data.year == 1992
    assert sample_data.features.exists()
    assert sample_data.valid_features.exists()
    assert sample_data.train.exists()
    assert sample_data.holdout.exists()
    assert sample_data.split.exists()

    # 1. Check features raster
    with rasterio.open(sample_data.features) as src:
        assert src.count == 10
        assert src.dtypes[0] == "float32"
        assert src.nodata == -9999.0
        assert src.descriptions == (
            "blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"
        )
        assert src.transform == sr_transform

    # 2. Check valid_features raster
    with rasterio.open(sample_data.valid_features) as src:
        assert src.dtypes[0] == "uint8"
        assert src.nodata == 255
        val_arr = src.read(1)
        # Pixel (0, 0) was fill -> 0
        assert val_arr[0, 0] == 0
        # Pixel (0, 2) was cloud -> 0
        assert val_arr[0, 2] == 0

    # 3. Check train.csv and holdout.csv
    expected_header = [
        "sample_id", "group_id", "year", "class_id",
        "row", "col", "x", "y",
        "blue", "green", "red", "nir", "swir1", "swir2",
        "ndvi", "ndbi", "mndwi", "bsi",
    ]

    def read_csv(p: Path) -> list[dict[str, str]]:
        with open(p, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == expected_header
            return list(reader)

    train_rows = read_csv(sample_data.train)
    holdout_rows = read_csv(sample_data.holdout)

    assert len(train_rows) > 0
    assert len(holdout_rows) > 0

    # 4. Check pixel coordinate accuracy: center of pixel
    for r in train_rows + holdout_rows:
        row_idx = int(r["row"])
        col_idx = int(r["col"])
        expected_x, expected_y = sr_transform * (col_idx + 0.5, row_idx + 0.5)
        assert math.isclose(float(r["x"]), expected_x, abs_tol=1e-3)
        assert math.isclose(float(r["y"]), expected_y, abs_tol=1e-3)

    # 5. Check group disjointness
    train_groups = {r["group_id"] for r in train_rows}
    holdout_groups = {r["group_id"] for r in holdout_rows}
    assert train_groups.isdisjoint(holdout_groups), "Train and holdout groups must be strictly disjoint!"

    # 6. Check coordinate disjointness
    train_coords = {(float(r["x"]), float(r["y"])) for r in train_rows}
    holdout_coords = {(float(r["x"]), float(r["y"])) for r in holdout_rows}
    assert train_coords.isdisjoint(holdout_coords), "Train and holdout pixel coordinates must be strictly disjoint!"

    # 7. Check stratified split requirements: each class has >=2 holdout groups
    with open(sample_data.split, "r", encoding="utf-8") as f:
        split_meta = json.load(f)

    for class_id_str, class_stats in split_meta["class_summary"].items():
        assert class_stats["holdout_groups"] >= 2, f"Class {class_id_str} must have >= 2 holdout groups!"
        assert class_stats["train_groups"] >= 2

    # 8. Check frozen split reusability
    orig_sha256 = split_meta["split_sha256"]
    sample_data_2 = build_samples(ctx, year=1992)
    with open(sample_data_2.split, "r", encoding="utf-8") as f:
        reloaded_meta = json.load(f)
    assert reloaded_meta["split_sha256"] == orig_sha256

    # 9. Check sampling report
    report_path = ctx.reports / "accuracy" / "sampling_1992.md"
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "遥感样本采集与分组留出说明报告（1992 年）" in report_text
    assert orig_sha256 in report_text


# ---------------------------------------------------------------------------
# Test 2: P2-G1 CLI Subprocess Handover (01_preprocess.py -> 02_samples.py)
# ---------------------------------------------------------------------------

def test_p2_g1_cli_pipeline(tmp_path: Path):
    """Verify execution of CLI entry points 01_preprocess.py and 02_samples.py."""
    ctx, config_path, env_path = _setup_g1_test_environment(tmp_path)
    labels_path = ctx.data / "samples" / "1992" / "labels.gpkg"
    _generate_realistic_sample_polygons(labels_path)

    python_exe = sys.executable
    repo_root = Path(__file__).resolve().parents[2]

    # CLI Step 1: boundaries
    cmd_bnd = [
        python_exe,
        str(repo_root / "src" / "01_preprocess.py"),
        "--config", str(config_path),
        "--env-file", str(env_path),
        "--step", "boundaries",
    ]
    res_bnd = subprocess.run(cmd_bnd, capture_output=True, text=True, cwd=str(repo_root))
    assert res_bnd.returncode == 0, f"01_preprocess boundaries failed: {res_bnd.stderr}"

    # CLI Step 2: surface 1992
    cmd_surf = [
        python_exe,
        str(repo_root / "src" / "01_preprocess.py"),
        "--config", str(config_path),
        "--env-file", str(env_path),
        "--step", "surface",
        "--year", "1992",
    ]
    res_surf = subprocess.run(cmd_surf, capture_output=True, text=True, cwd=str(repo_root))
    assert res_surf.returncode == 0, f"01_preprocess surface failed: {res_surf.stderr}"

    # CLI Step 3: samples 1992
    cmd_samp = [
        python_exe,
        str(repo_root / "src" / "02_samples.py"),
        "--config", str(config_path),
        "--env-file", str(env_path),
        "--year", "1992",
    ]
    res_samp = subprocess.run(cmd_samp, capture_output=True, text=True, cwd=str(repo_root))
    assert res_samp.returncode == 0, f"02_samples failed: {res_samp.stderr}"

    # Check generated files
    assert (ctx.data / "processed" / "1992" / "features_30m.tif").exists()
    assert (ctx.data / "processed" / "samples" / "1992" / "train.csv").exists()
    assert (ctx.data / "processed" / "samples" / "1992" / "holdout.csv").exists()
    assert (ctx.data / "processed" / "samples" / "1992" / "split.json").exists()


# ---------------------------------------------------------------------------
# Test 3: P2-G1 Real Small-Window Integration (A -> B on Real Landsat 5 Scene)
# ---------------------------------------------------------------------------

def test_p2_g1_real_window_a_to_b(tmp_path: Path):
    """Verify A -> B pipeline on an actual 50x50 window extracted from real Landsat 5 scene.

    Checks:
    1. Real Landsat 5 Level-2 scene exists (data/raw/landsat/1992/level2/LT05_L2SP_129044_19920816_20200914_02_T1).
    2. Reads actual USGS sensor bands (SR_B1..B5, B7, QA_PIXEL, QA_RADSAT) and MTL.
    3. Evaluates real DN scaling and QA bit masking.
    4. Computes 10-band spectral features on the real window.
    5. Extracts stratified samples, freezes split.json, and validates spatial group isolation.
    """
    repo_root = Path(__file__).resolve().parents[2]
    real_scene_dir = repo_root / "data" / "raw" / "landsat" / "1992" / "level2" / "LT05_L2SP_129044_19920816_20200914_02_T1"

    if not real_scene_dir.exists():
        pytest.skip(f"Real Landsat 5 scene directory not found at {real_scene_dir}")

    mtl_path = real_scene_dir / "LT05_L2SP_129044_19920816_20200914_02_T1_MTL.txt"
    assert mtl_path.exists()
    meta = parse_mtl_metadata(mtl_path)
    assert meta["SPACECRAFT_ID"] == "LANDSAT_5"
    assert meta["DATE_ACQUIRED"] == "1992-08-16"

    # Setup isolated test workspace
    ctx, _, _ = _setup_g1_test_environment(tmp_path)

    # Pick a 50x50 window from the center of the real Landsat 5 raster
    b1_path = real_scene_dir / "LT05_L2SP_129044_19920816_20200914_02_T1_SR_B1.TIF"
    with rasterio.open(b1_path) as src_b1:
        full_height, full_width = src_b1.height, src_b1.width
        crs = src_b1.crs.to_string()
        # 50x50 window centered in the scene
        win_row_start = full_height // 2
        win_col_start = full_width // 2
        win_h, win_w = 50, 50
        window = rasterio.windows.Window(win_col_start, win_row_start, win_w, win_h)
        win_transform = rasterio.windows.transform(window, src_b1.transform)

    # Read the 6 real SR bands in order [B1, B2, B3, B4, B5, B7]
    real_band_nums = [1, 2, 3, 4, 5, 7]
    sr_bands_data = []
    for b_num in real_band_nums:
        b_file = real_scene_dir / f"LT05_L2SP_129044_19920816_20200914_02_T1_SR_B{b_num}.TIF"
        with rasterio.open(b_file) as b_src:
            sr_bands_data.append(b_src.read(1, window=window))

    # Read QA_PIXEL and QA_RADSAT
    qa_pixel_file = real_scene_dir / "LT05_L2SP_129044_19920816_20200914_02_T1_QA_PIXEL.TIF"
    with rasterio.open(qa_pixel_file) as qa_src:
        qa_pixel_win = qa_src.read(1, window=window)

    qa_radsat_file = real_scene_dir / "LT05_L2SP_129044_19920816_20200914_02_T1_QA_RADSAT.TIF"
    with rasterio.open(qa_radsat_file) as rad_src:
        qa_radsat_win = rad_src.read(1, window=window)

    # Apply real scaling and QA mask
    scaled_sr = np.full((6, win_h, win_w), -9999.0, dtype=np.float32)
    valid_mask = np.ones((win_h, win_w), dtype=np.uint8)

    for b_idx in range(6):
        b_scaled, b_valid = mask_and_scale_surface_reflectance(
            dn=sr_bands_data[b_idx],
            qa_pixel=qa_pixel_win,
            sensor="LANDSAT_5",
            scale=0.0000275,
            offset=-0.2,
            nodata_val=-9999.0,
            qa_radsat=qa_radsat_win,
        )
        scaled_sr[b_idx] = b_scaled
        valid_mask = valid_mask & b_valid

    # Save small real window SR and valid_sr into ctx.data
    proc_1992_dir = ctx.data / "processed" / "1992"
    proc_1992_dir.mkdir(parents=True, exist_ok=True)
    sr_out = proc_1992_dir / "sr_30m.tif"
    valid_out = proc_1992_dir / "valid_sr_30m.tif"

    with rasterio.open(
        sr_out, "w", driver="GTiff", height=win_h, width=win_w, count=6,
        dtype="float32", crs=crs, transform=win_transform, nodata=-9999.0,
    ) as dst:
        dst.write(scaled_sr)
        dst.descriptions = ("blue", "green", "red", "nir", "swir1", "swir2")

    with rasterio.open(
        valid_out, "w", driver="GTiff", height=win_h, width=win_w, count=1,
        dtype="uint8", crs=crs, transform=win_transform, nodata=255,
    ) as dst:
        dst.write(valid_mask, 1)

    # Create real window sample labels (5 classes, 8 groups per class within window bounds)
    win_bounds = rasterio.windows.bounds(window, src_b1.transform)
    labels_gpkg = ctx.data / "samples" / "1992" / "labels.gpkg"
    _generate_realistic_sample_polygons(
        labels_gpkg,
        crs=crs,
        xmin=win_bounds[0] + 30.0,
        ymin=win_bounds[1] + 30.0,
    )

    # Execute build_samples on the real window
    sample_data = build_samples(ctx, year=1992)

    assert sample_data.features.exists()
    assert sample_data.valid_features.exists()
    assert sample_data.train.exists()
    assert sample_data.holdout.exists()
    assert sample_data.split.exists()

    # Verify features raster on real window
    with rasterio.open(sample_data.features) as src_feat:
        assert src_feat.count == 10
        assert src_feat.descriptions == (
            "blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"
        )
        assert src_feat.transform == win_transform

    # Verify train and holdout separation
    train_df = gpd.pd.read_csv(sample_data.train)
    holdout_df = gpd.pd.read_csv(sample_data.holdout)

    assert len(train_df) > 0
    assert len(holdout_df) > 0
    assert set(train_df["group_id"]).isdisjoint(set(holdout_df["group_id"]))
    assert set(zip(train_df["x"], train_df["y"])).isdisjoint(set(zip(holdout_df["x"], holdout_df["y"])))


# ---------------------------------------------------------------------------
# Test 4: Full Multi-Stage Integration (A -> B -> C -> D -> E)
# ---------------------------------------------------------------------------

def test_p2_full_pipeline_micro(tmp_path: Path):
    """End-to-end integration test of all five processing modules on micro fixtures."""
    ctx, _, _ = _setup_g1_test_environment(tmp_path)

    # 1. Step A: boundaries
    bnd_path = prepare_boundaries(ctx)
    assert bnd_path.exists()

    # 2. Step A: surface 1992
    prep_1992 = preprocess_year(ctx, 1992)
    assert prep_1992.sr.exists()

    # Create dummy 2021 SR by cloning 1992 with minor change
    proc_2021_dir = ctx.data / "processed" / "2021"
    proc_2021_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(prep_1992.sr) as src:
        sr_meta = src.meta.copy()
        sr_arr = src.read()
        sr_desc = src.descriptions
    with rasterio.open(proc_2021_dir / "sr_30m.tif", "w", **sr_meta) as dst:
        dst.write(sr_arr)
        dst.descriptions = sr_desc
    with rasterio.open(prep_1992.valid_sr) as src:
        val_meta = src.meta.copy()
        val_arr = src.read()
    with rasterio.open(proc_2021_dir / "valid_sr_30m.tif", "w", **val_meta) as dst:
        dst.write(val_arr)

    # 3. Step B: build_samples for 1992 and 2021
    labels_1992 = ctx.data / "samples" / "1992" / "labels.gpkg"
    _generate_realistic_sample_polygons(labels_1992)
    sample_1992 = build_samples(ctx, 1992)

    labels_2021 = ctx.data / "samples" / "2021" / "labels.gpkg"
    _generate_realistic_sample_polygons(labels_2021)
    sample_2021 = build_samples(ctx, 2021)

    # 4. Step C: train and predict
    cls_1992: ClassificationData = train_predict(ctx, 1992)
    cls_2021: ClassificationData = train_predict(ctx, 2021)
    assert cls_1992.model.exists()
    assert cls_1992.raw.exists()
    assert cls_2021.model.exists()
    assert cls_2021.raw.exists()

    # 5. Step D: finalize and evaluate
    eval_1992: EvaluationData = finalize_evaluate(ctx, 1992)
    eval_2021: EvaluationData = finalize_evaluate(ctx, 2021)
    assert eval_1992.final.exists()
    assert eval_1992.report.exists()
    assert eval_2021.final.exists()
    assert eval_2021.report.exists()

    # 6. Step E: analyze change
    change_data: ChangeData = analyze_change(ctx)
    assert change_data.raster.exists()
    assert change_data.townships.exists()
    assert change_data.district.exists()


# ==============================================================================
# Helper Generators for P2-G2 Dedicated Validation
# ==============================================================================

def create_synthetic_landscape_g2(
    data_dir: Path,
    year: int,
    height: int = 30,
    width: int = 30,
) -> tuple[Path, Path, Path, Affine]:
    """Create synthetic 6-band surface reflectance, valid mask, and study area boundary for G2 tests."""
    proc_year_dir = data_dir / "processed" / str(year)
    proc_year_dir.mkdir(parents=True, exist_ok=True)
    bound_dir = data_dir / "processed" / "boundaries"
    bound_dir.mkdir(parents=True, exist_ok=True)

    sr_path = proc_year_dir / "sr_30m.tif"
    valid_sr_path = proc_year_dir / "valid_sr_30m.tif"
    boundary_gpkg = bound_dir / "xindu_2021.gpkg"

    crs = "EPSG:32648"
    x_min = 500000.0
    y_max = 3380000.0 + height * 30.0
    transform = Affine(30.0, 0.0, x_min, 0.0, -30.0, y_max)

    sr_data = np.zeros((6, height, width), dtype=np.float32)

    # Base background (Class 2: 耕地)
    sr_data[0, :, :] = 0.12
    sr_data[1, :, :] = 0.22
    sr_data[2, :, :] = 0.20
    sr_data[3, :, :] = 0.50
    sr_data[4, :, :] = 0.35
    sr_data[5, :, :] = 0.25

    # Strip of Class 1 (建设用地) in rows 2..7
    sr_data[0, 2:8, :] = 0.25
    sr_data[1, 2:8, :] = 0.28
    sr_data[2, 2:8, :] = 0.32
    sr_data[3, 2:8, :] = 0.45
    sr_data[4, 2:8, :] = 0.50
    sr_data[5, 2:8, :] = 0.40

    # Strip of Class 3 (林草植被) in rows 10..15
    sr_data[0, 10:16, :] = 0.08
    sr_data[1, 10:16, :] = 0.18
    sr_data[2, 10:16, :] = 0.10
    sr_data[3, 10:16, :] = 0.72
    sr_data[4, 10:16, :] = 0.28
    sr_data[5, 10:16, :] = 0.18

    # Strip of Class 4 (水体) in rows 18..22
    sr_data[0, 18:23, :] = 0.15
    sr_data[1, 18:23, :] = 0.25
    sr_data[2, 18:23, :] = 0.12
    sr_data[3, 18:23, :] = 0.05
    sr_data[4, 18:23, :] = 0.03
    sr_data[5, 18:23, :] = 0.02

    # Strip of Class 4 (水体) in rows 24..28
    sr_data[0, 24:29, :] = 0.28
    sr_data[1, 24:29, :] = 0.35
    sr_data[2, 24:29, :] = 0.40
    sr_data[3, 24:29, :] = 0.38
    sr_data[4, 24:29, :] = 0.58
    sr_data[5, 24:29, :] = 0.50

    # Put a 1-pixel speckle of Class 1 inside Class 3 (at row 12, col 12) to test sieve
    sr_data[:, 12, 12] = sr_data[:, 4, 12]

    with rasterio.open(
        sr_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=6,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(sr_data)
        dst.descriptions = ("blue", "green", "red", "nir", "swir1", "swir2")

    # Valid mask
    valid_data = np.ones((1, height, width), dtype=np.uint8)
    valid_data[0, 0, :] = 255
    valid_data[0, height - 1, :] = 255
    valid_data[0, :, 0] = 255
    valid_data[0, :, width - 1] = 255

    with rasterio.open(
        valid_sr_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
        nodata=255,
    ) as dst:
        dst.write(valid_data)

    x_left = x_min + 30.0
    x_right = x_min + (width - 1) * 30.0
    y_bottom = y_max - (height - 1) * 30.0
    y_top = y_max - 30.0
    study_geom = box(x_left, y_bottom, x_right, y_top)

    gdf_study = gpd.GeoDataFrame(
        [{"area_id": "510114", "name": "成都市新都区", "reference_year": 2021, "geometry": study_geom}],
        crs=crs,
    )
    gdf_town = gpd.GeoDataFrame(
        [
            {"unit_id": "T01", "name": "西街镇", "unit_type": "town", "reference_year": 2021, "geometry": study_geom},
        ],
        crs=crs,
    )
    gdf_study.to_file(boundary_gpkg, layer="study_area", driver="GPKG")
    gdf_town.to_file(boundary_gpkg, layer="townships", driver="GPKG")

    return sr_path, valid_sr_path, boundary_gpkg, transform


def create_synthetic_labels_for_landscape_g2(
    data_dir: Path,
    year: int,
    transform: Affine,
) -> Path:
    """Create 5-class labels with at least 8 groups per class for G2 tests."""
    samples_dir = data_dir / "samples" / str(year)
    samples_dir.mkdir(parents=True, exist_ok=True)
    labels_path = samples_dir / "labels.gpkg"

    records = []
    sample_counter = 0

    class_row_ranges = {
        1: (3, 7),
        2: (8, 9),
        3: (11, 15),
        4: (19, 22),
        5: (25, 28),
    }

    for class_id, (r_start, r_end) in class_row_ranges.items():
        for g_idx in range(1, 9):
            group_id = f"c{class_id}_g{g_idx:02d}"
            for p_sub in range(2):
                sample_counter += 1
                row = r_start + (g_idx % (r_end - r_start + 1))
                col = 2 + g_idx * 2 + p_sub
                if col >= 28:
                    col = 2 + p_sub

                cx = transform.c + (col + 0.5) * transform.a
                cy = transform.f + (row + 0.5) * transform.e

                poly = Polygon([
                    (cx - 10, cy - 10),
                    (cx + 10, cy - 10),
                    (cx + 10, cy + 10),
                    (cx - 10, cy + 10),
                ])

                records.append({
                    "sample_id": f"s_{year}_{sample_counter:04d}",
                    "group_id": group_id,
                    "year": year,
                    "class_id": class_id,
                    "label_source": "test_interpretation",
                    "source_date": f"{year}-06-01",
                    "annotator": "tester",
                    "split": "unassigned",
                    "geometry": poly,
                })

    gdf = gpd.GeoDataFrame(records, crs="EPSG:32648")
    gdf.to_file(labels_path, layer="labels", driver="GPKG")
    return labels_path


# ==============================================================================
# P2-G2 Integration Tests: B -> C -> D
# ==============================================================================

def test_p2_g2_pipeline_b_to_c_to_d_python_api(tmp_path: Path) -> None:
    """Validate full P2-G2 chain (B -> C -> D) via Python API."""
    year = 2021
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    sr_path, valid_sr_path, bnd_gpkg, transform = create_synthetic_landscape_g2(data_dir, year=year)
    labels_gpkg = create_synthetic_labels_for_landscape_g2(data_dir, year=year, transform=transform)

    repo_root = Path(__file__).resolve().parents[2]
    cfg = load_context(write_ten_dim_config(repo_root, tmp_path / "project.toml"), repo_root / ".env").config

    ctx = ProjectContext(
        root=tmp_path,
        data=data_dir,
        outputs=outputs_dir,
        reports=reports_dir,
        scratch=scratch_dir,
        config=cfg,
    )

    # 1. Module B: Build Samples
    sample_data = build_samples(ctx=ctx, year=year)
    assert isinstance(sample_data, SampleData)
    assert sample_data.features.exists()
    assert sample_data.valid_features.exists()
    assert sample_data.train.exists()
    assert sample_data.holdout.exists()
    assert sample_data.split.exists()

    with open(sample_data.split, "r", encoding="utf-8") as f:
        split_meta = json.load(f)
    split_sha256 = split_meta["split_sha256"]
    assert split_meta["total_groups"] == 40
    assert split_meta["holdout_groups_count"] == 10
    assert split_meta["train_groups_count"] == 30

    train_df = pd.read_csv(sample_data.train)
    holdout_df = pd.read_csv(sample_data.holdout)
    assert len(train_df) > 0
    assert len(holdout_df) > 0
    assert set(train_df["group_id"]).isdisjoint(set(holdout_df["group_id"]))
    train_pixels = set(zip(train_df["row"], train_df["col"]))
    holdout_pixels = set(zip(holdout_df["row"], holdout_df["col"]))
    assert train_pixels.isdisjoint(holdout_pixels)

    # 2. Module C: Random Forest Classification
    class_data = train_predict(ctx=ctx, year=year)
    assert isinstance(class_data, ClassificationData)
    assert class_data.year == year
    assert class_data.model.exists()
    assert class_data.raw.exists()

    model_obj = joblib.load(class_data.model)
    assert "estimator" in model_obj
    assert model_obj["split_sha256"] == split_sha256
    assert model_obj["feature_names"] == cfg["features"]["order"]
    assert model_obj["class_codes"] == [1, 2, 3, 4]

    train_report_path = reports_dir / "accuracy" / f"training_{year}.json"
    assert train_report_path.exists()
    with open(train_report_path, "r", encoding="utf-8") as f:
        train_rep = json.load(f)
    assert train_rep["split_sha256"] == split_sha256
    assert train_rep["num_training_pixels"] == len(train_df)
    # 纯度过滤可能整组剔除训练像元，因此存活组数只能小于等于划分组数；
    # 划分组数另行记录，两者之差即被整组剔除的组数。
    assert train_rep["num_split_training_groups"] == split_meta["train_groups_count"]
    assert 0 < train_rep["num_training_groups"] <= split_meta["train_groups_count"]
    assert (
        train_rep["num_training_groups"] + train_rep["num_dropped_train_groups"]
        == train_rep["num_split_training_groups"]
    )

    # 3. Module D: Evaluation & Postprocessing
    eval_data = finalize_evaluate(ctx=ctx, year=year)
    assert isinstance(eval_data, EvaluationData)
    assert eval_data.year == year
    assert eval_data.final.exists()
    assert eval_data.vectors.exists()
    assert eval_data.report.exists()

    with rasterio.open(class_data.raw) as src_raw, rasterio.open(eval_data.final) as src_final:
        raw_arr = src_raw.read(1)
        final_arr = src_final.read(1)
        assert src_raw.crs == src_final.crs
        assert src_raw.transform == src_final.transform
        assert (raw_arr == 0).all() == (final_arr == 0).all()

    assert raw_arr[12, 12] == 1
    assert final_arr[12, 12] == 3

    shp_base = eval_data.vectors.with_suffix("")
    for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
        assert shp_base.with_suffix(ext).exists()

    gdf_out = gpd.read_file(eval_data.vectors)
    assert set(gdf_out.columns).issuperset({"class_id", "class_name", "year", "area_km2", "geometry"})
    assert set(gdf_out["class_id"]).issubset({1, 2, 3, 4, 5})
    assert (gdf_out["area_km2"] > 0).all()

    assert eval_data.oa_final > 0.75
    eval_json_path = reports_dir / "accuracy" / f"evaluation_{year}.json"
    with open(eval_json_path, "r", encoding="utf-8") as f:
        eval_json = json.load(f)

    assert eval_json["passed_oa_threshold"] is True
    assert eval_json["oa_final"] == pytest.approx(eval_data.oa_final)
    assert len(eval_json["matrix_final"]) == 4
    assert len(eval_json["metrics_final"]) == 4

    report_text = eval_data.report.read_text(encoding="utf-8")
    assert "独立精度评价报告" in report_text
    assert "通过" in report_text or "PASS" in report_text


def test_p2_g2_cli_command_chain(tmp_path: Path) -> None:
    """Verify executing B -> C -> D sequentially via subprocess CLI invocations."""
    year = 2021
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    sr_path, valid_sr_path, bnd_gpkg, transform = create_synthetic_landscape_g2(data_dir, year=year)
    labels_gpkg = create_synthetic_labels_for_landscape_g2(data_dir, year=year, transform=transform)

    repo_root = Path(__file__).resolve().parents[2]
    config_path = write_ten_dim_config(repo_root, tmp_path / "project.toml")

    env_path = tmp_path / ".env"
    env_content = f"""
RS_DATA_ROOT={data_dir.as_posix()}
RS_OUTPUT_ROOT={outputs_dir.as_posix()}
RS_REPORT_ROOT={reports_dir.as_posix()}
RS_SCRATCH_ROOT={scratch_dir.as_posix()}
GDAL_CACHEMAX=512
"""
    env_path.write_text(env_content, encoding="utf-8")

    cmd_samples = [
        sys.executable,
        str(repo_root / "src" / "02_samples.py"),
        "--config", str(config_path),
        "--env-file", str(env_path),
        "--year", str(year),
    ]
    res_b = subprocess.run(cmd_samples, capture_output=True, text=True)
    assert res_b.returncode == 0, f"02_samples.py failed:\n{res_b.stderr}"
    assert (data_dir / "processed" / "samples" / str(year) / "train.csv").exists()

    cmd_classify = [
        sys.executable,
        str(repo_root / "src" / "03_classify.py"),
        "--config", str(config_path),
        "--env-file", str(env_path),
        "--year", str(year),
    ]
    res_c = subprocess.run(cmd_classify, capture_output=True, text=True)
    assert res_c.returncode == 0, f"03_classify.py failed:\n{res_c.stderr}"
    assert (outputs_dir / "models" / str(year) / "rf.joblib").exists()
    assert (outputs_dir / "rasters" / f"lulc_{year}_raw_30m.tif").exists()

    cmd_eval = [
        sys.executable,
        str(repo_root / "src" / "04_evaluate.py"),
        "--config", str(config_path),
        "--env-file", str(env_path),
        "--year", str(year),
    ]
    res_d = subprocess.run(cmd_eval, capture_output=True, text=True)
    assert res_d.returncode == 0, f"04_evaluate.py failed:\n{res_d.stderr}"
    assert (outputs_dir / "rasters" / f"lulc_{year}_final_30m.tif").exists()
    assert (outputs_dir / "vectors" / str(year) / f"lulc_{year}.shp").exists()
    assert (reports_dir / "accuracy" / f"evaluation_{year}.json").exists()


def test_p2_g2_accuracy_sub_threshold_retention(tmp_path: Path) -> None:
    """Verify that when OA fails threshold (<= 0.75), actual metrics are retained faithfully."""
    year = 2021
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    sr_path, valid_sr_path, bnd_gpkg, transform = create_synthetic_landscape_g2(data_dir, year=year)
    labels_gpkg = create_synthetic_labels_for_landscape_g2(data_dir, year=year, transform=transform)

    repo_root = Path(__file__).resolve().parents[2]
    cfg = load_context(write_ten_dim_config(repo_root, tmp_path / "project.toml"), repo_root / ".env").config

    ctx = ProjectContext(
        root=tmp_path,
        data=data_dir,
        outputs=outputs_dir,
        reports=reports_dir,
        scratch=scratch_dir,
        config=cfg,
    )

    build_samples(ctx=ctx, year=year)
    train_predict(ctx=ctx, year=year)

    holdout_path = data_dir / "processed" / "samples" / str(year) / "holdout.csv"
    h_df = pd.read_csv(holdout_path)
    h_df["class_id"] = (h_df["class_id"] % 5) + 1
    h_df.to_csv(holdout_path, index=False)

    eval_data = finalize_evaluate(ctx=ctx, year=year)
    assert eval_data.oa_final <= 0.75

    eval_json_path = reports_dir / "accuracy" / f"evaluation_{year}.json"
    with open(eval_json_path, "r", encoding="utf-8") as f:
        eval_json = json.load(f)

    assert eval_json["passed_oa_threshold"] is False
    assert eval_json["oa_final"] <= 0.75
    assert len(eval_json["matrix_final"]) == 4
    assert len(eval_json["metrics_final"]) == 4

    report_text = eval_data.report.read_text(encoding="utf-8")
    assert "未达标" in report_text or "FAIL" in report_text or "未通过" in report_text


def test_p2_g2_multi_year_isolation(tmp_path: Path) -> None:
    """Verify that year 1992 and year 2021 can independently run through G2 without interference."""
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    repo_root = Path(__file__).resolve().parents[2]
    cfg = load_context(write_ten_dim_config(repo_root, tmp_path / "project.toml"), repo_root / ".env").config
    ctx = ProjectContext(
        root=tmp_path,
        data=data_dir,
        outputs=outputs_dir,
        reports=reports_dir,
        scratch=scratch_dir,
        config=cfg,
    )

    for y in [1992, 2021]:
        sr_path, valid_sr_path, bnd_gpkg, transform = create_synthetic_landscape_g2(data_dir, year=y)
        create_synthetic_labels_for_landscape_g2(data_dir, year=y, transform=transform)

        s_data = build_samples(ctx=ctx, year=y)
        c_data = train_predict(ctx=ctx, year=y)
        e_data = finalize_evaluate(ctx=ctx, year=y)

        assert s_data.year == y
        assert c_data.year == y
        assert e_data.year == y

    m_1992 = outputs_dir / "models" / "1992" / "rf.joblib"
    m_2021 = outputs_dir / "models" / "2021" / "rf.joblib"
    assert m_1992.exists()
    assert m_2021.exists()
    assert m_1992 != m_2021

    v_1992 = outputs_dir / "vectors" / "1992" / "lulc_1992.shp"
    v_2021 = outputs_dir / "vectors" / "2021" / "lulc_2021.shp"
    assert v_1992.exists()
    assert v_2021.exists()


def test_p2_g2_real_samples_available() -> None:
    """样本已就位后，build_samples 应能从真实 labels.gpkg 正常产出 train/holdout。

    历史背景：数据未就位时该用例断言抛 FileNotFoundError；数据到齐后改为断言可复现产出，
    缺文件路径由单元测试 test_samples_missing_labels 覆盖。
    """
    repo_root = Path(__file__).resolve().parents[2]
    ctx = load_context(repo_root / "configs" / "project.toml", repo_root / ".env")

    result = build_samples(ctx=ctx, year=2021)
    assert result is not None
    samples_dir = Path(repo_root) / "data" / "processed" / "samples" / "2021"
    assert (samples_dir / "split.json").exists()
    assert (samples_dir / "train.csv").exists()
    assert (samples_dir / "holdout.csv").exists()


# ==============================================================================
# Phase 2 Gateway 3 (P2-G3): Chaining Module D -> Module E -> Module F
# ==============================================================================

@pytest.fixture
def g3_integration_env(tmp_path: Path) -> dict[str, Any]:
    """Create a self-contained environment for P2-G3 change analysis integration.

    Layout: 6x6 grid, 30m resolution, EPSG:32648.
    Study area: [500000, 3380000, 500180, 3380180] (180m x 180m = 0.0324 km2).
    Townships: 9 rectangular units arranged in a 3x3 layout (7 streets, 2 towns).
      - Rows 0..2 (Y from 3380000 to 3380180 in 60m blocks)
      - Cols 0..2 (X from 500000 to 500180 in 60m blocks)
      - Each township is exactly 60m x 60m = 3600 m2 = 0.0036 km2 (4 pixels of 30m).
      - Total area = 9 * 0.0036 = 0.0324 km2 (matches district total exactly).
    """
    root = tmp_path / "g3_project"
    data = root / "data"
    outputs = root / "outputs"
    reports = root / "reports"
    scratch = root / "scratch"

    for d in [data, outputs, reports, scratch]:
        d.mkdir(parents=True, exist_ok=True)

    crs = "EPSG:32648"
    width, height = 6, 6
    xmin, ymin, xmax, ymax = 500000.0, 3380000.0, 500180.0, 3380180.0
    transform = Affine(30.0, 0.0, xmin, 0.0, -30.0, ymax)

    # 1. Study area and 9 Townships GPKG
    bnd_dir = data / "processed" / "boundaries"
    bnd_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = bnd_dir / "xindu_2021.gpkg"

    poly_study = box(xmin, ymin, xmax, ymax)
    gdf_study = gpd.GeoDataFrame(
        [{"area_id": "510114", "name": "成都市新都区", "reference_year": 2021, "geometry": poly_study}],
        crs=crs,
    )

    township_names = [
        ("510114001", "大丰街道", "street"),
        ("510114002", "三河街道", "street"),
        ("510114003", "新都街道", "street"),
        ("510114004", "新繁街道", "street"),
        ("510114005", "石板滩街道", "street"),
        ("510114006", "斑竹园街道", "street"),
        ("510114007", "桂湖街道", "street"),
        ("510114101", "清流镇", "town"),
        ("510114102", "军屯镇", "town"),
    ]

    township_records = []
    idx = 0
    for r_idx in range(3):
        for c_idx in range(3):
            t_xmin = xmin + c_idx * 60.0
            t_xmax = t_xmin + 60.0
            t_ymin = ymin + r_idx * 60.0
            t_ymax = t_ymin + 60.0
            u_id, u_name, u_type = township_names[idx]
            township_records.append({
                "unit_id": u_id,
                "name": u_name,
                "unit_type": u_type,
                "reference_year": 2021,
                "geometry": box(t_xmin, t_ymin, t_xmax, t_ymax),
            })
            idx += 1

    gdf_townships = gpd.GeoDataFrame(township_records, crs=crs)
    gdf_study.to_file(gpkg_path, layer="study_area", driver="GPKG")
    gdf_townships.to_file(gpkg_path, layer="townships", driver="GPKG")

    # 2. AOI raster (all 1 within study area)
    grids_dir = data / "processed" / "grids"
    grids_dir.mkdir(parents=True, exist_ok=True)
    aoi_path = grids_dir / "aoi_30m.tif"
    with rasterio.open(
        aoi_path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint8", crs=crs, transform=transform, nodata=0,
    ) as dst:
        dst.write(np.ones((height, width), dtype=np.uint8), 1)

    grid_json_path = grids_dir / "grid_30m.json"
    grid_meta = {
        "schema_version": 1,
        "crs": crs,
        "bounds": [xmin, ymin, xmax, ymax],
        "resolution": [30, 30],
        "width": width,
        "height": height,
        "transform": [xmin, 30.0, 0.0, ymax, 0.0, -30.0],
    }
    grid_json_path.write_text(json.dumps(grid_meta), encoding="utf-8")

    # 3. Two final classification rasters (1992 and 2021)
    grid_1992 = np.array([
        [1, 1, 2, 2, 3, 0],
        [1, 1, 2, 2, 3, 3],
        [2, 2, 1, 1, 4, 4],
        [2, 2, 1, 1, 4, 4],
        [3, 3, 4, 4, 5, 5],
        [3, 3, 4, 4, 5, 5],
    ], dtype=np.uint8)

    grid_2021 = np.array([
        [1, 1, 1, 1, 3, 1],  # (0, 5) was 0 in 1992, 1 in 2021 -> NoData!
        [1, 2, 1, 1, 3, 3],  # (1, 1) was 1 in 1992, 2 in 2021 -> Lost built!
        [1, 1, 1, 1, 4, 4],  # (2, 0),(2, 1) were 2 in 1992, 1 in 2021 -> Added built!
        [1, 1, 1, 1, 4, 4],
        [3, 3, 4, 4, 1, 5],  # (4, 4) was 5 in 1992, 1 in 2021 -> Added built!
        [3, 3, 4, 4, 5, 5],
    ], dtype=np.uint8)

    rasters_dir = outputs / "rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": rasterio.uint8,
        "crs": crs,
        "transform": transform,
        "nodata": 0,
    }

    final_1992_path = rasters_dir / "lulc_1992_final_30m.tif"
    final_2021_path = rasters_dir / "lulc_2021_final_30m.tif"

    with rasterio.open(final_1992_path, "w", **meta) as dst:
        dst.write(grid_1992, 1)

    with rasterio.open(final_2021_path, "w", **meta) as dst:
        dst.write(grid_2021, 1)

    config = {
        "schema_version": 1,
        "project_slug": "rs-urban-expansion",
        "years": [1992, 2021],
        "boundary_reference_year": 2021,
        "expected_township_count": 9,
        "target_crs": "EPSG:32648",
        "analysis_resolution_m": 30,
        "display_resolution_m": 15,
        "class_nodata": 0,
        "float_nodata": -9999.0,
        "mask_nodata": 255,
        "classes": [
            {"code": 1, "name": "城镇及建设用地", "color": "#D95F02"},
            {"code": 2, "name": "耕地", "color": "#E6C84F"},
            {"code": 3, "name": "林草植被", "color": "#2E8B57"},
            {"code": 4, "name": "水体", "color": "#377EB8"},
        ],
        "features": {
            "order": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"],
        },
        "model": {
            "classifier": "RandomForestClassifier",
            "n_estimators": 50,
            "min_samples_leaf": 2,
            "max_features": "sqrt",
            "class_weight": "balanced_subsample",
            "random_seed": 42,
            "n_jobs": 1,
        },
        "postprocess": {
            "sieve_threshold_pixels": 4,
            "connectivity": 8,
        },
        "evaluation": {
            "overall_accuracy_strictly_greater_than": 0.75,
            "built_up_f1_target": 0.75,
            "class_order": [1, 2, 3, 4],
        },
        "analysis": {
            "elapsed_years": 29,
            "comparison_mask": "intersection_of_valid_pixels",
            "area_unit": "km2",
        },
    }

    ctx = ProjectContext(
        root=root,
        data=data,
        outputs=outputs,
        reports=reports,
        scratch=scratch,
        config=config,
    )

    return {
        "ctx": ctx,
        "root": root,
        "grid_1992": grid_1992,
        "grid_2021": grid_2021,
        "transform": transform,
        "crs": crs,
        "width": width,
        "height": height,
        "gdf_study": gdf_study,
        "gdf_townships": gdf_townships,
    }


def test_p2_g3_change_analysis_and_area_balance(g3_integration_env: dict[str, Any]) -> None:
    """Verify D->E change analysis pipeline: valid common mask, 4 change classes, 9 townships, and exact area balance.

    Satisfies:
      - 两期final准备后运行变化分析，核对共同有效掩膜、9街镇和区级总量。
    """
    ctx = g3_integration_env["ctx"]

    # 1. Run change analysis
    result = analyze_change(ctx)
    assert isinstance(result, ChangeData)

    # 2. Check all expected files exist
    assert result.raster.exists()
    assert result.vectors.exists()
    assert result.townships.exists()
    assert result.district.exists()

    valid_common_path = ctx.data / "processed" / "common" / "valid_common_30m.tif"
    assert valid_common_path.exists()
    statistics_json_path = ctx.reports / "analysis" / "statistics.json"
    assert statistics_json_path.exists()

    # 3. Verify valid_common_30m.tif
    with rasterio.open(valid_common_path) as src_common:
        assert src_common.nodata == 255
        common_arr = src_common.read(1)
        # Pixel (0, 5) had 1992=0 (NoData) -> must be 0 in valid_common (invalid in study area)
        assert common_arr[0, 5] == 0
        # Other 35 pixels are valid in both years -> 1
        assert np.sum(common_arr == 1) == 35

    # 4. Verify change_1992_2021_30m.tif
    with rasterio.open(result.raster) as src_change:
        assert src_change.nodata == 0
        change_arr = src_change.read(1)

        # Pixel (0, 5) is 0 in 1992 and 1 in 2021: must strictly be 0 (NoData), NOT 2 (added)
        assert change_arr[0, 5] == 0

        # Pixel (1, 1): was 1 in 1992, 2 in 2021 -> 3 (lost built)
        assert change_arr[1, 1] == 3

        # Pixel (2, 0): was 2 in 1992, 1 in 2021 -> 2 (added built)
        assert change_arr[2, 0] == 2

        # Pixel (0, 0): was 1 in 1992, 1 in 2021 -> 1 (persistent built)
        assert change_arr[0, 0] == 1

        # Check Colormap
        cmap = src_change.colormap(1)
        for code, expected_rgba in CHANGE_COLORMAP.items():
            assert cmap[code] == expected_rgba

    # 5. Verify urban_change.gpkg (layer: change)
    gdf_change_vec = gpd.read_file(result.vectors, layer="change")
    assert "change_id" in gdf_change_vec.columns
    assert "change_name" in gdf_change_vec.columns
    assert "area_km2" in gdf_change_vec.columns
    assert set(gdf_change_vec["change_id"].unique()).issubset({1, 2, 3, 4})

    # 6. Verify 9-township CSV table
    df_townships = pd.read_csv(result.townships)
    assert list(df_townships.columns) == TABLE_FIELDNAMES
    assert len(df_townships) == 9

    expected_units = {"510114001", "510114002", "510114003", "510114004", "510114005", "510114006", "510114007", "510114101", "510114102"}
    assert set(df_townships["unit_id"].astype(str)) == expected_units
    assert "district" not in df_townships["unit_type"].values
    assert "总计" not in df_townships["name"].values

    # 7. Verify district CSV table
    df_district = pd.read_csv(result.district)
    assert list(df_district.columns) == TABLE_FIELDNAMES
    assert len(df_district) == 1
    assert df_district["unit_type"].iloc[0] == "district"

    # 8. Check mathematical equations on District level
    d_row = df_district.iloc[0]
    assert d_row["net_km2"] == pytest.approx(d_row["added_km2"] - d_row["lost_km2"], abs=1e-6)
    assert d_row["net_km2"] == pytest.approx(d_row["built_2021_km2"] - d_row["built_1992_km2"], abs=1e-6)
    assert d_row["annual_net_km2"] == pytest.approx(d_row["net_km2"] / 29.0, abs=1e-6)
    expected_intensity = (d_row["net_km2"] / (29.0 * d_row["total_area_km2"])) * 100.0
    assert d_row["annual_intensity_pct"] == pytest.approx(expected_intensity, abs=1e-6)

    # 9. Verify Area Balance between 9 Townships and District Total
    t_comp_sum = df_townships["comparable_area_km2"].sum()
    t_net_sum = df_townships["net_km2"].sum()
    t_p_sum = df_townships["persistent_km2"].sum()
    t_a_sum = df_townships["added_km2"].sum()
    t_l_sum = df_townships["lost_km2"].sum()

    tolerance = max(1e-6, d_row["total_area_km2"] * 1e-6)
    assert abs(t_comp_sum - d_row["comparable_area_km2"]) <= tolerance
    assert abs(t_net_sum - d_row["net_km2"]) <= tolerance
    assert abs(t_p_sum - d_row["persistent_km2"]) <= tolerance
    assert abs(t_a_sum - d_row["added_km2"]) <= tolerance
    assert abs(t_l_sum - d_row["lost_km2"]) <= tolerance

    # 10. Check statistics.json
    with open(statistics_json_path, "r", encoding="utf-8") as f:
        stat_data = json.load(f)
    assert stat_data["schema_version"] == 1
    assert stat_data["township_count"] == 9
    assert stat_data["area_balance_check"]["is_balanced"] is True


def test_p2_g3_cli_05_analyze_execution(g3_integration_env: dict[str, Any]) -> None:
    """Verify CLI 05_analyze.py runs cleanly and produces matching output files."""
    ctx = g3_integration_env["ctx"]
    root = g3_integration_env["root"]
    repo_root = Path(__file__).resolve().parents[2]

    conf_dir = root / "configs"
    conf_dir.mkdir(parents=True, exist_ok=True)
    real_toml = (repo_root / "configs" / "project.toml").read_text(encoding="utf-8")
    conf_path = conf_dir / "project.toml"
    conf_path.write_text(real_toml, encoding="utf-8")

    env_path = root / ".env"
    env_path.write_text(f"""
RS_DATA_ROOT={ctx.data.as_posix()}
RS_OUTPUT_ROOT={ctx.outputs.as_posix()}
RS_REPORT_ROOT={ctx.reports.as_posix()}
RS_SCRATCH_ROOT={ctx.scratch.as_posix()}
""", encoding="utf-8")

    import importlib
    cli_analyze = importlib.import_module("05_analyze")

    exit_code = cli_analyze.main([
        "--config", str(conf_path),
        "--env-file", str(env_path),
    ])

    assert exit_code == 0
    assert (ctx.outputs / "rasters" / "change_1992_2021_30m.tif").exists()
    assert (ctx.outputs / "tables" / "township_change_1992_2021.csv").exists()
    assert (ctx.outputs / "tables" / "district_change_1992_2021.csv").exists()


def test_p2_g3_map_and_report_consistency(g3_integration_env: dict[str, Any]) -> None:
    """Verify report template, QGIS project layer references, and quantitative consistency.

    Satisfies:
      - F完成四图和分析报告；I核对图表数据来自同一候选成果。
    """
    repo = Path(__file__).resolve().parents[2]

    # 1. Check reports/analysis/urban_expansion.md exists
    report_md_path = repo / "reports" / "analysis" / "urban_expansion.md"
    assert report_md_path.exists(), "urban_expansion.md must exist in reports/analysis/"

    content = report_md_path.read_text(encoding="utf-8")

    # 2. Check key sections exist
    required_keywords = [
        "成都市新都区 1992—2021 年建设用地扩张遥感分析报告",
        "大丰街道", "三河街道", "新都街道", "新繁街道", "石板滩街道",
        "斑竹园街道", "桂湖街道", "清流镇", "军屯镇",
        "EPSG:32648",
        "共同有效掩膜",
        "持续建设", "新增建设", "减少建设", "持续非建设",
        "时相跨季节差异",
        "29 年区间平均口径局限",
    ]
    for kw in required_keywords:
        assert kw in content, f"Report must mention '{kw}'"

    # 3. Check QGIS project xindu_1992_2021.qgs
    qgs_path = repo / "qgis" / "xindu_1992_2021.qgs"
    assert qgs_path.exists(), "QGIS project xindu_1992_2021.qgs must exist"

    qgs_text = qgs_path.read_text(encoding="utf-8")
    assert "EPSG:32648" in qgs_text
    assert "change_1992_2021_30m.tif" in qgs_text
    assert "urban_change.gpkg" in qgs_text
    assert "lulc_2021_final_30m.tif" in qgs_text
    assert "lulc_1992_final_30m.tif" in qgs_text
    assert "xindu_2021.gpkg" in qgs_text

    # 4. In g3 candidate run, verify that tables and statistics.json match exactly
    ctx = g3_integration_env["ctx"]
    analyze_change(ctx)

    df_townships = pd.read_csv(ctx.outputs / "tables" / "township_change_1992_2021.csv")
    df_district = pd.read_csv(ctx.outputs / "tables" / "district_change_1992_2021.csv")
    with open(ctx.reports / "analysis" / "statistics.json", "r", encoding="utf-8") as f:
        stat_json = json.load(f)

    d_csv = df_district.iloc[0].to_dict()
    d_stat = stat_json["district_summary"]
    for col in ["total_area_km2", "comparable_area_km2", "built_1992_km2", "built_2021_km2", "net_km2"]:
        assert pytest.approx(d_csv[col], abs=1e-6) == d_stat[col]


def test_p2_g3_five_entrypoints_reproducibility(tmp_path: Path) -> None:
    """Verify end-to-end reproducibility across two fresh, independent directories.

    Satisfies:
      - I在全新输出目录复现五个入口，固定样本、随机种子和参数；记录语义结果与原候选一致。
    """
    def run_full_pipeline(run_dir: Path) -> dict[str, Any]:
        """Execute all five pipeline stages in a clean directory."""
        data = run_dir / "data"
        outputs = run_dir / "outputs"
        reports = run_dir / "reports"
        scratch = run_dir / "scratch"

        for d in [data, outputs, reports, scratch]:
            d.mkdir(parents=True, exist_ok=True)

        crs = "EPSG:32648"
        width, height = 6, 6
        xmin, ymin, xmax, ymax = 500000.0, 3380000.0, 500180.0, 3380180.0
        transform = Affine(30.0, 0.0, xmin, 0.0, -30.0, ymax)

        # Stage 1: Boundaries
        bnd_dir = data / "processed" / "boundaries"
        bnd_dir.mkdir(parents=True, exist_ok=True)
        poly_study = box(xmin, ymin, xmax, ymax)
        gdf_study = gpd.GeoDataFrame([{"area_id": "510114", "name": "成都市新都区", "reference_year": 2021, "geometry": poly_study}], crs=crs)

        t_records = []
        for i in range(9):
            r = i // 3
            c = i % 3
            t_xmin = xmin + c * 60.0
            t_ymin = ymin + r * 60.0
            t_records.append({
                "unit_id": f"51011400{i+1}",
                "name": f"街镇_{i+1}",
                "unit_type": "street" if i < 7 else "town",
                "reference_year": 2021,
                "geometry": box(t_xmin, t_ymin, t_xmin + 60.0, t_ymin + 60.0),
            })
        gdf_townships = gpd.GeoDataFrame(t_records, crs=crs)
        gpkg_path = bnd_dir / "xindu_2021.gpkg"
        gdf_study.to_file(gpkg_path, layer="study_area", driver="GPKG")
        gdf_townships.to_file(gpkg_path, layer="townships", driver="GPKG")

        # Grids
        grids_dir = data / "processed" / "grids"
        grids_dir.mkdir(parents=True, exist_ok=True)
        with rasterio.open(grids_dir / "aoi_30m.tif", "w", driver="GTiff", height=height, width=width, count=1, dtype="uint8", crs=crs, transform=transform, nodata=0) as dst:
            dst.write(np.ones((height, width), dtype=np.uint8), 1)

        # Stage 2: Samples & Features
        for year in [1992, 2021]:
            feat_dir = data / "processed" / str(year)
            feat_dir.mkdir(parents=True, exist_ok=True)
            feat_arr = np.full((10, height, width), 0.2, dtype=np.float32)
            for b_idx in range(10):
                feat_arr[b_idx] += b_idx * 0.05
            with rasterio.open(feat_dir / "features_30m.tif", "w", driver="GTiff", height=height, width=width, count=10, dtype="float32", crs=crs, transform=transform, nodata=-9999.0) as dst:
                dst.write(feat_arr)
            with rasterio.open(feat_dir / "valid_features_30m.tif", "w", driver="GTiff", height=height, width=width, count=1, dtype="uint8", crs=crs, transform=transform, nodata=255) as dst:
                dst.write(np.ones((height, width), dtype=np.uint8), 1)

            # Samples
            s_dir = data / "processed" / "samples" / str(year)
            s_dir.mkdir(parents=True, exist_ok=True)
            rows = []
            for c_id in range(1, 6):
                for g_id in range(1, 9):
                    for p in range(2):
                        rows.append({
                            "sample_id": f"s_{c_id}_{g_id}_{p}",
                            "group_id": f"grp_{c_id}_{g_id}",
                            "year": year,
                            "class_id": c_id,
                            "row": (c_id - 1) % height,
                            "col": (g_id - 1) % width,
                            "x": xmin + ((g_id - 1) % width) * 30.0 + 15.0,
                            "y": ymax - ((c_id - 1) % height) * 30.0 - 15.0,
                            "blue": 0.1 * c_id,
                            "green": 0.15 * c_id,
                            "red": 0.2 * c_id,
                            "nir": 0.4 * c_id,
                            "swir1": 0.25 * c_id,
                            "swir2": 0.18 * c_id,
                            "ndvi": 0.33,
                            "ndbi": -0.2,
                            "mndwi": -0.33,
                            "bsi": 0.0,
                        })

            fieldnames = ["sample_id", "group_id", "year", "class_id", "row", "col", "x", "y", "blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"]
            train_rows = [r for r in rows if int(r["group_id"].split("_")[-1]) <= 6]
            holdout_rows = [r for r in rows if int(r["group_id"].split("_")[-1]) > 6]

            with open(s_dir / "train.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(train_rows)

            with open(s_dir / "holdout.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(holdout_rows)

            (s_dir / "split.json").write_text(json.dumps({
                "year": year,
                "train_groups": [f"grp_{c}_{g}" for c in range(1, 6) for g in range(1, 7)],
                "holdout_groups": [f"grp_{c}_{g}" for c in range(1, 6) for g in range(7, 9)],
            }), encoding="utf-8")

        config = {
            "schema_version": 1,
            "project_slug": "rs-urban-expansion",
            "years": [1992, 2021],
            "boundary_reference_year": 2021,
            "expected_township_count": 9,
            "target_crs": "EPSG:32648",
            "analysis_resolution_m": 30,
            "display_resolution_m": 15,
            "class_nodata": 0,
            "float_nodata": -9999.0,
            "mask_nodata": 255,
            "classes": [
                {"code": 1, "name": "城镇及建设用地", "color": "#D95F02"},
                {"code": 2, "name": "耕地", "color": "#E6C84F"},
                {"code": 3, "name": "林草植被", "color": "#2E8B57"},
                {"code": 4, "name": "水体", "color": "#377EB8"},
            ],
            "features": {
                "order": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"],
            },
            "model": {
                "classifier": "RandomForestClassifier",
                "n_estimators": 50,
                "min_samples_leaf": 2,
                "max_features": "sqrt",
                "class_weight": "balanced_subsample",
                "random_seed": 42,
                "n_jobs": 1,
            },
            "postprocess": {
                "sieve_threshold_pixels": 4,
                "connectivity": 8,
            },
            "evaluation": {
                "overall_accuracy_strictly_greater_than": 0.75,
                "built_up_f1_target": 0.75,
                "class_order": [1, 2, 3, 4],
            },
            "analysis": {
                "elapsed_years": 29,
                "comparison_mask": "intersection_of_valid_pixels",
                "area_unit": "km2",
            },
        }

        ctx = ProjectContext(root=run_dir, data=data, outputs=outputs, reports=reports, scratch=scratch, config=config)

        # Stage 3: Classify (1992 and 2021)
        cls_1992 = train_predict(ctx, 1992)
        cls_2021 = train_predict(ctx, 2021)

        # Stage 4: Evaluate (1992 and 2021)
        eval_1992 = finalize_evaluate(ctx, 1992)
        eval_2021 = finalize_evaluate(ctx, 2021)

        # Stage 5: Analyze
        chg = analyze_change(ctx)

        with rasterio.open(eval_1992.final) as f:
            final_1992_arr = f.read(1)
        with rasterio.open(eval_2021.final) as f:
            final_2021_arr = f.read(1)
        with rasterio.open(chg.raster) as f:
            chg_arr = f.read(1)

        df_t = pd.read_csv(chg.townships)
        df_d = pd.read_csv(chg.district)

        return {
            "final_1992": final_1992_arr,
            "final_2021": final_2021_arr,
            "change_arr": chg_arr,
            "oa_1992": eval_1992.oa_final,
            "oa_2021": eval_2021.oa_final,
            "df_townships": df_t,
            "df_district": df_d,
        }

    run_alpha = tmp_path / "run_alpha"
    run_beta = tmp_path / "run_beta"

    res_alpha = run_full_pipeline(run_alpha)
    res_beta = run_full_pipeline(run_beta)

    np.testing.assert_array_equal(res_alpha["final_1992"], res_beta["final_1992"])
    np.testing.assert_array_equal(res_alpha["final_2021"], res_beta["final_2021"])
    np.testing.assert_array_equal(res_alpha["change_arr"], res_beta["change_arr"])

    assert res_alpha["oa_1992"] == res_beta["oa_1992"]
    assert res_alpha["oa_2021"] == res_beta["oa_2021"]

    pd.testing.assert_frame_equal(res_alpha["df_townships"], res_beta["df_townships"])
    pd.testing.assert_frame_equal(res_alpha["df_district"], res_beta["df_district"])


def test_p2_g3_real_data_gap_integrity() -> None:
    """Verify that micro-integration evidence does not fake real data acceptance.

    Satisfies:
      - 微型集成与实景复现分别记证据，不混写一次PASS。
      - 真实数据缺失、指标未达标和未执行的验证分别如实记录，不能用示例数据或文档中的预期值代替验收证据。
    """
    repo = Path(__file__).resolve().parents[2]
    data_gaps_path = repo / "reports" / "data" / "data_gaps.md"
    assert data_gaps_path.exists(), "data_gaps.md must record data gap status"

    gaps_content = data_gaps_path.read_text(encoding="utf-8")
    # 原始影像与样本已补齐，但季节性、外部核验数据等缺口仍须如实登记
    assert "缺口清单" in gaps_content, "data_gaps.md must list remaining data gaps"
    assert "G1" in gaps_content, "data_gaps.md must record the missing summer scene (G1)"

    samples_1992 = repo / "data" / "samples" / "1992" / "labels.gpkg"
    samples_2021 = repo / "data" / "samples" / "2021" / "labels.gpkg"
    assert samples_1992.exists() and samples_2021.exists(), "两期样本应已就位"

    # 精度未达标必须在报告中留痕，不能用文档预期值替代验收证据
    acc_2021 = repo / "reports" / "accuracy" / "evaluation_2021.md"
    assert acc_2021.exists()

