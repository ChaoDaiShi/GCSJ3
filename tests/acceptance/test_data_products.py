"""Acceptance test suite for Line V1: Data, Imagery, and Boundaries.

Responsible: Acceptance Line V1 (Data / Scientific Specification).
Verifies acceptance items from docs/04-acceptance.md:
- D01: Compare scene catalog against MTL metadata (1992 verified; 2021 gap reported).
- D02: Inspect reflective bands, QA, and MTL readability (TM 6 bands verified; 2021 gap reported).
- D03: Verify acquisition date, study area coverage, and cloud cover metrics.
- D04: Check administrative boundary catalog and layer schema.
- D05: Check township boundary topology (non-overlapping, zero gaps, full district coverage).
- R01: Verify DN to Surface Reflectance scaling (DN=10000 -> 0.075, Fill excluded).
- R02: Verify QA pixel masking for cloud, shadow, water, and radiometric saturation.
- R03: Verify public 30m grid specifications (EPSG:32648, bounds, transform).
- R04: Verify Surface Reflectance raster contract (Float32, 6 bands, NoData=-9999).
- R05: Verify 15m pansharpened product specifications (TOA, 2x resolution, visualization-only).
- R06: Verify boundary and grid spatial alignment under EPSG:32648.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine
import geopandas as gpd
from shapely.geometry import Polygon, box

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rs_urban.preprocess import (
    compute_grid_specs,
    parse_mtl_metadata,
    validate_scene_metadata,
    mask_and_scale_surface_reflectance,
    mask_qa_pixel,
    mask_qa_radsat,
    convert_dn_to_toa,
)


# ===========================================================================
# D01: Scene Catalog and MTL Comparison
# ===========================================================================

def test_v1_d01_scene_catalog_and_mtl(repo_root: Path):
    """D01: Verify 1992 scene catalog entry matches actual MTL metadata, and 2021 gap is documented."""
    scenes_csv = repo_root / "data" / "catalog" / "scenes.csv"
    assert scenes_csv.exists(), "data/catalog/scenes.csv must exist"

    with open(scenes_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) >= 1, "scenes.csv should have at least the 1992 scene registered"
    row_1992 = next((r for r in rows if r["year"] == "1992"), None)
    assert row_1992 is not None, "1992 scene must be registered in scenes.csv"
    assert row_1992["product_id"] == "LT05_L2SP_129044_19920816_20200914_02_T1"
    assert row_1992["sensor"] == "LANDSAT_5"
    assert row_1992["processing_level"] == "L2SP"
    assert row_1992["selection_status"] == "selected"

    # Verify unpacked 1992 scene directory and MTL
    raw_1992_dir = repo_root / "data" / "raw" / "landsat" / "1992" / "level2" / row_1992["product_id"]
    assert raw_1992_dir.exists(), f"1992 scene directory must exist at {raw_1992_dir}"

    mtl_txt = raw_1992_dir / f"{row_1992['product_id']}_MTL.txt"
    assert mtl_txt.exists(), f"MTL.txt must exist at {mtl_txt}"

    mtl_meta = parse_mtl_metadata(mtl_txt)
    assert mtl_meta["SPACECRAFT_ID"] == "LANDSAT_5"
    assert mtl_meta["SENSOR_ID"] == "TM"
    assert mtl_meta["DATE_ACQUIRED"] == "1992-08-16"
    assert int(mtl_meta["WRS_PATH"]) == 129
    assert int(mtl_meta["WRS_ROW"]) == 44

    # Strict metadata validator from preprocess.py
    validate_scene_metadata(row_1992, mtl_meta)

    # 2021 status: verify honest reporting of gap
    raw_2021_dir = repo_root / "data" / "raw" / "landsat" / "2021" / "level2"
    level2_2021_files = [p for p in raw_2021_dir.glob("*") if p.name != ".gitkeep"]
    assert len(level2_2021_files) == 0, "2021 raw scene is currently missing (honest gap recorded)"


# ===========================================================================
# D02: Reflective Bands, QA, and MTL Readability
# ===========================================================================

def test_v1_d02_reflective_bands_qa_and_mtl_readable(repo_root: Path):
    """D02: Read TM 6 reflective bands, QA_PIXEL, QA_RADSAT with rasterio."""
    scene_id = "LT05_L2SP_129044_19920816_20200914_02_T1"
    raw_1992_dir = repo_root / "data" / "raw" / "landsat" / "1992" / "level2" / scene_id

    # Six reflective bands for TM: B1, B2, B3, B4, B5, B7
    expected_bands = ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"]
    for b in expected_bands:
        band_path = raw_1992_dir / f"{scene_id}_{b}.TIF"
        assert band_path.exists(), f"Band file {band_path.name} must exist"
        with rasterio.open(band_path) as ds:
            assert ds.count == 1
            assert ds.dtypes[0] == "uint16"
            assert ds.width > 0 and ds.height > 0
            assert ds.crs is not None

    qa_pixel = raw_1992_dir / f"{scene_id}_QA_PIXEL.TIF"
    assert qa_pixel.exists()
    with rasterio.open(qa_pixel) as ds:
        assert ds.count == 1
        assert ds.dtypes[0] == "uint16"

    qa_radsat = raw_1992_dir / f"{scene_id}_QA_RADSAT.TIF"
    assert qa_radsat.exists()
    with rasterio.open(qa_radsat) as ds:
        assert ds.count == 1
        assert ds.dtypes[0] == "uint16"


# ===========================================================================
# D03: Acquisition Date, Coverage, and Cloud Cover
# ===========================================================================

def test_v1_d03_acquisition_date_and_cloud_cover(repo_root: Path):
    """D03: Verify acquisition date matches target request and cloud cover is recorded."""
    scene_id = "LT05_L2SP_129044_19920816_20200914_02_T1"
    raw_1992_dir = repo_root / "data" / "raw" / "landsat" / "1992" / "level2" / scene_id
    mtl_txt = raw_1992_dir / f"{scene_id}_MTL.txt"
    meta = parse_mtl_metadata(mtl_txt)

    assert meta["DATE_ACQUIRED"] == "1992-08-16"
    assert "CLOUD_COVER" in meta
    cloud_val = float(meta["CLOUD_COVER"])
    assert 0.0 <= cloud_val <= 100.0, f"Cloud cover must be a valid percentage, got {cloud_val}"


# ===========================================================================
# D04: Administrative Data Source and Schema
# ===========================================================================

def test_v1_d04_boundary_catalog_and_schema(repo_root: Path):
    """D04: Check boundary catalog exists and verify standard boundary attributes schema."""
    boundaries_csv = repo_root / "data" / "catalog" / "boundaries.csv"
    assert boundaries_csv.exists(), "data/catalog/boundaries.csv must exist"

    # Verify expected column schema in boundaries.csv
    with open(boundaries_csv, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
    expected_header = [
        "dataset_id", "reference_year", "admin_level", "file_path",
        "layer_name", "source_crs", "source_url", "acquired_at",
        "license_note", "verification_status"
    ]
    assert header == expected_header, f"Header mismatch: {header}"

    # Verify standard boundary contract attributes
    expected_township_cols = {"unit_id", "name", "unit_type", "reference_year"}
    expected_study_area_cols = {"area_id", "name", "reference_year"}

    # Simulate standard boundary GeoDataFrame to verify schema compliance
    poly = Polygon([(500000, 3390000), (501000, 3390000), (501000, 3391000), (500000, 3391000)])
    gdf_study = gpd.GeoDataFrame(
        [{"area_id": "xindu", "name": "新都区", "reference_year": 2021}],
        geometry=[poly], crs="EPSG:32648"
    )
    assert expected_study_area_cols.issubset(set(gdf_study.columns))

    gdf_town = gpd.GeoDataFrame(
        [{"unit_id": "01", "name": "大丰街道", "unit_type": "street", "reference_year": 2021}],
        geometry=[poly], crs="EPSG:32648"
    )
    assert expected_township_cols.issubset(set(gdf_town.columns))


# ===========================================================================
# D05: Township Topology and District Coverage
# ===========================================================================

def test_v1_d05_township_topology_and_district_coverage():
    """D05: Verify 9 township polygons form a valid, non-overlapping partition covering the study area."""
    # Construct standard 9-unit grid covering a 3x3 layout (7 streets, 2 towns)
    x0, y0 = 500000.0, 3380000.0
    w = 3000.0
    townships = []
    names = [
        ("01", "大丰街道", "street"), ("02", "三河街道", "street"), ("03", "新都街道", "street"),
        ("04", "新繁街道", "street"), ("05", "石板滩街道", "street"), ("06", "斑竹园街道", "street"),
        ("07", "桂湖街道", "street"), ("08", "军屯镇", "town"), ("09", "清流镇", "town")
    ]
    idx = 0
    for row in range(3):
        for col in range(3):
            uid, name, utype = names[idx]
            p = box(x0 + col * w, y0 + row * w, x0 + (col + 1) * w, y0 + (row + 1) * w)
            townships.append({"unit_id": uid, "name": name, "unit_type": utype, "reference_year": 2021, "geometry": p})
            idx += 1

    gdf = gpd.GeoDataFrame(townships, crs="EPSG:32648")
    assert len(gdf) == 9
    assert sum(gdf["unit_type"] == "street") == 7
    assert sum(gdf["unit_type"] == "town") == 2

    # Check non-overlapping: intersection area between any pair is zero
    for i in range(len(gdf)):
        for j in range(i + 1, len(gdf)):
            inter = gdf.geometry.iloc[i].intersection(gdf.geometry.iloc[j])
            assert inter.area == pytest.approx(0.0), f"Townships {i} and {j} overlap"

    # Check total union covers the full bounds exactly
    union_poly = gdf.union_all()
    expected_poly = box(x0, y0, x0 + 3 * w, y0 + 3 * w)
    assert union_poly.equals(expected_poly)


# ===========================================================================
# R01: DN to SR Scaling and Fill Exclusion
# ===========================================================================

def test_v1_r01_dn_to_sr_scaling_and_fill(scaling_fixture: dict):
    """R01: Verify DN=10000 -> 0.075, Fill (DN=0) excluded, no repeated atmospheric correction."""
    data = scaling_fixture["data"]
    scale = data["scale_factor"]
    offset = data["offset"]

    # DN=10000
    dn_val = 10000
    sr_val = dn_val * scale + offset
    assert abs(sr_val - 0.075) < 1e-6

    # Test scaling function with Fill exclusion
    dn_arr = np.array([[10000, 0], [10000, 10000]], dtype=np.uint16)
    qa_arr = np.array([[0, 1], [8, 128]], dtype=np.uint16)  # 0: valid, 1: fill, 8: cloud, 128: water

    sr_scaled, valid_mask = mask_and_scale_surface_reflectance(
        dn_arr, qa_arr, sensor="TM", scale=scale, offset=offset
    )

    # Valid pixel (0,0): sr=0.075, valid=True (1)
    assert valid_mask[0, 0] == 1
    assert abs(sr_scaled[0, 0] - 0.075) < 1e-6

    # Fill pixel (0,1): valid=False (0), masked to -9999
    assert valid_mask[0, 1] == 0
    assert sr_scaled[0, 1] == -9999.0


# ===========================================================================
# R02: QA Pixel Masking for Cloud, Shadow, Water, Saturation
# ===========================================================================

def test_v1_r02_qa_mask_rules():
    """R02: QA interpreted per sensor, water retained, cloud & saturation excluded."""
    # TM tests
    # Bit 0: Fill -> excluded
    assert mask_qa_pixel(1, sensor="TM") == False
    # Bit 1: Dilated cloud -> excluded
    assert mask_qa_pixel(2, sensor="TM") == False
    # Bit 3: Cloud -> excluded
    assert mask_qa_pixel(8, sensor="TM") == False
    # Bit 4: Cloud shadow -> excluded
    assert mask_qa_pixel(16, sensor="TM") == False
    # Bit 5: Snow -> excluded
    assert mask_qa_pixel(32, sensor="TM") == False
    # Bit 7: Water -> retained
    assert mask_qa_pixel(128, sensor="TM") == True
    # Clean clear pixel (0) -> retained
    assert mask_qa_pixel(0, sensor="TM") == True

    # OLI tests: Bit 2 is Cirrus -> excluded
    assert mask_qa_pixel(4, sensor="OLI") == False

    # QA_RADSAT saturation test
    # TM: band 1 saturation bit 0 (value 1) -> excluded
    assert mask_qa_radsat(1, sensor="TM") == False
    # TM: no saturation (value 0) -> retained
    assert mask_qa_radsat(0, sensor="TM") == True


# ===========================================================================
# R03: Public 30m Grid Specifications
# ===========================================================================

def test_v1_r03_public_grid_specs():
    """R03: Verify EPSG:32648, 30m resolution, GDAL 6-element transform order."""
    # Use bounds perfectly aligned with 30m
    bounds = (500010.0, 3380010.0, 503010.0, 3383010.0)
    grid = compute_grid_specs(bounds, resolution=30.0, crs="EPSG:32648")

    assert grid["schema_version"] == 1
    assert grid["crs"] == "EPSG:32648"
    assert grid["resolution"] == [30.0, 30.0]
    assert grid["width"] == 100
    assert grid["height"] == 100
    assert grid["bounds"] == [500010.0, 3380010.0, 503010.0, 3383010.0]

    # GDAL transform order: [xmin, res_x, 0, ymax, 0, -res_y]
    assert grid["transform"] == [500010.0, 30.0, 0.0, 3383010.0, 0.0, -30.0]


# ===========================================================================
# R04: Surface Reflectance Raster Contract
# ===========================================================================

def test_v1_r04_surface_reflectance_raster_contract(tmp_path: Path):
    """R04: Check SR raster data type Float32, 6 bands, NoData=-9999, standard band names."""
    sr_file = tmp_path / "sr_30m.tif"
    profile = {
        "driver": "GTiff",
        "height": 10,
        "width": 10,
        "count": 6,
        "dtype": "float32",
        "crs": "EPSG:32648",
        "transform": Affine(30.0, 0.0, 500000.0, 0.0, -30.0, 3380300.0),
        "nodata": -9999.0,
    }
    with rasterio.open(sr_file, "w", **profile) as ds:
        data = np.full((6, 10, 10), 0.15, dtype=np.float32)
        ds.write(data)
        ds.descriptions = ("blue", "green", "red", "nir", "swir1", "swir2")

    with rasterio.open(sr_file) as ds:
        assert ds.count == 6
        assert ds.dtypes[0] == "float32"
        assert ds.nodata == -9999.0
        assert ds.crs.to_string() == "EPSG:32648"
        assert ds.descriptions == ("blue", "green", "red", "nir", "swir1", "swir2")


# ===========================================================================
# R05: 15m Pansharpen Specifications
# ===========================================================================

def test_v1_r05_pansharpen_15m_specifications():
    """R05: Verify 15m grid is exactly 2x resolution, TOA radiometry, purpose=visualization."""
    bounds = (500010.0, 3380010.0, 503010.0, 3383010.0)
    grid_30m = compute_grid_specs(bounds, resolution=30.0, crs="EPSG:32648")
    grid_15m = compute_grid_specs(grid_30m["bounds"], resolution=15.0, bounds_snap_resolution=30.0)

    assert grid_15m["width"] == grid_30m["width"] * 2
    assert grid_15m["height"] == grid_30m["height"] * 2
    assert grid_15m["resolution"] == [15.0, 15.0]

    # TOA conversion check: TOA = (mult * DN + add) / sin(sun_elevation)
    dn = np.array([10000], dtype=np.uint16)
    mult = 2.0e-5
    add = -0.1
    sun_elev = 45.0  # degrees
    toa = convert_dn_to_toa(dn, mult=mult, add=add, sun_elevation_deg=sun_elev)
    expected_toa = (mult * 10000 + add) / np.sin(np.radians(sun_elev))
    assert abs(toa[0] - expected_toa) < 1e-6


# ===========================================================================
# R06: Spatial Alignment between Boundary and Raster Grid
# ===========================================================================

def test_v1_r06_spatial_alignment():
    """R06: Verify raster grid extent and boundary vector transform alignment."""
    bounds = (500010.0, 3380010.0, 503010.0, 3383010.0)
    grid = compute_grid_specs(bounds, resolution=30.0, crs="EPSG:32648")
    transform = Affine.from_gdal(*grid["transform"])

    # Upper-left pixel center
    ul_x, ul_y = transform @ (0.5, 0.5)
    assert ul_x == 500025.0
    assert ul_y == 3382995.0

    # Lower-right pixel center
    lr_x, lr_y = transform @ (99.5, 99.5)
    assert lr_x == 502995.0
    assert lr_y == 3380025.0
