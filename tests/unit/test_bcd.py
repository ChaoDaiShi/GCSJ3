"""Analytical microcases only; never evidence of real-image accuracy."""

import copy
import json
from pathlib import Path
import tomllib

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from rs_urban.bcd import inventory, load_settings, run
from rs_urban.contracts import ProjectContext
from rs_urban.detector import detect, discretize, interaction_type, q_statistic
from rs_urban.enhance import (
    classify_experiment, evaluate_arrays, grouped_folds, predict_map, stable_transfer_candidates,
)
from rs_urban.spatial import (
    area_ellipse, connected_patches, landscape_metrics, lei_index, transition_polygons,
    zonal_factors,
)


def test_spatial_folds_have_no_group_leakage():
    y = np.repeat([1, 2, 3, 4], 24)
    groups = np.repeat(np.arange(24), 4)
    splits = grouped_folds(y, groups, 3, 42)
    visited = np.zeros(len(y), dtype=int)
    for train, test in splits:
        assert not (set(groups[train]) & set(groups[test]))
        assert set(y[train]) == set(y[test]) == {1, 2, 3, 4}
        visited[test] += 1
    assert (visited == 1).all()
    with pytest.raises(ValueError, match="at least"):
        grouped_folds(y, groups, 7, 42)


def test_nodata_holdout_predictions_count_as_errors():
    scores = evaluate_arrays([1, 1, 2, 3, 4], [1, 0, 2, 3, 4], [1, 2, 3, 4])
    assert scores["oa"] == 0.8
    assert scores["coverage"] == 0.8
    assert scores["confusion"][0] == [1, 0, 0, 0, 1]
    assert sum(map(sum, scores["confusion"])) == 5
    assert scores["f1"]["1"] == pytest.approx(2 / 3)


def test_cva_exports_only_lowest_label_stable_observations():
    first = np.zeros((6, 2, 5), dtype=float)
    second = np.broadcast_to(np.arange(10).reshape(2, 5), first.shape).astype(float)
    labels = np.ones((2, 5), dtype=int)
    other = labels.copy()
    other[0, 0] = 2
    selected, magnitude = stable_transfer_candidates(first, second, labels, other, labels > 0, 0.3)
    # 9 stable cells, floor(9 * .3) == 2.
    assert selected.sum() == 2
    assert selected[0, 1] and selected[0, 2] and not selected[0, 0]
    assert magnitude[0, 1] == pytest.approx(np.sqrt(6))


def test_lei_uses_external_observable_ring():
    patch = box(0, 0, 10, 10)
    observed = box(-100, -100, 100, 100)
    ring = patch.buffer(10).difference(patch)
    assert lei_index(patch, patch, observed, 10)["lei"] == 0
    assert lei_index(patch, ring, observed, 10)["lei"] == pytest.approx(100)
    assert lei_index(patch, ring, observed, 10)["type"] == "infilling"
    half = ring.intersection(box(-100, -100, 5, 100))
    result = lei_index(patch, half, observed, 10)
    assert result["lei"] == pytest.approx(50)
    assert result["type"] == "edge"
    assert lei_index(patch, half, box(-100, -100, 5, 100), 10)["lei"] == pytest.approx(100)
    assert lei_index(patch, ring, patch, 10)["lei"] is None


def test_exact_transition_areas_and_nodata():
    first = np.array([[1, 2], [0, 3]], dtype=np.uint8)
    last = np.array([[1, 1], [4, 2]], dtype=np.uint8)
    common = (first > 0) & (last > 0)
    result = transition_polygons(first, last, common, from_origin(0, 60, 30, 30),
                                 "EPSG:32648", box(10, 0, 60, 60))
    assert result.area_km2.sum() == pytest.approx(0.0024)
    assert result.loc[(result.from_class == 1) & (result.to_class == 1)].area_km2.sum() == pytest.approx(0.0006)
    assert result.loc[result.change_id == 2].area_km2.sum() == pytest.approx(0.0009)
    assert not (result.from_class == 0).any()


def test_ellipse_uses_uniform_area_and_handles_holes():
    result = area_ellipse(box(500000, 3380000, 500120, 3380060))
    assert result["x"] == 500060
    assert result["y"] == 3380030
    assert result["semi_major_m"] == pytest.approx(120 / np.sqrt(6))
    assert result["semi_minor_m"] == pytest.approx(60 / np.sqrt(6))
    assert result["angle_degrees_ccw_from_east"] == 0
    ring = box(-2, -2, 2, 2).difference(box(-1, -1, 1, 1))
    result = area_ellipse(ring)
    assert result["semi_major_m"] == pytest.approx(np.sqrt(10 / 3))
    assert area_ellipse(box(0, 0, 0, 0)) is None


def test_landscape_square_and_diagonal_connectivity():
    built = np.ones((2, 2), dtype=bool)
    result = landscape_metrics(built, built, 30)
    assert result["patch_count"] == 1
    assert result["lpi_pct"] == 100
    assert result["ai_pct"] == 100
    assert result["frac_am"] == pytest.approx(1)
    assert result["pd_per_100ha"] == pytest.approx(1e6 / 3600)
    diagonal = np.eye(2, dtype=bool)
    assert landscape_metrics(diagonal, built, 30, 4)["patch_count"] == 2
    assert landscape_metrics(diagonal, built, 30, 8)["patch_count"] == 1
    assert landscape_metrics(np.zeros_like(built), built)["ai_pct"] is None


def test_diagonal_patches_keep_valid_geometry_and_selected_connectivity():
    mask = np.eye(2, dtype=bool)
    transform = from_origin(0, 60, 30, 30)
    four = connected_patches(mask, transform, "EPSG:32648", 4)
    eight = connected_patches(mask, transform, "EPSG:32648", 8)
    assert len(four) == 2 and len(eight) == 1
    assert eight.geometry.is_valid.all()
    assert eight.geometry.iloc[0].geom_type == "MultiPolygon"
    assert eight.area.sum() == four.area.sum() == 1800
    empty = connected_patches(np.zeros_like(mask), transform, "EPSG:32648", 8)
    assert empty.empty


def test_detector_with_no_grids_surviving_coverage_filter():
    grid = gpd.GeoDataFrame(columns=["grid_id", "ueii", "geometry"], crs="EPSG:32648")
    grid = zonal_factors(grid, {"slope": np.ones((2, 2))}, from_origin(0, 60, 30, 30),
                         np.ones((2, 2), dtype=bool))
    result = detect(grid, ["slope"])
    assert result["status"] == "undefined" and result["n"] == 0


def test_detector_known_q_common_cases_and_determinism():
    y = [0, 0, 1, 1]
    assert q_statistic(y, [0, 0, 1, 1]) == 1
    assert q_statistic(y, [0, 1, 0, 1]) == 0
    assert q_statistic([1, 1], [0, 1]) is None
    strata, edges = discretize([3, 3, 3])
    assert len(set(strata)) == 1 and edges == [3]
    table = pd.DataFrame({"grid_id": list("abcde"), "ueii": [0, 0, 1, 1, 9],
                          "a": [0, 0, 1, 1, np.nan], "b": [0, 1, 0, 1, 9]})
    result = detect(table, ["a", "b"], bins=2, permutations=19)
    assert result == detect(table, ["a", "b"], bins=2, permutations=19)
    assert result["n"] == 4 and result["dropped_grids"] == 1
    assert result["interactions"][0]["q"] == 1
    assert interaction_type(0.2, 0.3, 0.7) == "nonlinear_enhance"
    assert interaction_type(0.2, 0.3, 0.4) == "bivariate_enhance"


def build_micro_context(tmp_path, repo_root):
    with (repo_root / "configs/project.toml").open("rb") as stream:
        config = tomllib.load(stream)
    config["model"].update(n_estimators=8, n_jobs=1)
    config["feature_stack"].update(dem_smooth_window=1, twi_buffer_cells=2)
    with (repo_root / "configs/bcd.toml").open("rb") as stream:
        settings = tomllib.load(stream)
    settings["classification"].update(methods=["svm", "rf"], folds=3, chunk_size=5)
    settings["analysis"].update(source="rf", grid_size_m=90, permutations=9, minimum_grid_coverage=0.5)
    settings["factors"] = settings["factors"][:2]
    ctx = ProjectContext(
        root=tmp_path, data=tmp_path / "data", outputs=tmp_path / "outputs",
        reports=tmp_path / "reports", scratch=tmp_path / "scratch", config=copy.deepcopy(config),
    )
    ctx.scratch.mkdir()
    transform = from_origin(500000, 3380360, 30, 30)
    profile = dict(driver="GTiff", width=12, height=12, transform=transform, crs="EPSG:32648")
    r, c = np.indices((12, 12))
    rng = np.random.default_rng(42)
    for year in config["years"]:
        labels = (1 + (r >= 6) * 2 + (c >= 6)).astype("uint8")
        if year == 2021:
            labels[:2, 6:8] = 1
        data = np.stack([
            labels * 0.1 + i * 0.003 + rng.normal(0, 0.001, (12, 12))
            for i, _ in enumerate(config["features"]["order"])
        ]).astype("float32")
        target = ctx.data / "processed" / str(year)
        target.mkdir(parents=True)
        with rasterio.open(target / "features_30m.tif", "w", **profile, count=len(data),
                           dtype="float32", nodata=-9999) as dst:
            dst.write(data)
            dst.descriptions = tuple(config["features"]["order"])
        valid = np.ones((12, 12), dtype="uint8")
        valid[-1, -1] = 0
        with rasterio.open(target / "valid_features_30m.tif", "w", **profile, count=1,
                           dtype="uint8", nodata=255) as dst:
            dst.write(valid, 1)
        records = []
        for row in range(12):
            for col in range(12):
                if not valid[row, col]:
                    continue
                group = (row // 2) * 6 + col // 2
                records.append({
                    "group_id": f"g{group}", "class_id": int(labels[row, col]), "row": row, "col": col,
                    "holdout": group % 3 == 0,
                    **dict(zip(config["features"]["order"], data[:, row, col])),
                })
        frame = pd.DataFrame(records)
        sample = ctx.data / "processed" / "samples" / str(year)
        sample.mkdir(parents=True)
        frame[~frame.holdout].drop(columns="holdout").to_csv(sample / "train.csv", index=False)
        frame[frame.holdout].drop(columns="holdout").to_csv(sample / "holdout.csv", index=False)
        (sample / "split.json").write_text('{"seed": 42}', encoding="utf-8")
    boundary = ctx.data / "processed" / "boundaries"
    boundary.mkdir()
    study = box(500005, 3380000, 500360, 3380360)
    gpd.GeoDataFrame([{"area_id": "test", "name": "micro", "geometry": study}], crs=profile["crs"]).to_file(
        boundary / "xindu_2021.gpkg", layer="study_area", driver="GPKG"
    )
    gpd.GeoDataFrame([
        {"unit_id": "a", "name": "west", "geometry": box(500005, 3380000, 500180, 3380360)},
        {"unit_id": "b", "name": "east", "geometry": box(500180, 3380000, 500360, 3380360)},
    ], crs=profile["crs"]).to_file(boundary / "xindu_2021.gpkg", layer="townships", driver="GPKG")
    for factor in settings["factors"]:
        path = ctx.data / factor["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        x = 500100 if factor["name"] == "river_distance" else 500300
        gpd.GeoDataFrame([{"geometry": LineString([(x, 3380000), (x, 3380360)])}],
                         crs=profile["crs"]).to_file(path, layer=factor["layer"], driver="GPKG")
    dem = ctx.data / config["feature_stack"]["dem_path"]
    dem.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dem, "w", **profile, count=1, dtype="float32", nodata=-9999) as dst:
        dst.write((500 + r * 2 + c).astype("float32"), 1)
    return ctx, settings


def test_missing_inputs_report_does_not_invent_results(tmp_path, repo_root):
    config = tomllib.loads((repo_root / "configs/project.toml").read_text(encoding="utf-8"))
    ctx = ProjectContext(tmp_path, tmp_path / "data", tmp_path / "outputs",
                         tmp_path / "reports", tmp_path / "scratch", config)
    settings = load_settings(ctx, repo_root / "configs/bcd.toml")
    assert all(task["status"] == "pending" for task in inventory(ctx, settings))
    result = run(ctx, settings, "all")
    assert all(task["status"] == "pending" for task in result)
    assert (ctx.reports / "bcd/report.md").exists()
    assert not list(ctx.outputs.rglob("*.tif"))
    assert not list(ctx.outputs.rglob("*.png"))


def test_bcd_micro_pipeline_with_all_six_real_artifact_figures(tmp_path, repo_root):
    """Synthetic inputs stay in tmp_path, including PNGs; no project results generated."""
    from PIL import Image
    ctx, settings = build_micro_context(tmp_path, repo_root)
    before = {
        (year, name): (ctx.data / "processed/samples" / str(year) / name).read_bytes()
        for year in ctx.config["years"] for name in ["train.csv", "holdout.csv", "split.json"]
    }
    outcomes = run(ctx, settings, "all")
    assert all(task["status"] in ("computed", "rendered") for task in outcomes)
    analysis = ctx.outputs / "bcd/analysis/rf"
    summary = json.loads((analysis / "summary.json").read_text(encoding="utf-8"))
    assert summary["area_balance"]["is_balanced"]
    assert summary["transition_sum_km2"] == pytest.approx(summary["common_area_km2"])
    assert summary["lei_area_km2"]["edge"] > 0
    assert all(item["status"] == "computed" for item in summary["factors"])
    assert json.loads((analysis / "geodetector.json").read_text())["status"] == "computed"
    assert len(list((ctx.outputs / "bcd/figures/rf").glob("*.png"))) == 6
    for path in (ctx.outputs / "bcd/figures/rf").glob("*.png"):
        pixels = np.asarray(Image.open(path).convert("RGB"))
        assert pixels.shape[1] > 1000 and pixels.std() > 10
    for year in ctx.config["years"]:
        rf = json.loads((ctx.reports / f"bcd/accuracy_{year}_rf.json").read_text())
        svm = json.loads((ctx.reports / f"bcd/accuracy_{year}_svm.json").read_text())
        assert rf["holdout_sha256"] == svm["holdout_sha256"]
        with rasterio.open(ctx.outputs / f"bcd/classification/{year}/rf/lulc.tif") as src:
            assert src.read(1)[-1, -1] == 0
        for name in ["train.csv", "holdout.csv", "split.json"]:
            assert before[(year, name)] == (ctx.data / "processed/samples" / str(year) / name).read_bytes()


def test_classifier_rejects_holdout_group_overlap(tmp_path, repo_root):
    ctx, settings = build_micro_context(tmp_path, repo_root)
    directory = ctx.data / "processed/samples/1992"
    train = pd.read_csv(directory / "train.csv")
    holdout = pd.read_csv(directory / "holdout.csv")
    holdout.loc[0, "group_id"] = train.loc[0, "group_id"]
    holdout.to_csv(directory / "holdout.csv", index=False)
    with pytest.raises(ValueError, match="overlap"):
        classify_experiment(ctx, 1992, "rf", settings["classification"])


def test_optional_requested_stacking_packages(tmp_path, repo_root):
    pytest.importorskip("lightgbm")
    pytest.importorskip("catboost")
    ctx, settings = build_micro_context(tmp_path, repo_root)
    settings["classification"]["stack_trees"] = 5
    result = classify_experiment(ctx, 1992, "stacking", settings["classification"])
    assert result[0]["method"] == "stacking"
    assert result[0]["coverage"] == 1


@pytest.mark.parametrize("objects,crf,dependency", [
    (True, False, "skimage"), (False, True, "pydensecrf"),
])
def test_optional_smoothing_preserves_nodata(objects, crf, dependency):
    pytest.importorskip(dependency)
    from rs_urban.enhance import smooth_probabilities
    probability = np.full((4, 8, 8), 0.05, dtype=np.float32)
    probability[0] = 0.85
    valid = np.ones((8, 8), dtype=bool)
    valid[3:5, 3:5] = False
    probability[:, ~valid] = -9999
    rgb = np.random.default_rng(42).random((3, 8, 8)).astype("float32")
    result = smooth_probabilities(probability, rgb, valid, objects=objects, crf=crf, segments=4)
    assert (result[:, ~valid] == -9999).all()
    assert np.allclose(result[:, valid].sum(axis=0), 1, atol=1e-5)
    assert (result[:, valid].argmax(axis=0) == 0).all()
