"""Unit tests for P1-A: data registration, boundary processing, and remote sensing preprocessing.

Verifies:
1. DN scaling and Fill preservation (Fill DN=0 does not become -0.2).
2. Sensor band mapping for Landsat 5 (TM) and Landsat 8 (OLI).
3. QA_PIXEL bit masking differences (water retained, cloud excluded, cirrus handled per sensor).
4. Snapping logic for 30m and 15m grids and transform generation.
5. MTL parsing and metadata validation (strict mismatch reporting).
6. Boundary extraction, layer schema, and AOI mask generation.
7. End-to-end preprocess_year pipeline and PreparedData contract.
8. Landsat 8 TOA conversion and 15m pansharpening.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

# Automatically configure GDAL_DATA and PROJ_DATA if available in active environment
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
from shapely.geometry import Polygon, box

from rs_urban.contracts import ProjectContext, PreparedData
from rs_urban.preprocess import (
    compute_grid_specs,
    parse_mtl_metadata,
    validate_scene_metadata,
    mask_and_scale_surface_reflectance,
    mask_qa_pixel,
    mask_qa_radsat,
    prepare_boundaries,
    preprocess_year,
    pansharpen_2021,
    convert_dn_to_toa,
)


# ---------------------------------------------------------------------------
# Test 1: Scaling DN to SR and Fill exclusion
# ---------------------------------------------------------------------------

def test_scale_dn_to_sr_and_fill_exclusion(scaling_fixture: dict):
    """Verify that DN=10000 scales to 0.075 and DN=0 (Fill) does not become -0.2."""
    data = scaling_fixture["data"]
    scale = data["scale_factor"]
    offset = data["offset"]

    # 1. Normal valid pixel
    dn_valid = np.array([[10000]], dtype=np.uint16)
    qa_pixel_valid = np.array([[0]], dtype=np.uint16)
    sr, valid = mask_and_scale_surface_reflectance(
        dn=dn_valid,
        qa_pixel=qa_pixel_valid,
        sensor="LANDSAT_5",
        scale=scale,
        offset=offset,
        nodata_val=-9999.0,
    )
    assert valid[0, 0] == 1
    assert math.isclose(sr[0, 0], 0.075, rel_tol=1e-5)

    # 2. Fill pixel (DN=0, QA bit 0 = 1)
    dn_fill = np.array([[0]], dtype=np.uint16)
    qa_pixel_fill = np.array([[1]], dtype=np.uint16)
    sr_fill, valid_fill = mask_and_scale_surface_reflectance(
        dn=dn_fill,
        qa_pixel=qa_pixel_fill,
        sensor="LANDSAT_5",
        scale=scale,
        offset=offset,
        nodata_val=-9999.0,
    )
    assert valid_fill[0, 0] == 0
    assert sr_fill[0, 0] == -9999.0
    # Crucial acceptance check: Fill must NOT be -0.2!
    assert not math.isclose(sr_fill[0, 0], -0.2, abs_tol=1e-5)


# ---------------------------------------------------------------------------
# Test 2: Sensor band mapping
# ---------------------------------------------------------------------------

def test_sensor_band_mapping():
    """Verify Landsat 5 TM and Landsat 8 OLI band mapping to standard order."""
    from rs_urban.preprocess import get_sensor_band_files

    l5_bands = [1, 2, 3, 4, 5, 7]
    l8_bands = [2, 3, 4, 5, 6, 7]
    standard_order = ["blue", "green", "red", "nir", "swir1", "swir2"]

    # Landsat 5 mapping
    l5_map = get_sensor_band_files("LANDSAT_5", l5_bands, standard_order)
    assert l5_map == {
        "blue": "SR_B1",
        "green": "SR_B2",
        "red": "SR_B3",
        "nir": "SR_B4",
        "swir1": "SR_B5",
        "swir2": "SR_B7",
    }

    # Landsat 8 mapping
    l8_map = get_sensor_band_files("LANDSAT_8", l8_bands, standard_order)
    assert l8_map == {
        "blue": "SR_B2",
        "green": "SR_B3",
        "red": "SR_B4",
        "nir": "SR_B5",
        "swir1": "SR_B6",
        "swir2": "SR_B7",
    }


# ---------------------------------------------------------------------------
# Test 3: QA_PIXEL bit masking differences (water, cloud, cirrus)
# ---------------------------------------------------------------------------

def test_qa_pixel_masking_rules():
    """Verify water retained, cloud excluded, cirrus handled per sensor."""
    # Pixel 0: Clear (qa = 0) -> valid
    # Pixel 1: Fill (bit 0 = 1) -> invalid
    # Pixel 2: Dilated cloud (bit 1 = 2) -> invalid
    # Pixel 3: Cirrus (bit 2 = 4) -> invalid for L8, valid for L5
    # Pixel 4: Cloud (bit 3 = 8) -> invalid
    # Pixel 5: Cloud shadow (bit 4 = 16) -> invalid
    # Pixel 6: Snow (bit 5 = 32) -> invalid
    # Pixel 7: Water (bit 7 = 128) -> VALID (water must be retained!)
    qa = np.array([0, 1, 2, 4, 8, 16, 32, 128], dtype=np.uint16)

    # Landsat 5: bits 0, 1, 3, 4, 5 excluded. Bit 2 (cirrus) unused in TM. Bit 7 retained.
    valid_l5 = mask_qa_pixel(qa, sensor="LANDSAT_5")
    assert valid_l5[0] == True    # clear
    assert valid_l5[1] == False   # fill
    assert valid_l5[2] == False   # dilated cloud
    assert valid_l5[3] == True    # bit 2 is unused in L5, not excluded
    assert valid_l5[4] == False   # cloud
    assert valid_l5[5] == False   # cloud shadow
    assert valid_l5[6] == False   # snow
    assert valid_l5[7] == True    # water retained!

    # Landsat 8: bits 0, 1, 2, 3, 4, 5 excluded. Bit 7 retained.
    valid_l8 = mask_qa_pixel(qa, sensor="LANDSAT_8")
    assert valid_l8[0] == True    # clear
    assert valid_l8[1] == False   # fill
    assert valid_l8[2] == False   # dilated cloud
    assert valid_l8[3] == False   # cirrus excluded for L8
    assert valid_l8[4] == False   # cloud
    assert valid_l8[5] == False   # cloud shadow
    assert valid_l8[6] == False   # snow
    assert valid_l8[7] == True    # water retained!


# ---------------------------------------------------------------------------
# Test 4: Grid snapping and dimensions
# ---------------------------------------------------------------------------

def test_grid_snapping_and_specs():
    """Verify 30m snapping (floor xmin/ymin, ceil xmax/ymax) and 15m doubling."""
    raw_bounds = (500012.3, 3380015.6, 500098.2, 3380105.1)
    grid_30 = compute_grid_specs(raw_bounds, resolution=30, crs="EPSG:32648")

    assert grid_30["crs"] == "EPSG:32648"
    assert grid_30["resolution"] == [30, 30]
    assert grid_30["bounds"] == [500010.0, 3380010.0, 500100.0, 3380130.0]
    assert grid_30["width"] == 3    # (500100 - 500010) / 30 = 90 / 30 = 3
    assert grid_30["height"] == 4   # (3380130 - 3380010) / 30 = 120 / 30 = 4
    assert grid_30["transform"] == [500010.0, 30.0, 0.0, 3380130.0, 0.0, -30.0]

    # 15m grid specs
    grid_15 = compute_grid_specs(raw_bounds, resolution=15, crs="EPSG:32648", bounds_snap_resolution=30)
    assert grid_15["bounds"] == grid_30["bounds"]
    assert grid_15["width"] == grid_30["width"] * 2   # 6
    assert grid_15["height"] == grid_30["height"] * 2 # 8
    assert grid_15["transform"] == [500010.0, 15.0, 0.0, 3380130.0, 0.0, -15.0]


# ---------------------------------------------------------------------------
# Test 5: MTL Parsing and Strict Validation
# ---------------------------------------------------------------------------

def test_mtl_parsing_and_validation(tmp_path: Path):
    """Verify parsing MTL key-values and strict failure on metadata mismatch."""
    mtl_content = """GROUP = L1_METADATA_FILE
  GROUP = METADATA_FILE_INFO
    ORIGIN = "Image courtesy of the U.S. Geological Survey"
    LANDSAT_PRODUCT_ID = "LC08_L2SP_129039_20210205_20210308_02_T1"
    PROCESSING_LEVEL = "L2SP"
  END_GROUP = METADATA_FILE_INFO
  GROUP = IMAGE_ATTRIBUTES
    SPACECRAFT_ID = "LANDSAT_8"
    SENSOR_ID = "OLI_TIRS"
    DATE_ACQUIRED = 2021-02-05
    SUN_ELEVATION = 36.85
  END_GROUP = IMAGE_ATTRIBUTES
  GROUP = LEVEL2_SURFACE_REFLECTANCE_PARAMETERS
    REFLECTANCE_MULT_BAND_1 = 2.75e-05
    REFLECTANCE_ADD_BAND_1 = -0.2
  END_GROUP = LEVEL2_SURFACE_REFLECTANCE_PARAMETERS
END_GROUP = L1_METADATA_FILE
END
"""
    mtl_path = tmp_path / "test_MTL.txt"
    mtl_path.write_text(mtl_content, encoding="utf-8")

    meta = parse_mtl_metadata(mtl_path)
    assert meta["SPACECRAFT_ID"] == "LANDSAT_8"
    assert meta["DATE_ACQUIRED"] == "2021-02-05"
    assert float(meta["SUN_ELEVATION"]) == 36.85

    # Valid check passes
    validate_scene_metadata(
        catalog_entry={
            "year": 2021,
            "sensor": "LANDSAT_8",
            "acquisition_date": "2021-02-05",
            "product_id": "LC08_L2SP_129039_20210205_20210308_02_T1",
        },
        mtl_meta=meta,
    )

    # Sensor mismatch raises ValueError with exact field name
    with pytest.raises(ValueError, match="sensor mismatch"):
        validate_scene_metadata(
            catalog_entry={
                "year": 2021,
                "sensor": "LANDSAT_5",  # Mismatched!
                "acquisition_date": "2021-02-05",
                "product_id": "LC08_L2SP_129039_20210205_20210308_02_T1",
            },
            mtl_meta=meta,
        )

    # Date mismatch raises ValueError with exact field name
    with pytest.raises(ValueError, match="acquisition_date mismatch"):
        validate_scene_metadata(
            catalog_entry={
                "year": 2021,
                "sensor": "LANDSAT_8",
                "acquisition_date": "2021-02-06",  # Mismatched!
                "product_id": "LC08_L2SP_129039_20210205_20210308_02_T1",
            },
            mtl_meta=meta,
        )


# ---------------------------------------------------------------------------
# Test 6: TOA conversion for Level-1 bands
# ---------------------------------------------------------------------------

def test_convert_dn_to_toa():
    """Verify Level-1 TOA formula: TOA = (M_rho * DN + A_rho) / sin(sun_elevation)."""
    dn = np.array([20000], dtype=np.uint16)
    m_rho = 2.0e-05
    a_rho = -0.1
    sun_elev_deg = 30.0  # sin(30 deg) = 0.5

    toa = convert_dn_to_toa(dn, mult=m_rho, add=a_rho, sun_elevation_deg=sun_elev_deg, nodata_val=-9999.0)
    # Expected numerator = 20000 * 0.00002 - 0.1 = 0.4 - 0.1 = 0.3
    # Denominator = sin(radians(30)) = 0.5
    # Expected TOA = 0.3 / 0.5 = 0.6
    assert math.isclose(toa[0], 0.6, rel_tol=1e-5)

    # DN=0 (Fill) must return nodata_val (-9999.0)
    dn_fill = np.array([0], dtype=np.uint16)
    toa_fill = convert_dn_to_toa(dn_fill, mult=m_rho, add=a_rho, sun_elevation_deg=sun_elev_deg, nodata_val=-9999.0)
    assert toa_fill[0] == -9999.0


# ---------------------------------------------------------------------------
# Test 7: Prepare Boundaries, Grids, and AOI Mask
# ---------------------------------------------------------------------------

def test_prepare_boundaries_and_grids(tmp_path: Path):
    """Verify boundary processing, layer schema, grid exports, and aoi_30m mask."""
    # Create mock environment
    root = tmp_path / "project"
    data = root / "data"
    outputs = root / "outputs"
    reports = root / "reports"
    scratch = root / "scratch"

    boundaries_catalog_dir = data / "catalog"
    boundaries_catalog_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy raw boundary files
    raw_bnd_dir = data / "raw" / "boundaries"
    raw_bnd_dir.mkdir(parents=True, exist_ok=True)

    # 1 county polygon (Xindu)
    poly_county = box(500000, 3380000, 500120, 3380120)
    gdf_county = gpd.GeoDataFrame(
        [{"district_code": "510114", "district_name": "新都区", "geometry": poly_county}],
        crs="EPSG:32648",
    )
    county_shp = raw_bnd_dir / "county_2021.shp"
    gdf_county.to_file(county_shp)

    # 9 township polygons
    township_records = []
    for i in range(9):
        # 3x3 layout
        r = i // 3
        c = i % 3
        p = box(500000 + c * 40, 3380000 + r * 40, 500000 + (c + 1) * 40, 3380000 + (r + 1) * 40)
        u_type = "street" if i < 7 else "town"
        township_records.append({
            "code": f"51011400{i+1}",
            "township_name": f"街镇_{i+1}",
            "type_code": u_type,
            "geometry": p,
        })
    gdf_townships = gpd.GeoDataFrame(township_records, crs="EPSG:32648")
    townships_shp = raw_bnd_dir / "townships_2021.shp"
    gdf_townships.to_file(townships_shp)

    # Register in boundaries.csv
    bnd_csv = boundaries_catalog_dir / "boundaries.csv"
    bnd_csv.write_text(
        "dataset_id,reference_year,admin_level,file_path,layer_name,source_crs,source_url,acquired_at,license_note,verification_status\n"
        f"county_2021,2021,county,data/raw/boundaries/county_2021.shp,county_2021,EPSG:32648,http://example.com,2026-10-15,test,verified\n"
        f"townships_2021,2021,township,data/raw/boundaries/townships_2021.shp,townships_2021,EPSG:32648,http://example.com,2026-10-15,test,verified\n",
        encoding="utf-8",
    )

    ctx = ProjectContext(
        root=root,
        data=data,
        outputs=outputs,
        reports=reports,
        scratch=scratch,
        config={
            "target_crs": "EPSG:32648",
            "boundary_reference_year": 2021,
            "expected_township_count": 9,
            "analysis_resolution_m": 30,
            "display_resolution_m": 15,
        },
    )

    gpkg_path = prepare_boundaries(ctx)
    assert gpkg_path.exists()
    assert gpkg_path == data / "processed" / "boundaries" / "xindu_2021.gpkg"

    # Verify GPKG layers
    gdf_study = gpd.read_file(gpkg_path, layer="study_area")
    assert "area_id" in gdf_study.columns
    assert "name" in gdf_study.columns
    assert "reference_year" in gdf_study.columns
    assert len(gdf_study) == 1

    gdf_towns = gpd.read_file(gpkg_path, layer="townships")
    assert "unit_id" in gdf_towns.columns
    assert "name" in gdf_towns.columns
    assert "unit_type" in gdf_towns.columns
    assert "reference_year" in gdf_towns.columns
    assert len(gdf_towns) == 9
    assert all(gdf_towns["unit_type"].isin(["street", "town"]))

    # Verify grid_30m.json and grid_15m.json
    grid_30_path = data / "processed" / "grids" / "grid_30m.json"
    grid_15_path = data / "processed" / "grids" / "grid_15m.json"
    assert grid_30_path.exists()
    assert grid_15_path.exists()

    with open(grid_30_path, "r", encoding="utf-8") as f:
        g30 = json.load(f)
    with open(grid_15_path, "r", encoding="utf-8") as f:
        g15 = json.load(f)

    assert g30["crs"] == "EPSG:32648"
    assert g15["width"] == g30["width"] * 2
    assert g15["height"] == g30["height"] * 2

    # Verify aoi_30m.tif
    aoi_tif_path = data / "processed" / "grids" / "aoi_30m.tif"
    assert aoi_tif_path.exists()
    with rasterio.open(aoi_tif_path) as src:
        assert src.dtypes[0] == "uint8"
        assert src.shape == (g30["height"], g30["width"])
        arr = src.read(1)
        assert np.all(np.isin(arr, [0, 1]))
        assert np.sum(arr == 1) > 0


# ---------------------------------------------------------------------------
# Test 8: preprocess_year end-to-end
# ---------------------------------------------------------------------------

def test_preprocess_year_pipeline(tmp_path: Path):
    """Verify preprocess_year generates 6-band sr_30m, valid_sr_30m, and copies to outputs."""
    root = tmp_path / "project"
    data = root / "data"
    outputs = root / "outputs"
    reports = root / "reports"
    scratch = root / "scratch"

    year = 1992
    scene_dir = data / "raw" / "landsat" / str(year) / "level2" / "LT05_L2SP_129039_19920816_02_T1"
    scene_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy MTL
    mtl_file = scene_dir / "LT05_L2SP_129039_19920816_02_T1_MTL.txt"
    mtl_file.write_text("""GROUP = L1_METADATA_FILE
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

    # Create 3x3 mock bands in EPSG:32648
    transform = Affine(30.0, 0.0, 500000.0, 0.0, -30.0, 3380090.0)
    crs = "EPSG:32648"
    width, height = 3, 3

    # Generate band files: B1..B5, B7
    l5_band_names = ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"]
    for bname in l5_band_names:
        bpath = scene_dir / f"LT05_L2SP_129039_19920816_02_T1_{bname}.TIF"
        # DN=10000 everywhere
        arr = np.full((height, width), 10000, dtype=np.uint16)
        with rasterio.open(
            bpath, "w", driver="GTiff", height=height, width=width, count=1,
            dtype="uint16", crs=crs, transform=transform, nodata=0,
        ) as dst:
            dst.write(arr, 1)

    # QA_PIXEL: center pixel is cloud (bit 3 = 8), others clear (0)
    qa_path = scene_dir / "LT05_L2SP_129039_19920816_02_T1_QA_PIXEL.TIF"
    qa_arr = np.zeros((height, width), dtype=np.uint16)
    qa_arr[1, 1] = 8
    with rasterio.open(
        qa_path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint16", crs=crs, transform=transform, nodata=1,
    ) as dst:
        dst.write(qa_arr, 1)

    # QA_RADSAT: 0 (no saturation)
    radsat_path = scene_dir / "LT05_L2SP_129039_19920816_02_T1_QA_RADSAT.TIF"
    radsat_arr = np.zeros((height, width), dtype=np.uint16)
    with rasterio.open(
        radsat_path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint16", crs=crs, transform=transform,
    ) as dst:
        dst.write(radsat_arr, 1)

    # Register in scenes.csv
    cat_dir = data / "catalog"
    cat_dir.mkdir(parents=True, exist_ok=True)
    (cat_dir / "scenes.csv").write_text(
        "year,sensor,processing_level,product_id,acquisition_date,wrs_path,wrs_row,scene_dir,mtl_path,paired_product_id,source_url,downloaded_at,selection_status\n"
        f"1992,LANDSAT_5,L2SP,LT05_L2SP_129039_19920816_02_T1,1992-08-16,129,039,{scene_dir.relative_to(data)},{mtl_file.relative_to(data)},,,2026-10-15,selected\n",
        encoding="utf-8",
    )

    # Mock grid and AOI
    grids_dir = data / "processed" / "grids"
    grids_dir.mkdir(parents=True, exist_ok=True)
    grid_dict = {
        "schema_version": 1,
        "crs": "EPSG:32648",
        "bounds": [500000.0, 3380000.0, 500090.0, 3380090.0],
        "resolution": [30, 30],
        "width": 3,
        "height": 3,
        "transform": [500000.0, 30.0, 0.0, 3380090.0, 0.0, -30.0],
    }
    (grids_dir / "grid_30m.json").write_text(json.dumps(grid_dict), encoding="utf-8")

    # aoi_30m.tif: all 1
    with rasterio.open(
        grids_dir / "aoi_30m.tif", "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint8", crs=crs, transform=transform,
    ) as dst:
        dst.write(np.ones((height, width), dtype=np.uint8), 1)

    # Standard boundary GPKG placeholder
    bnd_proc_dir = data / "processed" / "boundaries"
    bnd_proc_dir.mkdir(parents=True, exist_ok=True)
    bnd_gpkg = bnd_proc_dir / "xindu_2021.gpkg"
    gdf_dummy = gpd.GeoDataFrame([{"area_id": "510114", "name": "新都区", "reference_year": 2021, "geometry": box(500000, 3380000, 500090, 3380090)}], crs=crs)
    gdf_dummy.to_file(bnd_gpkg, layer="study_area")

    ctx = ProjectContext(
        root=root,
        data=data,
        outputs=outputs,
        reports=reports,
        scratch=scratch,
        config={
            "target_crs": "EPSG:32648",
            "float_nodata": -9999.0,
            "mask_nodata": 255,
            "imagery": {
                "surface_reflectance_scale": 0.0000275,
                "surface_reflectance_offset": -0.2,
                "band_order": ["blue", "green", "red", "nir", "swir1", "swir2"],
                "landsat5_bands": [1, 2, 3, 4, 5, 7],
                "landsat8_bands": [2, 3, 4, 5, 6, 7],
                "reflectance_resampling": "bilinear",
                "categorical_resampling": "nearest",
            },
        },
    )

    prepared: PreparedData = preprocess_year(ctx, year=1992)
    assert prepared.year == 1992
    assert prepared.sr.exists()
    assert prepared.valid_sr.exists()

    # Verify SR raster properties
    with rasterio.open(prepared.sr) as src:
        assert src.count == 6
        assert src.dtypes[0] == "float32"
        assert src.nodata == -9999.0
        assert src.descriptions == ("blue", "green", "red", "nir", "swir1", "swir2")
        arr = src.read()
        # Pixel (1, 1) was cloud, must be -9999.0 across all bands
        assert np.all(arr[:, 1, 1] == -9999.0)
        # Clear pixel (0, 0) must be 0.075
        assert np.allclose(arr[:, 0, 0], 0.075, atol=1e-4)

    # Verify valid_sr raster
    with rasterio.open(prepared.valid_sr) as src:
        assert src.dtypes[0] == "uint8"
        assert src.nodata == 255
        varr = src.read(1)
        assert varr[1, 1] == 0   # cloud in AOI -> 0 (invalid inside AOI)
        assert varr[0, 0] == 1   # valid inside AOI -> 1

    # Verify published output copy
    pub_sr = outputs / "rasters" / "xindu_1992_sr_30m.tif"
    assert pub_sr.exists()
    assert pub_sr.stat().st_size == prepared.sr.stat().st_size


# ---------------------------------------------------------------------------
# Test 9: Pansharpening 2021
# ---------------------------------------------------------------------------

def test_pansharpen_2021_pipeline(tmp_path: Path):
    """Verify pansharpening creates 15m 3-band Float32 GeoTIFF and report."""
    root = tmp_path / "project"
    data = root / "data"
    outputs = root / "outputs"
    reports = root / "reports"
    scratch = root / "scratch"

    scene_dir = data / "raw" / "landsat" / "2021" / "level1" / "LC08_L1TP_129039_20210205_02_T1"
    scene_dir.mkdir(parents=True, exist_ok=True)

    mtl_file = scene_dir / "LC08_L1TP_129039_20210205_02_T1_MTL.txt"
    mtl_file.write_text("""GROUP = L1_METADATA_FILE
  GROUP = METADATA_FILE_INFO
    LANDSAT_PRODUCT_ID = "LC08_L1TP_129039_20210205_02_T1"
    PROCESSING_LEVEL = "L1TP"
  END_GROUP = METADATA_FILE_INFO
  GROUP = IMAGE_ATTRIBUTES
    SPACECRAFT_ID = "LANDSAT_8"
    DATE_ACQUIRED = 2021-02-05
    SUN_ELEVATION = 30.0
  END_GROUP = IMAGE_ATTRIBUTES
  GROUP = LEVEL1_RADIANCE_SCALING
    REFLECTANCE_MULT_BAND_2 = 2.0e-05
    REFLECTANCE_ADD_BAND_2 = -0.1
    REFLECTANCE_MULT_BAND_3 = 2.0e-05
    REFLECTANCE_ADD_BAND_3 = -0.1
    REFLECTANCE_MULT_BAND_4 = 2.0e-05
    REFLECTANCE_ADD_BAND_4 = -0.1
    REFLECTANCE_MULT_BAND_8 = 2.0e-05
    REFLECTANCE_ADD_BAND_8 = -0.1
  END_GROUP = LEVEL1_RADIANCE_SCALING
END_GROUP = L1_METADATA_FILE
END
""", encoding="utf-8")

    # 30m grid specs (3x3)
    transform_30 = Affine(30.0, 0.0, 500000.0, 0.0, -30.0, 3380090.0)
    transform_15 = Affine(15.0, 0.0, 500000.0, 0.0, -15.0, 3380090.0)
    crs = "EPSG:32648"

    # RGB bands: 30m (3x3)
    for b in [2, 3, 4]:
        bpath = scene_dir / f"LC08_L1TP_129039_20210205_02_T1_B{b}.TIF"
        arr = np.full((3, 3), 20000, dtype=np.uint16)
        with rasterio.open(bpath, "w", driver="GTiff", height=3, width=3, count=1, dtype="uint16", crs=crs, transform=transform_30, nodata=0) as dst:
            dst.write(arr, 1)

    # Pan band (B8): 15m (6x6)
    pan_path = scene_dir / "LC08_L1TP_129039_20210205_02_T1_B8.TIF"
    arr_pan = np.full((6, 6), 20000, dtype=np.uint16)
    with rasterio.open(pan_path, "w", driver="GTiff", height=6, width=6, count=1, dtype="uint16", crs=crs, transform=transform_15, nodata=0) as dst:
        dst.write(arr_pan, 1)

    # QA bands
    qa_path = scene_dir / "LC08_L1TP_129039_20210205_02_T1_QA_PIXEL.TIF"
    with rasterio.open(qa_path, "w", driver="GTiff", height=3, width=3, count=1, dtype="uint16", crs=crs, transform=transform_30) as dst:
        dst.write(np.zeros((3, 3), dtype=np.uint16), 1)

    radsat_path = scene_dir / "LC08_L1TP_129039_20210205_02_T1_QA_RADSAT.TIF"
    with rasterio.open(radsat_path, "w", driver="GTiff", height=3, width=3, count=1, dtype="uint16", crs=crs, transform=transform_30) as dst:
        dst.write(np.zeros((3, 3), dtype=np.uint16), 1)

    # Register in scenes.csv
    cat_dir = data / "catalog"
    cat_dir.mkdir(parents=True, exist_ok=True)
    (cat_dir / "scenes.csv").write_text(
        "year,sensor,processing_level,product_id,acquisition_date,wrs_path,wrs_row,scene_dir,mtl_path,paired_product_id,source_url,downloaded_at,selection_status\n"
        f"2021,LANDSAT_8,L1TP,LC08_L1TP_129039_20210205_02_T1,2021-02-05,129,039,{scene_dir.relative_to(data)},{mtl_file.relative_to(data)},,,2026-10-15,selected\n",
        encoding="utf-8",
    )

    # Grids
    grids_dir = data / "processed" / "grids"
    grids_dir.mkdir(parents=True, exist_ok=True)
    grid_15_dict = {
        "schema_version": 1,
        "crs": "EPSG:32648",
        "bounds": [500000.0, 3380000.0, 500090.0, 3380090.0],
        "resolution": [15, 15],
        "width": 6,
        "height": 6,
        "transform": [500000.0, 15.0, 0.0, 3380090.0, 0.0, -15.0],
    }
    (grids_dir / "grid_15m.json").write_text(json.dumps(grid_15_dict), encoding="utf-8")

    ctx = ProjectContext(
        root=root,
        data=data,
        outputs=outputs,
        reports=reports,
        scratch=scratch,
        config={
            "target_crs": "EPSG:32648",
            "float_nodata": -9999.0,
            "imagery": {
                "pan_rgb_bands": [4, 3, 2],
                "pan_band": 8,
            },
        },
    )

    pan_res = pansharpen_2021(ctx)
    assert pan_res.exists()

    with rasterio.open(pan_res) as src:
        assert src.count == 3
        assert src.dtypes[0] == "float32"
        assert src.width == 6
        assert src.height == 6
        assert src.nodata == -9999.0

    # Verify report
    report_path = reports / "data" / "pansharpen_2021.json"
    assert report_path.exists()
    with open(report_path, "r", encoding="utf-8") as f:
        rep = json.load(f)
    assert rep["radiometry"] == "TOA"
    assert rep["purpose"] == "visualization"


def test_cli_preprocess_invocation(tmp_path: Path):
    """Verify CLI error on missing year for surface step and parsing."""
    import subprocess
    import sys

    # 1. Missing year for surface step
    cmd = [sys.executable, "src/01_preprocess.py", "--step", "surface"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "--year is required when --step is 'surface'" in res.stderr

    # 2. Help message
    cmd_help = [sys.executable, "src/01_preprocess.py", "--help"]
    res_help = subprocess.run(cmd_help, capture_output=True, text=True)
    assert res_help.returncode == 0
    assert "--step" in res_help.stdout

