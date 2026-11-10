"""消除人工标注图层之间的重叠：按优先级从高到低裁切。

优先级：城镇(1) > 水体(4) > 耕地(2) > 林草(3)
即低优先级的面在与高优先级相交处被裁掉，裁切量写入 JSON 备查。

    python -X utf8 tools/resolve_annotation_overlaps.py --year 2021
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import union_all as shp_union_all

REPO = Path(__file__).resolve().parents[1]
LAYERS = {1: "urban", 2: "crop", 3: "forest", 4: "water"}
NAME = {1: "城镇及建设用地", 2: "耕地", 3: "林草植被", 4: "水体"}
PRIORITY = [1, 4, 2, 3]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2021)
    args = ap.parse_args()
    year = args.year

    paths = {c: REPO / "data" / "samples" / str(year) / f"annot_{year}_c{c}_{e}.gpkg"
             for c, e in LAYERS.items()}
    frames = {c: gpd.read_file(p, layer="labels_edit") for c, p in paths.items()}

    taken = None
    report = []
    for cid in PRIORITY:
        gdf = frames[cid].copy()
        before = gdf.geometry.area.sum()
        if taken is not None and not taken.is_empty:
            clipped = gdf.geometry.difference(taken)
            gdf["geometry"] = clipped
            gdf = gdf[~gdf.geometry.is_empty].copy()
            gdf = gdf[gdf.geometry.area > 100.0].copy()   # 100 m² 以下视为噪声碎片
        after = gdf.geometry.area.sum()
        if before - after > 1.0:
            report.append({
                "class_id": cid, "name": NAME[cid],
                "polygons_before": int(len(frames[cid])),
                "polygons_after": int(len(gdf)),
                "area_before_ha": round(float(before / 10000), 2),
                "area_after_ha": round(float(after / 10000), 2),
                "trimmed_ha": round(float((before - after) / 10000), 2),
            })
        frames[cid] = gdf
        geom = shp_union_all(list(gdf.geometry))
        taken = geom if taken is None else shp_union_all([taken, geom])

    from osgeo import ogr

    for cid in (1, 2, 3, 4):
        p = paths[cid]
        backup = p.with_name(p.stem + ".bak_pre_overlap.gpkg")
        if not backup.exists():
            shutil.copy2(p, backup)
        out = frames[cid].copy()
        if not out.empty and "note" not in out.columns:
            out["note"] = ""
        # 原地改写要素（QGIS 打开着文件时无法删除重建）
        ds = ogr.Open(str(p), 1)
        lyr = ds.GetLayerByName("labels_edit")
        fids = [f.GetFID() for f in lyr]
        for fid in fids:
            lyr.DeleteFeature(fid)
        lyr.ResetReading()
        for _, r in out.iterrows():
            feat = ogr.Feature(lyr.GetLayerDefn())
            feat.SetGeometry(ogr.CreateGeometryFromWkb(r.geometry.wkb))
            if "note" in out.columns and pd.notna(r.get("note")):
                feat.SetField("note", str(r["note"]))
            lyr.CreateFeature(feat)
        ds = None

    record = {
        "date": str(date(2026, 11, 10)),
        "year": year,
        "rule": "按优先级 城镇>水体>耕地>林草 裁切重叠部分，100 m² 以下碎片丢弃",
        "changes": report,
        "final": {str(c): {"name": NAME[c], "polygons": int(len(frames[c])),
                           "area_ha": round(float(frames[c].geometry.area.sum() / 10000), 2)}
                  for c in (1, 2, 3, 4)},
    }
    out = REPO / "reports" / "samples" / f"{year}_annotation_overlap_resolution.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    if report:
        print("已消除重叠：")
        for r in report:
            print(f"  {r['name']}: {r['area_before_ha']:.0f} -> {r['area_after_ha']:.0f} ha "
                  f"(裁掉 {r['trimmed_ha']:.1f} ha, 面数 {r['polygons_before']}->{r['polygons_after']})")
    else:
        print("未发现重叠，无需处理")
    print(f"记录 -> {out.name}")


if __name__ == "__main__":
    main()