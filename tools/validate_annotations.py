"""校验人工标注图层（每类一个 gpkg，图层名 labels_edit）。

检查项：
  1. 每类面数与最小面积（建议 ≥3 ha，<2 ha 判为不合格）；
  2. 面之间是否重叠（同类允许不重叠，跨类必须不重叠）；
  3. 逐面的 NDVI/NDBI 是否与所标类别自洽（仅提示，不阻断）；
  4. 空间分散度：每类至少覆盖 3 个街镇。

    python -X utf8 tools/validate_annotations.py --year 2021
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio

REPO = Path(__file__).resolve().parents[1]
LAYERS = {1: "urban", 2: "crop", 3: "forest", 4: "water"}
NAME = {1: "城镇及建设用地", 2: "耕地", 3: "林草植被", 4: "水体"}
MIN_HA = 3.0
WARN_HA = 2.0
# 各类的 NDVI 合理区间（仅提示）
NDVI_RANGE = {1: (0.0, 0.45), 2: (0.35, 0.85), 3: (0.45, 0.95), 4: (0.0, 0.45)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2021)
    args = ap.parse_args()
    year = args.year

    feat = REPO / "data" / "processed" / "features" / f"feat_{year}_30m.tif"
    with rasterio.open(feat) as ds:
        names = list(ds.descriptions)
        ndvi = ds.read(names.index("ndvi") + 1).astype("float32")
        ndbi = ds.read(names.index("ndbi") + 1).astype("float32")
        from rasterio.features import rasterize

        transform, shape_hw = ds.transform, (ds.height, ds.width)

    towns = gpd.read_file(REPO / "data" / "processed" / "boundaries" / "xindu_2021.gpkg",
                          layer="townships").to_crs("EPSG:32648")

    problems: list[str] = []
    warnings: list[str] = []
    frames = {}
    for cid, en in LAYERS.items():
        path = REPO / "data" / "samples" / str(year) / f"annot_{year}_c{cid}_{en}.gpkg"
        if not path.exists():
            problems.append(f"缺少图层文件 {path.name}")
            continue
        gdf = gpd.read_file(path, layer="labels_edit")
        if gdf.empty:
            problems.append(f"{NAME[cid]}：没有任何面")
            continue
        gdf["area_ha"] = gdf.geometry.area / 10000.0
        frames[cid] = gdf
        print(f"\n=== {cid} {NAME[cid]}：{len(gdf)} 个面，合计 {gdf.area_ha.sum():.1f} ha ===")
        print(f"  面积 min {gdf.area_ha.min():.2f} / 中位 {gdf.area_ha.median():.2f} / max {gdf.area_ha.max():.2f} ha")
        if len(gdf) < 8:
            problems.append(f"{NAME[cid]}：只有 {len(gdf)} 个面，至少需要 8 个（建议 12）")
        small = gdf[gdf.area_ha < WARN_HA]
        if len(small):
            problems.append(f"{NAME[cid]}：{len(small)} 个面小于 {WARN_HA} ha")

        # NDVI / NDBI 自洽性
        lo, hi = NDVI_RANGE[cid]
        bad = []
        for _, r in gdf.iterrows():
            m = rasterize([(r.geometry, 1)], out_shape=shape_hw, transform=transform,
                          fill=0, dtype="uint8").astype(bool)
            if not m.any():
                continue
            v = ndvi[m]
            v = v[v > -1000]
            if v.size and not (lo <= v.mean() <= hi):
                bad.append((r.get("note") or f"fid{r.name}", float(v.mean()), float(ndbi[m].mean())))
        if bad:
            warnings.append(f"{NAME[cid]}：{len(bad)} 个面的 NDVI 均值超出 [{lo}, {hi}]")
            for note, a, b in bad:
                print(f"  [提示] {note}: NDVI={a:.3f} NDBI={b:.3f}")

        joined = gpd.sjoin(gdf, towns[["name", "geometry"]], how="left", predicate="intersects")
        covered = joined["name"].dropna().nunique()
        print(f"  覆盖街镇 {covered} 个")
        if covered < 3:
            warnings.append(f"{NAME[cid]}：只覆盖 {covered} 个街镇，空间分散度偏低")

    # 跨类重叠
    ids = sorted(frames)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            for _, ra in frames[a].iterrows():
                for _, rb in frames[b].iterrows():
                    if ra.geometry.intersects(rb.geometry):
                        inter = ra.geometry.intersection(rb.geometry).area
                        if inter > 1.0:
                            problems.append(
                                f"{NAME[a]} 与 {NAME[b]} 有重叠 {inter:.0f} m²"
                            )

    print("\n================ 校验结果 ================")
    for w in warnings:
        print(f"[警告] {w}")
    for p in problems:
        print(f"[错误] {p}")
    if not problems:
        print("通过：可以导入")
    else:
        print(f"共 {len(problems)} 项错误，需修正后重新校验")


if __name__ == "__main__":
    main()