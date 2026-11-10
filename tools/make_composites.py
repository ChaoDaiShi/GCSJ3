"""生成多套判读用影像组合（1992 / 2021），便于在 QGIS 里分辨地类。

组合说明（括号内为波段顺序）：
  真彩色   R=red, G=green, B=blue            —— 接近肉眼，但老影像对比度低
  标准假彩色 R=nir, G=red,  B=green           —— 植被鲜红、城镇灰青、水体深黑
  短波红外组合 R=swir1, G=nir, B=red          —— 建成区粉紫最突出，最适合画城镇
  NDVI 灰度 单波段，植被越亮越绿              —— 判断耕地/林草边界

    python -X utf8 tools/make_composites.py --year 1992
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio

REPO = Path(__file__).resolve().parents[1]
NODATA = -9999.0

COMBOS = {
    "fcc": (["nir", "red", "green"], "标准假彩色 R近红外-G红-B绿"),
    "swir": (["swir1", "nir", "red"], "短波红外 R-SWIR1-G近红外-B红"),
}


def stretch(band: np.ndarray, valid: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(band[valid], 2), np.percentile(band[valid], 98)
    if hi <= lo:
        return np.zeros_like(band, dtype=np.uint8)
    out = (band - lo) / (hi - lo)
    return (np.clip(out, 0, 1) * 255.0).astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=1992)
    args = ap.parse_args()

    src = REPO / "data" / "processed" / str(args.year) / "sr_30m.tif"
    outdir = REPO / "outputs" / "rasters"
    outdir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(src) as ds:
        names = list(ds.descriptions)
        bands = {n: ds.read(i + 1).astype("float32") for i, n in enumerate(names)}
        profile = ds.profile.copy()
        valid = np.isfinite(bands["red"]) & (bands["red"] != NODATA) & (bands["red"] > -100)

    for key, (order, desc) in COMBOS.items():
        stack = np.dstack([stretch(bands[b], valid) for b in order])
        stack[~valid] = 0
        prof = profile.copy()
        prof.update(count=3, dtype="uint8", nodata=None, photometric="RGB",
                    compress="deflate", tiled=False)
        dst = outdir / f"xindu_{args.year}_{key}_30m.tif"
        with rasterio.open(dst, "w", **prof) as out:
            for i, b in enumerate(order):
                out.write(stack[:, :, i], i + 1)
                out.set_band_description(i + 1, b)
        print(f"{desc} -> {dst.name}  "
              f"均值 {stack[:, :, 0].mean():.0f}/{stack[:, :, 1].mean():.0f}/{stack[:, :, 2].mean():.0f}")

    # NDVI 灰度
    ndvi = (bands["nir"] - bands["red"]) / (bands["nir"] + bands["red"] + 1e-6)
    nd = np.zeros_like(ndvi, dtype=np.uint8)
    # 固定区间，保证 1992 与 2021 的灰度可比，且城镇（NDVI 0.2—0.4）不至于全黑
    lo, hi = -0.20, 0.90
    nd[valid] = (np.clip((ndvi[valid] - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
    prof = profile.copy()
    prof.update(count=1, dtype="uint8", nodata=None, compress="deflate", tiled=False)
    dst = outdir / f"xindu_{args.year}_ndvi_30m.tif"
    with rasterio.open(dst, "w", **prof) as out:
        out.write(nd, 1)
        out.set_band_description(1, "ndvi")
    print(f"NDVI 灰度 ({lo:.2f}~{hi:.2f}) -> {dst.name}  均值 {nd[valid].mean():.0f}")


if __name__ == "__main__":
    main()