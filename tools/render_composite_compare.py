"""拼一张 1992 年四种判读组合的对照图，方便挑最清楚的那套。

    python -X utf8 tools/render_composite_compare.py --year 1992
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
import numpy as np
import rasterio
from matplotlib import font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

PANELS = [
    ("truecolor", "真彩色（R红 G绿 B蓝）", "房屋灰白、稻田绿、林子深绿"),
    ("fcc", "标准假彩色（R近红外 G红 B绿）", "植被鲜红、城镇灰青、水体黑"),
    ("swir", "短波红外（R SWIR1 G近红外 B红）", "城镇粉紫、耕地绿、水体黑"),
    ("ndvi", "NDVI 灰度（越白植被越密）", "城镇/水体暗、耕地浅灰、林草白"),
]


def load(path: Path, window) -> np.ndarray:
    with rasterio.open(path) as ds:
        data = ds.read(window=window)
    if data.shape[0] == 1:
        return np.repeat(data, 3, axis=0).transpose(1, 2, 0)
    return data[:3].transpose(1, 2, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=1992)
    ap.add_argument("--cx", type=float, default=410500.0)
    ap.add_argument("--cy", type=float, default=3403500.0)
    ap.add_argument("--half_km", type=float, default=4.0)
    args = ap.parse_args()

    font_manager.fontManager.addfont(r"C:\Windows\Fonts\msyh.ttc")
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    half = args.half_km * 1000.0
    bounds = (args.cx - half, args.cy - half, args.cx + half, args.cy + half)

    fig, axes = plt.subplots(2, 2, figsize=(15, 15), dpi=150)
    for ax, (key, title, hint) in zip(axes.ravel(), PANELS):
        path = REPO / "outputs" / "rasters" / f"xindu_{args.year}_{key}_30m.tif"
        with rasterio.open(path) as ds:
            win = from_bounds(*bounds, transform=ds.transform)
            img = load(path, win)
        ax.imshow(img)
        ax.set_title(f"{title}\n{hint}", fontsize=12)
        ax.axis("off")
    fig.suptitle(f"新都区 {args.year} 年影像判读组合对照（{args.half_km * 2:.0f} km × "
                 f"{args.half_km * 2:.0f} km）", fontsize=15)
    out = REPO / "outputs" / "maps" / f"{args.year}_composites_compare.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"对照图 -> {out}")


if __name__ == "__main__":
    main()