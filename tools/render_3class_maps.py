"""出三类分类结果对比图（1992 / 2021）。

    python -X utf8 tools/render_3class_maps.py
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import rasterio
from matplotlib import font_manager
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
COLORS = {1: "#D95F02", 2: "#6BA355", 3: "#377EB8"}
LABELS = {1: "城镇及建设用地", 2: "植被（耕地+林草）", 3: "水体"}


def main() -> None:
    font_manager.fontManager.addfont(r"C:\Windows\Fonts\msyh.ttc")
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    towns = gpd.read_file(REPO / "data" / "processed" / "boundaries" / "xindu_2021.gpkg",
                          layer="townships").to_crs("EPSG:32648")
    study = gpd.read_file(REPO / "data" / "processed" / "boundaries" / "xindu_2021.gpkg",
                          layer="study_area").to_crs("EPSG:32648")

    cmap = ListedColormap([COLORS[k] for k in (1, 2, 3)])
    fig, axes = plt.subplots(1, 2, figsize=(17, 8), dpi=160)
    for ax, year in zip(axes, (1992, 2021)):
        with rasterio.open(REPO / "outputs" / "rasters" / f"lulc_{year}_3class_30m.tif") as ds:
            data = ds.read(1)
            bounds = ds.bounds
        show = np.where(data > 0, data - 1, np.nan)
        ax.imshow(show, cmap=cmap, vmin=0, vmax=2,
                  extent=(bounds.left, bounds.right, bounds.bottom, bounds.top))
        towns.boundary.plot(ax=ax, color="white", linewidth=0.6, alpha=0.7)
        study.boundary.plot(ax=ax, color="black", linewidth=1.2)
        for _, r in towns.iterrows():
            p = r.geometry.representative_point()
            ax.annotate(r["name"], (p.x, p.y), ha="center", fontsize=8, color="black",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.65))
        built = (data == 1).sum() * 900 / 1e6
        ax.set_title(f"{year} 年　建成区 {built:.1f} km²", fontsize=14)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.legend(handles=[Patch(color=COLORS[k], label=LABELS[k]) for k in (1, 2, 3)],
               loc="lower center", ncol=3, frameon=False, fontsize=12)
    fig.suptitle("新都区土地利用分类（三类）1992 vs 2021", fontsize=16)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    out = REPO / "outputs" / "maps" / "lulc_3class_1992_2021.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"分类对比图 -> {out}")


if __name__ == "__main__":
    main()