"""渲染 2021 年 15 m 与 30 m 分类对照图。

三联图：左 15 m 全图、中 30 m 同一窗口、右 15 m 同一窗口。
仅用于展示 15 m 产品的空间细节，不产生任何统计结论。

    python -X utf8 tools/render_15m_compare.py --cx 415360 --cy 3411289 --half_km 3
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib import font_manager
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

font_manager.fontManager.addfont(r"C:\Windows\Fonts\msyh.ttc")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "maps" / "lulc_2021_15m_vs_30m.png"
COLORS = {1: "#D95F02", 2: "#E6C84F", 3: "#2E8B57", 4: "#377EB8"}
NAMES = {1: "城镇及建设用地", 2: "耕地", 3: "林草植被", 4: "水体"}


def load(path: Path) -> tuple[np.ndarray, rasterio.Affine, rasterio.crs.CRS]:
    with rasterio.open(path) as ds:
        return ds.read(1), ds.transform, ds.crs


def window(arr: np.ndarray, transform, cx: float, cy: float, half_m: float) -> np.ndarray:
    col = int((cx - transform.c) / transform.a)
    row = int((cy - transform.f) / transform.e)
    half = int(half_m / abs(transform.a))
    r0, r1 = max(row - half, 0), min(row + half, arr.shape[0])
    c0, c1 = max(col - half, 0), min(col + half, arr.shape[1])
    return arr[r0:r1, c0:c1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cx", type=float, default=415360)
    ap.add_argument("--cy", type=float, default=3411289)
    ap.add_argument("--half_km", type=float, default=3.0)
    args = ap.parse_args()

    a15, t15, _ = load(REPO / "outputs" / "rasters" / "lulc_2021_15m.tif")
    a30, t30, _ = load(REPO / "outputs" / "rasters" / "lulc_2021_final_30m.tif")

    cmap = ListedColormap(["#00000000"] + [COLORS[c] for c in sorted(COLORS)])
    norm = matplotlib.colors.BoundaryNorm(np.arange(-0.5, 4.6, 1), cmap.N)

    fig, axes = plt.subplots(1, 3, figsize=(19, 7.2), gridspec_kw={"width_ratios": [1.55, 1, 1]})

    axes[0].imshow(a15, cmap=cmap, norm=norm, interpolation="nearest")
    axes[0].set_title("2021 年分类（15 m，2712×2140）", fontsize=13)
    axes[0].set_xticks([]); axes[0].set_yticks([])

    half = args.half_km * 1000
    w30 = window(a30, t30, args.cx, args.cy, half)
    w15 = window(a15, t15, args.cx, args.cy, half)
    axes[1].imshow(w30, cmap=cmap, norm=norm, interpolation="nearest")
    axes[1].set_title(f"30 m 窗口（{w30.shape[0]}×{w30.shape[1]} 像元）", fontsize=12)
    axes[1].set_xticks([]); axes[1].set_yticks([])

    axes[2].imshow(w15, cmap=cmap, norm=norm, interpolation="nearest")
    axes[2].set_title(f"15 m 窗口（{w15.shape[0]}×{w15.shape[1]} 像元，同范围）", fontsize=12)
    axes[2].set_xticks([]); axes[2].set_yticks([])

    handles = [Patch(facecolor=COLORS[c], edgecolor="none", label=f"{c} {NAMES[c]}") for c in sorted(COLORS)]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=11)
    fig.suptitle("2021 年 15 m 与 30 m 分类对照（15 m 产品仅用于展示，不参与变化统计）", fontsize=14)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=200)
    plt.close(fig)
    print(f"已生成：{OUT}")


if __name__ == "__main__":
    main()