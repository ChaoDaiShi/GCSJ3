"""生成「候选样本面」（机器提案，供人工逐条复核），不写 labels.gpkg。

产物：data/samples/<year>/labels_candidates.gpkg，图层 labels_candidates。

**这些面是候选，不是真值。** label_source 一律 candidate_review。在有人逐条
复核（保留/改类/剔除）之前，不得用于训练或精度评价——否则精度会自我实现。

用法：
    python tools/make_sample_candidates.py --year 2021
    python tools/make_sample_candidates.py --year 1992 --per-class 15

算法：
1. 阈值按**当年自身的指数分布分位数**标定（2021 冬春枯黄期与 1992 水稻旺长期
   的绝对值差了 0.3 以上，固定阈值必然失效）；
2. 按优先级给每个有效像元唯一类别（水体 > 建设 > 林草 > 耕地），避免重复认领；
3. 每类开运算去毛刺、腐蚀留内部纯像元（水体窄河道用 3x3，其余 5x5）；
4. 剔除过小（<5x5 像元）与过大（>25 ha，多为混合大斑块）的斑块；
5. 同类候选间保持最小间距，按面积贪心挑选；
6. 面内光谱统计写入属性，供复核时优先排查可疑项。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from scipy import ndimage as ndi
from shapely.geometry import shape

REPO = Path(__file__).resolve().parent.parent

CLASS_NAMES = {1: "城镇及建设用地", 2: "耕地", 3: "林草植被", 4: "水体"}
PRIORITY = (4, 1, 3, 2)

# 每类条件：(指数, 比较符, 分位数%)。分位数由当年有效像元自身分布决定。
PCT_RULES: dict[int, dict[int, list[tuple[str, str, float]]]] = {
    2021: {
        4: [("mndwi", ">", 98.5)],
        1: [("ndbi", ">", 72), ("ndvi", "<", 52)],
        3: [("ndvi", ">", 88), ("ndbi", "<", 35)],
        2: [("ndvi", ">=", 18), ("ndvi", "<=", 72), ("nir_std", "<", 60), ("ndbi", "<=", 75)],
    },
    1992: {
        4: [("mndwi", ">", 99.2)],
        1: [("ndbi", ">", 90), ("ndvi", "<", 15)],
        3: [("ndvi", ">", 60), ("nir_std", ">", 55)],
        2: [("ndvi", ">=", 25), ("ndvi", "<=", 72), ("nir_std", "<", 55)],
    },
}

SEPARATION_M = 300.0
SEPARATION_WATER_M = 180.0
MIN_PIXELS = 25          # 5x5 像元
MIN_PIXELS_WATER = 9     # 3x3 像元（河道窄）
# 面积上限（公顷）。林草成片分布，上限放宽；建设用地/耕地过大则多半混了别的地类。
MAX_AREA_HA = {1: 30.0, 2: 30.0, 3: 60.0, 4: 40.0}


def compute_indices(year: int) -> tuple[dict[str, np.ndarray], dict, np.ndarray]:
    """算指数与 5x5 纹理；返回 (指数, 栅格元信息, 有效掩膜)。"""
    sr = REPO / "data" / "processed" / str(year) / "sr_30m.tif"
    with rasterio.open(sr) as ds:
        # 波段顺序：blue, green, red, nir, swir1, swir2
        blue, green, red, nir, swir1, swir2 = ds.read().astype("float64")
        meta = {"transform": ds.transform, "crs": ds.crs}
    valid = np.all(np.stack([blue, green, red, nir, swir1, swir2]) > -9000.0, axis=0)

    def safe(num, den):
        out = np.zeros_like(num)
        np.divide(num, den, out=out, where=np.abs(den) > 1e-6)
        return out

    idx = {
        "ndvi": safe(nir - red, nir + red),
        "ndbi": safe(swir1 - nir, swir1 + nir),
        "mndwi": safe(green - swir1, green + swir1),
        "bsi": safe((swir1 + red) - (nir + blue), (swir1 + red) + (nir + blue)),
    }
    mean = ndi.uniform_filter(np.where(valid, nir, 0.0), size=5)
    sq = ndi.uniform_filter(np.where(valid, nir, 0.0) ** 2, size=5)
    idx["nir_std"] = np.sqrt(np.maximum(sq - mean ** 2, 0.0))
    return idx, meta, valid


def pick_thresholds(idx: dict[str, np.ndarray], valid: np.ndarray, year: int) -> dict:
    """按当年分布取分位数阈值。"""
    th: dict[str, float] = {}
    for conditions in PCT_RULES[year].values():
        for name, _op, pct in conditions:
            key = f"{name}_{pct:g}"
            if key not in th:
                th[key] = float(np.percentile(idx[name][valid], pct))
    return th


def build_class_map(year: int, idx: dict, valid: np.ndarray, th: dict) -> np.ndarray:
    """按优先级给每个有效像元唯一类别，0 = 未归类。"""
    ops = {">": np.greater, "<": np.less, ">=": np.greater_equal, "<=": np.less_equal}
    labels = np.zeros(idx["ndvi"].shape, dtype="uint8")
    for cls in PRIORITY:
        mask = valid & (labels == 0)
        for name, op, pct in PCT_RULES[year][cls]:
            mask &= ops[op](idx[name], th[f"{name}_{pct:g}"])
        labels[mask] = cls
    return labels


def components_for_class(class_map: np.ndarray, cls: int) -> np.ndarray:
    """某类斑块标记（开运算 + 腐蚀留内部）。水体窄，腐蚀用 3x3。"""
    mask = class_map == cls
    # 闭运算先填补椒盐空洞，否则纹理类条件会把斑块打碎成小点
    mask = ndi.binary_closing(mask, structure=np.ones((5, 5)))
    mask = ndi.binary_opening(mask, structure=np.ones((3, 3)))
    structure = np.ones((5, 5)) if cls in (1, 2) else np.ones((3, 3))
    mask = ndi.binary_erosion(mask, structure=structure)
    return ndi.label(mask)[0]


def pick_candidates(cls: int, class_map: np.ndarray, comps: np.ndarray,
                    idx: dict, meta: dict, per_class: int) -> list[dict]:
    picked: list[dict] = []
    centroids: list[tuple[float, float]] = []
    min_px = MIN_PIXELS_WATER if cls == 4 else MIN_PIXELS
    gap = SEPARATION_WATER_M if cls == 4 else SEPARATION_M
    objects = ndi.find_objects(comps)
    order = sorted(range(1, comps.max() + 1), key=lambda k: -(comps == k).sum())

    for k in order:
        sl = objects[k - 1]
        if sl is None:
            continue
        sub = comps[sl] == k
        area_px = int(sub.sum())
        if area_px < min_px:
            continue
        area_ha = area_px * 900.0 / 10000.0
        if area_ha > MAX_AREA_HA[cls]:
            continue
        row0, row1 = sl[0].start, sl[0].stop
        col0, col1 = sl[1].start, sl[1].stop
        if row0 <= 1 or col0 <= 1 or row1 >= class_map.shape[0] - 1 or col1 >= class_map.shape[1] - 1:
            continue

        mask_full = np.zeros(class_map.shape, dtype=bool)
        mask_full[sl] = sub
        geoms = [shape(g) for g, v in shapes(mask_full.astype("uint8"),
                                             mask=mask_full, transform=meta["transform"]) if v == 1]
        if not geoms:
            continue
        geom = max(geoms, key=lambda g: g.area)
        cx, cy = geom.centroid.x, geom.centroid.y
        if any((cx - px) ** 2 + (cy - py) ** 2 < gap ** 2 for px, py in centroids):
            continue

        vals = {name: idx[name][sl][sub] for name in ("ndvi", "ndbi", "mndwi", "bsi", "nir_std")}
        picked.append({
            "class_id": cls,
            "geometry": geom,
            "area_px": area_px,
            "area_ha": round(area_ha, 2),
            "ndvi_mean": round(float(vals["ndvi"].mean()), 4),
            "ndbi_mean": round(float(vals["ndbi"].mean()), 4),
            "mndwi_mean": round(float(vals["mndwi"].mean()), 4),
            "bsi_mean": round(float(vals["bsi"].mean()), 4),
            "nir_std_mean": round(float(vals["nir_std"].mean()), 5),
        })
        centroids.append((cx, cy))
        if len(picked) >= per_class:
            break
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description="生成候选样本面（待人工复核）")
    ap.add_argument("--year", type=int, required=True, choices=[1992, 2021])
    ap.add_argument("--per-class", type=int, default=15)
    args = ap.parse_args()
    year = args.year

    idx, meta, valid = compute_indices(year)
    th = pick_thresholds(idx, valid, year)
    class_map = build_class_map(year, idx, valid, th)
    print(f"{year} 分位阈值: " + ", ".join(f"{k}={v:.3f}" for k, v in sorted(th.items())))
    print(f"{year} 像元归类占比: " + ", ".join(
        f"{CLASS_NAMES[c]}={float((class_map == c).mean() * 100):.2f}%" for c in PRIORITY))

    rows: list[dict] = []
    for cls in PRIORITY:
        comps = components_for_class(class_map, cls)
        picked = pick_candidates(cls, class_map, comps, idx, meta, args.per_class)
        areas = [p["area_ha"] for p in picked]
        span = f"{min(areas):.1f}-{max(areas):.1f} ha" if areas else "—"
        print(f"  {CLASS_NAMES[cls]}: 候选 {len(picked)} 个（{span}）")
        rows.extend(picked)

    if not rows:
        print("没有候选面，阈值需要调整。")
        return 1

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=meta["crs"])
    towns = gpd.read_file(REPO / "data" / "processed" / "boundaries" / "xindu_2021.gpkg",
                          layer="townships")[["name", "geometry"]]
    joined = gpd.sjoin(gdf, towns, how="left", predicate="intersects")
    joined = joined[~joined.index.duplicated(keep="first")]
    gdf = gdf.loc[joined.index].copy()
    gdf["township"] = joined["name"].values

    gdf = gdf.sort_values(["class_id", "area_px"], ascending=[True, False]).reset_index(drop=True)
    counters = {c: 0 for c in CLASS_NAMES}
    group_ids, sample_ids = [], []
    for _, row in gdf.iterrows():
        c = int(row["class_id"])
        counters[c] += 1
        gid = f"c{c}_g{counters[c]:02d}"
        group_ids.append(gid)
        sample_ids.append(f"{year}_{gid}_p01")
    gdf["sample_id"] = sample_ids
    gdf["group_id"] = group_ids
    gdf["year"] = year
    gdf["label_source"] = "candidate_review"
    gdf["source_date"] = "2021-02-05" if year == 2021 else "1992-08-16"
    gdf["annotator"] = ""
    gdf["keep"] = 1

    cols = ["sample_id", "group_id", "year", "class_id", "label_source", "source_date",
            "annotator", "keep", "township", "area_px", "area_ha",
            "ndvi_mean", "ndbi_mean", "mndwi_mean", "bsi_mean", "nir_std_mean", "geometry"]
    gdf = gdf[cols]
    out = REPO / "data" / "samples" / str(year) / "labels_candidates.gpkg"
    if out.exists():
        out.unlink()
    gdf.to_file(out, layer="labels_candidates", driver="GPKG")

    summary = {
        "year": year,
        "per_class": {CLASS_NAMES[c]: int((gdf["class_id"] == c).sum()) for c in PRIORITY},
        "total": int(len(gdf)),
        "townships_covered": int(gdf["township"].nunique()),
        "area_ha_total": round(float(gdf["area_ha"].sum()), 2),
        "thresholds": {k: round(v, 4) for k, v in th.items()},
        "note": "候选面，未经人工确认不得作为训练/评价真值使用",
    }
    (REPO / "reports" / "data").mkdir(parents=True, exist_ok=True)
    (REPO / "reports" / "data" / f"sample_candidates_{year}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())