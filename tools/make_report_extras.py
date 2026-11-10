"""为 Word 报告预计算附属统计（Word 运行时没有 rasterio）。

产出 outputs/tables/report_extras.json：
  - class_areas：两期四类面积与占比
  - distance_bands：新增建设用地相对 1992 年建成区的距离分级
  - ndvi_sensitivity：1992 年不同 NDVI 阈值下的林草面积

    python -X utf8 tools/make_report_extras.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from scipy.ndimage import distance_transform_edt

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "tables" / "report_extras.json"
TOTAL_KM2 = 497.032


def class_areas() -> dict:
    out: dict[str, dict[str, dict[str, float]]] = {}
    for year in (1992, 2021):
        with rasterio.open(REPO / "outputs" / "rasters" / f"lulc_{year}_final_30m.tif") as ds:
            a = ds.read(1)
        valid = int((a > 0).sum())
        out[str(year)] = {
            str(c): {
                "km2": round(int((a == c).sum()) * 900 / 1e6, 2),
                "share": round(int((a == c).sum()) / valid * 100, 2) if valid else 0.0,
            }
            for c in (1, 2, 3, 4)
        }
    return out


def distance_bands() -> list[dict]:
    with rasterio.open(REPO / "outputs" / "rasters" / "lulc_1992_final_30m.tif") as ds:
        a92 = ds.read(1)
    with rasterio.open(REPO / "outputs" / "rasters" / "lulc_2021_final_30m.tif") as ds:
        a21 = ds.read(1)
    valid = (a92 > 0) & (a21 > 0)
    b92 = (a92 == 1) & valid
    added = (a21 == 1) & valid & ~b92
    d = distance_transform_edt(~b92, sampling=30.0)[added]
    total = max(int(added.sum()), 1)
    bands = [
        ("< 300 m（内部填充）", 0, 300),
        ("300—600 m（贴边蔓延）", 300, 600),
        ("600—1000 m", 600, 1000),
        ("1000—2000 m（跳跃增长）", 1000, 2000),
        ("> 2000 m", 2000, float("inf")),
    ]
    return [
        {
            "label": label,
            "km2": round(float(((d >= lo) & (d < hi)).sum()) * 900 / 1e6, 2),
            "pct": round(float(((d >= lo) & (d < hi)).sum()) / total * 100, 2),
        }
        for label, lo, hi in bands
    ]


def ndvi_sensitivity() -> list[dict]:
    with rasterio.open(REPO / "data" / "processed" / "features" / "feat_1992_30m.tif") as ds:
        names = list(ds.descriptions)
        ndvi = ds.read(names.index("ndvi") + 1).astype("float32")
    v = ndvi[(ndvi > -1) & (ndvi < 1)]
    return [
        {"cut": cut, "km2": round(float((v >= cut).mean()) * TOTAL_KM2, 2)}
        for cut in (0.60, 0.62, 0.64, 0.66, 0.68)
    ]


def main() -> None:
    payload = {
        "class_areas": class_areas(),
        "distance_bands": distance_bands(),
        "ndvi_sensitivity": ndvi_sensitivity(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成：{OUT}")
    print("  距离分级:", [(b['label'], b['pct']) for b in payload["distance_bands"]])
    print("  阈值敏感性:", [(s['cut'], s['km2']) for s in payload["ndvi_sensitivity"]])


if __name__ == "__main__":
    main()