"""Remote sensing preprocessing and boundary preparation module (P1-A).

Implements:
1. prepare_boundaries: Extracts county and township boundaries, creates standard GPKG,
   computes 30m and 15m grids, and generates the aoi_30m.tif binary mask.
2. preprocess_year: Reads USGS Landsat Level-2 scenes, applies QA masking (clouds/shadows/snow),
   DN to surface reflectance scaling (protecting Fill from becoming -0.2), reprojects to the
   standard 30m grid, and creates sr_30m.tif and valid_sr_30m.tif.
3. pansharpen_2021: Converts 2021 Level-1 RGB and Pan bands to TOA reflectance, performs
   15m pansharpening, and outputs pan_rgb_15m.tif strictly labeled for visualization.
"""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
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
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.warp import reproject
from shapely.geometry import box

from rs_urban.contracts import PreparedData, ProjectContext


# ---------------------------------------------------------------------------
# 1. Grid computation and snapping
# ---------------------------------------------------------------------------

def compute_grid_specs(
    raw_bounds: tuple[float, float, float, float] | list[float],
    resolution: float = 30.0,
    crs: str = "EPSG:32648",
    bounds_snap_resolution: float | None = None,
) -> dict[str, Any]:
    """Compute standard snapped grid specifications according to Contract Section 1.

    Bounds are snapped outward (xmin/ymin floor, xmax/ymax ceil) based on bounds_snap_resolution
    (defaulting to resolution, typically 30m).
    Transform follows GDAL 6-element order: [xmin, res, 0, ymax, 0, -res].
    """
    snap_res = float(bounds_snap_resolution if bounds_snap_resolution is not None else resolution)
    res = float(resolution)

    xmin, ymin, xmax, ymax = raw_bounds
    xmin_snap = math.floor(xmin / snap_res) * snap_res
    ymin_snap = math.floor(ymin / snap_res) * snap_res
    xmax_snap = math.ceil(xmax / snap_res) * snap_res
    ymax_snap = math.ceil(ymax / snap_res) * snap_res

    width = int(round((xmax_snap - xmin_snap) / res))
    height = int(round((ymax_snap - ymin_snap) / res))
    transform = [xmin_snap, res, 0.0, ymax_snap, 0.0, -res]

    return {
        "schema_version": 1,
        "crs": crs,
        "bounds": [xmin_snap, ymin_snap, xmax_snap, ymax_snap],
        "resolution": [res, res],
        "width": width,
        "height": height,
        "transform": transform,
    }


# ---------------------------------------------------------------------------
# 2. MTL and Metadata Parsing
# ---------------------------------------------------------------------------

def parse_mtl_metadata(mtl_path: Path) -> dict[str, str]:
    """Parse a USGS Landsat MTL text file into a flat key-value dictionary."""
    if not mtl_path.exists():
        raise FileNotFoundError(f"MTL file does not exist: {mtl_path}")

    meta: dict[str, str] = {}
    with open(mtl_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line in ("END", "GROUP = L1_METADATA_FILE", "END_GROUP = L1_METADATA_FILE"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                key = k.strip()
                val = v.strip().strip('"').strip("'")
                if key not in meta:
                    meta[key] = val
    return meta


def validate_scene_metadata(catalog_entry: dict[str, Any], mtl_meta: dict[str, str]) -> None:
    """Strictly validate scene catalog registration against MTL metadata.

    Fails immediately upon any discrepancy with an explicit error naming the specific field.
    No automatic replacement of sensor or date.
    """
    cat_sensor = catalog_entry.get("sensor")
    mtl_sensor = mtl_meta.get("SPACECRAFT_ID")
    if cat_sensor and mtl_sensor and cat_sensor.upper() != mtl_sensor.upper():
        raise ValueError(
            f"Metadata validation error: sensor mismatch (catalog '{cat_sensor}' != MTL '{mtl_sensor}')"
        )

    cat_date = catalog_entry.get("acquisition_date")
    mtl_date = mtl_meta.get("DATE_ACQUIRED")
    if cat_date and mtl_date and cat_date != mtl_date:
        raise ValueError(
            f"Metadata validation error: acquisition_date mismatch (catalog '{cat_date}' != MTL '{mtl_date}')"
        )

    cat_prod_id = catalog_entry.get("product_id")
    mtl_prod_id = mtl_meta.get("LANDSAT_PRODUCT_ID")
    if cat_prod_id and mtl_prod_id and cat_prod_id != mtl_prod_id:
        raise ValueError(
            f"Metadata validation error: product_id mismatch (catalog '{cat_prod_id}' != MTL '{mtl_prod_id}')"
        )

    cat_level = catalog_entry.get("processing_level")
    mtl_level = mtl_meta.get("PROCESSING_LEVEL")
    if cat_level and mtl_level and cat_level != mtl_level:
        raise ValueError(
            f"Metadata validation error: processing_level mismatch (catalog '{cat_level}' != MTL '{mtl_level}')"
        )


def get_sensor_band_files(sensor: str, bands: list[int], standard_order: list[str]) -> dict[str, str]:
    """Map standard band names to USGS SR band file prefixes based on sensor."""
    mapping: dict[str, str] = {}
    for name, band_num in zip(standard_order, bands):
        mapping[name] = f"SR_B{band_num}"
    return mapping


# ---------------------------------------------------------------------------
# 3. QA Masking and Radiometric Scaling
# ---------------------------------------------------------------------------

def mask_qa_pixel(qa: np.ndarray, sensor: str) -> np.ndarray:
    """Evaluate USGS Collection 2 QA_PIXEL bits to determine pixel validity.

    Rules from Contract Section 2:
    - Exclude Fill (bit 0), Dilated Cloud (bit 1), Cloud (bit 3), Cloud Shadow (bit 4), Snow (bit 5).
    - For Landsat 8/9: also exclude Cirrus (bit 2).
    - For Landsat 5 (TM): bit 2 is unused, do not exclude.
    - Water (bit 7) is retained (NOT excluded).
    - Clear (bit 6) is not required to be 1.
    """
    sensor_clean = sensor.upper()
    if sensor_clean in ("LANDSAT_8", "LANDSAT_9", "OLI"):
        # Bits 0, 1, 2, 3, 4, 5
        exclude_bits = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5)
    else:
        # Landsat 5 / TM: bits 0, 1, 3, 4, 5
        exclude_bits = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4) | (1 << 5)

    return (qa & exclude_bits) == 0


def mask_qa_radsat(radsat: np.ndarray, sensor: str) -> np.ndarray:
    """Evaluate USGS QA_RADSAT saturation and artifact bits."""
    sensor_clean = sensor.upper()
    if sensor_clean in ("LANDSAT_8", "LANDSAT_9", "OLI"):
        # Bits 1..6: bands 2..7 saturation; Bit 11: terrain occlusion
        exclude_mask = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 6) | (1 << 11)
    else:
        # Landsat 5 TM: Bits 0..4, 6 for bands 1..5, 7; Bit 7 for dropped pixel
        exclude_mask = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 6) | (1 << 7)

    return (radsat & exclude_mask) == 0


def mask_and_scale_surface_reflectance(
    dn: np.ndarray,
    qa_pixel: np.ndarray,
    sensor: str,
    scale: float = 0.0000275,
    offset: float = -0.2,
    nodata_val: float = -9999.0,
    qa_radsat: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Scale raw DN to surface reflectance while protecting Fill and QA invalid pixels.

    Returns:
        sr: float32 surface reflectance array with nodata_val for invalid pixels.
        valid_mask: uint8 array (1 = valid, 0 = invalid).
    """
    # Fill DN in Landsat C2 is 0 or QA bit 0 == 1
    is_fill = (dn == 0) | ((qa_pixel & 1) != 0)
    qa_valid = mask_qa_pixel(qa_pixel, sensor)

    valid_mask = (~is_fill) & qa_valid
    if qa_radsat is not None:
        radsat_valid = mask_qa_radsat(qa_radsat, sensor)
        valid_mask = valid_mask & radsat_valid

    # Scale valid pixels; Fill DN=0 must NOT become -0.2
    sr = np.where(valid_mask, dn.astype(np.float32) * scale + offset, nodata_val)
    return sr.astype(np.float32), valid_mask.astype(np.uint8)


def convert_dn_to_toa(
    dn: np.ndarray,
    mult: float,
    add: float,
    sun_elevation_deg: float,
    nodata_val: float = -9999.0,
) -> np.ndarray:
    """Convert Landsat Level-1 DN to Top of Atmosphere (TOA) reflectance."""
    sin_elev = math.sin(math.radians(sun_elevation_deg))
    if sin_elev <= 0:
        raise ValueError(f"Invalid sun elevation angle: {sun_elevation_deg} deg")

    is_fill = dn == 0
    toa = np.where(
        is_fill,
        nodata_val,
        (dn.astype(np.float32) * mult + add) / sin_elev,
    )
    return toa.astype(np.float32)


# ---------------------------------------------------------------------------
# 4. Step: prepare_boundaries
# ---------------------------------------------------------------------------

def prepare_boundaries(ctx: ProjectContext) -> Path:
    """Read boundary registration, output standard GPKG, grids, and AOI mask.

    Returns path to data/processed/boundaries/xindu_2021.gpkg.
    """
    boundaries_csv = ctx.data / "catalog" / "boundaries.csv"
    if not boundaries_csv.exists():
        raise FileNotFoundError(f"Boundaries catalog not found: {boundaries_csv}")

    target_crs = ctx.config.get("target_crs", "EPSG:32648")
    ref_year = ctx.config.get("boundary_reference_year", 2021)
    res_30 = float(ctx.config.get("analysis_resolution_m", 30))
    res_15 = float(ctx.config.get("display_resolution_m", 15))

    # Read registered boundaries
    county_row = None
    townships_row = None

    with open(boundaries_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            admin_lvl = row.get("admin_level", "").strip()
            verif = row.get("verification_status", "").strip()
            year_val = int(row.get("reference_year", ref_year))
            if admin_lvl == "county" and year_val == ref_year:
                if verif in ("verified", "candidate") or county_row is None:
                    county_row = row
            elif admin_lvl == "township" and year_val == ref_year:
                if verif in ("verified", "candidate") or townships_row is None:
                    townships_row = row

    if county_row is None:
        raise FileNotFoundError(
            f"No registered county boundary for year {ref_year} found in {boundaries_csv}"
        )
    if townships_row is None:
        raise FileNotFoundError(
            f"No registered townships boundary for year {ref_year} found in {boundaries_csv}"
        )

    county_path = ctx.data / county_row["file_path"].replace("data/", "", 1) if county_row["file_path"].startswith("data/") else ctx.data / county_row["file_path"]
    townships_path = ctx.data / townships_row["file_path"].replace("data/", "", 1) if townships_row["file_path"].startswith("data/") else ctx.data / townships_row["file_path"]

    if not county_path.exists():
        raise FileNotFoundError(f"County boundary file does not exist: {county_path}")
    if not townships_path.exists():
        raise FileNotFoundError(f"Townships boundary file does not exist: {townships_path}")

    # Read vectors with geopandas
    gdf_county = gpd.read_file(county_path, layer=county_row.get("layer_name") or None)
    gdf_townships = gpd.read_file(townships_path, layer=townships_row.get("layer_name") or None)

    if gdf_county.crs is None:
        gdf_county.set_crs(county_row.get("source_crs", target_crs), inplace=True)
    if gdf_county.crs.to_string() != target_crs:
        gdf_county = gdf_county.to_crs(target_crs)

    if gdf_townships.crs is None:
        gdf_townships.set_crs(townships_row.get("source_crs", target_crs), inplace=True)
    if gdf_townships.crs.to_string() != target_crs:
        gdf_townships = gdf_townships.to_crs(target_crs)

    # Standardize county schema: area_id, name, reference_year, geometry
    area_id_col = next((c for c in ["area_id", "district_code", "PAC", "code"] if c in gdf_county.columns), None)
    name_col = next((c for c in ["name", "district_name", "NAME", "NAME_CH"] if c in gdf_county.columns), None)

    std_county = gpd.GeoDataFrame({
        "area_id": gdf_county[area_id_col].astype(str) if area_id_col else "510114",
        "name": gdf_county[name_col].astype(str) if name_col else "新都区",
        "reference_year": int(ref_year),
        "geometry": gdf_county.geometry,
    }, crs=target_crs)

    # Standardize townships schema: unit_id, name, unit_type, reference_year, geometry
    t_id_col = next((c for c in ["unit_id", "code", "PAC", "township_code"] if c in gdf_townships.columns), None)
    t_name_col = next((c for c in ["name", "township_name", "NAME", "NAME_CH"] if c in gdf_townships.columns), None)
    t_type_col = next((c for c in ["unit_type", "type", "type_code", "T_TYPE"] if c in gdf_townships.columns), None)

    def determine_unit_type(val: Any, name_val: str) -> str:
        s = str(val).lower() if val is not None else ""
        if "street" in s or "街道" in str(name_val):
            return "street"
        return "town"

    unit_ids = []
    unit_names = []
    unit_types = []
    for idx, row in gdf_townships.iterrows():
        uid = str(row[t_id_col]) if t_id_col else f"{idx+1:02d}"
        uname = str(row[t_name_col]) if t_name_col else f"Unit_{idx+1}"
        utype = determine_unit_type(row[t_type_col] if t_type_col else None, uname)
        unit_ids.append(uid)
        unit_names.append(uname)
        unit_types.append(utype)

    std_townships = gpd.GeoDataFrame({
        "unit_id": unit_ids,
        "name": unit_names,
        "unit_type": unit_types,
        "reference_year": int(ref_year),
        "geometry": gdf_townships.geometry,
    }, crs=target_crs)

    # Save standard GPKG
    out_bnd_dir = ctx.data / "processed" / "boundaries"
    out_bnd_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = out_bnd_dir / f"xindu_{ref_year}.gpkg"

    if gpkg_path.exists():
        gpkg_path.unlink()

    std_county.to_file(gpkg_path, layer="study_area", driver="GPKG")
    std_townships.to_file(gpkg_path, layer="townships", driver="GPKG")

    # Compute standard 30m and 15m grids
    bounds = tuple(std_county.total_bounds)
    grid_30 = compute_grid_specs(bounds, resolution=res_30, crs=target_crs)
    grid_15 = compute_grid_specs(bounds, resolution=res_15, crs=target_crs, bounds_snap_resolution=res_30)

    out_grid_dir = ctx.data / "processed" / "grids"
    out_grid_dir.mkdir(parents=True, exist_ok=True)
    (out_grid_dir / "grid_30m.json").write_text(json.dumps(grid_30, indent=2), encoding="utf-8")
    (out_grid_dir / "grid_15m.json").write_text(json.dumps(grid_15, indent=2), encoding="utf-8")

    # Generate aoi_30m.tif
    width = grid_30["width"]
    height = grid_30["height"]
    transform_affine = Affine.from_gdal(*grid_30["transform"])

    # Rasterize county boundary (all_touched=True, 1 inside, 0 outside)
    shapes = [(geom, 1) for geom in std_county.geometry]
    aoi_arr = rasterize(
        shapes=shapes,
        out_shape=(height, width),
        transform=transform_affine,
        fill=0,
        default_value=1,
        all_touched=True,
        dtype=np.uint8,
    )

    aoi_path = out_grid_dir / "aoi_30m.tif"
    with rasterio.open(
        aoi_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=target_crs,
        transform=transform_affine,
        nodata=None,
    ) as dst:
        dst.write(aoi_arr, 1)

    return gpkg_path


# ---------------------------------------------------------------------------
# 5. Step: preprocess_year
# ---------------------------------------------------------------------------

def preprocess_year(ctx: ProjectContext, year: int) -> PreparedData:
    """Preprocess Landsat Level-2 surface reflectance imagery for a given year.

    Generates:
      - data/processed/{year}/sr_30m.tif (Float32, 6 bands, NoData=-9999.0)
      - data/processed/{year}/valid_sr_30m.tif (Byte, 1=valid, 0=invalid inside AOI, 255=outside AOI)
      - published copy in outputs/rasters/xindu_{year}_sr_30m.tif
      - reports/data/preprocess_{year}.json

    Returns PreparedData.
    """
    scenes_csv = ctx.data / "catalog" / "scenes.csv"
    if not scenes_csv.exists():
        raise FileNotFoundError(f"Scenes catalog not found: {scenes_csv}")

    # Find registered scene
    selected_scene = None
    with open(scenes_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row.get("year", 0)) == year:
                lvl = row.get("processing_level", "").upper()
                if lvl in ("L2SP", "L2SR"):
                    status = row.get("selection_status", "").lower()
                    if status == "selected" or selected_scene is None:
                        selected_scene = row

    if selected_scene is None:
        raise FileNotFoundError(f"No selected Level-2 scene found for year {year} in {scenes_csv}")

    scene_dir_rel = selected_scene["scene_dir"]
    mtl_path_rel = selected_scene["mtl_path"]

    scene_dir = ctx.data / (scene_dir_rel.replace("data/", "", 1) if scene_dir_rel.startswith("data/") else scene_dir_rel)
    mtl_path = ctx.data / (mtl_path_rel.replace("data/", "", 1) if mtl_path_rel.startswith("data/") else mtl_path_rel)

    if not scene_dir.exists():
        raise FileNotFoundError(f"Scene directory does not exist: {scene_dir}")
    if not mtl_path.exists():
        raise FileNotFoundError(f"MTL file does not exist: {mtl_path}")

    # Parse and validate MTL
    mtl_meta = parse_mtl_metadata(mtl_path)
    validate_scene_metadata(selected_scene, mtl_meta)

    # Load 30m grid and AOI mask
    grid_path = ctx.data / "processed" / "grids" / "grid_30m.json"
    aoi_path = ctx.data / "processed" / "grids" / "aoi_30m.tif"
    if not grid_path.exists() or not aoi_path.exists():
        raise FileNotFoundError("Grids and AOI mask must be prepared first via prepare_boundaries().")

    with open(grid_path, "r", encoding="utf-8") as f:
        grid_30 = json.load(f)

    target_crs = grid_30["crs"]
    target_width = grid_30["width"]
    target_height = grid_30["height"]
    target_transform = Affine.from_gdal(*grid_30["transform"])

    with rasterio.open(aoi_path) as aoi_src:
        aoi_mask = aoi_src.read(1)

    # Retrieve configuration parameters
    img_cfg = ctx.config.get("imagery", {})
    scale_factor = float(img_cfg.get("surface_reflectance_scale", 0.0000275))
    offset = float(img_cfg.get("surface_reflectance_offset", -0.2))
    band_order = img_cfg.get("band_order", ["blue", "green", "red", "nir", "swir1", "swir2"])
    nodata_float = float(ctx.config.get("float_nodata", -9999.0))
    mask_nodata = int(ctx.config.get("mask_nodata", 255))

    sensor = selected_scene["sensor"].upper()
    if sensor in ("LANDSAT_5", "TM"):
        bands_cfg = img_cfg.get("landsat5_bands", [1, 2, 3, 4, 5, 7])
    elif sensor in ("LANDSAT_8", "LANDSAT_9", "OLI"):
        bands_cfg = img_cfg.get("landsat8_bands", [2, 3, 4, 5, 6, 7])
    else:
        raise ValueError(f"Unsupported sensor in configuration: {sensor}")

    band_file_map = get_sensor_band_files(sensor, bands_cfg, band_order)

    # Find QA band files
    qa_pixel_file = next(scene_dir.glob("*_QA_PIXEL.TIF"), None) or next(scene_dir.glob("*_QA_PIXEL.tif"), None)
    if qa_pixel_file is None:
        raise FileNotFoundError(f"QA_PIXEL band not found in {scene_dir}")

    qa_radsat_file = next(scene_dir.glob("*_QA_RADSAT.TIF"), None) or next(scene_dir.glob("*_QA_RADSAT.tif"), None)

    # Read QA_PIXEL
    with rasterio.open(qa_pixel_file) as qa_src:
        qa_pixel_native = qa_src.read(1)
        qa_crs = qa_src.crs
        qa_transform = qa_src.transform

    qa_radsat_native = None
    if qa_radsat_file is not None and qa_radsat_file.exists():
        with rasterio.open(qa_radsat_file) as radsat_src:
            qa_radsat_native = radsat_src.read(1)

    # Calculate native valid mask
    is_fill_qa = (qa_pixel_native & 1) != 0
    valid_qa = mask_qa_pixel(qa_pixel_native, sensor)
    native_valid_mask = (~is_fill_qa) & valid_qa
    if qa_radsat_native is not None:
        native_valid_mask = native_valid_mask & mask_qa_radsat(qa_radsat_native, sensor)

    # Reproject valid mask to target grid using nearest neighbor
    reprojected_valid_mask = np.zeros((target_height, target_width), dtype=np.uint8)
    reproject(
        source=native_valid_mask.astype(np.uint8),
        destination=reprojected_valid_mask,
        src_transform=qa_transform,
        src_crs=qa_crs,
        dst_transform=target_transform,
        dst_crs=target_crs,
        resampling=Resampling.nearest,
    )

    # Process and reproject each continuous surface reflectance band
    sr_reprojected_bands: list[np.ndarray] = []

    for band_name in band_order:
        band_suffix = band_file_map[band_name]
        band_file = next(scene_dir.glob(f"*{band_suffix}.TIF"), None) or next(scene_dir.glob(f"*{band_suffix}.tif"), None)
        if band_file is None:
            raise FileNotFoundError(f"Band file for {band_name} ({band_suffix}) not found in {scene_dir}")

        with rasterio.open(band_file) as b_src:
            dn_native = b_src.read(1)
            b_crs = b_src.crs
            b_transform = b_src.transform

        # Scale on native grid with Fill protection
        scaled_sr_native, band_valid = mask_and_scale_surface_reflectance(
            dn=dn_native,
            qa_pixel=qa_pixel_native,
            sensor=sensor,
            scale=scale_factor,
            offset=offset,
            nodata_val=nodata_float,
            qa_radsat=qa_radsat_native,
        )

        # Reproject continuous reflectance to target grid using bilinear interpolation
        reprojected_sr = np.full((target_height, target_width), nodata_float, dtype=np.float32)
        reproject(
            source=scaled_sr_native,
            destination=reprojected_sr,
            src_transform=b_transform,
            src_crs=b_crs,
            src_nodata=nodata_float,
            dst_transform=target_transform,
            dst_crs=target_crs,
            dst_nodata=nodata_float,
            resampling=Resampling.bilinear,
        )
        sr_reprojected_bands.append(reprojected_sr)

    # Combine into 6-band array
    sr_stack = np.stack(sr_reprojected_bands, axis=0)  # (6, height, width)

    # Establish final valid_sr mask according to Contract Section 2:
    # 1 = valid inside AOI (reprojected_valid_mask == 1 and all 6 bands != nodata_float and not NaN)
    # 0 = invalid inside AOI
    # 255 = outside AOI
    bands_valid = np.all((sr_stack != nodata_float) & (~np.isnan(sr_stack)), axis=0)
    all_valid_condition = (reprojected_valid_mask == 1) & bands_valid

    valid_sr_arr = np.full((target_height, target_width), mask_nodata, dtype=np.uint8)
    valid_sr_arr[aoi_mask == 1] = np.where(all_valid_condition[aoi_mask == 1], 1, 0)

    # Mask all bands in sr_stack to nodata where valid_sr_arr != 1
    sr_stack[:, valid_sr_arr != 1] = nodata_float

    # Save data/processed/{year}/sr_30m.tif
    out_year_dir = ctx.data / "processed" / str(year)
    out_year_dir.mkdir(parents=True, exist_ok=True)
    sr_path = out_year_dir / "sr_30m.tif"
    valid_sr_path = out_year_dir / "valid_sr_30m.tif"

    with rasterio.open(
        sr_path,
        "w",
        driver="GTiff",
        height=target_height,
        width=target_width,
        count=len(band_order),
        dtype="float32",
        crs=target_crs,
        transform=target_transform,
        nodata=nodata_float,
    ) as dst:
        dst.write(sr_stack)
        for idx, bname in enumerate(band_order, start=1):
            dst.set_band_description(idx, bname)

    # Save data/processed/{year}/valid_sr_30m.tif
    with rasterio.open(
        valid_sr_path,
        "w",
        driver="GTiff",
        height=target_height,
        width=target_width,
        count=1,
        dtype="uint8",
        crs=target_crs,
        transform=target_transform,
        nodata=mask_nodata,
    ) as dst:
        dst.write(valid_sr_arr, 1)

    # Publish copy to outputs/rasters/xindu_{year}_sr_30m.tif
    out_raster_dir = ctx.outputs / "rasters"
    out_raster_dir.mkdir(parents=True, exist_ok=True)
    pub_sr_path = out_raster_dir / f"xindu_{year}_sr_30m.tif"
    shutil.copy2(sr_path, pub_sr_path)

    # Generate processing report
    rep_dir = ctx.reports / "data"
    rep_dir.mkdir(parents=True, exist_ok=True)
    aoi_total_pixels = int(np.sum(aoi_mask == 1))
    valid_pixel_count = int(np.sum(valid_sr_arr == 1))
    valid_ratio = round(valid_pixel_count / aoi_total_pixels, 6) if aoi_total_pixels > 0 else 0.0

    report_data = {
        "year": year,
        "product_id": selected_scene["product_id"],
        "sensor": sensor,
        "acquisition_date": selected_scene["acquisition_date"],
        "crs": target_crs,
        "bounds": grid_30["bounds"],
        "width": target_width,
        "height": target_height,
        "bands": band_order,
        "total_aoi_pixels": aoi_total_pixels,
        "valid_pixels": valid_pixel_count,
        "valid_ratio": valid_ratio,
        "nodata_float": nodata_float,
        "mask_nodata": mask_nodata,
    }
    (rep_dir / f"preprocess_{year}.json").write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    boundaries_gpkg = ctx.data / "processed" / "boundaries" / f"xindu_{ctx.config.get('boundary_reference_year', 2021)}.gpkg"

    return PreparedData(
        year=year,
        sr=sr_path,
        valid_sr=valid_sr_path,
        grid=grid_path,
        boundaries=boundaries_gpkg,
    )


# ---------------------------------------------------------------------------
# 6. Step: pansharpen_2021
# ---------------------------------------------------------------------------

def pansharpen_2021(ctx: ProjectContext) -> Path:
    """Preprocess Landsat 8 Level-1 TOA RGB and Pan bands and produce 15m pansharpened image.

    Strictly labeled for display / visualization purposes only (radiometry=TOA, purpose=visualization).
    Returns path to data/processed/2021/pan_rgb_15m.tif.
    """
    scenes_csv = ctx.data / "catalog" / "scenes.csv"
    if not scenes_csv.exists():
        raise FileNotFoundError(f"Scenes catalog not found: {scenes_csv}")

    selected_l1 = None
    with open(scenes_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row.get("year", 0)) == 2021:
                lvl = row.get("processing_level", "").upper()
                if lvl == "L1TP":
                    status = row.get("selection_status", "").lower()
                    if status == "selected" or selected_l1 is None:
                        selected_l1 = row

    if selected_l1 is None:
        raise FileNotFoundError(f"No selected Level-1 scene found for 2021 in {scenes_csv}")

    scene_dir_rel = selected_l1["scene_dir"]
    mtl_path_rel = selected_l1["mtl_path"]
    scene_dir = ctx.data / (scene_dir_rel.replace("data/", "", 1) if scene_dir_rel.startswith("data/") else scene_dir_rel)
    mtl_path = ctx.data / (mtl_path_rel.replace("data/", "", 1) if mtl_path_rel.startswith("data/") else mtl_path_rel)

    if not scene_dir.exists():
        raise FileNotFoundError(f"L1 scene directory does not exist: {scene_dir}")
    if not mtl_path.exists():
        raise FileNotFoundError(f"L1 MTL file does not exist: {mtl_path}")

    mtl_meta = parse_mtl_metadata(mtl_path)
    validate_scene_metadata(selected_l1, mtl_meta)

    sun_elev = float(mtl_meta.get("SUN_ELEVATION", 45.0))

    # Read 15m grid
    grid_15_path = ctx.data / "processed" / "grids" / "grid_15m.json"
    if not grid_15_path.exists():
        raise FileNotFoundError("grid_15m.json must be prepared first via prepare_boundaries().")

    with open(grid_15_path, "r", encoding="utf-8") as f:
        grid_15 = json.load(f)

    target_crs = grid_15["crs"]
    w15 = grid_15["width"]
    h15 = grid_15["height"]
    transform_15 = Affine.from_gdal(*grid_15["transform"])

    img_cfg = ctx.config.get("imagery", {})
    rgb_band_nums = img_cfg.get("pan_rgb_bands", [4, 3, 2])  # R, G, B
    pan_band_num = int(img_cfg.get("pan_band", 8))
    nodata_float = float(ctx.config.get("float_nodata", -9999.0))

    # Read and convert RGB bands to 15m TOA
    reprojected_rgb_15m: list[np.ndarray] = []
    for bnum in rgb_band_nums:
        bfile = next(scene_dir.glob(f"*_B{bnum}.TIF"), None) or next(scene_dir.glob(f"*_B{bnum}.tif"), None)
        if bfile is None:
            raise FileNotFoundError(f"L1 Band {bnum} not found in {scene_dir}")

        mult = float(mtl_meta.get(f"REFLECTANCE_MULT_BAND_{bnum}", 2.0e-5))
        add = float(mtl_meta.get(f"REFLECTANCE_ADD_BAND_{bnum}", -0.1))

        with rasterio.open(bfile) as b_src:
            dn_native = b_src.read(1)
            b_crs = b_src.crs
            b_trans = b_src.transform

        toa_native = convert_dn_to_toa(dn_native, mult, add, sun_elev, nodata_val=nodata_float)

        # Reproject to 15m grid with bilinear
        toa_15m = np.full((h15, w15), nodata_float, dtype=np.float32)
        reproject(
            source=toa_native,
            destination=toa_15m,
            src_transform=b_trans,
            src_crs=b_crs,
            src_nodata=nodata_float,
            dst_transform=transform_15,
            dst_crs=target_crs,
            dst_nodata=nodata_float,
            resampling=Resampling.bilinear,
        )
        reprojected_rgb_15m.append(toa_15m)

    # Read and convert Pan band (B8) to 15m TOA
    pan_file = next(scene_dir.glob(f"*_B{pan_band_num}.TIF"), None) or next(scene_dir.glob(f"*_B{pan_band_num}.tif"), None)
    if pan_file is None:
        raise FileNotFoundError(f"L1 Pan Band {pan_band_num} not found in {scene_dir}")

    pan_mult = float(mtl_meta.get(f"REFLECTANCE_MULT_BAND_{pan_band_num}", 2.0e-5))
    pan_add = float(mtl_meta.get(f"REFLECTANCE_ADD_BAND_{pan_band_num}", -0.1))

    with rasterio.open(pan_file) as p_src:
        pan_dn_native = p_src.read(1)
        p_crs = p_src.crs
        p_trans = p_src.transform

    pan_toa_native = convert_dn_to_toa(pan_dn_native, pan_mult, pan_add, sun_elev, nodata_val=nodata_float)
    pan_15m = np.full((h15, w15), nodata_float, dtype=np.float32)
    reproject(
        source=pan_toa_native,
        destination=pan_15m,
        src_transform=p_trans,
        src_crs=p_crs,
        src_nodata=nodata_float,
        dst_transform=transform_15,
        dst_crs=target_crs,
        dst_nodata=nodata_float,
        resampling=Resampling.bilinear,
    )

    # Brovey pansharpening:
    # R_sharp = (R / I) * Pan where I = (R + G + B) / 3
    r_15, g_15, b_15 = reprojected_rgb_15m[0], reprojected_rgb_15m[1], reprojected_rgb_15m[2]

    valid_mask = (
        (r_15 != nodata_float) & (g_15 != nodata_float) & (b_15 != nodata_float) & (pan_15m != nodata_float)
        & (~np.isnan(r_15)) & (~np.isnan(g_15)) & (~np.isnan(b_15)) & (~np.isnan(pan_15m))
    )

    intensity = (r_15 + g_15 + b_15) / 3.0
    valid_mask = valid_mask & (intensity > 1e-6)

    r_sharp = np.where(valid_mask, (r_15 / intensity) * pan_15m, nodata_float).astype(np.float32)
    g_sharp = np.where(valid_mask, (g_15 / intensity) * pan_15m, nodata_float).astype(np.float32)
    b_sharp = np.where(valid_mask, (b_15 / intensity) * pan_15m, nodata_float).astype(np.float32)

    stack_15m = np.stack([r_sharp, g_sharp, b_sharp], axis=0)

    # Save data/processed/2021/pan_rgb_15m.tif
    out_dir = ctx.data / "processed" / "2021"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pan_path = out_dir / "pan_rgb_15m.tif"

    with rasterio.open(
        out_pan_path,
        "w",
        driver="GTiff",
        height=h15,
        width=w15,
        count=3,
        dtype="float32",
        crs=target_crs,
        transform=transform_15,
        nodata=nodata_float,
    ) as dst:
        dst.write(stack_15m)
        dst.set_band_description(1, "red")
        dst.set_band_description(2, "green")
        dst.set_band_description(3, "blue")

    # Publish copy to outputs/rasters/xindu_2021_pan_rgb_15m.tif
    out_raster_dir = ctx.outputs / "rasters"
    out_raster_dir.mkdir(parents=True, exist_ok=True)
    pub_pan_path = out_raster_dir / "xindu_2021_pan_rgb_15m.tif"
    shutil.copy2(out_pan_path, pub_pan_path)

    # Save report
    rep_dir = ctx.reports / "data"
    rep_dir.mkdir(parents=True, exist_ok=True)
    report_data = {
        "radiometry": "TOA",
        "purpose": "visualization",
        "product_id": selected_l1["product_id"],
        "sun_elevation_deg": sun_elev,
        "resolution": 15,
        "width": w15,
        "height": h15,
        "rgb_bands": rgb_band_nums,
        "pan_band": pan_band_num,
        "nodata_val": nodata_float,
    }
    (rep_dir / "pansharpen_2021.json").write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    return out_pan_path
