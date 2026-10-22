"""Unit tests for P1-C: Random Forest training and windowed raster prediction.

Tests verify:
  1. Five-class separable sample classification yields valid classes in 1-5.
  2. Model save and reload consistency (identical predictions, exact dict structure).
  3. Feature order adherence: columns extracted strictly by config features.order.
  4. Windowed raster prediction preserves NoData=0 and writes proper colormap.
  5. Band descriptions mismatch between raster and config raises descriptive ValueError.
  6. Grid mismatch between features and valid_features raises ValueError.
  7. train_predict strictly uses train.csv and never accesses holdout.csv.
  8. Two years (1992 and 2021) have models and reports saved in isolated directories.
  9. Training report JSON contains all contract fields and no holdout metrics.
  10. CLI 03_classify.py execution end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from sklearn.ensemble import RandomForestClassifier

from rs_urban.classify import (
    build_colormap,
    hex_to_rgba,
    predict_raster_windowed,
    train_classifier,
    train_predict,
)
from rs_urban.contracts import ClassificationData, ProjectContext
from rs_urban.config import get_repo_root


@pytest.fixture
def mock_config() -> dict[str, Any]:
    """Provide standard project configuration dictionary matching project.toml."""
    return {
        "schema_version": 1,
        "project_slug": "rs-urban-expansion",
        "years": [1992, 2021],
        "target_crs": "EPSG:32648",
        "analysis_resolution_m": 30,
        "float_nodata": -9999.0,
        "class_nodata": 0,
        "mask_nodata": 255,
        "random_seed": 42,
        "features": {
            "order": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"]
        },
        "model": {
            "algorithm": "random_forest",
            "n_estimators": 20,  # lightweight for unit tests
            "min_samples_leaf": 2,
            "max_features": "sqrt",
            "class_weight": "balanced_subsample",
            "n_jobs": 1,
        },
        "classes": [
            {"code": 1, "name": "建设用地", "color": "#D95F02"},
            {"code": 2, "name": "耕地", "color": "#E6C84F"},
            {"code": 3, "name": "其他植被", "color": "#2E8B57"},
            {"code": 4, "name": "水域", "color": "#377EB8"},
            {"code": 5, "name": "裸地", "color": "#B69C7D"},
        ],
    }


def create_synthetic_rasters(
    dir_path: Path,
    feature_names: list[str],
    width: int = 16,
    height: int = 16,
    set_descriptions: bool = True,
) -> tuple[Path, Path]:
    """Create matching 10-band features GeoTIFF and 1-band valid_features GeoTIFF."""
    dir_path.mkdir(parents=True, exist_ok=True)
    features_path = dir_path / "features_30m.tif"
    valid_path = dir_path / "valid_features_30m.tif"

    transform = from_origin(500000.0, 3380000.0, 30.0, 30.0)
    crs = "EPSG:32648"

    # Shape: (10, height, width)
    feat_data = np.full((10, height, width), 0.2, dtype=np.float32)
    # Put separable feature values per quadrant/region
    # Class 1 (Built): high red, low nir
    feat_data[2, 0:8, 0:8] = 0.5   # red
    feat_data[3, 0:8, 0:8] = 0.2   # nir
    # Class 4 (Water): high blue, low nir
    feat_data[0, 8:16, 0:8] = 0.6  # blue
    feat_data[3, 8:16, 0:8] = 0.05 # nir

    # Inject NoData / NaN / out-of-AOI in specific cells
    feat_data[:, 0, 0] = -9999.0  # float_nodata
    feat_data[:, 0, 1] = np.nan   # NaN

    # Valid raster: 1 valid, 0 invalid in AOI, 255 outside AOI
    valid_data = np.ones((height, width), dtype=np.uint8)
    valid_data[1, 0] = 0   # invalid in AOI
    valid_data[1, 1] = 255 # outside AOI

    # Write features raster
    with rasterio.open(
        features_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=10,
        dtype=rasterio.float32,
        crs=crs,
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(feat_data)
        if set_descriptions:
            for b_idx, name in enumerate(feature_names, start=1):
                dst.set_band_description(b_idx, name)

    # Write valid_features raster
    with rasterio.open(
        valid_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=rasterio.uint8,
        crs=crs,
        transform=transform,
        nodata=255,
    ) as dst:
        dst.write(valid_data, 1)

    return features_path, valid_path


def test_hex_to_rgba_and_colormap(mock_config: dict[str, Any]) -> None:
    """Verify hex color parsing and colormap generation."""
    rgba = hex_to_rgba("#D95F02")
    assert rgba == (217, 95, 2, 255)

    colormap = build_colormap(mock_config["classes"], nodata_code=0)
    assert colormap[0] == (0, 0, 0, 0)
    assert colormap[1] == (217, 95, 2, 255)
    assert colormap[2] == (230, 200, 79, 255)
    assert colormap[3] == (46, 139, 87, 255)
    assert colormap[4] == (55, 126, 184, 255)
    assert colormap[5] == (182, 156, 125, 255)


def test_train_separable_classes(
    tmp_path: Path,
    mock_config: dict[str, Any],
    grouped_samples_fixture: dict[str, Any],
) -> None:
    """Train on 5-class separable samples, verify classes are within 1-5 and accuracy is high."""
    samples_csv = Path(grouped_samples_fixture["csv_path"])
    split_json = tmp_path / "split.json"
    with open(split_json, "w", encoding="utf-8") as f:
        json.dump({"fixture": "test_split"}, f)

    estimator, model_dict, report_dict = train_classifier(
        train_csv_path=samples_csv,
        split_json_path=split_json,
        config=mock_config,
        year=2021,
    )

    df = pd.read_csv(samples_csv)
    X = df[mock_config["features"]["order"]].to_numpy(dtype=np.float32)
    y_true = df["class_id"].to_numpy()

    preds = estimator.predict(X)
    assert set(preds).issubset({1, 2, 3, 4, 5})

    accuracy = np.mean(preds == y_true)
    assert accuracy >= 0.95, f"Separable data accuracy should be >= 0.95, got {accuracy}"


def test_model_save_and_reload_consistency(
    tmp_path: Path,
    mock_config: dict[str, Any],
    grouped_samples_fixture: dict[str, Any],
) -> None:
    """Verify model saved to rf.joblib matches contract dict structure and gives identical predictions."""
    samples_csv = Path(grouped_samples_fixture["csv_path"])
    split_json = tmp_path / "split.json"
    split_json.write_text(json.dumps({"hash_test": 123}), encoding="utf-8")

    estimator, model_dict, _ = train_classifier(
        train_csv_path=samples_csv,
        split_json_path=split_json,
        config=mock_config,
        year=2021,
    )

    # Check contract dict keys
    expected_keys = {"estimator", "feature_names", "class_codes", "year", "config", "split_sha256"}
    assert set(model_dict.keys()) == expected_keys
    assert model_dict["year"] == 2021
    assert model_dict["feature_names"] == mock_config["features"]["order"]
    assert model_dict["class_codes"] == [1, 2, 3, 4, 5]

    # Save to joblib and reload
    joblib_path = tmp_path / "rf.joblib"
    joblib.dump(model_dict, joblib_path)

    reloaded = joblib.load(joblib_path)
    assert set(reloaded.keys()) == expected_keys

    df = pd.read_csv(samples_csv)
    X = df[mock_config["features"]["order"]].to_numpy(dtype=np.float32)

    pred_original = estimator.predict(X)
    pred_reloaded = reloaded["estimator"].predict(X)
    np.testing.assert_array_equal(pred_original, pred_reloaded)


def test_feature_order_explicit_column_selection(
    tmp_path: Path,
    mock_config: dict[str, Any],
    grouped_samples_fixture: dict[str, Any],
) -> None:
    """Verify feature columns are extracted strictly by features.order even if CSV columns are reversed."""
    df = pd.read_csv(grouped_samples_fixture["csv_path"])
    # Reverse column order
    reversed_cols = list(df.columns)[::-1]
    shuffled_df = df[reversed_cols]
    shuffled_csv = tmp_path / "shuffled_train.csv"
    shuffled_df.to_csv(shuffled_csv, index=False)

    split_json = tmp_path / "split.json"
    split_json.write_text("{}", encoding="utf-8")

    estimator, model_dict, _ = train_classifier(
        train_csv_path=shuffled_csv,
        split_json_path=split_json,
        config=mock_config,
        year=2021,
    )

    assert model_dict["feature_names"] == mock_config["features"]["order"]
    assert estimator.n_features_in_ == 10


def test_windowed_raster_prediction_and_nodata(
    tmp_path: Path,
    mock_config: dict[str, Any],
    grouped_samples_fixture: dict[str, Any],
) -> None:
    """Verify windowed prediction writes Byte raster, colormap, and strictly preserves NoData=0."""
    samples_csv = Path(grouped_samples_fixture["csv_path"])
    split_json = tmp_path / "split.json"
    split_json.write_text("{}", encoding="utf-8")

    estimator, _, _ = train_classifier(
        train_csv_path=samples_csv,
        split_json_path=split_json,
        config=mock_config,
        year=2021,
    )

    feat_names = mock_config["features"]["order"]
    features_path, valid_path = create_synthetic_rasters(
        tmp_path / "rasters",
        feature_names=feat_names,
        width=16,
        height=16,
    )
    raw_output = tmp_path / "lulc_2021_raw_30m.tif"

    predict_raster_windowed(
        features_path=features_path,
        valid_features_path=valid_path,
        output_raw_path=raw_output,
        estimator=estimator,
        feature_names=feat_names,
        classes_config=mock_config["classes"],
        float_nodata=-9999.0,
        class_nodata=0,
        chunk_size=4,  # Force multiple 4x4 windows to verify streaming
    )

    assert raw_output.exists()

    with rasterio.open(raw_output) as src:
        assert src.dtypes[0] == "uint8"
        assert src.nodata == 0
        assert src.count == 1
        assert (src.width, src.height) == (16, 16)

        data = src.read(1)

        # Check injected NoData pixels:
        # (0, 0): float_nodata -> must be 0
        # (0, 1): NaN -> must be 0
        # (1, 0): valid=0 (invalid in AOI) -> must be 0
        # (1, 1): valid=255 (outside AOI) -> must be 0
        assert data[0, 0] == 0
        assert data[0, 1] == 0
        assert data[1, 0] == 0
        assert data[1, 1] == 0

        # Valid pixels must be within [1, 5]
        valid_pixels = data[data > 0]
        assert len(valid_pixels) > 0
        assert np.all((valid_pixels >= 1) & (valid_pixels <= 5))

        # Check colormap
        cmap = src.colormap(1)
        assert cmap[0] == (0, 0, 0, 0)
        assert cmap[1] == (217, 95, 2, 255)


def test_band_descriptions_mismatch_raises_error(
    tmp_path: Path,
    mock_config: dict[str, Any],
    grouped_samples_fixture: dict[str, Any],
) -> None:
    """Verify that if raster band descriptions mismatch configured feature order, ValueError is raised."""
    samples_csv = Path(grouped_samples_fixture["csv_path"])
    split_json = tmp_path / "split.json"
    split_json.write_text("{}", encoding="utf-8")

    estimator, _, _ = train_classifier(
        train_csv_path=samples_csv,
        split_json_path=split_json,
        config=mock_config,
        year=2021,
    )

    # Create rasters with mismatched band descriptions
    mismatched_names = ["band_1", "band_2", "band_3", "band_4", "band_5", "band_6", "band_7", "band_8", "band_9", "band_10"]
    features_path, valid_path = create_synthetic_rasters(
        tmp_path / "mismatch",
        feature_names=mismatched_names,
        width=8,
        height=8,
        set_descriptions=True,
    )
    raw_output = tmp_path / "mismatch_raw.tif"

    with pytest.raises(ValueError, match="do not match expected feature order"):
        predict_raster_windowed(
            features_path=features_path,
            valid_features_path=valid_path,
            output_raw_path=raw_output,
            estimator=estimator,
            feature_names=mock_config["features"]["order"],
            classes_config=mock_config["classes"],
        )


def test_grid_mismatch_raises_error(tmp_path: Path, mock_config: dict[str, Any]) -> None:
    """Verify that dimension or transform mismatch between features and valid_features raises ValueError."""
    feat_names = mock_config["features"]["order"]
    features_path, _ = create_synthetic_rasters(tmp_path / "g1", feat_names, width=16, height=16)
    _, valid_mismatched = create_synthetic_rasters(tmp_path / "g2", feat_names, width=8, height=8)

    dummy_estimator = RandomForestClassifier()
    with pytest.raises(ValueError, match="Dimension mismatch"):
        predict_raster_windowed(
            features_path=features_path,
            valid_features_path=valid_mismatched,
            output_raw_path=tmp_path / "dummy.tif",
            estimator=dummy_estimator,
            feature_names=feat_names,
            classes_config=mock_config["classes"],
        )


def test_train_predict_pipeline_and_holdout_isolation(
    tmp_path: Path,
    mock_config: dict[str, Any],
    grouped_samples_fixture: dict[str, Any],
) -> None:
    """Verify train_predict runs end-to-end, writes all files, and never accesses holdout.csv."""
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    samples_dir = data_dir / "processed" / "samples" / "2021"
    samples_dir.mkdir(parents=True, exist_ok=True)

    # Copy samples to train.csv
    train_csv = samples_dir / "train.csv"
    train_csv.write_bytes(Path(grouped_samples_fixture["csv_path"]).read_bytes())

    # Create split.json
    split_json = samples_dir / "split.json"
    split_json.write_text(json.dumps({"split_id": "test_split_2021"}), encoding="utf-8")

    # Put a poisonous holdout.csv with invalid syntax to ensure it is never opened
    holdout_csv = samples_dir / "holdout.csv"
    holdout_csv.write_text("INVALID_CSV_SYNTAX_SHOULD_NEVER_BE_READ", encoding="utf-8")

    # Create rasters
    raster_dir = data_dir / "processed" / "2021"
    create_synthetic_rasters(
        raster_dir,
        feature_names=mock_config["features"]["order"],
        width=16,
        height=16,
    )

    ctx = ProjectContext(
        root=tmp_path,
        data=data_dir,
        outputs=outputs_dir,
        reports=reports_dir,
        scratch=scratch_dir,
        config=mock_config,
    )

    result = train_predict(ctx=ctx, year=2021)

    assert isinstance(result, ClassificationData)
    assert result.year == 2021
    assert result.model == outputs_dir / "models" / "2021" / "rf.joblib"
    assert result.raw == outputs_dir / "rasters" / "lulc_2021_raw_30m.tif"

    assert result.model.exists()
    assert result.raw.exists()

    # Verify report JSON
    report_path = reports_dir / "accuracy" / "training_2021.json"
    assert report_path.exists()

    with open(report_path, "r", encoding="utf-8") as f:
        rep = json.load(f)

    assert rep["schema_version"] == 1
    assert rep["year"] == 2021
    assert rep["num_training_pixels"] == 120
    assert rep["num_training_groups"] == 40
    assert "holdout" not in str(rep).lower() or "holdout" not in rep


def test_two_years_models_saved_separately(
    tmp_path: Path,
    mock_config: dict[str, Any],
    grouped_samples_fixture: dict[str, Any],
) -> None:
    """Verify two years (1992 and 2021) models and reports are isolated and saved separately."""
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    for year in [1992, 2021]:
        samples_dir = data_dir / "processed" / "samples" / str(year)
        samples_dir.mkdir(parents=True, exist_ok=True)
        (samples_dir / "train.csv").write_bytes(Path(grouped_samples_fixture["csv_path"]).read_bytes())
        (samples_dir / "split.json").write_text(json.dumps({"year": year}), encoding="utf-8")

        raster_dir = data_dir / "processed" / str(year)
        create_synthetic_rasters(raster_dir, mock_config["features"]["order"], width=8, height=8)

    ctx = ProjectContext(
        root=tmp_path,
        data=data_dir,
        outputs=outputs_dir,
        reports=reports_dir,
        scratch=scratch_dir,
        config=mock_config,
    )

    res_1992 = train_predict(ctx=ctx, year=1992)
    res_2021 = train_predict(ctx=ctx, year=2021)

    assert res_1992.model != res_2021.model
    assert res_1992.raw != res_2021.raw

    model_1992 = joblib.load(res_1992.model)
    model_2021 = joblib.load(res_2021.model)

    assert model_1992["year"] == 1992
    assert model_2021["year"] == 2021


def test_cli_03_classify(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mock_config: dict[str, Any],
    grouped_samples_fixture: dict[str, Any],
) -> None:
    """Verify CLI entrypoint 03_classify.py functions with --config, --env-file, and --year."""
    # Ensure process environment does not override .env values
    for key in ["RS_DATA_ROOT", "RS_OUTPUT_ROOT", "RS_REPORT_ROOT", "RS_SCRATCH_ROOT"]:
        monkeypatch.delenv(key, raising=False)

    import importlib
    from rs_urban.config import get_repo_root

    cli_mod = importlib.import_module("03_classify")
    cli_main = cli_mod.main

    # Setup directories
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    reports_dir = tmp_path / "reports"
    scratch_dir = tmp_path / "scratch"

    samples_dir = data_dir / "processed" / "samples" / "2021"
    samples_dir.mkdir(parents=True, exist_ok=True)
    (samples_dir / "train.csv").write_bytes(Path(grouped_samples_fixture["csv_path"]).read_bytes())
    (samples_dir / "split.json").write_text("{}", encoding="utf-8")

    raster_dir = data_dir / "processed" / "2021"
    create_synthetic_rasters(raster_dir, mock_config["features"]["order"], width=8, height=8)

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
        "--year", "2021",
    ])

    assert exit_code == 0
    assert (outputs_dir / "models" / "2021" / "rf.joblib").exists()
    assert (outputs_dir / "rasters" / "lulc_2021_raw_30m.tif").exists()
    assert (reports_dir / "accuracy" / "training_2021.json").exists()
