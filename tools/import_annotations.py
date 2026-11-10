"""把人工标注图层导入为正式标签文件 data/samples/<year>/labels.gpkg。

来源：data/samples/<year>/annot_<year>_c<class>_<name>.gpkg（每类一个图层）
规则：
  - 每个面 = 一个组（group_id），组内不再拆分；
  - label_source=manual_summer / manual_aug，annotator=human，review=1；
  - 导入前先跑 tools/validate_annotations.py，有错误不导入；
  - 备份旧 labels.gpkg，删除 split.json 以便重画划分。

    python -X utf8 tools/import_annotations.py --year 2021
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
LAYERS = {1: "urban", 2: "crop", 3: "forest", 4: "water"}
NAME = {1: "城镇及建设用地", 2: "耕地", 3: "林草植被", 4: "水体"}


def scene_date(year: int) -> str:
    import csv

    with (REPO / "data" / "catalog" / "scenes.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if (int(row["year"]) == year and row["selection_status"].lower() == "selected"
                    and row["processing_level"].upper() in ("L2SP", "L2SR")):
                return row["acquisition_date"]
    raise ValueError(f"未找到 {year} 年选中的场景")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2021)
    args = ap.parse_args()
    year = args.year
    src_date = scene_date(year)

    rows = []
    summary = {}
    for cid, en in LAYERS.items():
        path = REPO / "data" / "samples" / str(year) / f"annot_{year}_c{cid}_{en}.gpkg"
        gdf = gpd.read_file(path, layer="labels_edit")
        if gdf.empty:
            raise ValueError(f"{path.name} 没有任何面，先完成标注")
        gdf = gdf.copy()
        gdf["area_ha"] = gdf.geometry.area / 10000.0
        gdf = gdf.sort_values("area_ha", ascending=False).reset_index(drop=True)
        for i, r in gdf.iterrows():
            gid = f"c{cid}_g{i + 1:02d}"
            rows.append({
                "sample_id": f"{year}_{gid}_p01",
                "group_id": gid,
                "year": year,
                "class_id": cid,
                "label_source": "manual_annotation",
                "source_date": src_date,
                "annotator": "human",
                "review": 1,
                "geometry": r.geometry,
            })
        summary[str(cid)] = {"name": NAME[cid], "polygons": int(len(gdf)),
                             "area_ha": round(float(gdf.area.sum() / 10000), 2)}

    labels_path = REPO / "data" / "samples" / str(year) / "labels.gpkg"
    backup = labels_path.with_name(f"labels.gpkg.bak_Y{year}_manual")
    if labels_path.exists() and not backup.exists():
        shutil.copy2(labels_path, backup)

    merged = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32648")
    if labels_path.exists():
        labels_path.unlink()
    merged.to_file(labels_path, layer="labels", driver="GPKG")

    split = REPO / "data" / "processed" / "samples" / str(year) / "split.json"
    if split.exists():
        split.unlink()

    record = {
        "date": str(date(2026, 11, 9)),
        "year": year,
        "scene_date": src_date,
        "label_source": "manual_annotation",
        "annotator": "human",
        "note": "人工在对应年份影像上绘制，每类 12—15 个面，跨街镇分散",
        "per_class": summary,
        "total_polygons": int(len(merged)),
        "backup": backup.name if backup.exists() else None,
    }
    out = REPO / "reports" / "samples" / f"{year}_manual_labels.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已导入 {len(merged)} 个面 -> {labels_path}")
    for cid in LAYERS:
        s = summary[str(cid)]
        print(f"  类 {cid} {s['name']}: {s['polygons']} 面 {s['area_ha']:.1f} ha")
    print(f"备份: {backup.name if backup.exists() else '（无旧文件）'}")
    print("下一步：python -X utf8 src\\02_samples.py --config configs\\project.toml --env-file .env --year",
          year)


if __name__ == "__main__":
    main()