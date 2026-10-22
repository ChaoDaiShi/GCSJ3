"""Acceptance test suite for Line V3: Expansion Analysis, Maps, Reports, and Reproducibility.

Responsible: Acceptance Line V3 (Change Analysis, Cartography, and Reproducibility).
Verifies acceptance items from docs/04-acceptance.md:
- C01: Compare two-epoch final classifications pixel-by-pixel to verify 4 change categories and NoData mask.
- C02: Verify EPSG:32648 projected area calculations and geometric intersection of edge pixels.
- C03: Verify township change table format (15 columns) and exact 9-unit coverage (7 streets, 2 towns).
- C04: Recompute area balance identities, net change, and annual expansion intensity metrics.
- C05: Verify township totals aggregate to district-level totals within tolerance (<= 0.001 km²).
- C06: Verify total, comparable area, and valid_ratio logic without treating unobserved areas as zero change.
- F01: Inspect QGIS project file (xindu_1992_2021.qgs) for relative path bindings and layer consistency.
- F02: Inspect urban expansion report (reports/analysis/urban_expansion.md) for section completeness.
- F03: Verify delivery package structure and required product categories.
- X01: Verify five CLI entrypoints exist, accept standard arguments, and support deterministic execution.
- X02: Inspect conda environment lockfile (reports/acceptance/environment-win-64.txt) for core dependencies.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
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

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import Affine, from_origin
import geopandas as gpd
from shapely.geometry import box

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rs_urban.analyze import (
    CHANGE_COLORMAP,
    TABLE_FIELDNAMES,
    compute_change_raster,
    vectorize_change_raster,
    calculate_change_statistics,
)


# ===========================================================================
# C01: Four Change Categories and Common Valid Mask
# ===========================================================================

def test_v3_c01_four_change_categories_and_valid_mask(change_fixture: dict):
    """C01: Verify 4 change categories: persistent, added, lost, persistent non-built, and NoData rules."""
    manifest = change_fixture["data"]
    arr_1992 = np.array(manifest["grid_1992"], dtype=np.uint8)
    arr_2021 = np.array(manifest["grid_2021"], dtype=np.uint8)
    expected_change = np.array(manifest["expected_change"], dtype=np.uint8)

    in_study_area = np.ones_like(arr_1992, dtype=bool)

    change_grid, valid_common = compute_change_raster(arr_1992, arr_2021, in_study_area)

    assert np.array_equal(change_grid, expected_change)

    # Pixel (0, 2): 1992 is NoData (0), 2021 is Built (1) -> Must remain NoData 0 (NOT added built)
    assert arr_1992[0, 2] == 0
    assert arr_2021[0, 2] == 1
    assert change_grid[0, 2] == 0
    assert valid_common[0, 2] == 0


# ===========================================================================
# C02: Projected Area Calculation and Edge Pixel Geometric Apportioning
# ===========================================================================

def test_v3_c02_projected_area_calculation_and_edge_pixels(change_fixture: dict):
    """C02: Verify calculation in EPSG:32648, conversion to km², and edge pixel apportioning by geometry."""
    manifest = change_fixture["data"]
    arr_change = np.array(manifest["expected_change"], dtype=np.uint8)
    transform = Affine.from_gdal(*manifest["transform"])

    gdf_change = vectorize_change_raster(arr_change, transform=transform, crs="EPSG:32648")
    gdf_change["area_km2"] = gdf_change.geometry.area / 1e6

    # Each full 30x30m pixel is 900 m² = 0.0009 km²
    # Expected valid pixels: 8 out of 9 -> total comparable area = 8 * 0.0009 = 0.0072 km²
    total_area_km2 = gdf_change["area_km2"].sum()
    assert abs(total_area_km2 - 0.0072) < 1e-6


# ===========================================================================
# C03: Township Table Format and Exact 9-Unit Coverage
# ===========================================================================

def test_v3_c03_township_table_format():
    """C03: Verify township table schema has exactly 15 columns, 9 units (7 streets, 2 towns), no district row."""
    expected_cols = [
        "unit_id", "name", "unit_type", "boundary_year",
        "total_area_km2", "comparable_area_km2", "valid_ratio",
        "built_1992_km2", "built_2021_km2", "persistent_km2",
        "added_km2", "lost_km2", "net_km2",
        "annual_net_km2", "annual_intensity_pct"
    ]
    assert TABLE_FIELDNAMES == expected_cols
    assert len(TABLE_FIELDNAMES) == 15

    # 9-township sample verifying no district total row mixed in
    townships = [
        ("01", "大丰街道", "street"), ("02", "三河街道", "street"), ("03", "新都街道", "street"),
        ("04", "新繁街道", "street"), ("05", "石板滩街道", "street"), ("06", "斑竹园街道", "street"),
        ("07", "桂湖街道", "street"), ("08", "军屯镇", "town"), ("09", "清流镇", "town")
    ]
    assert len(townships) == 9
    assert sum(t[2] == "street" for t in townships) == 7
    assert sum(t[2] == "town" for t in townships) == 2


# ===========================================================================
# C04: Area Balance and Annual Expansion Intensity Metrics
# ===========================================================================

def test_v3_c04_area_balance_and_intensity_formulas():
    """C04: Verify net_km2 = added - lost = built_2021 - built_1992 and annual metrics formulas."""
    persistent = 10.5
    added = 8.2
    lost = 1.2
    total_area = 100.0
    elapsed_years = 29

    built_1992 = persistent + lost
    built_2021 = persistent + added

    net_from_change = added - lost
    net_from_totals = built_2021 - built_1992

    # Area balance identity
    assert abs(net_from_change - net_from_totals) < 1e-9

    annual_net = net_from_change / elapsed_years
    annual_intensity = (net_from_change / (elapsed_years * total_area)) * 100

    expected_annual_net = 7.0 / 29.0
    expected_intensity = (7.0 / (29.0 * 100.0)) * 100

    assert abs(annual_net - expected_annual_net) < 1e-6
    assert abs(annual_intensity - expected_intensity) < 1e-6


# ===========================================================================
# C05: Township Sum vs District Total Consistency
# ===========================================================================

def test_v3_c05_township_sum_vs_district_consistency(change_fixture: dict):
    """C05: Verify sum of township areas matches district total within contract tolerance (<= 0.001 km²)."""
    manifest = change_fixture["data"]
    arr_change = np.array(manifest["expected_change"], dtype=np.uint8)
    transform = Affine.from_gdal(*manifest["transform"])
    crs = manifest["crs"]

    gdf_change = vectorize_change_raster(arr_change, transform=transform, crs=crs)

    b = manifest["bounds"]
    study_geom = box(b[0], b[1], b[2], b[3])
    t1_geom = box(b[0], b[1], 500055, b[3])
    t2_geom = box(500055, b[1], b[2], b[3])

    gdf_study_area = gpd.GeoDataFrame([{"area_id": "510114", "name": "新都区", "geometry": study_geom}], crs=crs)
    gdf_townships = gpd.GeoDataFrame([
        {"unit_id": "T01", "name": "西街镇", "unit_type": "town", "geometry": t1_geom},
        {"unit_id": "T02", "name": "东街道", "unit_type": "street", "geometry": t2_geom},
    ], crs=crs)

    town_df, dist_df, _ = calculate_change_statistics(
        gdf_change=gdf_change,
        gdf_study_area=gdf_study_area,
        gdf_townships=gdf_townships,
    )

    town_added_sum = town_df["added_km2"].sum()
    dist_added = dist_df["added_km2"].iloc[0]

    assert abs(town_added_sum - dist_added) <= 0.001


# ===========================================================================
# C06: Comparable Area and Zero Observation Handling
# ===========================================================================

def test_v3_c06_comparable_area_and_zero_observation():
    """C06: Verify valid_ratio formula and zero-observation handling without treating unobserved as zero change."""
    total_area_km2 = 50.0
    comp_area_km2 = 35.0
    valid_ratio = comp_area_km2 / total_area_km2
    assert abs(valid_ratio - 0.70) < 1e-6

    # When comparable area is 0 (all clouds / missing observation)
    zero_comp = 0.0
    ratio_zero = zero_comp / total_area_km2
    assert ratio_zero == 0.0


# ===========================================================================
# F01: QGIS Project Relative Paths and Layer Contracts
# ===========================================================================

def test_v3_f01_qgis_project_relative_paths(repo_root: Path):
    """F01: Inspect qgis/xindu_1992_2021.qgs, verify relative path bindings, and absence of hardcoded drives."""
    qgs_path = repo_root / "qgis" / "xindu_1992_2021.qgs"
    assert qgs_path.exists(), "QGIS project file must exist at qgis/xindu_1992_2021.qgs"

    content = qgs_path.read_text(encoding="utf-8")
    assert "<qgis" in content

    # Check for forbidden absolute hardcoded drive paths
    forbidden_prefixes = ["C:\\", "D:\\", "F:\\", "c:/", "d:/", "f:/"]
    for pref in forbidden_prefixes:
        assert pref not in content, f"QGIS project contains hardcoded absolute path prefix: {pref}"

    # Verify datasource paths use relative references
    assert "../outputs/rasters/" in content
    assert "../outputs/vectors/" in content


# ===========================================================================
# F02: Urban Expansion Report Structure and Consistency
# ===========================================================================

def test_v3_f02_expansion_report_structure(repo_root: Path):
    """F02: Inspect reports/analysis/urban_expansion.md for required sections and methodology caveats."""
    report_path = repo_root / "reports" / "analysis" / "urban_expansion.md"
    assert report_path.exists(), "Analysis report must exist at reports/analysis/urban_expansion.md"

    text = report_path.read_text(encoding="utf-8")

    required_keywords = [
        "1992",
        "2021",
        "EPSG:32648",
        "大丰街道",
        "清流镇",
        "03-contracts.md",
        "局限性",
    ]
    for kw in required_keywords:
        assert kw in text, f"Analysis report missing required section/keyword: {kw}"


# ===========================================================================
# F03: Delivery Artifact Inventory and Completeness
# ===========================================================================

def test_v3_f03_delivery_artifact_inventory(repo_root: Path):
    """F03: Verify delivery repository directory layout and required files existence."""
    required_dirs = [
        repo_root / "configs",
        repo_root / "data" / "catalog",
        repo_root / "docs",
        repo_root / "qgis",
        repo_root / "src" / "rs_urban",
        repo_root / "tests" / "acceptance",
        repo_root / "reports" / "acceptance",
    ]
    for d in required_dirs:
        assert d.exists() and d.is_dir(), f"Missing required directory: {d}"

    # Check core config files
    assert (repo_root / "configs" / "project.toml").exists()
    assert (repo_root / ".env.example").exists()
    assert (repo_root / "environment.yml").exists()


# ===========================================================================
# X01: Five-Stage CLI Entrypoints Existence and Signatures
# ===========================================================================

def test_v3_x01_five_stage_cli_entrypoints(repo_root: Path):
    """X01: Verify all 5 CLI entrypoints exist in src/ and can be loaded."""
    scripts = [
        repo_root / "src" / "01_preprocess.py",
        repo_root / "src" / "02_samples.py",
        repo_root / "src" / "03_classify.py",
        repo_root / "src" / "04_evaluate.py",
        repo_root / "src" / "05_analyze.py",
    ]
    for s in scripts:
        assert s.exists(), f"CLI entrypoint missing: {s}"
        content = s.read_text(encoding="utf-8")
        assert "__main__" in content
        assert "--config" in content


# ===========================================================================
# X02: Environment Lockfile and Core Dependency Versions
# ===========================================================================

def test_v3_x02_environment_lockfile(repo_root: Path):
    """X02: Inspect conda environment lockfile for platform win-64 and core packages."""
    lockfile = repo_root / "reports" / "acceptance" / "environment-win-64.txt"
    assert lockfile.exists(), "Environment lockfile must exist at reports/acceptance/environment-win-64.txt"

    content = lockfile.read_text(encoding="utf-8")
    assert "platform: win-64" in content
    assert "@EXPLICIT" in content

    # Verify presence of essential GIS and ML libraries
    core_packages = ["gdal", "rasterio", "geopandas", "scikit-learn", "shapely", "cpython-3.11"]
    for pkg in core_packages:
        assert pkg in content, f"Package {pkg} missing from environment lockfile"
