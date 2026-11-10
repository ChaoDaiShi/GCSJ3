"""Unit tests for configuration loading, path resolution, and scientific parameters."""

import os
from pathlib import Path
import pytest

from rs_urban.config import load_context, get_repo_root


def test_load_context_basic(repo_root: Path):
    """Test basic loading of context from default configs."""
    ctx = load_context(Path("configs/project.toml"), Path(".env"))
    assert ctx.root == repo_root
    assert ctx.data == (repo_root / "data").resolve()
    assert ctx.outputs == (repo_root / "outputs").resolve()
    assert ctx.reports == (repo_root / "reports").resolve()
    assert ctx.scratch == (repo_root / ".cache/processing").resolve()
    assert ctx.config["project_slug"] == "rs-urban-expansion"
    assert os.environ.get("CPL_TMPDIR") == str(ctx.scratch)


def test_different_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo_root: Path):
    """Verify that launching from another working directory resolves to the same data root."""
    monkeypatch.chdir(tmp_path)
    assert Path.cwd() == tmp_path.resolve()

    ctx = load_context(Path("configs/project.toml"), Path(".env"))
    # Even though cwd is tmp_path, relative paths resolve against repository root
    assert ctx.root == repo_root
    assert ctx.data == (repo_root / "data").resolve()
    assert ctx.data != (tmp_path / "data").resolve()
    assert ctx.outputs == (repo_root / "outputs").resolve()


def test_process_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo_root: Path):
    """Verify that process environment variables override values in .env."""
    custom_data = tmp_path / "custom_data_dir"
    monkeypatch.setenv("RS_DATA_ROOT", str(custom_data))
    monkeypatch.setenv("GDAL_CACHEMAX", "2048")

    ctx = load_context(Path("configs/project.toml"), Path(".env"))
    assert ctx.data == custom_data.resolve()
    assert os.environ.get("GDAL_CACHEMAX") == "2048"


def test_config_classes_and_features_consistency():
    """Verify that the 4 classes and 10 features order are fully consistent with project.toml."""
    ctx = load_context(Path("configs/project.toml"), Path(".env"))
    config = ctx.config

    # Check 4 classes
    classes = config["classes"]
    assert len(classes) == 4
    expected_codes = [1, 2, 3, 4]
    expected_names = ["城镇及建设用地", "耕地", "林草植被", "水体"]
    assert [c["code"] for c in classes] == expected_codes
    assert [c["name"] for c in classes] == expected_names

    # Check 19 features order：22 维方案去掉地形三项（空间位置代理，见 docs/changes/2026-11-09-feature-19dim-22dim-comparison.md）
    expected_features = [
        "blue", "green", "red", "nir", "swir1", "swir2",
        "ndvi", "savi", "mndwi", "ndbi", "ui", "bsi", "ibi",
        "nir_mean", "nir_std", "red_mean", "red_std", "swir1_mean", "swir1_std",
    ]
    assert config["features"]["order"] == expected_features
    assert config["feature_stack"]["order"] == expected_features
    assert config["feature_stack"]["texture_window"] == 5

    # Check key scientific parameters
    assert config["target_crs"] == "EPSG:32648"
    assert config["analysis_resolution_m"] == 30
    assert config["display_resolution_m"] == 15
    assert config["class_nodata"] == 0
    assert config["float_nodata"] == -9999.0
    assert config["years"] == [1992, 2021]
    assert config["boundary_reference_year"] == 2021
    assert config["expected_township_count"] == 9


def test_micro_fixtures(
    scaling_fixture: dict,
    feature_fixture: dict,
    grouped_samples_fixture: dict,
    metric_fixture: dict,
    change_fixture: dict,
    tmp_path: Path,
):
    """Verify that all 5 micro-data fixtures are generated and accessible strictly in tmp_path."""
    # Scaling fixture
    assert scaling_fixture["data"]["expected_valid_sr"] == 0.075
    assert len(scaling_fixture["data"]["pixels"]) == 4

    # Feature fixture
    feat = feature_fixture["data"]
    assert feat["feature_order"] == ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"]
    assert abs(feat["valid_pixel"]["expected_ndvi"] - 1.0 / 3.0) < 1e-6
    assert abs(feat["valid_pixel"]["expected_ndbi"] - (-0.2)) < 1e-6
    assert abs(feat["valid_pixel"]["expected_mndwi"] - (-1.0 / 3.0)) < 1e-6
    assert feat["valid_pixel"]["expected_bsi"] == 0.0

    # Grouped samples fixture
    samples = grouped_samples_fixture["data"]
    assert samples["num_classes"] == 4
    assert samples["groups_per_class"] == 8
    assert samples["total_samples"] == 96
    assert Path(grouped_samples_fixture["csv_path"]).exists()

    # Metric fixture
    metric = metric_fixture["data"]
    assert metric["overall_accuracy"] == 0.8
    assert len(metric["confusion_matrix"]) == 4
    assert len(metric["class_metrics"]) == 4

    # Change fixture
    change = change_fixture["data"]
    assert change["crs"] == "EPSG:32648"
    assert change["bounds"] == [500010, 3380010, 500100, 3380100]
    assert change["district_expected"]["net_km2"] == pytest.approx(0.0018)
    assert change["district_expected"]["comparable_area_km2"] == pytest.approx(0.0072)
    assert len(change["townships"]) == 2

    # Verify no test output written to repository data/ or outputs/
    for f in [
        scaling_fixture["manifest_path"],
        feature_fixture["manifest_path"],
        grouped_samples_fixture["manifest_path"],
        metric_fixture["manifest_path"],
        change_fixture["manifest_path"],
    ]:
        assert tmp_path in Path(f).parents
