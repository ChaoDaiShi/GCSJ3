"""把某年的地表反射率合成为真彩色 RGB GeoTIFF，供 QGIS 目视复核。

输出为 3 波段 uint8（R=Red、G=Green、B=Blue），已做 2%—98% 线性拉伸，
任何 GIS 打开即为正常彩色，不需要另调符号系统。

    python -X utf8 tools/make_truecolor.py --year 2021
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio

REPO = Path(__file__).resolve().parents[1]
BAND_ORDER = ("red", "green", "blue")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src_path = REPO / "data" / "processed" / str(args.year) / "sr_30m.tif"
    out_path = Path(args.out) if args.out else (
        REPO / "outputs" / "rasters" / f"xindu_{args.year}_truecolor_30m.tif"
    )

    with rasterio.open(src_path) as ds:
        names = list(ds.descriptions)
        missing = [b for b in BAND_ORDER if b not in names]
        if missing:
            raise ValueError(f"缺少波段: {missing}；现有: {names}")
        idx = [names.index(b) + 1 for b in BAND_ORDER]
        rgb = ds.read(idx).astype("float32")
        profile = ds.profile.copy()
        nodata = ds.nodata

    valid = np.ones(rgb.shape[1:], dtype=bool)
    for band in rgb:
        if nodata is not None:
            valid &= band != nodata
        valid &= np.isfinite(band) & (band > -1000)

    for i in range(3):
        vals = rgb[i][valid]
        lo, hi = np.percentile(vals, 2), np.percentile(vals, 98)
        rgb[i] = np.clip((rgb[i] - lo) / (hi - lo + 1e-6) * 255.0, 0, 255)
    rgb[:, ~valid] = 0

    profile.update(count=3, dtype="uint8", nodata=0, compress="deflate", predictor=2,
                   photometric="RGB")
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(rgb.astype("uint8"))
        dst.descriptions = ("red", "green", "blue")

    print(f"{args.year} 真彩色 -> {out_path}")
    print(f"  尺寸 {profile['width']}x{profile['height']}，有效像元 {int(valid.sum())}")


if __name__ == "__main__":
    main()