"""把人工确认的三类候选面写入 2021 年标签文件。

本次确认方式：采用 tools/make_class_candidates.py 中「建议」列（每类得分前 12），
由用户 2026-11-09 确认（"按照建议"）。标签的 provenance 如实记录为
`human_confirmed_candidate` + `annotator=human`，并在 JSON 里写明选择规则是机器排序。

    python -X utf8 tools/apply_class_candidates.py --per-class 12
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
YEAR = 2021
SCENE_DATE = ""
CLASS_NAMES = {1: "城镇及建设用地", 2: "耕地", 3: "林草植被"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=12)
    ap.add_argument("--year", type=int, default=2021)
    ap.add_argument("--label-source", default="human_confirmed_candidate")
    args = ap.parse_args()

    global YEAR, SCENE_DATE
    YEAR = args.year
    with (REPO / "data" / "catalog" / "scenes.csv").open(encoding="utf-8") as fh:
        import csv as _csv

        for row in _csv.DictReader(fh):
            if int(row["year"]) == YEAR and row["selection_status"].lower() == "selected" \
                    and row["processing_level"].upper() in ("L2SP", "L2SR"):
                SCENE_DATE = row["acquisition_date"]

    labels_path = REPO / "data" / "samples" / str(YEAR) / "labels.gpkg"
    cand_path = REPO / "data" / "samples" / str(YEAR) / "class_candidates.gpkg"

    labels = gpd.read_file(labels_path, layer="labels")
    cand = gpd.read_file(cand_path, layer="candidates")

    water_all = labels[labels["class_id"] == 4]

    chosen_frames = []
    for cls in (1, 2, 3):
        pool = cand[cand["prop_class"] == cls].sort_values("score", ascending=False)
        picked = []
        for _, c in pool.iterrows():
            if len(picked) >= args.per_class:
                break
            # 与水体标签重叠的候选直接跳过（水体已有可靠样本，不与之冲突）
            hits = water_all[water_all.geometry.intersects(c.geometry)]
            if any(c.geometry.intersection(w).area > 1.0 for w in hits.geometry):
                continue
            picked.append(c)
        if len(picked) < args.per_class:
            raise ValueError(f"类 {cls} 可用候选不足：需要 {args.per_class}，实有 {len(picked)}")
        chosen_frames.append(gpd.GeoDataFrame(picked, crs=cand.crs))
    chosen = gpd.GeoDataFrame(pd.concat(chosen_frames, ignore_index=True),
                              geometry="geometry", crs=cand.crs)

    # 候选之间、候选与保留类（水体）之间的重叠检查
    overlaps = []
    for cls, sub in chosen.groupby("prop_class"):
        for i in range(len(sub)):
            for j in range(i + 1, len(sub)):
                a, b = sub.iloc[i], sub.iloc[j]
                if a.geometry.intersects(b.geometry):
                    inter = a.geometry.intersection(b.geometry).area
                    if inter > 1.0:
                        overlaps.append({"a": a.cand_id, "b": b.cand_id,
                                         "overlap_m2": round(float(inter), 1)})
    water = labels[labels["class_id"] == 4]
    for _, c in chosen.iterrows():
        hit = water[water.geometry.intersects(c.geometry)]
        for _, w in hit.iterrows():
            inter = c.geometry.intersection(w.geometry).area
            if inter > 1.0:
                overlaps.append({"a": c.cand_id, "b": w["sample_id"],
                                 "overlap_m2": round(float(inter), 1)})

    backup = labels_path.with_name(f"labels.gpkg.bak_Y{YEAR}_class_relabel")
    if not backup.exists():
        shutil.copy2(labels_path, backup)

    rows = []
    for cls in (1, 2, 3):
        sub = chosen[chosen["prop_class"] == cls].reset_index(drop=True)
        for i, c in sub.iterrows():
            gid = f"c{cls}_g{i + 1:02d}"
            rows.append({
                "sample_id": f"{YEAR}_{gid}_p01",
                "group_id": gid,
                "year": YEAR,
                "class_id": cls,
                "label_source": args.label_source,
                "source_date": SCENE_DATE,
                "annotator": "human",
                "review": 1,
                "geometry": c.geometry,
            })
    new_rows = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs=labels.crs)

    kept = labels[labels["class_id"] == 4].copy()
    merged = gpd.GeoDataFrame(pd.concat([new_rows, kept], ignore_index=True),
                              geometry="geometry", crs=labels.crs)
    merged["year"] = merged["year"].astype(int)
    merged["review"] = merged["review"].astype(int)

    if labels_path.exists():
        labels_path.unlink()
    merged.to_file(labels_path, layer="labels", driver="GPKG")

    replaced = {int(c): int((labels["class_id"] == c).sum()) for c in (1, 2, 3)}
    record = {
        "date": str(date(2026, 11, 9)),
        "year": YEAR,
        "scene_date": SCENE_DATE,
        "selection_rule": f"top{args.per_class}_by_score_per_class",
        "confirmed_by": "user",
        "confirmation_note": f"用户 2026-11-09 回复「按照建议」，{YEAR} 年采用候选清单中每类得分前 {args.per_class} 个；未逐个目视判读",
        "label_source": args.label_source,
        "per_class": {
            str(c): {
                "name": CLASS_NAMES[c],
                "replaced_polygons": replaced[c],
                "new_polygons": int(len(chosen[chosen["prop_class"] == c])),
                "candidates": [
                    {"cand_id": r.cand_id, "sample_id": f"{YEAR}_c{c}_g{i + 1:02d}_p01",
                     "township": r["township"], "area_ha": round(float(r.area_ha), 2),
                     "ndvi": round(float(r.ndvi), 4), "ndbi": round(float(r.ndbi), 4),
                     "slope": round(float(r.slope), 2)}
                    for i, r in chosen[chosen["prop_class"] == c].reset_index(drop=True).iterrows()
                ],
            }
            for c in (1, 2, 3)
        },
        "kept_unchanged": {"class_id": 4, "polygons": int(len(kept))},
        "overlaps": overlaps,
    }
    out = REPO / "reports" / "samples" / f"{YEAR}_class_relabel.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    split = REPO / "data" / "processed" / "samples" / str(YEAR) / "split.json"
    if split.exists():
        split.unlink()
        print(f"已删除旧划分 {split.name}")

    print(f"标签已重建：{len(merged)} 个面（3 类 × {args.per_class} + 水体 {len(kept)}）")
    print(f"重叠：{len(overlaps)} 处")
    print(f"备份：{backup.name}")
    for cls in (1, 2, 3):
        sub = merged[merged["class_id"] == cls]
        print(f"  类 {cls} {CLASS_NAMES[cls]}: {len(sub)} 面，{sub.geometry.area.sum()/1e6:.2f} km²")


if __name__ == "__main__":
    main()