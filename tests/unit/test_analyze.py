"""Unit tests for P1-E: Urban expansion and land cover change analysis.

Tests verify:
  1. Micro-data change matrix: 4 change categories (persistent, added, lost, persistent non-built).
  2. NoData / missing pixel rule: 1992 NoData with 2021 built is strictly NoData, NOT added built.
  3. Half-pixel township boundary partition at x=500055 correctly divides area.
  4. Area balance between township sums and district total within tolerance.
  5. Zero-observation township retains row with empty change strings ("") and 0.0 comparable area.
  6. Urban change GPKG contains layer 'change' with change_id, change_name, area_km2.
  7. Township table does not contain district total row; district table has exactly one row.
  8. Full analyze_change pipeline end-to-end execution.
  9. CLI 05_analyze.py execution end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from affine import Affine
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from rs_urban.analyze import (
    CHANGE_COLORMAP,
    CHANGE_NAMES,
    TABLE_FIELDNAMES,
    analyze_change,
    calculate_change_statistics,
    compute_change_raster,
    vectorize_change_raster,
)
from rs_urban.contracts import ChangeData, ProjectContext
from rs_urban.config import get_repo_root


@pytest.fixture
def mock_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_slug": "rs-urban-expansion",
        "years": [1992, 2021],
        "boundary_reference_year": 2021,
        "expected_township_count": 2,
        "target_crs": "EPSG:32648",
        "analysis_resolution_m": 30,
        "class_nodata": 0,
        "float_nodata": -9999.0,
        "mask_nodata": 255,
        "analysis": {
            "elapsed_years": 29,
            "comparison_mask": "intersection_of_valid_pixels",
            "area_unit": "km2",
        },
    }


def test_micro_change_matrix_and_nodata(change_fixture: dict[str, Any]) -> None:
    """Verify 3x3 micro-data change matrix and ensure missing 1992 pixel is not misclassified as added built."""
    fix = change_fixture["data"]
    grid_1992 = np.array(fix["grid_1992"], dtype=np.uint8)
    grid_2021 = np.array(fix["grid_2021"], dtype=np.uint8)
    in_study_area = np.ones((3, 3), dtype=bool)

    change_grid, valid_common = compute_change_raster(grid_1992, grid_2021, in_study_area)

    expected_change = np.array(fix["expected_change"], dtype=np.uint8)
    np.testing.assert_array_equal(change_grid, expected_change)

    # Pixel (0, 2): 1992=0 (NoData), 2021=1 (Built)
    # Must be 0 in change_grid (NoData), and 0 in valid_common (invalid in study area)
    assert change_grid[0, 2] == 0
    assert valid_common[0, 2] == 0

    # Common valid cells: 8 cells
    assert np.sum(valid_common == 1) == 8


def test_half_pixel_partition_and_area_balance(change_fixture: dict[str, Any]) -> None:
    """Verify half-pixel township partition at x=500055 and exact district vs township area balance."""
    fix = change_fixture["data"]
    grid_change = np.array(fix["expected_change"], dtype=np.uint8)
    transform = Affine.from_gdal(*fix["transform"])
    crs = fix["crs"]

    gdf_change = vectorize_change_raster(grid_change, transform=transform, crs=crs)

    # Reconstruct test geometries
    b = fix["bounds"]
    study_geom = box(b[0], b[1], b[2], b[3])
    t1_geom = box(b[0], b[1], 500055, b[3])
    t2_geom = box(500055, b[1], b[2], b[3])

    gdf_study_area = gpd.GeoDataFrame([{"area_id": "510114", "name": "新都区", "geometry": study_geom}], crs=crs)
    gdf_townships = gpd.GeoDataFrame([
        {"unit_id": "T01", "name": "西街镇", "unit_type": "town", "geometry": t1_geom},
        {"unit_id": "T02", "name": "东街道", "unit_type": "street", "geometry": t2_geom},
    ], crs=crs)

    townships_df, district_df, stats_summary = calculate_change_statistics(
        gdf_change=gdf_change,
        gdf_study_area=gdf_study_area,
        gdf_townships=gdf_townships,
        elapsed_years=29,
        boundary_year=2021,
    )

    # Check District metrics
    dist_row = district_df.iloc[0]
    assert dist_row["comparable_area_km2"] == pytest.approx(0.0072, abs=1e-6)
    assert dist_row["persistent_km2"] == pytest.approx(0.0018, abs=1e-6)
    assert dist_row["added_km2"] == pytest.approx(0.0027, abs=1e-6)
    assert dist_row["lost_km2"] == pytest.approx(0.0009, abs=1e-6)
    assert dist_row["net_km2"] == pytest.approx(0.0018, abs=1e-6)

    # Check Townships metrics
    t1_row = townships_df[townships_df["unit_id"] == "T01"].iloc[0]
    t2_row = townships_df[townships_df["unit_id"] == "T02"].iloc[0]

    # T1: half pixel allocated
    assert t1_row["comparable_area_km2"] == pytest.approx(0.00405, abs=1e-6)
    assert t1_row["persistent_km2"] == pytest.approx(0.0009, abs=1e-6)
    assert t1_row["added_km2"] == pytest.approx(0.0009, abs=1e-6)
    assert t1_row["lost_km2"] == pytest.approx(0.0009, abs=1e-6)
    assert t1_row["net_km2"] == pytest.approx(0.0, abs=1e-6)

    # T2: half pixel allocated
    assert t2_row["comparable_area_km2"] == pytest.approx(0.00315, abs=1e-6)
    assert t2_row["persistent_km2"] == pytest.approx(0.0009, abs=1e-6)
    assert t2_row["added_km2"] == pytest.approx(0.0018, abs=1e-6)
    assert t2_row["lost_km2"] == pytest.approx(0.0, abs=1e-6)
    assert t2_row["net_km2"] == pytest.approx(0.0018, abs=1e-6)

    # Check balance summary
    balance = stats_summary["area_balance_check"]
    assert balance["is_balanced"] is True
    assert balance["discrepancy_net_km2"] < 1e-6
    assert balance["discrepancy_comparable_km2"] < 1e-6


def test_zero_observation_township() -> None:
    """Verify that a township with zero valid observation retains its row with empty strings for change metrics."""
    crs = "EPSG:32648"
    study_geom = box(0, 0, 100, 100)
    t1_geom = box(0, 0, 50, 100)
    t2_geom = box(50, 0, 100, 100)  # T2 will have zero change observation

    # Change only occurs in T1
    change_geom = box(10, 10, 40, 40)
    gdf_change = gpd.GeoDataFrame([{"change_id": 1, "change_name": "持续建设", "geometry": change_geom}], crs=crs)

    gdf_study_area = gpd.GeoDataFrame([{"area_id": "510114", "name": "新都区", "geometry": study_geom}], crs=crs)
    gdf_townships = gpd.GeoDataFrame([
        {"unit_id": "T01", "name": "西街镇", "unit_type": "town", "geometry": t1_geom},
        {"unit_id": "T02", "name": "零观测镇", "unit_type": "town", "geometry": t2_geom},
    ], crs=crs)

    townships_df, _, stats = calculate_change_statistics(
        gdf_change=gdf_change,
        gdf_study_area=gdf_study_area,
        gdf_townships=gdf_townships,
        elapsed_years=29,
        boundary_year=2021,
    )

    assert len(townships_df) == 2
    t2_row = townships_df[townships_df["unit_id"] == "T02"].iloc[0]
    assert t2_row["comparable_area_km2"] == 0.0
    assert t2_row["valid_ratio"] == 0.0
    assert t2_row["built_1992_km2"] == ""
    assert t2_row["built_2021_km2"] == ""
    assert t2_row["persistent_km2"] == ""
    assert t2_row["added_km2"] == ""
    assert t2_row["lost_km2"] == ""
    assert t2_row["net_km2"] == ""
    assert t2_row["annual_net_km2"] == ""
    assert t2_row["annual_intensity_pct"] == ""


def test_table_headers_and_no_total_in_townships(change_fixture: dict[str, Any]) -> None:
    """Verify table headers match contract exactly and township table never contains district total."""
    fix = change_fixture["data"]
    grid_change = np.array(fix["expected_change"], dtype=np.uint8)
    transform = Affine.from_gdal(*fix["transform"])
    crs = fix["crs"]

    gdf_change = vectorize_change_raster(grid_change, transform=transform, crs=crs)

    b = fix["bounds"]
    study_geom = box(b[0], b[1], b[2], b[3])
    t1_geom = box(b[0], b[1], 500055, b[3])
    t2_geom = box(500055, b[1], b[2], b[3])

    gdf_study_area = gpd.GeoDataFrame([{"area_id": "510114", "name": "新都区", "geometry": study_geom}], crs=crs)
    gdf_townships = gpd.GeoDataFrame([
        {"unit_id": "T01", "name": "西街镇", "unit_type": "town", "geometry": t1_geom},
        {"unit_id": "T02", "name": "东街道", "unit_type": "street", "geometry": t2_geom},
    ], crs=crs)

    townships_df, district_df, _ = calculate_change_statistics(
        gdf_change=gdf_change,
        gdf_study_area=gdf_study_area,
        gdf_townships=gdf_townships,
    )

    assert list(townships_df.columns) == TABLE_FIELDNAMES
    assert list(district_df.columns) == TABLE_FIELDNAMES

    # Township table must not have summary rows like 'total', 'district', or '合计'
    assert len(townships_df) == 2
    assert "district" not in townships_df["unit_type"].values
    assert "总计" not in townships_df["name"].values

    # District table has exactly one row
    assert len(district_df) == 1
    assert district_df["unit_type"].iloc[0] == "district"


def test_analyze_change_pipeline_and_artifacts(
    tmp_path: Path,
    mock_config: dict[str, Any],
    change_fixture: dict[str, Any],
) -> None:
    """Verify full analyze_change pipeline writes rasters, vector GPKG, CSVs and statistics JSON."""
    fix = change_fixture["data"]
    crs = fix["crs"]
    transform = Affine.from_gdal(*fix["transform"])

    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    # 1. Create final classification rasters for 1992 and 2021
    rasters_dir = outputs_dir / "rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)

    grid_1992 = np.array(fix["grid_1992"], dtype=np.uint8)
    grid_2021 = np.array(fix["grid_2021"], dtype=np.uint8)

    meta = {
        "driver": "GTiff",
        "height": 3,
        "width": 3,
        "count": 1,
        "dtype": rasterio.uint8,
        "crs": crs,
        "transform": transform,
        "nodata": 0,
    }

    with rasterio.open(rasters_dir / "lulc_1992_final_30m.tif", "w", **meta) as dst:
        dst.write(grid_1992, 1)

    with rasterio.open(rasters_dir / "lulc_2021_final_30m.tif", "w", **meta) as dst:
        dst.write(grid_2021, 1)

    # 2. Create boundaries GPKG
    bound_dir = data_dir / "processed" / "boundaries"
    bound_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = bound_dir / "xindu_2021.gpkg"

    b = fix["bounds"]
    study_geom = box(b[0], b[1], b[2], b[3])
    t1_geom = box(b[0], b[1], 500055, b[3])
    t2_geom = box(500055, b[1], b[2], b[3])

    gdf_study = gpd.GeoDataFrame([{"area_id": "510114", "name": "成都市新都区", "reference_year": 2021, "geometry": study_geom}], crs=crs)
    gdf_town = gpd.GeoDataFrame([
        {"unit_id": "T01", "name": "西街镇", "unit_type": "town", "reference_year": 2021, "geometry": t1_geom},
        {"unit_id": "T02", "name": "东街道", "unit_type": "street", "reference_year": 2021, "geometry": t2_geom},
    ], crs=crs)

    gdf_study.to_file(gpkg_path, layer="study_area", driver="GPKG")
    gdf_town.to_file(gpkg_path, layer="townships", driver="GPKG")

    ctx = ProjectContext(
        root=tmp_path,
        data=data_dir,
        outputs=outputs_dir,
        reports=reports_dir,
        scratch=scratch_dir,
        config=mock_config,
    )

    result = analyze_change(ctx)

    assert isinstance(result, ChangeData)
    assert result.raster == outputs_dir / "rasters" / "change_1992_2021_30m.tif"
    assert result.vectors == outputs_dir / "vectors" / "change" / "urban_change.gpkg"
    assert result.townships == outputs_dir / "tables" / "township_change_1992_2021.csv"
    assert result.district == outputs_dir / "tables" / "district_change_1992_2021.csv"

    # Verify all outputs exist
    assert result.raster.exists()
    assert result.vectors.exists()
    assert result.townships.exists()
    assert result.district.exists()

    # Verify valid_common_30m.tif exists
    valid_common_path = data_dir / "processed" / "common" / "valid_common_30m.tif"
    assert valid_common_path.exists()

    with rasterio.open(valid_common_path) as src_common:
        assert src_common.nodata == 255
        assert (src_common.width, src_common.height) == (3, 3)

    # Verify change raster colormap
    with rasterio.open(result.raster) as src_change:
        assert src_change.nodata == 0
        cmap = src_change.colormap(1)
        assert cmap[0] == (0, 0, 0, 0)
        assert cmap[1] == (217, 95, 2, 255)

    # Verify vector GPKG layer 'change'
    gdf_v = gpd.read_file(result.vectors, layer="change")
    assert "change_id" in gdf_v.columns
    assert "change_name" in gdf_v.columns
    assert "area_km2" in gdf_v.columns

    # Verify statistics.json
    stats_path = reports_dir / "analysis" / "statistics.json"
    assert stats_path.exists()
    with open(stats_path, "r", encoding="utf-8") as f:
        stat = json.load(f)
    assert stat["area_balance_check"]["is_balanced"] is True


def test_cli_05_analyze(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mock_config: dict[str, Any],
    change_fixture: dict[str, Any],
) -> None:
    """Verify CLI entrypoint 05_analyze.py functions end-to-end with --config and --env-file."""
    for key in ["RS_DATA_ROOT", "RS_OUTPUT_ROOT", "RS_REPORT_ROOT", "RS_SCRATCH_ROOT"]:
        monkeypatch.delenv(key, raising=False)

    import importlib
    cli_mod = importlib.import_module("05_analyze")
    cli_main = cli_mod.main

    fix = change_fixture["data"]
    crs = fix["crs"]
    transform = Affine.from_gdal(*fix["transform"])

    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    rasters_dir = outputs_dir / "rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "driver": "GTiff",
        "height": 3,
        "width": 3,
        "count": 1,
        "dtype": rasterio.uint8,
        "crs": crs,
        "transform": transform,
        "nodata": 0,
    }
    with rasterio.open(rasters_dir / "lulc_1992_final_30m.tif", "w", **meta) as dst:
        dst.write(np.array(fix["grid_1992"], dtype=np.uint8), 1)
    with rasterio.open(rasters_dir / "lulc_2021_final_30m.tif", "w", **meta) as dst:
        dst.write(np.array(fix["grid_2021"], dtype=np.uint8), 1)

    bound_dir = data_dir / "processed" / "boundaries"
    bound_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = bound_dir / "xindu_2021.gpkg"

    b = fix["bounds"]
    study_geom = box(b[0], b[1], b[2], b[3])
    t1_geom = box(b[0], b[1], 500055, b[3])
    t2_geom = box(500055, b[1], b[2], b[3])

    gdf_study = gpd.GeoDataFrame([{"area_id": "510114", "name": "成都市新都区", "reference_year": 2021, "geometry": study_geom}], crs=crs)
    gdf_town = gpd.GeoDataFrame([
        {"unit_id": "T01", "name": "西街镇", "unit_type": "town", "reference_year": 2021, "geometry": t1_geom},
        {"unit_id": "T02", "name": "东街道", "unit_type": "street", "reference_year": 2021, "geometry": t2_geom},
    ], crs=crs)

    gdf_study.to_file(gpkg_path, layer="study_area", driver="GPKG")
    gdf_town.to_file(gpkg_path, layer="townships", driver="GPKG")

    # Copy project.toml
    config_path = tmp_path / "project.toml"
    config_path.write_text((get_repo_root() / "configs" / "project.toml").read_text(encoding="utf-8"), encoding="utf-8")

    # Write .env
    env_path = tmp_path / ".env"
    env_content = f"""
RS_DATA_ROOT={data_dir.as_posix()}
RS_OUTPUT_ROOT={outputs_dir.as_posix()}
RS_REPORT_ROOT={reports_dir.as_posix()}
RS_SCRATCH_ROOT={scratch_dir.as_posix()}
"""
    env_path.write_text(env_content, encoding="utf-8")

    exit_code = cli_main([
        "--config", str(config_path),
        "--env-file", str(env_path),
    ])

    assert exit_code == 0
    assert (outputs_dir / "rasters" / "change_1992_2021_30m.tif").exists()
    assert (outputs_dir / "tables" / "township_change_1992_2021.csv").exists()
    assert (outputs_dir / "tables" / "district_change_1992_2021.csv").exists()
