"""把四类分类结果按二级类合并为三类（耕地与林草并入「植被」），并重算面积、精度与变化。

背景：1992 年 8 月单期影像上稻田与林木光谱重叠，二级类拆分不可靠；合并后结论可辩护。

    python -X utf8 tools/merge_three_class.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs"
REPORTS = REPO / "reports"

# 四类 -> 三类
MERGE = {1: 1, 2: 2, 3: 2, 4: 3}
NAMES = {1: "城镇及建设用地", 2: "植被（耕地+林草）", 3: "水体"}
COLORS = {1: (217, 95, 2, 255), 2: (107, 163, 85, 255), 3: (55, 126, 184, 255)}


def merge_raster(year: int) -> Path:
    src = OUT / "rasters" / f"lulc_{year}_final_30m.tif"
    dst = OUT / "rasters" / f"lulc_{year}_3class_30m.tif"
    with rasterio.open(src) as ds:
        data = ds.read(1)
        profile = ds.profile.copy()
    out = np.zeros_like(data)
    for k, v in MERGE.items():
        out[data == k] = v
    profile.update(nodata=0)
    with rasterio.open(dst, "w", **profile) as w:
        w.write(out, 1)
        w.write_colormap(1, COLORS)
    return dst


def area_table() -> pd.DataFrame:
    rows = []
    for year in (1992, 2021):
        with rasterio.open(OUT / "rasters" / f"lulc_{year}_3class_30m.tif") as ds:
            a = ds.read(1)
        valid = int((a > 0).sum())
        for cid, name in NAMES.items():
            px = int((a == cid).sum())
            rows.append({
                "year": year,
                "class_id": cid,
                "class_name": name,
                "pixels": px,
                "area_km2": round(px * 900 / 1e6, 2),
                "share_pct": round(px / valid * 100, 2) if valid else 0.0,
            })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "tables" / "class_area_3class.csv", index=False, encoding="utf-8")
    return df


def change_table() -> pd.DataFrame:
    with rasterio.open(OUT / "rasters" / "lulc_1992_3class_30m.tif") as ds:
        a92 = ds.read(1)
    with rasterio.open(OUT / "rasters" / "lulc_2021_3class_30m.tif") as ds:
        a21 = ds.read(1)
    valid = (a92 > 0) & (a21 > 0)
    rows = []
    for cid, name in NAMES.items():
        s92 = (a92 == cid) & valid
        s21 = (a21 == cid) & valid
        rows.append({
            "class_id": cid,
            "class_name": name,
            "area_1992_km2": round(s92.sum() * 900 / 1e6, 2),
            "area_2021_km2": round(s21.sum() * 900 / 1e6, 2),
            "persistent_km2": round((s92 & s21).sum() * 900 / 1e6, 2),
            "added_km2": round((~s92 & s21).sum() * 900 / 1e6, 2),
            "lost_km2": round((s92 & ~s21).sum() * 900 / 1e6, 2),
            "net_km2": round((s21.sum() - s92.sum()) * 900 / 1e6, 2),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "tables" / "change_3class_1992_2021.csv", index=False, encoding="utf-8")
    return df


def merged_accuracy(year: int) -> dict:
    """用同一套留出像元重算三类精度（仅作内部一致性参考）。"""
    from sklearn.metrics import confusion_matrix, f1_score
    ho = pd.read_csv(REPO / "data" / "processed" / "samples" / str(year) / "holdout.csv")
    with rasterio.open(OUT / "rasters" / f"lulc_{year}_final_30m.tif") as ds:
        pred_raw = ds.read(1)[ho["row"].to_numpy(), ho["col"].to_numpy()]
    with rasterio.open(OUT / "rasters" / f"lulc_{year}_raw_30m.tif") as ds:
        pred_nomajority = ds.read(1)[ho["row"].to_numpy(), ho["col"].to_numpy()]
    ref = np.array([MERGE.get(int(c), 0) for c in ho["class_id"]])
    out = {}
    for tag, pred4 in (("raw", pred_nomajority), ("final", pred_raw)):
        pred = np.array([MERGE.get(int(c), 0) for c in pred4])
        mask = (ref > 0) & (pred > 0)
        labels = [1, 2, 3]
        cm = confusion_matrix(ref[mask], pred[mask], labels=labels)
        f1 = f1_score(ref[mask], pred[mask], labels=labels, average=None, zero_division=0)
        out[tag] = {
            "oa": round(float(np.trace(cm) / cm.sum()), 4),
            "per_class_f1": {int(l): round(float(v), 4) for l, v in zip(labels, f1)},
            "confusion_matrix": cm.tolist(),
            "n_pixels": int(mask.sum()),
        }
    return out


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def main() -> None:
    for y in (1992, 2021):
        p = merge_raster(y)
        print(f"三类栅格 -> {p.name}")

    areas = area_table()
    chg = change_table()
    acc = {y: merged_accuracy(y) for y in (1992, 2021)}

    (REPORTS / "accuracy" / "metrics_3class.json").write_text(
        json.dumps(acc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n面积：")
    print(areas.pivot(index="class_name", columns="year", values="area_km2").to_string())
    print("\n变化：")
    print(chg.to_string(index=False))
    print("\n三类精度（留出像元，内部一致性）：")
    for y, v in acc.items():
        print(f"  {y}: Final OA {v['final']['oa']:.4f} | 城镇 {v['final']['per_class_f1'][1]:.3f} "
              f"植被 {v['final']['per_class_f1'][2]:.3f} 水体 {v['final']['per_class_f1'][3]:.3f}")

    built = chg.set_index("class_id").loc[1]
    lines = [
        "# 三类合并的稳健性检验（1992—2021）",
        "",
        "> 官方口径仍是四类（见 `reports/analysis/urban_expansion.md`）。本文件只做一次稳健性检验："
        "把耕地与林草合并为「植被」后重算，看主要结论是否依赖二级类划分。",
        "",
        "1992 年 8 月单期影像上稻田与林木光谱重叠（见报告第 7 节），二级类不可分，"
        "合并后的结果用于验证建成区扩张结论的稳健性。",
        "",
        "## 面积",
        "",
        md_table(areas.pivot(index="class_name", columns="year", values="area_km2").reset_index()),
        "",
        "## 变化",
        "",
        md_table(chg),
        "",
        "## 精度（留出像元，内部一致性，非独立精度）",
        "",
        "> 三类 OA 与 F1 均为 1.0000，**不具判别意义**：像元纯度过滤已把城镇限定在 NDVI≤0.40、"
        "水体限定在 MNDWI≥0，留出像元与训练规则同源。此处只说明分类结果与人工边界自洽，"
        "不能作为精度证据引用。",
        "",
        f"- 1992：OA {acc[1992]['final']['oa']:.4f}，城镇 F1 {acc[1992]['final']['per_class_f1'][1]:.3f}，"
        f"植被 F1 {acc[1992]['final']['per_class_f1'][2]:.3f}，水体 F1 {acc[1992]['final']['per_class_f1'][3]:.3f}",
        f"- 2021：OA {acc[2021]['final']['oa']:.4f}，城镇 F1 {acc[2021]['final']['per_class_f1'][1]:.3f}，"
        f"植被 F1 {acc[2021]['final']['per_class_f1'][2]:.3f}，水体 F1 {acc[2021]['final']['per_class_f1'][3]:.3f}",
        "",
        f"## 结论",
        "",
        f"- 建成区由 {built['area_1992_km2']:.2f} km² 增至 {built['area_2021_km2']:.2f} km²，"
        f"净增 {built['net_km2']:.2f} km²；",
        f"- 新增 {built['added_km2']:.2f} km²，减少 {built['lost_km2']:.2f} km²，"
        f"持续建成区 {built['persistent_km2']:.2f} km²；",
        f"- 建成区占研究区比例 {built['area_1992_km2'] / 481.34 * 100:.1f}% → "
        f"{built['area_2021_km2'] / 481.34 * 100:.1f}%。",
    ]
    (REPORTS / "analysis" / "three_class_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n报告 -> reports/analysis/three_class_summary.md")


if __name__ == "__main__":
    main()