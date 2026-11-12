"""Module B: spatial OOF stacking, frozen-holdout ablation and optional smoothing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import rasterio
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier, StackingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, cohen_kappa_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from rs_urban.classify import build_colormap, iter_windows
from rs_urban.contracts import ProjectContext

SPECTRAL = ["blue", "green", "red", "nir", "swir1", "swir2"]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def grouped_folds(y, groups, folds: int, seed: int):
    """Materialize folds before stacking; never use pixel-random CV."""
    y, groups = np.asarray(y), np.asarray(groups)
    if folds < 2 or pd.isna(groups).any():
        raise ValueError("Spatial CV needs >=2 folds and nonmissing group_id.")
    for label in np.unique(y):
        if len(np.unique(groups[y == label])) < folds:
            raise ValueError(f"Class {label} needs at least {folds} training groups.")
    splits = list(StratifiedGroupKFold(
        n_splits=folds, shuffle=True, random_state=seed
    ).split(np.zeros(len(y)), y, groups))
    for train, valid in splits:
        if set(groups[train]) & set(groups[valid]):
            raise ValueError("Spatial groups overlap within CV.")
        if set(y[train]) != set(y) or set(y[valid]) != set(y):
            raise ValueError("A spatial fold lacks a class; revise groups or fold count.")
    return splits


def build_model(method: str, config: dict, settings: dict, splits):
    seed = int(config["random_seed"])
    rf_cfg = config["model"]
    rf = RandomForestClassifier(
        n_estimators=rf_cfg["n_estimators"],
        min_samples_leaf=rf_cfg["min_samples_leaf"],
        max_features=rf_cfg["max_features"],
        class_weight=rf_cfg["class_weight"],
        n_jobs=rf_cfg["n_jobs"], random_state=seed,
    )
    if method == "rf":
        return rf
    if method == "svm":
        # SVC decision values suffice for the baseline. Avoid its internal
        # pixel-random probability calibration on spatially correlated samples.
        return make_pipeline(StandardScaler(), SVC(
            C=settings["svm_c"], gamma=settings["svm_gamma"], class_weight="balanced"
        ))
    if method != "stacking":
        raise ValueError(f"Unknown method: {method}")
    from lightgbm import LGBMClassifier
    from catboost import CatBoostClassifier
    estimators = [
        ("rf", rf),
        ("lgb", LGBMClassifier(
            n_estimators=settings["stack_trees"], learning_rate=0.05,
            num_leaves=31, random_state=seed, n_jobs=rf_cfg["n_jobs"], verbosity=-1,
        )),
        ("cat", CatBoostClassifier(
            iterations=settings["stack_trees"], depth=6, learning_rate=0.05,
            random_seed=seed, verbose=False, allow_writing_files=False,
            thread_count=rf_cfg["n_jobs"],
        )),
    ]
    return StackingClassifier(
        estimators=estimators,
        final_estimator=LogisticRegression(max_iter=2000, random_state=seed),
        cv=splits, stack_method="predict_proba", n_jobs=1,
    )


def check_grid(first, second) -> None:
    if (first.crs, first.transform, first.shape) != (
        second.crs, second.transform, second.shape
    ):
        raise ValueError(f"Grid mismatch: {first.name} / {second.name}")


def predict_map(model, features: Path, mask: Path, target: Path,
                feature_names: list[str], classes: list[dict],
                chunk_size: int, probabilities: Path | None = None) -> None:
    """Select named bands, preserve invalid cells and persist class-ordered probabilities."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(features) as src, rasterio.open(mask) as valid_src:
        check_grid(src, valid_src)
        if any(name not in src.descriptions for name in feature_names):
            raise ValueError("Feature bands need complete, matching descriptions.")
        indexes = [src.descriptions.index(name) + 1 for name in feature_names]
        codes = np.asarray(model.classes_, dtype=np.uint8)
        profile = src.profile.copy()
        profile.update(count=1, dtype="uint8", nodata=0, compress="deflate")
        prob_dst = None
        try:
            if probabilities is not None:
                prob_profile = profile | {"count": len(codes), "dtype": "float32", "nodata": -9999.0}
                prob_dst = rasterio.open(probabilities, "w", **prob_profile)
                prob_dst.descriptions = tuple(str(int(c)) for c in codes)
            with rasterio.open(target, "w", **profile) as dst:
                for window in iter_windows(src.width, src.height, chunk_size):
                    data = src.read(indexes, window=window, masked=True)
                    valid = (valid_src.read(1, window=window) == 1)
                    valid &= ~np.ma.getmaskarray(data).any(axis=0)
                    valid &= np.isfinite(data.data).all(axis=0)
                    labels = np.zeros(valid.shape, dtype=np.uint8)
                    if valid.any():
                        x = data.data[:, valid].T
                        labels[valid] = model.predict(x).astype(np.uint8)
                    dst.write(labels, 1, window=window)
                    if prob_dst is not None:
                        p = np.full((len(codes), *valid.shape), -9999.0, dtype=np.float32)
                        if valid.any():
                            p[:, valid] = model.predict_proba(x).T
                        prob_dst.write(p, window=window)
                dst.write_colormap(1, build_colormap(classes))
        finally:
            if prob_dst is not None:
                prob_dst.close()


def smooth_probabilities(probability, rgb, valid, *, objects=False, crf=False,
                         segments=5000, compactness=0.1, iterations=5):
    """Whole-scene optional SLIC and DenseCRF; never fill masked cells."""
    p = np.array(probability, dtype=np.float32, copy=True)
    valid = np.asarray(valid, dtype=bool)
    if not valid.any():
        raise ValueError("No valid observations for spatial smoothing.")
    image = np.moveaxis(np.asarray(rgb, dtype=np.float32), 0, -1).copy()
    for band in range(3):
        lo, hi = np.percentile(image[..., band][valid], [2, 98])
        image[..., band] = np.clip((image[..., band] - lo) / max(hi - lo, 1e-6), 0, 1)
    image[~valid] = 0
    if objects:
        from skimage.segmentation import slic
        objects_map = slic(
            image, n_segments=segments, compactness=compactness,
            start_label=1, mask=valid, convert2lab=False, channel_axis=-1,
        )
        ids = objects_map[valid]
        counts = np.bincount(ids)
        for k in range(p.shape[0]):
            sums = np.bincount(ids, weights=p[k, valid], minlength=len(counts))
            means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
            p[k, valid] = means[ids]
    if crf:
        import pydensecrf.densecrf as dcrf
        from pydensecrf.utils import unary_from_softmax
        # DenseCRF2D treats missing cells as latent nodes. A general graph over
        # observed cells keeps nodata holes from mediating pairwise messages.
        coords = np.asarray(np.nonzero(valid), dtype=np.float32)
        colors = (image[valid].T * 255).astype(np.float32)
        engine = dcrf.DenseCRF(int(valid.sum()), p.shape[0])
        engine.setUnaryEnergy(unary_from_softmax(np.ascontiguousarray(p[:, valid])))
        engine.addPairwiseEnergy(np.ascontiguousarray(coords / 3), compat=3)
        bilateral = np.vstack((coords / 20, colors / 13))
        engine.addPairwiseEnergy(np.ascontiguousarray(bilateral), compat=10)
        p[:, valid] = np.asarray(engine.inference(iterations), dtype=np.float32)
    p[:, ~valid] = -9999.0
    return p


def evaluate_arrays(truth, prediction, codes) -> dict:
    truth, prediction = np.asarray(truth), np.asarray(prediction)
    if not len(truth) or not np.isin(truth, codes).all():
        raise ValueError("Holdout must be nonempty and use configured classes.")
    covered = np.isin(prediction, codes)
    # Nodata predictions remain errors in OA and F1, rather than disappearing
    # from a 4x4 matrix. The fifth column explicitly records abstentions.
    matrix = np.column_stack((
        confusion_matrix(truth, prediction, labels=codes),
        [int(((truth == c) & ~covered).sum()) for c in codes],
    ))
    kappa = float(cohen_kappa_score(truth, prediction, labels=[*codes, 0]))
    precision, recall, f1, support = precision_recall_fscore_support(
        truth, prediction, labels=codes, zero_division=0,
    )
    return {
        "n": int(len(truth)), "coverage": float(covered.mean()),
        "oa": float(accuracy_score(truth, prediction)),
        "kappa": kappa if np.isfinite(kappa) else None,
        "macro_f1": float(f1_score(truth, prediction, labels=codes, average="macro", zero_division=0)),
        "f1": dict(zip(map(str, codes), f1_score(
            truth, prediction, labels=codes, average=None, zero_division=0
        ).tolist())),
        "classes": [
            {"class_id": int(code), "precision": float(p), "recall": float(r),
             "f1": float(f), "support": int(n)}
            for code, p, r, f, n in zip(codes, precision, recall, f1, support)
        ],
        "confusion_columns": [*codes, "unclassified"], "confusion": matrix.tolist(),
    }


def classify_experiment(ctx: ProjectContext, year: int, method: str, settings: dict):
    sample_dir = ctx.data / "processed" / "samples" / str(year)
    train_file, holdout_file = sample_dir / "train.csv", sample_dir / "holdout.csv"
    train, holdout = pd.read_csv(train_file), pd.read_csv(holdout_file)
    if set(train.group_id) & set(holdout.group_id):
        raise ValueError("Training and frozen holdout groups overlap.")
    if train.group_id.isna().any() or holdout.group_id.isna().any():
        raise ValueError("Missing spatial group identifiers.")
    if pd.MultiIndex.from_frame(train[["row", "col"]]).intersection(
        pd.MultiIndex.from_frame(holdout[["row", "col"]])
    ).size:
        raise ValueError("Training and holdout pixel coordinates overlap.")
    codes = [int(c["code"]) for c in ctx.config["classes"]]
    if set(train.class_id) != set(codes):
        raise ValueError("Training labels do not match the configured classes.")
    split_file = sample_dir / "split.json"
    # Check the metadata is valid JSON and retain its actual byte fingerprint.
    json.loads(split_file.read_text(encoding="utf-8"))
    names = SPECTRAL if method == "svm" else ctx.config["features"]["order"]
    x, y = train[names].to_numpy(dtype=np.float32), train.class_id.to_numpy()
    if not np.isfinite(x).all():
        raise ValueError("Training features contain nonfinite values.")
    folds = grouped_folds(y, train.group_id, settings["folds"], ctx.config["random_seed"])
    model = build_model(method, ctx.config, settings, folds)
    # Baseline models also receive a spatial CV audit. A stacking model already
    # uses these folds for its meta learner; don't nest a holdout-based search.
    cv_scores = []
    if method != "stacking":
        for a, b in folds:
            fold_model = clone(model).fit(x[a], y[a])
            cv_scores.append(float(accuracy_score(y[b], fold_model.predict(x[b]))))
    model.fit(x, y)
    root = ctx.outputs / "bcd" / "classification" / str(year) / method
    root.mkdir(parents=True, exist_ok=True)
    bundle = {
        "estimator": model, "feature_names": names, "class_codes": codes,
        "train_sha256": digest(train_file), "split_sha256": digest(split_file),
        "holdout_sha256": digest(holdout_file), "year": year, "method": method,
    }
    joblib.dump(bundle, root / "model.joblib")
    source = ctx.data / "processed" / str(year)
    probability_path = root / "probabilities.tif" if method != "svm" else None
    raw_path = root / "lulc.tif"
    predict_map(
        model, source / "features_30m.tif", source / "valid_features_30m.tif",
        raw_path, names, ctx.config["classes"], settings["chunk_size"], probability_path,
    )
    maps = {method: raw_path}
    if method == "stacking" and (settings["object_smoothing"] or settings["crf"]):
        with rasterio.open(probability_path) as src, rasterio.open(source / "features_30m.tif") as feat:
            p, profile = src.read(), src.profile.copy()
            valid = (p >= 0).all(axis=0) & np.isfinite(p).all(axis=0)
            rgb = feat.read([feat.descriptions.index(n) + 1 for n in ["red", "green", "blue"]])
        p = smooth_probabilities(
            p, rgb, valid, objects=settings["object_smoothing"], crf=settings["crf"],
            segments=settings["slic_segments"], compactness=settings["slic_compactness"],
            iterations=settings["crf_iterations"],
        )
        variant = "stacking" + ("_obia" if settings["object_smoothing"] else "") + ("_crf" if settings["crf"] else "")
        path = root.parent / variant / "lulc.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        labels = np.zeros(valid.shape, dtype=np.uint8)
        labels[valid] = model.classes_[p[:, valid].argmax(axis=0)]
        profile.update(count=1, dtype="uint8", nodata=0)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(labels, 1)
            dst.write_colormap(1, build_colormap(ctx.config["classes"]))
        maps[variant] = path
    results = []
    rows, cols = holdout.row.to_numpy(), holdout.col.to_numpy()
    if (rows != rows.astype(int)).any() or (cols != cols.astype(int)).any():
        raise ValueError("Holdout row/col must be integer grid coordinates.")
    rows, cols = rows.astype(int), cols.astype(int)
    for variant, path in maps.items():
        with rasterio.open(path) as src:
            if ((rows < 0) | (cols < 0) | (rows >= src.height) | (cols >= src.width)).any():
                raise ValueError("Holdout samples lie outside the classification grid.")
            prediction = src.read(1)[rows, cols]
        report = evaluate_arrays(holdout.class_id, prediction, codes) | {
            "year": year, "method": variant, "feature_names": names,
            "train_sha256": bundle["train_sha256"], "split_sha256": bundle["split_sha256"],
            "holdout_sha256": bundle["holdout_sha256"],
            "map_path": str(path), "map_sha256": digest(path),
            "spatial_cv_oa": cv_scores, "spatial_folds": len(folds),
            "selection": "Exploratory comparison; holdout is not used to choose parameters.",
            "scope": "Purity-filtered internal holdout, not external map accuracy.",
        }
        write_json(ctx.reports / "bcd" / f"accuracy_{year}_{variant}.json", report)
        results.append(report)
    return results


def stable_transfer_candidates(first, second, first_labels, second_labels, valid,
                               fraction=0.3):
    """CVA shortlist only: no insertion into train.csv or the frozen holdout."""
    if not 0 < fraction <= 1:
        raise ValueError("CVA fraction must be in (0, 1].")
    first, second = np.asarray(first), np.asarray(second)
    if first.shape != second.shape or first.ndim != 3:
        raise ValueError("CVA needs aligned reflectance bands with matching units.")
    valid = np.array(valid, dtype=bool, copy=True)
    valid &= np.isfinite(first).all(axis=0) & np.isfinite(second).all(axis=0)
    valid &= (first_labels > 0) & (first_labels == second_labels)
    magnitude = np.sqrt(np.sum((first.astype(float) - second.astype(float)) ** 2, axis=0))
    candidates = np.zeros(valid.shape, dtype=bool)
    if valid.any():
        indexes = np.flatnonzero(valid)
        keep = max(1, int(np.floor(len(indexes) * fraction)))
        # Stable sort breaks ties without admitting an entire uniform scene.
        selected = indexes[np.argsort(magnitude.ravel()[indexes], kind="stable")[:keep]]
        candidates.ravel()[selected] = True
    return candidates, magnitude
