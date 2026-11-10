"""2021 年 15 m 分类对照产品（仅用于展示，不参与任何变化统计）。

为什么单独做一个工具：
  Landsat Collection 2 的 Level-2 地表反射率产品不含全色波段 B8，15 m 融合必须用
  Level-1（TOA）场景。本工具因此把 30 m 的 SR 作为光谱底座、把 L1 B8 的 15 m 高频
  细节注入进去，避免整体改用 TOA 辐射口径而与 30 m 主线结果不可比。

流程：
  1. B8 → TOA 反射率，重投影到 15 m 网格；
  2. 六波段 SR（30 m）与 B8 做 Gram-Schmidt 自适应融合，得到 6 波段 15 m 影像；
  3. 在 15 m 网格上按与 30 m 完全相同的公式重算 19 维特征（公式由自检对齐）；
  4. 用同一个人工样本与同一个 split.json 训练/留出，训练随机森林；
  5. 推理 + 4 像元 Sieve，输出 lulc_2021_15m.tif；
  6. 面积、精度、对比图与说明文件。

    python -X utf8 tools/classify_2021_15m.py
"""

from __future__ import annotations

import csv
import json
import sys
import tomllib
from pathlib import Path

import numpy as np
import rasterio
import geopandas as gpd
from affine import Affine
from rasterio.warp import Resampling, reproject
from scipy.ndimage import uniform_filter
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rs_urban import classify as cls  # noqa: E402
from rs_urban import samples as smp  # noqa: E402
from rs_urban.evaluate import sieve_classification  # noqa: E402

SCENE = REPO / "data" / "raw" / "landsat" / "2021" / "level1" / "LC08_L1TP_129039_20210731_20210804_02_T1"
SR_30 = REPO / "data" / "processed" / "2021" / "sr_30m.tif"
VALID_30 = REPO / "data" / "processed" / "2021" / "valid_sr_30m.tif"
FEAT_30 = REPO / "data" / "processed" / "features" / "feat_2021_30m.tif"
LABELS = REPO / "data" / "samples" / "2021" / "labels.gpkg"
SPLIT = REPO / "data" / "processed" / "samples" / "2021" / "split.json"
OUT_DIR = REPO / "outputs" / "rasters"
REPORT_DIR = REPO / "reports" / "accuracy"
FLOAT_NODATA = -9999.0
EPS = 1e-6


def load_config() -> dict:
    return tomllib.loads((REPO / "configs" / "project.toml").read_text(encoding="utf-8"))


def read_toa_pan(dst_transform: Affine, width: int, height: int, crs, scene: Path) -> np.ndarray:
    """读取 B8 全色波段并转为 TOA 反射率，重投影到 15 m 网格。"""
    mtl = next(scene.glob("*_MTL.txt")).read_text(encoding="utf-8")
    mult = add = None
    sun_elev = None
    for line in mtl.splitlines():
        if "REFLECTANCE_MULT_BAND_8" in line:
            mult = float(line.split("=")[1].strip())
        elif "REFLECTANCE_ADD_BAND_8" in line:
            add = float(line.split("=")[1].strip())
        elif "SUN_ELEVATION" in line and sun_elev is None:
            sun_elev = float(line.split("=")[1].strip())
    if mult is None or add is None or sun_elev is None:
        raise ValueError("B8 定标系数或太阳高度角缺失")

    src = next(scene.glob("*_B8.TIF"))
    dst = np.full((height, width), np.nan, dtype=np.float32)
    with rasterio.open(src) as ds:
        reproject(
            source=rasterio.band(ds, 1),
            destination=dst,
            resampling=Resampling.bilinear,
            dst_transform=dst_transform,
            dst_crs=crs,
        )
    toa = mult * dst + add
    return (toa / np.sin(np.deg2rad(sun_elev))).astype(np.float32)


def block_mean(arr: np.ndarray, factor: int = 2) -> np.ndarray:
    h, w = arr.shape
    return arr.reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3)).astype(np.float32)


def upsample(arr: np.ndarray, height: int, width: int) -> np.ndarray:
    """双线性放大到目标尺寸。"""
    out = np.empty((height, width), dtype=np.float32)
    reproject(
        source=arr,
        destination=out,
        resampling=Resampling.bilinear,
        src_transform=Affine(width / arr.shape[1], 0, 0, 0, -height / arr.shape[0], height),
        src_crs="EPSG:4326",
        dst_transform=Affine(width / width, 0, 0, 0, -height / height, height),
        dst_crs="EPSG:4326",
    )
    return out


def gs_pansharpen(sr: np.ndarray, valid: np.ndarray, pan15: np.ndarray, h15: int, w15: int) -> tuple[np.ndarray, dict]:
    """Gram-Schmidt 自适应融合：SR 30 m 做光谱底座，B8 注入 15 m 细节。"""
    pan30 = block_mean(pan15, 2)
    mask = (valid == 1) & np.isfinite(pan30) & np.min([np.isfinite(sr[b]) for b in range(sr.shape[0])], axis=0)

    sub = np.zeros_like(mask)
    sub[::4, ::4] = True
    fit = mask & sub
    n = int(fit.sum())
    if n < 1000:
        raise ValueError(f"回归可用像元过少：{n}")

    design = np.column_stack([np.ones(n)] + [sr[b][fit] for b in range(sr.shape[0])])
    coef, *_ = np.linalg.lstsq(design, pan30[fit], rcond=None)

    pan_sim = np.full_like(pan30, np.nan, dtype=np.float32)
    pan_sim[mask] = coef[0] + sum(coef[i + 1] * sr[i][mask] for i in range(sr.shape[0]))

    pan_sim_15 = upsample(pan_sim, h15, w15)
    delta = pan15 - pan_sim_15

    var_pan = float(np.nanvar(pan_sim[mask]))
    sharp = np.empty((sr.shape[0], h15, w15), dtype=np.float32)
    gains = []
    for b in range(sr.shape[0]):
        band = sr[b]
        cov = float(np.nanmean((band[mask] - np.nanmean(band[mask])) * (pan_sim[mask] - np.nanmean(pan_sim[mask]))))
        gain = cov / var_pan if var_pan > EPS else 0.0
        gains.append(gain)
        sharp[b] = upsample(band.astype(np.float32), h15, w15) + gain * delta

    info = {
        "regression_coef": [float(c) for c in coef],
        "gains": gains,
        "pan_sim_var": var_pan,
        "fit_pixels": n,
    }
    return sharp, info


def compute_features(bands: np.ndarray, valid15: np.ndarray, order: list[str], window: int) -> np.ndarray:
    """与 preprocess.build_feature_stack 完全一致的 19 维特征公式（在本文件内自检对齐）。"""
    is_valid = valid15 == 1
    for b in range(bands.shape[0]):
        is_valid &= np.isfinite(bands[b])

    blue, green, red, nir, swir1, swir2 = (bands[i] for i in range(6))

    def ratio(num, den):
        safe = is_valid & (np.abs(den) > EPS)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(safe, num / den, FLOAT_NODATA).astype(np.float32)

    t_b = ratio(2.0 * swir1, swir1 + nir)
    t_v = ratio(nir, nir + red) + ratio(green, green + swir1)
    t_v = np.where(is_valid, t_v, FLOAT_NODATA).astype(np.float32)

    values: dict[str, np.ndarray] = {
        "blue": blue, "green": green, "red": red, "nir": nir, "swir1": swir1, "swir2": swir2,
        "ndvi": ratio(nir - red, nir + red),
        "savi": ratio(1.5 * (nir - red), nir + red + 0.5),
        "mndwi": ratio(green - swir1, green + swir1),
        "ndbi": ratio(swir1 - nir, swir1 + nir),
        "ui": ratio(swir2 - nir, swir2 + nir),
        "bsi": ratio((swir1 + red) - (nir + blue), (swir1 + red) + (nir + blue)),
        "ibi": ratio(t_b - t_v, t_b + t_v),
    }

    def texture(band):
        weight = is_valid.astype(np.float32)
        filled = np.where(is_valid, band, 0.0).astype(np.float32)
        wsum = uniform_filter(weight, size=window, mode="nearest")
        bsum = uniform_filter(filled, size=window, mode="nearest")
        bsq = uniform_filter(filled * filled, size=window, mode="nearest")
        with np.errstate(divide="ignore", invalid="ignore"):
            mean = np.where(wsum > 0, bsum / wsum, FLOAT_NODATA)
            var = np.where(wsum > 0, bsq / wsum - mean * mean, FLOAT_NODATA)
        std = np.sqrt(np.clip(np.where(np.isfinite(var), var, 0.0), 0.0, None))
        return (np.where(is_valid, mean, FLOAT_NODATA).astype(np.float32),
                np.where(is_valid, std, FLOAT_NODATA).astype(np.float32))

    for name, arr in (("nir", nir), ("red", red), ("swir1", swir1)):
        m, s = texture(arr)
        values[f"{name}_mean"] = m
        values[f"{name}_std"] = s

    unknown = [n for n in order if n not in values]
    if unknown:
        raise ValueError(f"未知特征：{unknown}")
    return np.stack([np.where(is_valid, values[n], FLOAT_NODATA) for n in order], axis=0).astype(np.float32)


def write_stack(path: Path, stack: np.ndarray, transform, crs, order: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=stack.shape[1], width=stack.shape[2],
        count=stack.shape[0], dtype="float32", crs=crs, transform=transform,
        nodata=FLOAT_NODATA, compress="deflate", tiled=True, blockxsize=256, blockysize=256,
    ) as dst:
        dst.write(stack)
        for i, name in enumerate(order, start=1):
            dst.set_band_description(i, name)


def self_check(order: list[str], window: int) -> float:
    """用同一套公式重算 30 m 特征，与流水线产物比对，证明公式无漂移。"""
    with rasterio.open(SR_30) as ds:
        sr = ds.read().astype(np.float32)
    with rasterio.open(VALID_30) as ds:
        valid = ds.read(1)
    mine = compute_features(sr, valid, order, window)
    with rasterio.open(FEAT_30) as ds:
        theirs = ds.read()
    band = order.index("ndvi")
    a = mine[band]
    b = theirs[band]
    ok = (a != FLOAT_NODATA) & (b != FLOAT_NODATA)
    return float(np.nanmax(np.abs(a[ok] - b[ok])))


def resolve_overlaps(labels: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, list[dict]]:
    """在内存中消除样本面重叠（不改动源 gpkg）。

    30 m 网格下重叠缝隙没有落进任何像元中心，15 m 网格下会落进去，导致同一像元被
    两个组认领而报错。这里按 group_id 顺序做差集：先到的面保留，后到的减去重叠区。
    """
    g = labels.copy().reset_index(drop=True)
    removed = []
    geoms = []
    taken = None
    for i in range(len(g)):
        geom = g.geometry.iloc[i]
        if taken is not None and not taken.is_empty:
            inter = geom.intersection(taken)
            if not inter.is_empty and inter.area > 1e-6:
                removed.append({"index": i, "group_id": g["group_id"].iloc[i],
                                "area_m2": round(float(inter.area), 2)})
                geom = geom.difference(taken)
        geoms.append(geom)
        taken = geom if taken is None else unary_union([taken, geom])
    g = g.set_geometry(gpd.GeoSeries(geoms, crs=g.crs))
    return g, removed


def main() -> None:
    cfg = load_config()
    order = list(cfg["feature_stack"]["order"])
    window = int(cfg["feature_stack"].get("texture_window", 5))
    float_nodata = float(cfg.get("float_nodata", FLOAT_NODATA))

    print("[1/7] 特征公式自检（30 m 复算 vs 流水线产物）")
    drift = self_check(order, window)
    print(f"      NDVI 最大绝对偏差 = {drift:.3e}（应 < 1e-6）")
    if drift > 1e-5:
        raise ValueError("特征公式与流水线不一致，停止")

    with rasterio.open(SR_30) as ds:
        sr = ds.read().astype(np.float32)
        crs, t30 = ds.crs, ds.transform
        h30, w30 = ds.height, ds.width
    with rasterio.open(VALID_30) as ds:
        valid30 = ds.read(1)

    t15 = Affine(t30.a / 2, t30.b, t30.c, t30.d, t30.e / 2, t30.f)
    h15, w15 = h30 * 2, w30 * 2

    print(f"[2/7] B8 全色 → {w15}×{h15} @15 m TOA")
    pan15 = read_toa_pan(t15, w15, h15, crs, SCENE)
    print(f"      有效值范围 {np.nanpercentile(pan15[np.isfinite(pan15)], [2, 50, 98]).round(3)}")

    print("[3/7] GS 自适应融合 6 波段")
    sharp, info = gs_pansharpen(sr, valid30, pan15, h15, w15)
    print(f"      增益 = {[round(g, 4) for g in info['gains']]}")

    band_names = list(cfg.get("imagery", {}).get("band_order", ["blue", "green", "red", "nir", "swir1", "swir2"]))
    pan_path = OUT_DIR / "pan_2021_6band_15m.tif"
    with rasterio.open(
        pan_path, "w", driver="GTiff", height=h15, width=w15, count=6, dtype="float32",
        crs=crs, transform=t15, nodata=float_nodata, compress="deflate", tiled=True,
        blockxsize=256, blockysize=256,
    ) as dst:
        dst.write(sharp)
        for i, name in enumerate(band_names, start=1):
            dst.set_band_description(i, name)

    print("[4/7] 15 m 特征堆栈")
    valid15 = np.repeat(np.repeat(valid30, 2, axis=0), 2, axis=1)
    stack = compute_features(sharp, valid15, order, window)
    feat15 = REPO / "data" / "processed" / "features" / "feat_2021_15m.tif"
    valid15_path = REPO / "data" / "processed" / "features" / "valid_feat_2021_15m.tif"
    write_stack(feat15, stack, t15, crs, order)
    with rasterio.open(
        valid15_path, "w", driver="GTiff", height=h15, width=w15, count=1, dtype="uint8",
        crs=crs, transform=t15, nodata=255, compress="deflate",
    ) as dst:
        dst.write(valid15.astype(np.uint8), 1)
    print(f"      有效像元比 {(valid15 == 1).mean():.4f}")

    print("[5/7] 采样与训练")
    labels = gpd.read_file(LABELS, layer="labels")
    labels, overlap_removed = resolve_overlaps(labels)
    if overlap_removed:
        print(f"      15m 网格下消解重叠：{overlap_removed}")
    split_map = json.loads(SPLIT.read_text(encoding="utf-8"))["groups"]
    purity_cfg = cfg.get("sampling", {}).get("purity", {})
    rules_raw = purity_cfg.get("ranges_2021") or purity_cfg.get("ranges", {})
    rules = {int(k): {n: tuple(v) for n, v in r.items()} for k, r in rules_raw.items()}
    train_df, holdout_df, sample_summary = smp.extract_pixel_samples(
        feat15, valid15_path, labels, split_map, 2021, order, rules
    )
    print(f"      训练 {len(train_df)} / 留出 {len(holdout_df)}")

    tmp = REPO / "data" / "processed" / "samples" / "2021" / "train_15m.csv"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    train_df.to_csv(tmp, index=False)
    split15 = json.loads(SPLIT.read_text(encoding="utf-8"))
    split15["total_train_samples"] = int(len(train_df))
    split15["total_holdout_samples"] = int(len(holdout_df))
    split15_path = REPO / "data" / "processed" / "samples" / "2021" / "split_15m.json"
    split15_path.write_text(json.dumps(split15, ensure_ascii=False, indent=2), encoding="utf-8")

    estimator, model_dict, train_report = cls.train_classifier(tmp, split15_path, cfg, 2021)

    print("[6/7] 推理 + Sieve")
    raw = OUT_DIR / "lulc_2021_15m_raw.tif"
    final = OUT_DIR / "lulc_2021_15m.tif"
    classes = cfg["classes"]
    cls.predict_raster_windowed(feat15, valid15_path, raw, estimator, order, classes,
                                float_nodata=float_nodata, class_nodata=0, chunk_size=512)
    with rasterio.open(raw) as ds:
        raw_arr = ds.read(1)
        raw_profile = ds.profile.copy()
    final_arr = sieve_classification(raw_arr, threshold_pixels=4)
    raw_profile.update(dtype="uint8", nodata=0)
    with rasterio.open(final, "w", **raw_profile) as ds:
        ds.write(final_arr, 1)
    cmap = cls.build_colormap(classes)
    with rasterio.open(final, "r+") as ds:
        ds.write_colormap(1, cmap)

    print("[7/7] 精度与面积")
    y_true = holdout_df["class_id"].to_numpy()
    proba = estimator.predict(holdout_df[order].to_numpy())
    names = {int(c["code"]): c["name"] for c in classes}
    with rasterio.open(final) as ds:
        lulc = ds.read(1)
    valid_mask = lulc > 0
    total = int(valid_mask.sum())
    areas = {
        int(c): {
            "name": names[c],
            "km2_15m": round(int((lulc == c).sum()) * 225 / 1e6, 2),
            "share_15m": round(int((lulc == c).sum()) / total * 100, 2),
        }
        for c in sorted(names)
    }
    with rasterio.open(REPO / "outputs" / "rasters" / "lulc_2021_final_30m.tif") as ds:
        lulc30 = ds.read(1)
    total30 = int((lulc30 > 0).sum())
    for c in areas:
        areas[c]["km2_30m"] = round(int((lulc30 == c).sum()) * 900 / 1e6, 2)
        areas[c]["share_30m"] = round(int((lulc30 == c).sum()) / total30 * 100, 2)

    from sklearn.metrics import confusion_matrix, f1_score

    labels_idx = sorted(names)
    cm = confusion_matrix(y_true, proba, labels=labels_idx)
    oa = float(np.trace(cm) / cm.sum())
    f1s = f1_score(y_true, proba, labels=labels_idx, average=None, zero_division=0)
    per_class = [
        {"class_id": c, "name": names[c], "f1": round(float(f1s[i]), 4),
         "support": int(cm[i].sum())}
        for i, c in enumerate(labels_idx)
    ]

    payload = {
        "product": "lulc_2021_15m",
        "purpose": "visual_comparison_only",
        "pan_scene": SCENE.name,
        "radiometry": "SR 底座 + L1 B8 细节注入",
        "grid": {"width": w15, "height": h15, "res_m": 15.0, "crs": str(crs)},
        "fusion": info,
        "self_check_ndvi_max_abs_diff": drift,
        "overlap_removed_in_memory": overlap_removed,
        "samples": {"train": int(len(train_df)), "holdout": int(len(holdout_df)),
                    "purity_dropped": sample_summary.get("purity_dropped_pixels", {})},
        "accuracy": {"oa_final": round(oa, 4), "per_class": per_class,
                     "caveat": "留出像元与训练规则同源（纯度过滤），仅为内部一致性"},
        "areas": areas,
    }
    (REPORT_DIR / "evaluation_2021_15m.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with (REPO / "outputs" / "tables" / "class_area_2021_15m.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["class_id", "name", "km2_15m", "share_15m_pct", "km2_30m", "share_30m_pct"])
        for c, d in areas.items():
            w.writerow([c, d["name"], d["km2_15m"], d["share_15m"], d["km2_30m"], d["share_30m"]])

    print(f"完成：{final}")
    print(f"  OA(留出) {oa:.4f}")
    for d in areas.values():
        print(f"  {d['name']}: 15m {d['km2_15m']} km² ({d['share_15m']}%) | 30m {d['km2_30m']} km² ({d['share_30m']}%)")


if __name__ == "__main__":
    main()