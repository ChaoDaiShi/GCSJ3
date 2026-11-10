"""为 2021 年城镇类生成候选面（仅供人工复核，不自动成为标签）。

判据（全部满足）：
  1. 落在研究区内、特征栅格有效；
  2. NDVI < 0.30（排除植被）；
  3. NDBI > -0.05（偏建筑）；
  4. MNDWI < 0（排除水体）；
  5. 连片面积 >= 3 ha（30 m 网格下约 34 个像元），且经 3×3 开运算去毛刺。

输出：
  data/samples/2021/urban_candidates.gpkg   候选面（review=0，label_source=candidate）
  data/samples/2021/urban_candidates.csv    复核用清单
  reports/samples/2021_urban_candidates.md  判据、清单与旧面问题说明
  reports/samples/2021_urban_candidates.json 机器可读清单
  outputs/maps/candidates_2021_urban.png    真彩色底图 + 候选面编号
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask, rasterize, shapes as rio_shapes
from scipy import ndimage
from shapely.geometry import shape

REPO = Path(__file__).resolve().parents[1]
YEAR = 2021
PIXEL_HA = 900 / 10000.0
MIN_AREA_HA = 3.0
MIN_PIXELS = int(MIN_AREA_HA / PIXEL_HA)
NDVI_MAX = 0.30
NDBI_MIN = -0.05
MIN_SEPARATION_M = 2500.0
MAX_CANDIDATES = 24
SCENE_ID = "LC08_L2SP_129039_20210731_20210804_02_T1"


def poly_means(geoms, arrays: dict[str, np.ndarray], transform, shape_hw) -> dict[str, list[float]]:
    """按面统计各波段均值；逐面栅格化后取均值，避免反复读文件。"""
    out = {name: [] for name in arrays}
    for geom in geoms:
        inside = rasterize([(geom, 1)], out_shape=shape_hw, transform=transform, fill=0,
                           dtype="uint8").astype(bool)
        for name, arr in arrays.items():
            vals = arr[inside]
            out[name].append(float(vals.mean()) if vals.size else np.nan)
    return out


def main() -> None:
    feat_path = REPO / "data" / "processed" / "features" / f"feat_{YEAR}_30m.tif"
    valid_path = REPO / "data" / "processed" / str(YEAR) / "valid_features_30m.tif"
    bounds_path = REPO / "data" / "processed" / "boundaries" / "xindu_2021.gpkg"

    with rasterio.open(feat_path) as ds:
        names = list(ds.descriptions)
        arrays = {n: ds.read(i + 1).astype("float32") for i, n in enumerate(names)}
        transform, crs = ds.transform, ds.crs
        shape_hw = (ds.height, ds.width)

    with rasterio.open(valid_path) as ds:
        valid = ds.read(1) == 1

    area_gdf = gpd.read_file(bounds_path, layer="study_area").to_crs(crs)
    towns = gpd.read_file(bounds_path, layer="townships").to_crs(crs)
    aoi = area_gdf.union_all()
    inside_aoi = geometry_mask([aoi], out_shape=shape_hw, transform=transform, invert=True)

    hit = (
        (arrays["ndvi"] < NDVI_MAX)
        & (arrays["ndbi"] > NDBI_MIN)
        & (arrays["mndwi"] < 0.0)
        & valid
        & inside_aoi
    )
    hit = ndimage.binary_opening(hit, structure=np.ones((3, 3)))
    labeled, n_lab = ndimage.label(hit)
    sizes = ndimage.sum(hit, labeled, range(1, n_lab + 1))
    keep = np.isin(labeled, np.flatnonzero(sizes >= MIN_PIXELS) + 1)

    # rio_shapes 会同时输出背景（值 0）区域，必须按值过滤，否则会得到整幅栅格的外框
    polys = []
    for geom, value in rio_shapes(keep.astype("uint8"), transform=transform):
        if value != 1:
            continue
        poly = shape(geom)
        if poly.area / 10000.0 >= MIN_AREA_HA:
            polys.append(poly)
    gdf = gpd.GeoDataFrame(geometry=polys, crs=crs)
    gdf["area_ha"] = gdf.geometry.area / 10000.0
    cents = gdf.geometry.representative_point()
    gdf["cx"], gdf["cy"] = cents.x, cents.y

    means = poly_means(gdf.geometry, {"ndvi": arrays["ndvi"], "ndbi": arrays["ndbi"],
                                      "mndwi": arrays["mndwi"]}, transform, shape_hw)
    gdf["ndvi_mean"] = means["ndvi"]
    gdf["ndbi_mean"] = means["ndbi"]
    gdf["mndwi_mean"] = means["mndwi"]
    gdf = gdf.dropna(subset=["ndvi_mean"]).reset_index(drop=True)

    joined = gpd.sjoin(gdf, towns[["name", "geometry"]], how="left", predicate="intersects")
    gdf["township"] = joined[~joined.index.duplicated(keep="first")]["name"].to_numpy()

    gdf["score"] = (gdf["ndbi_mean"] - gdf["ndvi_mean"]) + 0.02 * np.log1p(gdf["area_ha"])
    gdf = gdf.sort_values("score", ascending=False).reset_index(drop=True)

    picked = []
    for _, row in gdf.iterrows():
        if len(picked) >= MAX_CANDIDATES:
            break
        far = all(((row.cx - p.cx) ** 2 + (row.cy - p.cy) ** 2) ** 0.5 >= MIN_SEPARATION_M
                  for p in picked)
        if far:
            picked.append(row)
    cand = gpd.GeoDataFrame(picked, crs=crs).reset_index(drop=True)
    cand["cand_id"] = [f"2021_u{i + 1:02d}" for i in range(len(cand))]
    cand["proposed_class"] = 1
    cand["review"] = 0
    cand["label_source"] = "candidate"

    out_gpkg = REPO / "data" / "samples" / str(YEAR) / "urban_candidates.gpkg"
    out_gpkg.parent.mkdir(parents=True, exist_ok=True)
    if out_gpkg.exists():
        out_gpkg.unlink()
    cand.to_file(out_gpkg, layer="candidates", driver="GPKG")

    out_csv = REPO / "data" / "samples" / str(YEAR) / "urban_candidates.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["cand_id", "township", "area_ha", "ndvi_mean", "ndbi_mean", "score",
                    "review", "label_source"])
        for _, r in cand.iterrows():
            w.writerow([r.cand_id, r.township, f"{r.area_ha:.2f}", f"{r.ndvi_mean:.4f}",
                        f"{r.ndbi_mean:.4f}", f"{r.score:.4f}", 0, "candidate"])

    old = gpd.read_file(REPO / "data" / "samples" / str(YEAR) / "labels.gpkg", layer="labels")
    old_means = poly_means(old.geometry, {"ndvi": arrays["ndvi"]}, transform, shape_hw)
    old["ndvi_jul"] = old_means["ndvi"]

    md = REPO / "reports" / "samples" / f"{YEAR}_urban_candidates.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {YEAR} 年城镇类候选面复核清单",
        "",
        f"- 影像：`{SCENE_ID}`（2021-07-31）",
        f"- 判据：NDVI < {NDVI_MAX}、NDBI > {NDBI_MIN}、MNDWI < 0、连片 ≥ {MIN_AREA_HA:g} ha、"
        f"相互间距 ≥ {MIN_SEPARATION_M / 1000:.1f} km",
        f"- 候选数量：{len(cand)} 个，按建筑得分（NDBI − NDVI）降序",
        "- **候选面只是机器筛选结果，未经人工确认**：`review=0`、`label_source=candidate`。",
        "",
        "## 1. 候选面",
        "",
        "| 编号 | 街镇 | 面积 ha | NDVI | NDBI | 得分 | 采用(1)/否(0) | 备注 |",
        "| --- | --- | ---: | ---: | ---: | ---: | :---: | --- |",
    ]
    for _, r in cand.iterrows():
        lines.append(f"| {r.cand_id} | {r.township} | {r.area_ha:.2f} | {r.ndvi_mean:.3f} | "
                     f"{r.ndbi_mean:.3f} | {r.score:.3f} |  |  |")
    lines += ["", "## 2. 现有 8 个城镇面在 7 月影像上的表现", "",
              "| 样本 | 7 月 NDVI | 判定 |", "| --- | ---: | --- |"]
    for _, r in old[old["class_id"] == 1].sort_values("ndvi_jul", ascending=False).iterrows():
        flag = "疑似非建成区（NDVI 偏高）" if r.ndvi_jul > 0.40 else "尚可"
        lines.append(f"| {r['sample_id']} | {r.ndvi_jul:.3f} | {flag} |")
    lines += [
        "",
        "## 3. 复核方式",
        "",
        "在 QGIS 中打开 `data/samples/2021/urban_candidates.gpkg`（图层 `candidates`），对照",
        "`outputs/maps/candidates_2021_urban.png` 的真彩色影像，选出 8 个真正是建成区的候选面，",
        "把编号填回上表。确认后据此重建 `labels.gpkg` 的城镇类，再删 `split.json` 重跑 02—05。",
    ]
    md.write_text("\n".join(lines), encoding="utf-8")

    (REPO / "reports" / "samples" / f"{YEAR}_urban_candidates.json").write_text(
        json.dumps(
            {
                "year": YEAR,
                "scene": SCENE_ID,
                "criteria": {"ndvi_max": NDVI_MAX, "ndbi_min": NDBI_MIN, "mndwi_max": 0.0,
                             "min_area_ha": MIN_AREA_HA, "min_separation_m": MIN_SEPARATION_M},
                "candidate_count": int(len(cand)),
                "candidates": [
                    {"cand_id": r.cand_id, "township": r.township,
                     "area_ha": round(float(r.area_ha), 2),
                     "ndvi_mean": round(float(r.ndvi_mean), 4),
                     "ndbi_mean": round(float(r.ndbi_mean), 4),
                     "cx": round(float(r.cx), 1), "cy": round(float(r.cy), 1),
                     "review": 0, "label_source": "candidate"}
                    for _, r in cand.iterrows()
                ],
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    render_preview(cand, old, area_gdf, arrays, shape_hw, transform)

    print(f"候选面 {len(cand)} 个 -> {out_gpkg}")
    print(cand[["cand_id", "township", "area_ha", "ndvi_mean", "ndbi_mean", "score"]]
          .round(3).to_string(index=False))


def render_preview(cand, old, area_gdf, arrays, shape_hw, transform) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

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
    rgb[nodata] = np.nan  # 无效区留白，避免整幅发黑

    left, top = transform.c, transform.f
    right, bottom = left + w * transform.a, top + h * transform.e
    aoi_b = area_gdf.total_bounds  # minx, miny, maxx, maxy

    fig, ax = plt.subplots(figsize=(15, 12), dpi=170)
    ax.imshow(rgb, extent=(left, right, bottom, top), origin="upper")
    area_gdf.boundary.plot(ax=ax, color="#222222", linewidth=1.0)
    old[old["class_id"] == 1].boundary.plot(ax=ax, color="#D62728", linewidth=2.2,
                                            label="现有城镇面（存疑）")
    cand.boundary.plot(ax=ax, color="#1F77B4", linewidth=1.8, label="候选面")
    for _, r in cand.iterrows():
        ax.annotate(r.cand_id.replace("2021_", ""), (r.cx, r.cy), color="white", fontsize=8,
                    ha="center", fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.15", fc="#1F77B4", ec="none", alpha=0.85))
    ax.set_title("2021-07-31 真彩色影像上的城镇类候选面（蓝）与现有存疑面（红）", fontsize=13)
    ax.set_xlim(aoi_b[0], aoi_b[2])
    ax.set_ylim(aoi_b[1], aoi_b[3])
    ax.axis("off")
    ax.legend(loc="lower right", fontsize=10, framealpha=0.9)
    out = REPO / "outputs" / "maps" / "candidates_2021_urban.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"预览图 -> {out}")


if __name__ == "__main__":
    main()