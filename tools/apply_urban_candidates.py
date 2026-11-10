"""把人工确认的城镇类候选面写入 2021 年标签文件。

前置：tools/make_urban_candidates.py 已生成候选面。
本次确认方式：按建筑得分取前 8 个候选（用户 2026-11-09 确认）。
写入后：
  - 旧的 8 个城镇面被替换（原文件备份为 labels.gpkg.bak_pre_summer_relabel）；
  - 其余三类（耕地/林草/水体）保持不动；
  - 记录 reports/samples/2021_urban_relabel.json，含旧→新映射与判据。

    python -X utf8 tools/apply_urban_candidates.py --top 8
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
SCENE_DATE = "2021-07-31"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--ids", nargs="*", default=None, help="显式指定候选编号，优先于 --top")
    args = ap.parse_args()

    labels_path = REPO / "data" / "samples" / str(YEAR) / "labels.gpkg"
    cand_path = REPO / "data" / "samples" / str(YEAR) / "urban_candidates.gpkg"

    labels = gpd.read_file(labels_path, layer="labels")
    cand = gpd.read_file(cand_path, layer="candidates")

    if args.ids:
        chosen = cand[cand["cand_id"].isin(args.ids)].copy()
        if len(chosen) != len(args.ids):
            raise ValueError(f"候选编号不存在: {set(args.ids) - set(chosen['cand_id'])}")
        rule = f"explicit_ids={args.ids}"
    else:
        chosen = cand.sort_values("score", ascending=False).head(args.top).copy()
        rule = f"top{args.top}_by_score"

    chosen = chosen.sort_values("score", ascending=False).reset_index(drop=True)
    if len(chosen) != args.top:
        raise ValueError(f"需要 {args.top} 个候选面，实际取到 {len(chosen)} 个")

    # 与其他类别的重叠检查（重叠说明同一个面被标成两类，需要人工判断）
    others = labels[labels["class_id"] != 1]
    overlap_report = []
    for _, c in chosen.iterrows():
        hit = others[others.geometry.intersects(c.geometry)]
        if len(hit):
            inter = sum(c.geometry.intersection(o).area for o in hit.geometry)
            if inter > 1.0:
                overlap_report.append({
                    "cand_id": c.cand_id,
                    "overlap_area_m2": round(float(inter), 1),
                    "overlap_ratio": round(float(inter / c.geometry.area), 4),
                    "with": hit["sample_id"].tolist(),
                })

    old_c1 = labels[labels["class_id"] == 1].copy()
    backup = labels_path.with_name(f"labels.gpkg.bak_pre_summer_relabel")
    if not backup.exists():
        shutil.copy2(labels_path, backup)

    rows = []
    for i, c in chosen.iterrows():
        gid = f"c1_g{i + 1:02d}"
        rows.append({
            "sample_id": f"2021_{gid}_p01",
            "group_id": gid,
            "year": YEAR,
            "class_id": 1,
            "label_source": "human_confirmed_candidate",
            "source_date": SCENE_DATE,
            "annotator": "human",
            "review": 1,
            "geometry": c.geometry,
        })
    new_c1 = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs=labels.crs)

    merged = gpd.GeoDataFrame(
        pd.concat([new_c1, labels[labels["class_id"] != 1]], ignore_index=True),
        geometry="geometry", crs=labels.crs,
    )
    merged["year"] = merged["year"].astype(int)
    merged["review"] = merged["review"].astype(int)

    if labels_path.exists():
        labels_path.unlink()
    merged.to_file(labels_path, layer="labels", driver="GPKG")

    record = {
        "date": str(date(2026, 11, 9)),
        "year": YEAR,
        "scene_date": SCENE_DATE,
        "selection_rule": rule,
        "confirmed_by": "user",
        "confirmation_note": "用户 2026-11-09 选择「就按得分前 8 个」，候选面由 tools/make_urban_candidates.py 按 NDVI/NDBI 判据生成",
        "replaced_class1": [
            {"sample_id": r.sample_id, "ndvi_jul": None} for r in old_c1.itertuples()
        ],
        "new_class1": [
            {"sample_id": row["sample_id"], "cand_id": c["cand_id"], "township": c["township"],
             "area_ha": round(float(c["area_ha"]), 2),
             "ndvi_mean": round(float(c["ndvi_mean"]), 4),
             "ndbi_mean": round(float(c["ndbi_mean"]), 4)}
            for row, (_, c) in zip(rows, chosen.iterrows())
        ],
        "overlaps_with_other_classes": overlap_report,
    }
    out = REPO / "reports" / "samples" / f"{YEAR}_urban_relabel.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # 需要重画样本划分：标签已变
    split = REPO / "data" / "processed" / "samples" / str(YEAR) / "split.json"
    if split.exists():
        split.unlink()
        print(f"已删除旧划分 {split.name}（标签已变更，必须重画）")

    print(f"已替换城镇类：{len(old_c1)} 个旧面 -> {len(chosen)} 个候选面")
    print(chosen[["cand_id", "township", "area_ha", "ndvi_mean", "ndbi_mean"]].round(2)
          .to_string(index=False))
    print(f"重叠检查: {len(overlap_report)} 处与其他类别的重叠")
    print(f"备份: {backup.name}")


if __name__ == "__main__":
    main()