"""按年份生成 城镇/耕地/林草 三类候选面，供人工复核。

设计原则：
  - 候选面只是机器初筛，全部 review=0、label_source=candidate，人工确认后才成为标签；
  - 每类判据分开写，判据只用于"圈出可能的候选"，不是分类规则；
  - 城镇类按面积分档抽样（大/中/小），避免全是工业园；
  - 耕地与林草用坡度做初分（平原/坡地），最终仍由人看影像定。

    python -X utf8 tools/make_class_candidates.py --year 1992
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask, rasterize, shapes as rio_shapes
from rasterio.warp import Resampling, reproject
from scipy import ndimage
from shapely.geometry import shape

REPO = Path(__file__).resolve().parents[1]
YEAR = 2021
SCENE = ""
SCENE_DATE = ""
PIXEL_HA = 0.09
MIN_SEPARATION_M = 1500.0

# 早期 TM 影像城镇含较多树木、林草分布也不同，按年份调整初筛阈值（仅影响候选圈选）
YEAR_OVERRIDES = {
    1992: {
        1: {"ndvi_max": 0.45, "ndbi_min": -0.15},
        3: {"slope_min": 2.0},
    },
}

# 每类的初筛判据与配额
SPECS = {
    1: {"name": "城镇及建设用地", "ndvi_max": 0.40, "ndbi_min": -0.10, "mndwi_max": 0.0,
        "area_min_ha": 3.0, "quota": 24, "color": "#1F77B4"},
    2: {"name": "耕地", "ndvi_min": 0.45, "ndvi_max": 0.75, "slope_max": 3.0,
        "area_min_ha": 15.0, "quota": 20, "color": "#E6C84F"},
    3: {"name": "林草植被", "ndvi_min": 0.65, "slope_min": 3.0,
        "area_min_ha": 5.0, "quota": 20, "color": "#2E8B57"},
}


def slope_degrees(dem_path: Path, transform, shape_hw) -> np.ndarray:
    """复用 preprocess 的地形算法计算坡度（度），保证与特征工程口径一致。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from rs_urban.preprocess import _compute_terrain_arrays

    import tomllib

    cfg = tomllib.loads((REPO / "configs" / "project.toml").read_text(encoding="utf-8"))
    fs = cfg["feature_stack"]
    _dem, slope, _twi, _ok = _compute_terrain_arrays(
        dem_path, transform, "EPSG:32648", shape_hw[0], shape_hw[1],
        float_nodata=-9999.0,
        dem_smooth_window=int(fs["dem_smooth_window"]),
        twi_buffer_cells=int(fs["twi_buffer_cells"]),
    )
    return slope


def poly_stats(geoms, arrays, transform, shape_hw) -> dict[str, list[float]]:
    out = {k: [] for k in arrays}
    for geom in geoms:
        inside = rasterize([(geom, 1)], out_shape=shape_hw, transform=transform,
                           fill=0, dtype="uint8").astype(bool)
        for k, arr in arrays.items():
            vals = arr[inside]
            vals = vals[np.isfinite(vals)]
            out[k].append(float(vals.mean()) if vals.size else np.nan)
    return out


def components(mask: np.ndarray, min_pixels: int, transform):
    lab, n = ndimage.label(mask)
    if n == 0:
        return []
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = np.isin(lab, np.flatnonzero(sizes >= min_pixels) + 1)
    polys = []
    for geom, value in rio_shapes(keep.astype("uint8"), transform=transform):
        if value != 1:
            continue
        poly = shape(geom)
        if poly.area / 10000.0 >= min_pixels * PIXEL_HA * 0.95:
            polys.append(poly)
    return polys


def greedy_spread(gdf, quota: int, size_bins=None):
    """按得分降序、保持最小间距地挑选；size_bins 用于面积分档均衡取样。"""
    picked = []

    def far_enough(row):
        return all(((row.cx - p.cx) ** 2 + (row.cy - p.cy) ** 2) ** 0.5 >= MIN_SEPARATION_M
                   for p in picked)

    if size_bins is None:
        for _, row in gdf.iterrows():
            if len(picked) >= quota:
                break
            if far_enough(row):
                picked.append(row)
    else:
        per_bin = max(1, quota // len(size_bins))
        for lo, hi in size_bins:
            subset = gdf[(gdf.area_ha >= lo) & (gdf.area_ha < hi)]
            taken = 0
            for _, row in subset.iterrows():
                if taken >= per_bin or len(picked) >= quota:
                    break
                if far_enough(row):
                    picked.append(row)
                    taken += 1
        for _, row in gdf.iterrows():
            if len(picked) >= quota:
                break
            if far_enough(row):
                picked.append(row)
    return picked


def load_scene(year: int) -> tuple[str, str]:
    """从 data/catalog/scenes.csv 取该年被选中的 L2SP 产品与成像日期。"""
    scenes = REPO / "data" / "catalog" / "scenes.csv"
    with scenes.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if int(row["year"]) == year and row["processing_level"].upper() in ("L2SP", "L2SR"):
                if row["selection_status"].lower() == "selected":
                    return row["product_id"], row["acquisition_date"]
    raise ValueError(f"scenes.csv 中没有 {year} 年选中的 L2SP 场景")


def main() -> None:
    global YEAR, SCENE, SCENE_DATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2021)
    args = ap.parse_args()
    YEAR = args.year
    SCENE, SCENE_DATE = load_scene(YEAR)
    for cls, patch in YEAR_OVERRIDES.get(YEAR, {}).items():
        SPECS[cls].update(patch)

    feat_path = REPO / "data" / "processed" / "features" / f"feat_{YEAR}_30m.tif"
    valid_path = REPO / "data" / "processed" / str(YEAR) / "valid_features_30m.tif"
    bounds_path = REPO / "data" / "processed" / "boundaries" / "xindu_2021.gpkg"
    dem_path = REPO / "data" / "raw" / "dem" / "xindu_dem_mosaic_30m.tif"

    with rasterio.open(feat_path) as ds:
        names = list(ds.descriptions)
        arrays = {n: ds.read(i + 1).astype("float32") for i, n in enumerate(names)}
        transform, crs, shape_hw = ds.transform, ds.crs, (ds.height, ds.width)
    with rasterio.open(valid_path) as ds:
        valid = ds.read(1) == 1

    area_gdf = gpd.read_file(bounds_path, layer="study_area").to_crs(crs)
    towns = gpd.read_file(bounds_path, layer="townships").to_crs(crs)
    inside = geometry_mask([area_gdf.union_all()], out_shape=shape_hw, transform=transform,
                           invert=True)

    slope = slope_degrees(dem_path, transform, shape_hw)
    base = valid & inside

    ndvi, ndbi, mndwi = arrays["ndvi"], arrays["ndbi"], arrays["mndwi"]
    tex_std = arrays.get("nir_std", np.zeros_like(ndvi))

    raw_masks = {
        1: (ndvi < SPECS[1]["ndvi_max"]) & (ndbi > SPECS[1]["ndbi_min"]) & (mndwi < 0.0) & base,
        2: (ndvi >= SPECS[2]["ndvi_min"]) & (ndvi <= SPECS[2]["ndvi_max"])
           & (slope < SPECS[2]["slope_max"]) & base,
        3: (ndvi >= SPECS[3]["ndvi_min"]) & (slope >= SPECS[3]["slope_min"]) & base,
    }
    # 互斥分配：城镇 > 林草 > 耕地，保证一个像元只属于一类
    assigned = np.zeros(shape_hw, dtype=bool)
    masks = {}
    for cls in (1, 3, 2):
        masks[cls] = raw_masks[cls] & ~assigned
        assigned |= masks[cls]

    stats_arrays = {"ndvi": ndvi, "ndbi": ndbi, "mndwi": mndwi, "slope": slope, "tex_std": tex_std}
    frames = []
    for cls, spec in SPECS.items():
        mask = ndimage.binary_opening(masks[cls], structure=np.ones((3, 3)))
        min_px = int(spec["area_min_ha"] / PIXEL_HA)
        polys = components(mask, min_px, transform)
        if not polys:
            print(f"[警告] 类 {cls} 无候选")
            continue
        gdf = gpd.GeoDataFrame(geometry=polys, crs=crs)
        gdf["area_ha"] = gdf.geometry.area / 10000.0
        cents = gdf.geometry.representative_point()
        gdf["cx"], gdf["cy"] = cents.x, cents.y
        st = poly_stats(gdf.geometry, stats_arrays, transform, shape_hw)
        for k, v in st.items():
            gdf[k] = v
        gdf = gdf.dropna(subset=["ndvi"]).reset_index(drop=True)

        if cls == 1:
            gdf["score"] = (gdf.ndbi - gdf.ndvi) + 0.02 * np.log1p(gdf.area_ha)
            bins = [(3.0, 8.0), (8.0, 30.0), (30.0, 1e9)]
        elif cls == 2:
            gdf["score"] = -gdf.tex_std + 0.001 * gdf.area_ha
            bins = None
        else:
            gdf["score"] = gdf.slope + gdf.tex_std
            bins = None

        gdf = gdf.sort_values("score", ascending=False).reset_index(drop=True)
        picked = greedy_spread(gdf, spec["quota"], bins)
        sub = gpd.GeoDataFrame(picked, crs=crs).reset_index(drop=True)
        sub["prop_class"] = cls
        sub["cand_id"] = [f"{YEAR}_{'u' if cls == 1 else ('a' if cls == 2 else 'f')}{i + 1:02d}"
                          for i in range(len(sub))]
        sub["township"] = ""
        joined = gpd.sjoin(sub, towns[["name", "geometry"]], how="left", predicate="intersects")
        sub["township"] = joined[~joined.index.duplicated(keep="first")]["name"].to_numpy()
        frames.append(sub)
        print(f"类 {cls}（{spec['name']}）：候选 {len(sub)} 个，"
              f"总面积 {sub.area_ha.sum():.0f} ha")

    allc = gpd.GeoDataFrame(
        __import__("pandas").concat(frames, ignore_index=True), geometry="geometry", crs=crs
    )
    allc["review"] = 0
    allc["label_source"] = "candidate"
    cols = ["cand_id", "prop_class", "township", "area_ha", "ndvi", "ndbi", "mndwi",
            "slope", "tex_std", "score", "review", "label_source"]
    allc = allc[cols + ["cx", "cy", "geometry"]]

    out = REPO / "data" / "samples" / str(YEAR) / "class_candidates.gpkg"
    if out.exists():
        out.unlink()
    allc.to_file(out, layer="candidates", driver="GPKG")

    csv_path = REPO / "data" / "samples" / str(YEAR) / "class_candidates.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for _, r in allc.iterrows():
            w.writerow([r.cand_id, r.prop_class, r.township, f"{r.area_ha:.2f}",
                        f"{r.ndvi:.4f}", f"{r.ndbi:.4f}", f"{r.mndwi:.4f}",
                        f"{r.slope:.2f}", f"{r.tex_std:.4f}", f"{r.score:.4f}", 0, "candidate"])

    write_worksheet(allc)
    render(allc, area_gdf, arrays, shape_hw, transform)

    print(f"\n合计 {len(allc)} 个候选 -> {out}")
    for cls in (1, 2, 3):
        sub = allc[allc.prop_class == cls]
        print(f"  {SPECS[cls]['name']}: {len(sub)} 个，{sub.area_ha.sum():.0f} ha，"
              f"街镇覆盖 {sub.township.nunique()} 个")


def write_worksheet(allc) -> None:
    md = REPO / "reports" / "samples" / f"{YEAR}_class_candidates.md"
    lines = [
        f"# {YEAR} 年三类候选面复核清单（{SCENE_DATE} 影像）",
        "",
        f"- 影像：`{SCENE}`（{SCENE_DATE}）",
        "- **候选面为机器初筛，未经人工确认**：`review=0`、`label_source=candidate`。",
        "- 判据见下表；确认方式：在「采用」列填 1，并在备注写地物类型（老城/工业园/乡村居民点 等）。",
        "",
        "| 类 | 判据 | 配额 |",
        "| --- | --- | ---: |",
        "| 1 城镇 | NDVI < 0.40、NDBI > −0.10、MNDWI < 0，按大/中/小面积分档各取，间距 ≥ 1.5 km | 24 |",
        "| 2 耕地 | 0.45 ≤ NDVI ≤ 0.75、坡度 < 3°、连片 ≥ 15 ha | 20 |",
        "| 3 林草 | NDVI ≥ 0.65、坡度 ≥ 3°、连片 ≥ 5 ha | 20 |",
        "",
    ]
    for cls, spec in SPECS.items():
        sub = allc[allc.prop_class == cls].sort_values("score", ascending=False)
        suggested = set(sub.sort_values("score", ascending=False).head(12)["cand_id"])
        lines += [
            f"## {cls}. {spec['name']}（{len(sub)} 个，合计 {sub.area_ha.sum():.0f} ha）",
            "",
            "| 编号 | 街镇 | 面积 ha | NDVI | NDBI | 坡度° | 纹理(σ) | 建议 | 采用 | 地物类型/备注 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | --- |",
        ]
        for _, r in sub.iterrows():
            tick = "✓" if r.cand_id in suggested else ""
            lines.append(
                f"| {r.cand_id} | {r.township} | {r.area_ha:.2f} | {r.ndvi:.3f} | {r.ndbi:.3f} | "
                f"{r.slope:.1f} | {r.tex_std:.3f} | {tick} |  |  |"
            )
        lines.append("")
    lines += [
        "## 说明",
        "",
        "- 城镇类每档面积至少取 3 个：小（3–8 ha，乡村居民点）、中（8–30 ha，镇区）、大（>30 ha，城区/工业园）；",
        "  若某档不足，用其他档补足。",
        "- 耕地与林草在 7 月 NDVI 很接近（水稻与苗木都绿），坡度只是初分依据，最终按真彩色纹理判断：",
        "  耕地多为规则田块、边界笔直；林草多为不规则、纹理粗糙、坡度较大的坡地或林盘。",
        "- 候选不足时可放宽：城镇 NDVI < 0.45；耕地 NDVI 下限 0.40；林草 NDVI ≥ 0.60。",
    ]
    md.write_text("\n".join(lines), encoding="utf-8")


def render(allc, area_gdf, arrays, shape_hw, transform) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Patch

    font_manager.fontManager.addfont(r"C:\Windows\Fonts\msyh.ttc")
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    h, w = shape_hw
    rgb = np.dstack([arrays["red"], arrays["green"], arrays["blue"]]).astype("float32")
    nodata = rgb[:, :, 0] < -1000
    flat = rgb.reshape(-1, 3)
    ok = np.isfinite(flat).all(axis=1) & (flat[:, 0] > -1000)
    lo = np.percentile(flat[ok], 2, axis=0)
    hi = np.percentile(flat[ok], 98, axis=0)
    rgb = np.clip((rgb - lo) / (hi - lo + 1e-6), 0, 1)
    rgb[nodata] = np.nan

    left, top = transform.c, transform.f
    right, bottom = left + w * transform.a, top + h * transform.e
    b = area_gdf.total_bounds

    fig, ax = plt.subplots(figsize=(16, 13), dpi=170)
    ax.imshow(rgb, extent=(left, right, bottom, top), origin="upper")
    area_gdf.boundary.plot(ax=ax, color="#222222", linewidth=1.0)
    for cls, spec in SPECS.items():
        sub = allc[allc.prop_class == cls]
        if sub.empty:
            continue
        sub.boundary.plot(ax=ax, color=spec["color"], linewidth=1.6)
        for _, r in sub.iterrows():
            ax.annotate(r.cand_id.replace("2021_", ""), (r.cx, r.cy), color="white", fontsize=7,
                        ha="center", fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.12", fc=spec["color"], ec="none", alpha=0.85))
    ax.set_xlim(b[0], b[2])
    ax.set_ylim(b[1], b[3])
    ax.axis("off")
    ax.set_title(f"{SCENE_DATE} 三类候选面：蓝=城镇、黄=耕地、绿=林草", fontsize=13)
    ax.legend(handles=[Patch(color=SPECS[c]["color"], label=SPECS[c]["name"]) for c in SPECS],
              loc="lower right", fontsize=10, framealpha=0.9)
    out = REPO / "outputs" / "maps" / f"candidates_{YEAR}_classes.png"
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"预览图 -> {out}")


if __name__ == "__main__":
    main()