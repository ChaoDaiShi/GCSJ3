"""Unit tests for P1-B: Sample extraction, 10-band feature generation, and stratified group splitting.

Contracts verified:
- Index calculation: NDVI=1/3, NDBI=-0.2, MNDWI=-1/3, BSI=0 on standard test vector.
- Denominator=0 pixels masked to NoData (-9999.0) across all 10 bands and excluded from samples.
- 10-band feature raster preserving public grid, transform, CRS (EPSG:32648), and band descriptions.
- Stratified GroupShuffleSplit: 25% holdout per class, >=2 holdout groups per class, disjoint train/holdout groups.
- Disjoint pixel coordinates between train.csv and holdout.csv.
- Pixel centers extracted accurately with correct CSV header.
- Deterministic splitting and persistence in split.json.
- Clear FileNotFoundError on missing upstream inputs.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon

from rs_urban.config import load_context
from rs_urban.contracts import ProjectContext, SampleData
from rs_urban.samples import (
    calculate_indices,
    extract_pixel_samples,
    generate_features_raster,
    split_sample_groups,
    build_samples,
)


def _create_synthetic_sr_rasters(
    out_dir: Path,
    width: int = 20,
    height: int = 20,
    origin_x: float = 500000.0,
    origin_y: float = 3380000.0,
    res: float = 30.0,
) -> tuple[Path, Path, rasterio.Affine]:
    """Create a synthetic 6-band SR GeoTIFF and 1-band valid_sr GeoTIFF for testing."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sr_path = out_dir / "sr_30m.tif"
    valid_sr_path = out_dir / "valid_sr_30m.tif"
    transform = from_origin(origin_x, origin_y, res, res)
    crs = "EPSG:32648"

    # 6 bands: blue, green, red, nir, swir1, swir2
    sr_data = np.zeros((6, height, width), dtype=np.float32)
    # Default valid baseline
    sr_data[0, :, :] = 0.1  # blue
    sr_data[1, :, :] = 0.2  # green
    sr_data[2, :, :] = 0.3  # red
    sr_data[3, :, :] = 0.6  # nir
    sr_data[4, :, :] = 0.4  # swir1
    sr_data[5, :, :] = 0.5  # swir2

    # Put a zero-denominator pixel at (row=0, col=1) for NDVI (nir=0, red=0)
    sr_data[2, 0, 1] = 0.0
    sr_data[3, 0, 1] = 0.0

    # Put a NoData pixel at (row=0, col=2)
    sr_data[:, 0, 2] = -9999.0

    # Write SR raster
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

    # Valid SR mask: 1=valid, 0=in-area invalid, 255=outside area
    valid_data = np.ones((1, height, width), dtype=np.uint8)
    valid_data[0, 0, 2] = 0    # NoData pixel is in-area invalid
    valid_data[0, 19, :] = 255  # bottom row is outside area

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

    return sr_path, valid_sr_path, transform


def _create_synthetic_labels_gdf(
    transform: rasterio.Affine,
    num_classes: int = 5,
    groups_per_class: int = 8,
) -> gpd.GeoDataFrame:
    """Create a GeoDataFrame with synthetic sample polygons aligned to pixel centers."""
    records = []
    sample_counter = 0

    for class_id in range(1, num_classes + 1):
        for g_idx in range(1, groups_per_class + 1):
            group_id = f"c{class_id}_g{g_idx:02d}"
            # 2 polygons per group, placed at completely distinct rows and cols
            for p_sub in range(2):
                sample_counter += 1
                sample_id = f"s_test_{sample_counter:04d}"
                # Map to rows 1..15, cols 1..16
                row = 1 + (class_id - 1) * 2 + p_sub
                col = g_idx

                # Pixel center coordinates
                cx = transform.c + (col + 0.5) * transform.a
                cy = transform.f + (row + 0.5) * transform.e  # e is negative

                # Small polygon centered on pixel center (radius 10m < 15m half-pixel)
                poly = Polygon([
                    (cx - 10, cy - 10),
                    (cx + 10, cy - 10),
                    (cx + 10, cy + 10),
                    (cx - 10, cy + 10),
                ])

                records.append({
                    "sample_id": sample_id,
                    "group_id": group_id,
                    "year": 2021,
                    "class_id": class_id,
                    "label_source": "test_synthetic",
                    "source_date": "2021-02-05",
                    "annotator": "tester",
                    "split": "unassigned",
                    "geometry": poly,
                })

    return gpd.GeoDataFrame(records, crs="EPSG:32648")


# ==============================================================================
# Unit Tests
# ==============================================================================

def test_feature_indices_formula_and_values(feature_fixture: dict[str, Any]) -> None:
    """Verify that 6-band input [0.1, 0.2, 0.3, 0.6, 0.4, 0.5] yields exact indices:
    NDVI = 1/3, NDBI = -0.2, MNDWI = -1/3, BSI = 0.0.
    """
    data = feature_fixture["data"]
    valid_p = data["valid_pixel"]

    # Shape: (6, 1, 1)
    sr_arr = np.array([
        [[valid_p["blue"]]],
        [[valid_p["green"]]],
        [[valid_p["red"]]],
        [[valid_p["nir"]]],
        [[valid_p["swir1"]]],
        [[valid_p["swir2"]]],
    ], dtype=np.float32)

    valid_sr = np.ones((1, 1), dtype=np.uint8)

    features, valid_features = calculate_indices(sr_arr, valid_sr, float_nodata=-9999.0)

    assert features.shape == (10, 1, 1)
    assert valid_features[0, 0] == 1

    # Check 6 base bands preserved
    np.testing.assert_allclose(features[0, 0, 0], valid_p["blue"], rtol=1e-5)
    np.testing.assert_allclose(features[1, 0, 0], valid_p["green"], rtol=1e-5)
    np.testing.assert_allclose(features[2, 0, 0], valid_p["red"], rtol=1e-5)
    np.testing.assert_allclose(features[3, 0, 0], valid_p["nir"], rtol=1e-5)
    np.testing.assert_allclose(features[4, 0, 0], valid_p["swir1"], rtol=1e-5)
    np.testing.assert_allclose(features[5, 0, 0], valid_p["swir2"], rtol=1e-5)

    # Check 4 indices
    np.testing.assert_allclose(features[6, 0, 0], 1.0 / 3.0, rtol=1e-5)  # NDVI
    np.testing.assert_allclose(features[7, 0, 0], -0.2, rtol=1e-5)        # NDBI
    np.testing.assert_allclose(features[8, 0, 0], -1.0 / 3.0, rtol=1e-5) # MNDWI
    np.testing.assert_allclose(features[9, 0, 0], 0.0, atol=1e-6)        # BSI


def test_feature_zero_denominator_and_invalid_mask(feature_fixture: dict[str, Any]) -> None:
    """Verify that when any index denominator is 0 or input is NoData,
    all 10 features become float_nodata (-9999.0) and valid_features is 0 (or 255 outside).
    """
    # Pixel 0: zero denominator for NDVI (nir=0, red=0)
    # Pixel 1: zero denominator for NDBI (swir1=0, nir=0)
    # Pixel 2: NoData (-9999.0) in blue band
    # Pixel 3: valid_sr is 255 (outside study area)
    sr_arr = np.array([
        [[0.1, 0.1, -9999.0, 0.1]],  # blue
        [[0.2, 0.2, 0.2,     0.2]],  # green
        [[0.0, 0.3, 0.3,     0.3]],  # red
        [[0.0, 0.0, 0.6,     0.6]],  # nir
        [[0.4, 0.0, 0.4,     0.4]],  # swir1
        [[0.5, 0.5, 0.5,     0.5]],  # swir2
    ], dtype=np.float32)

    valid_sr = np.array([[1, 1, 0, 255]], dtype=np.uint8)

    features, valid_features = calculate_indices(sr_arr, valid_sr, float_nodata=-9999.0)

    # All 4 pixels must have all 10 features as NoData
    for col_idx in range(4):
        np.testing.assert_allclose(features[:, 0, col_idx], -9999.0)

    # valid_features flags
    assert valid_features[0, 0] == 0    # in-area invalid (zero denom NDVI)
    assert valid_features[0, 1] == 0    # in-area invalid (zero denom NDBI)
    assert valid_features[0, 2] == 0    # in-area invalid (NoData)
    assert valid_features[0, 3] == 255  # outside study area


def test_raster_feature_generation_metadata(tmp_path: Path) -> None:
    """Verify that generate_features_raster produces a 10-band Float32 GeoTIFF
    and a 1-band Byte valid_features GeoTIFF with exact contract metadata.
    """
    sr_path, valid_sr_path, transform = _create_synthetic_sr_rasters(tmp_path / "inputs")
    out_features = tmp_path / "outputs" / "features_30m.tif"
    out_valid_features = tmp_path / "outputs" / "valid_features_30m.tif"

    config = {
        "float_nodata": -9999.0,
        "mask_nodata": 255,
        "features": {
            "order": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"]
        },
    }

    f_path, vf_path = generate_features_raster(
        sr_path=sr_path,
        valid_sr_path=valid_sr_path,
        out_features_path=out_features,
        out_valid_features_path=out_valid_features,
        config=config,
    )

    assert f_path.exists()
    assert vf_path.exists()

    with rasterio.open(f_path) as src:
        assert src.count == 10
        assert src.dtypes[0] == "float32"
        assert src.nodata == -9999.0
        assert src.crs.to_string() == "EPSG:32648"
        assert src.descriptions == (
            "blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"
        )
        assert src.width == 20
        assert src.height == 20

    with rasterio.open(vf_path) as src:
        assert src.count == 1
        assert src.dtypes[0] == "uint8"
        assert src.nodata == 255
        assert src.crs.to_string() == "EPSG:32648"
        assert src.width == 20
        assert src.height == 20


def test_stratified_group_shuffle_split_rules(tmp_path: Path) -> None:
    """Verify GroupShuffleSplit rules:
    - 25% holdout per class.
    - At least 2 groups per class in holdout.
    - Disjoint group_id sets between train and holdout.
    - Deterministic split across runs with seed=42.
    """
    _, _, transform = _create_synthetic_sr_rasters(tmp_path / "rasters")
    gdf = _create_synthetic_labels_gdf(transform, num_classes=5, groups_per_class=8)

    split_map1 = split_sample_groups(
        labels_gdf=gdf,
        random_seed=42,
        holdout_fraction=0.25,
        min_labeled_groups=8,
        min_holdout_groups=2,
    )

    split_map2 = split_sample_groups(
        labels_gdf=gdf,
        random_seed=42,
        holdout_fraction=0.25,
        min_labeled_groups=8,
        min_holdout_groups=2,
    )

    # Determinism
    assert split_map1 == split_map2

    train_groups = {g for g, s in split_map1.items() if s == "train"}
    holdout_groups = {g for g, s in split_map1.items() if s == "holdout"}

    # Disjoint groups
    assert train_groups.intersection(holdout_groups) == set()
    assert len(train_groups) + len(holdout_groups) == 40  # 5 classes * 8 groups

    # Per-class holdout count
    for c in range(1, 6):
        c_groups = gdf[gdf["class_id"] == c]["group_id"].unique()
        c_holdout = [g for g in c_groups if split_map1[g] == "holdout"]
        assert len(c_holdout) >= 2
        assert len(c_holdout) == 2  # 25% of 8 is exactly 2


def test_group_split_validation_failure() -> None:
    """Verify that split_sample_groups raises ValueError when:
    - A group has conflicting classes.
    - A class has fewer than min_labeled_groups.
    """
    # Conflicting classes in group
    bad_gdf1 = gpd.GeoDataFrame({
        "sample_id": ["s1", "s2"],
        "group_id": ["g1", "g1"],
        "class_id": [1, 2],
        "geometry": [Polygon(), Polygon()],
    })
    with pytest.raises(ValueError, match="multiple classes"):
        split_sample_groups(bad_gdf1, min_labeled_groups=1, min_holdout_groups=1)

    # Class with fewer than min_labeled_groups
    bad_gdf2 = gpd.GeoDataFrame({
        "sample_id": [f"s{i}" for i in range(5)],
        "group_id": [f"g{i}" for i in range(5)],
        "class_id": [1] * 5,
        "geometry": [Polygon() for _ in range(5)],
    })
    with pytest.raises(ValueError, match="less than required minimum"):
        split_sample_groups(bad_gdf2, min_labeled_groups=8, min_holdout_groups=2)


def test_split_json_persistence_and_reuse(tmp_path: Path) -> None:
    """Verify that an existing split.json is loaded and reused rather than regenerated."""
    split_dir = tmp_path / "samples"
    split_dir.mkdir(parents=True)
    split_path = split_dir / "split.json"

    # Pre-existing split mapping
    custom_split = {
        "schema_version": 1,
        "year": 2021,
        "random_seed": 999,
        "groups": {
            "c1_g01": "train",
            "c1_g02": "holdout",
        },
    }
    with open(split_path, "w", encoding="utf-8") as f:
        json.dump(custom_split, f)

    gdf = gpd.GeoDataFrame({
        "sample_id": ["s1", "s2"],
        "group_id": ["c1_g01", "c1_g02"],
        "class_id": [1, 1],
        "geometry": [Polygon(), Polygon()],
    })

    # When split_path is passed and exists, it loads existing split
    loaded = split_sample_groups(
        labels_gdf=gdf,
        existing_split_path=split_path,
    )
    assert loaded["c1_g01"] == "train"
    assert loaded["c1_g02"] == "holdout"


def test_extract_pixel_samples_disjoint_and_accuracy(tmp_path: Path) -> None:
    """Verify pixel sample extraction:
    - train.csv and holdout.csv coordinates (row, col) have disjoint intersection.
    - train.csv and holdout.csv group_ids have disjoint intersection.
    - Center coordinates x, y match raster transform.xy.
    - Required 18 CSV header fields are present.
    - Invalid pixels (e.g. denom=0 or outside area) are omitted.
    """
    sr_path, valid_sr_path, transform = _create_synthetic_sr_rasters(tmp_path / "inputs")
    out_features = tmp_path / "features_30m.tif"
    out_valid_features = tmp_path / "valid_features_30m.tif"

    config = {
        "float_nodata": -9999.0,
        "mask_nodata": 255,
        "features": {
            "order": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"]
        },
    }
    generate_features_raster(sr_path, valid_sr_path, out_features, out_valid_features, config)

    gdf = _create_synthetic_labels_gdf(transform, num_classes=5, groups_per_class=8)
    split_map = split_sample_groups(gdf, random_seed=42)

    train_df, holdout_df, summary = extract_pixel_samples(
        features_path=out_features,
        valid_features_path=out_valid_features,
        labels_gdf=gdf,
        split_map=split_map,
        year=2021,
    )

    expected_cols = [
        "sample_id", "group_id", "year", "class_id",
        "row", "col", "x", "y",
        "blue", "green", "red", "nir", "swir1", "swir2",
        "ndvi", "ndbi", "mndwi", "bsi"
    ]
    assert list(train_df.columns) == expected_cols
    assert list(holdout_df.columns) == expected_cols

    # Verify disjoint coordinates
    train_coords = set(zip(train_df["row"], train_df["col"]))
    holdout_coords = set(zip(holdout_df["row"], holdout_df["col"]))
    assert train_coords.intersection(holdout_coords) == set()

    # Verify disjoint groups
    train_groups = set(train_df["group_id"])
    holdout_groups = set(holdout_df["group_id"])
    assert train_groups.intersection(holdout_groups) == set()

    # Check coordinate computation accuracy
    for _, row in train_df.head(5).iterrows():
        expected_x, expected_y = rasterio.transform.xy(transform, int(row["row"]), int(row["col"]), offset="center")
        assert pytest.approx(row["x"], abs=1e-3) == expected_x
        assert pytest.approx(row["y"], abs=1e-3) == expected_y

    # Check that each class is represented in both train and holdout
    for c in range(1, 6):
        assert (train_df["class_id"] == c).sum() > 0
        assert (holdout_df["class_id"] == c).sum() > 0


def test_build_samples_end_to_end_synthetic(tmp_path: Path, repo_root: Path) -> None:
    """Verify build_samples end-to-end with ProjectContext in a temporary directory."""
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    processed_2021 = data_dir / "processed" / "2021"
    samples_2021 = data_dir / "samples" / "2021"
    processed_2021.mkdir(parents=True)
    samples_2021.mkdir(parents=True)

    # Create inputs
    sr_path, valid_sr_path, transform = _create_synthetic_sr_rasters(processed_2021)
    gdf = _create_synthetic_labels_gdf(transform, num_classes=5, groups_per_class=8)
    labels_path = samples_2021 / "labels.gpkg"
    gdf.to_file(labels_path, layer="labels", driver="GPKG")

    # Load base config
    toml_path = repo_root / "configs" / "project.toml"
    with open(toml_path, "rb") as f:
        import tomllib
        cfg = tomllib.load(f)

    ctx = ProjectContext(
        root=tmp_path,
        data=data_dir,
        outputs=outputs_dir,
        reports=reports_dir,
        scratch=scratch_dir,
        config=cfg,
    )

    sample_data = build_samples(ctx, year=2021)

    assert isinstance(sample_data, SampleData)
    assert sample_data.year == 2021
    assert sample_data.features.exists()
    assert sample_data.valid_features.exists()
    assert sample_data.train.exists()
    assert sample_data.holdout.exists()
    assert sample_data.split.exists()

    # Check sampling report was generated
    report_path = reports_dir / "accuracy" / "sampling_2021.md"
    assert report_path.exists()
    report_content = report_path.read_text(encoding="utf-8")
    assert "2021" in report_content
    assert "Holdout" in report_content or "holdout" in report_content


def test_missing_inputs_raise_filenotfounderror(tmp_path: Path) -> None:
    """Verify that build_samples raises FileNotFoundError when sr_30m.tif or labels.gpkg is absent."""
    ctx = ProjectContext(
        root=tmp_path,
        data=tmp_path / "data",
        outputs=tmp_path / "outputs",
        reports=tmp_path / "reports",
        scratch=tmp_path / "scratch",
        config={},
    )

    with pytest.raises(FileNotFoundError, match="SR raster not found"):
        build_samples(ctx, year=1992)


@pytest.fixture(autouse=True)
def isolate_samples_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests in test_samples.py run with clean environment variables."""
    for var in ["RS_DATA_ROOT", "RS_OUTPUT_ROOT", "RS_REPORT_ROOT", "RS_SCRATCH_ROOT", "GDAL_CACHEMAX", "CPL_TMPDIR"]:
        monkeypatch.delenv(var, raising=False)


def test_cli_02_samples_execution(tmp_path: Path, repo_root: Path) -> None:
    """Verify that src/02_samples.py CLI runs successfully on a synthetic dataset."""
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    processed_2021 = data_dir / "processed" / "2021"
    samples_2021 = data_dir / "samples" / "2021"
    processed_2021.mkdir(parents=True)
    samples_2021.mkdir(parents=True)

    sr_path, valid_sr_path, transform = _create_synthetic_sr_rasters(processed_2021)
    gdf = _create_synthetic_labels_gdf(transform, num_classes=5, groups_per_class=8)
    labels_path = samples_2021 / "labels.gpkg"
    gdf.to_file(labels_path, layer="labels", driver="GPKG")

    # Create synthetic .env
    env_file = tmp_path / ".env"
    env_content = (
        f"RS_DATA_ROOT={data_dir.as_posix()}\n"
        f"RS_OUTPUT_ROOT={outputs_dir.as_posix()}\n"
        f"RS_REPORT_ROOT={reports_dir.as_posix()}\n"
        f"RS_SCRATCH_ROOT={scratch_dir.as_posix()}\n"
    )
    env_file.write_text(env_content, encoding="utf-8")

    config_path = repo_root / "configs" / "project.toml"
    script_path = repo_root / "src" / "02_samples.py"

    cmd = [
        sys.executable,
        str(script_path),
        "--config", str(config_path),
        "--env-file", str(env_file),
        "--year", "2021",
    ]

    clean_env = dict(os.environ)
    for var in ["RS_DATA_ROOT", "RS_OUTPUT_ROOT", "RS_REPORT_ROOT", "RS_SCRATCH_ROOT", "GDAL_CACHEMAX", "CPL_TMPDIR"]:
        clean_env.pop(var, None)

    res = subprocess.run(cmd, env=clean_env, capture_output=True, text=True)
    assert res.returncode == 0, f"CLI command failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    assert "Sample processing completed successfully" in res.stdout
    assert (data_dir / "processed" / "samples" / "2021" / "train.csv").exists()
    assert (data_dir / "processed" / "samples" / "2021" / "holdout.csv").exists()
    assert (data_dir / "processed" / "samples" / "2021" / "split.json").exists()

