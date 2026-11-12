"""Module D: six figure groups and an evidence-based Markdown report."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Ellipse, PathPatch
from matplotlib.path import Path as PlotPath
import numpy as np
import pandas as pd
import rasterio

from rs_urban.enhance import digest, write_json
from rs_urban.spatial import source_maps

plt.rcParams.update({
    "font.family": ["Microsoft YaHei", "DejaVu Sans"],
    "axes.unicode_minus": False, "figure.dpi": 120,
    "savefig.bbox": "tight",
})


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def raster_image(path, band=1):
    with rasterio.open(path) as src:
        data = src.read(band, masked=True)
        return data, (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)


def show_class(ax, path, config, title):
    data, extent = raster_image(path)
    codes = [c["code"] for c in config["classes"]]
    ax.imshow(data, extent=extent, cmap=ListedColormap([c["color"] for c in config["classes"]]),
              norm=BoundaryNorm([c - 0.5 for c in codes] + [codes[-1] + 0.5], len(codes)),
              interpolation="nearest")
    ax.set_title(title, fontsize=10)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=7)


def class_legend(fig, config):
    from matplotlib.patches import Patch
    fig.legend(
        handles=[Patch(color=c["color"], label=c["name"]) for c in config["classes"]],
        loc="lower center", ncol=4, frameon=False, fontsize=8,
    )


def figure_features(ctx, target):
    years = ctx.config["years"]
    fig, axes = plt.subplots(2, 3, figsize=(12, 8))
    for row, year in enumerate(years):
        with rasterio.open(ctx.data / "processed" / str(year) / "features_30m.tif") as src:
            rgb = src.read([src.descriptions.index(n) + 1 for n in ["nir", "red", "green"]], masked=True)
            rgb = np.moveaxis(rgb.filled(np.nan), 0, -1)
            with rasterio.open(ctx.data / "processed" / str(year) / "valid_features_30m.tif") as mask_src:
                valid = mask_src.read(1) == 1
            for band in range(3):
                finite = valid & np.isfinite(rgb[..., band])
                if finite.any():
                    lo, hi = np.percentile(rgb[..., band][finite], [2, 98])
                    rgb[..., band] = np.clip((rgb[..., band] - lo) / max(hi - lo, 1e-6), 0, 1)
            rgb[~valid] = 1
            axes[row, 0].imshow(np.nan_to_num(rgb, nan=1))
            axes[row, 0].set_title(f"{year} NIR / Red / Green", fontsize=10)
            for col, name in [(1, "ndbi"), (2, "nir_std")]:
                data = src.read(src.descriptions.index(name) + 1, masked=True)
                data = np.ma.masked_where(~valid, data)
                artist = axes[row, col].imshow(data, cmap="cividis")
                axes[row, col].set_title(f"{year} {name}", fontsize=10)
                fig.colorbar(artist, ax=axes[row, col], shrink=0.65)
            for ax in axes[row]:
                ax.axis("off")
    fig.suptitle("Features: false colour, building index, local NIR standard deviation")
    fig.tight_layout()
    fig.savefig(target, dpi=240)
    plt.close(fig)


def figure_ablation(ctx, settings, target):
    methods, years = settings["classification"]["methods"], ctx.config["years"]
    fig, axes = plt.subplots(3, len(methods), figsize=(4 * len(methods), 11), squeeze=False)
    for col, method in enumerate(methods):
        for row, year in enumerate(years):
            path = ctx.outputs / "bcd" / "classification" / str(year) / method / "lulc.tif"
            score = read_json(ctx.reports / "bcd" / f"accuracy_{year}_{method}.json")
            show_class(axes[row, col], path, ctx.config, f"{year} {method}  OA {score['oa']:.3f}")
        scores = [read_json(ctx.reports / "bcd" / f"accuracy_{year}_{method}.json") for year in years]
        x = np.arange(len(years))
        axes[2, col].bar(x - 0.18, [s["oa"] for s in scores], 0.36, label="OA", color="#377EB8")
        axes[2, col].bar(x + 0.18, [s["f1"]["1"] for s in scores], 0.36, label="Built F1", color="#D95F02")
        axes[2, col].set_xticks(x, years)
        axes[2, col].set_ylim(0, 1)
        axes[2, col].legend(fontsize=8)
    class_legend(fig, ctx.config)
    fig.suptitle("Ablation: identical frozen internal holdout; no accuracy guarantee")
    fig.tight_layout(rect=(0, 0.035, 1, 0.96))
    fig.savefig(target, dpi=240)
    plt.close(fig)


def transition_ribbons(ax, matrix, config):
    """Area-proportional Sankey ribbons with actual transition totals."""
    values = matrix.to_numpy(dtype=float)
    total = values.sum()
    if total <= 0:
        raise ValueError("No comparable transition area for Sankey.")
    values /= total
    gap = 0.04
    left = np.r_[0, np.cumsum(values.sum(axis=1)[:-1])] + np.arange(len(values)) * gap
    right = np.r_[0, np.cumsum(values.sum(axis=0)[:-1])] + np.arange(len(values)) * gap
    offsets_a, offsets_b = left.copy(), right.copy()
    for i in range(len(values)):
        for j in range(len(values)):
            width = values[i, j]
            if width <= 0:
                continue
            a, b = offsets_a[i], offsets_b[j]
            vertices = [(0, a), (0.4, a), (0.6, b), (1, b),
                        (1, b + width), (0.6, b + width), (0.4, a + width),
                        (0, a + width), (0, a)]
            codes = [PlotPath.MOVETO, *([PlotPath.CURVE4] * 3), PlotPath.LINETO,
                     *([PlotPath.CURVE4] * 3), PlotPath.CLOSEPOLY]
            ax.add_patch(PathPatch(PlotPath(vertices, codes), facecolor=config["classes"][i]["color"],
                                   edgecolor="none", alpha=0.55))
            offsets_a[i] += width
            offsets_b[j] += width
    for i, item in enumerate(config["classes"]):
        a, b = values[i].sum(), values[:, i].sum()
        ax.plot([0, 0], [left[i], left[i] + a], color=item["color"], lw=5)
        ax.plot([1, 1], [right[i], right[i] + b], color=item["color"], lw=5)
        ax.text(-0.03, left[i] + a / 2, f"{item['name']}\n{a * total:.2f}", ha="right", va="center", fontsize=7)
        ax.text(1.03, right[i] + b / 2, f"{item['name']}\n{b * total:.2f}", ha="left", va="center", fontsize=7)
    ax.set_xlim(-0.5, 1.5)
    ax.set_ylim(-0.02, 1 + len(values) * gap)
    ax.invert_yaxis()
    ax.axis("off")
    ax.set_title("Transition flows (km2)", fontsize=10)


def figure_transitions(ctx, settings, target, analysis):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, path, year in zip(axes[:2], source_maps(ctx, settings["analysis"]["source"]), ctx.config["years"]):
        show_class(ax, path, ctx.config, str(year))
    matrix = pd.read_csv(analysis / "transition_km2.csv", index_col=0)
    transition_ribbons(axes[2], matrix, ctx.config)
    class_legend(fig, ctx.config)
    fig.suptitle(f"Classification and transitions: {settings['analysis']['source']}")
    fig.tight_layout(rect=(0, 0.08, 1, 0.95))
    fig.savefig(target, dpi=240)
    plt.close(fig)


def figure_expansion(ctx, target, analysis):
    summary = read_json(analysis / "summary.json")
    towns = gpd.read_file(ctx.data / "processed" / "boundaries" / "xindu_2021.gpkg", layer="townships")
    table = pd.read_csv(analysis / "township.csv", dtype={"unit_id": str})
    towns["unit_id"] = towns.unit_id.astype(str)
    towns = towns.merge(table, on="unit_id", suffixes=("", "_stats"), validate="one_to_one")
    first, last = ctx.config["years"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 6))
    towns.plot(column="annual_intensity_pct", ax=axes[0], cmap="YlOrRd", legend=True,
               edgecolor="#444444", linewidth=0.5)
    axes[0].set_title("Township UEII (% / year)", fontsize=10)
    towns.boundary.plot(ax=axes[1], color="#999999", linewidth=0.5)
    centers = []
    for year, color in [(first, "#377EB8"), (last, "#D95F02")]:
        item = summary["ellipses"][str(year)]
        if item is None:
            continue
        axes[1].add_patch(Ellipse(
            (item["x"], item["y"]), 2 * item["semi_major_m"], 2 * item["semi_minor_m"],
            angle=item["angle_degrees_ccw_from_east"], fill=False, edgecolor=color, lw=1.5,
        ))
        axes[1].scatter([item["x"]], [item["y"]], color=color, label=str(year), s=20)
        centers.append((item["x"], item["y"]))
    if len(centers) == 2:
        axes[1].annotate("", xy=centers[1], xytext=centers[0], arrowprops={"arrowstyle": "->", "color": "#333333"})
    axes[1].legend(fontsize=8)
    axes[1].set_title("Area-weighted centroids and ellipses", fontsize=10)
    x = np.arange(len(table))
    axes[2].barh(x - 0.18, table.built_1992_km2, 0.36, label=str(first), color="#377EB8")
    axes[2].barh(x + 0.18, table.built_2021_km2, 0.36, label=str(last), color="#D95F02")
    axes[2].set_yticks(x, table.name, fontsize=8)
    axes[2].set_xlabel("Built-up area (km2)")
    axes[2].legend(fontsize=8)
    for ax in axes[:2]:
        ax.set_aspect("equal")
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(target, dpi=240)
    plt.close(fig)


def figure_constraints(ctx, target, analysis):
    data = pd.read_csv(analysis / "factor_exposure.csv")
    rivers = data[data.factor == "river_distance"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    for ax, name in zip(axes[:2], ["elevation", "slope"]):
        values, extent = raster_image(analysis / f"factor_{name}.tif")
        im = ax.imshow(values, extent=extent, cmap="terrain" if name == "elevation" else "cividis")
        fig.colorbar(im, ax=ax, shrink=0.7, label="m" if name == "elevation" else "degrees")
        ax.set_title(name)
        ax.tick_params(labelsize=7)
    axes[2].bar(rivers.zone, rivers.added_km2, color="#377EB8")
    axes[2].tick_params(axis="x", rotation=40, labelsize=7)
    axes[2].set_ylabel("New built-up area (km2)")
    axes[2].set_title("River buffers (cumulative)")
    fig.tight_layout()
    fig.savefig(target, dpi=240)
    plt.close(fig)


def figure_detector(ctx, target, analysis):
    report = read_json(analysis / "geodetector.json")
    factors = report["factors"]
    names = [row["factor"] for row in factors]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].barh(names[::-1], [row["q"] for row in factors][::-1], color="#2E8B57")
    axes[0].set_xlim(0, 1)
    axes[0].set_xlabel("q (spatial association)")
    matrix = np.full((len(names), len(names)), np.nan)
    for i, row in enumerate(factors):
        matrix[i, i] = row["q"]
    for row in report["interactions"]:
        i, j = names.index(row["first"]), names.index(row["second"])
        matrix[i, j] = matrix[j, i] = row["q"]
    im = axes[1].imshow(matrix, vmin=0, vmax=1, cmap="YlGnBu")
    axes[1].set_xticks(range(len(names)), names, rotation=45, ha="right", fontsize=8)
    axes[1].set_yticks(range(len(names)), names, fontsize=8)
    for i in range(len(names)):
        for j in range(len(names)):
            if np.isfinite(matrix[i, j]):
                axes[1].text(j, i, f"{matrix[i, j]:.2f}", ha="center", va="center",
                             fontsize=8, color="white" if matrix[i, j] > 0.5 else "black")
    fig.colorbar(im, ax=axes[1], shrink=0.7)
    fig.suptitle("GeoDetector: common complete-case grids")
    fig.tight_layout()
    fig.savefig(target, dpi=240)
    plt.close(fig)


def render_report(ctx, settings, inventory=None, render=True):
    source = settings["analysis"]["source"]
    analysis = ctx.outputs / "bcd" / "analysis" / source
    figure_dir = ctx.outputs / "bcd" / "figures" / source
    figure_dir.mkdir(parents=True, exist_ok=True)
    report_dir = ctx.reports / "bcd"
    report_dir.mkdir(parents=True, exist_ok=True)
    years, methods = ctx.config["years"], settings["classification"]["methods"]
    features = [ctx.data / "processed" / str(y) / name for y in years
                for name in ["features_30m.tif", "valid_features_30m.tif"]]
    ablation = [ctx.outputs / "bcd" / "classification" / str(y) / m / "lulc.tif" for y in years for m in methods]
    ablation += [report_dir / f"accuracy_{y}_{m}.json" for y in years for m in methods]
    summary_path, detector_path = analysis / "summary.json", analysis / "geodetector.json"
    summary = read_json(summary_path) if summary_path.exists() else None
    detector = read_json(detector_path) if detector_path.exists() else None
    requirements = [
        ("01_features", features, figure_features),
        ("02_ablation", ablation, lambda c, p: figure_ablation(c, settings, p)),
        ("03_transitions", [*source_maps(ctx, source), analysis / "transition_km2.csv", summary_path],
         lambda c, p: figure_transitions(c, settings, p, analysis)),
        ("04_expansion", [analysis / "township.csv", summary_path,
                          ctx.data / "processed" / "boundaries" / "xindu_2021.gpkg"],
         lambda c, p: figure_expansion(c, p, analysis)),
        ("05_constraints", [analysis / "factor_elevation.tif", analysis / "factor_slope.tif",
                            analysis / "factor_exposure.csv"],
         lambda c, p: figure_constraints(c, p, analysis)),
        ("06_geodetector", [detector_path], lambda c, p: figure_detector(c, p, analysis)),
    ]
    figures = []
    for name, required, renderer in requirements:
        missing = [str(path) for path in required if not path.exists()]
        reason = None
        if name == "06_geodetector" and detector is not None and detector["status"] != "computed":
            reason = detector.get("reason", "Undefined detector.")
        if name == "05_constraints" and not missing:
            exposure = pd.read_csv(analysis / "factor_exposure.csv")
            if not (exposure.factor == "river_distance").any():
                reason = "River vector exposure is missing."
        # Recheck provenance so old results are not presented as current outputs.
        if name in ("03_transitions", "04_expansion", "05_constraints", "06_geodetector") and summary:
            provenance = summary["inputs"] + [item for item in summary["factors"] if item["status"] == "computed"]
            if any(not Path(item["path"]).exists() or digest(Path(item["path"])) != item["sha256"]
                   for item in provenance):
                reason = "Analysis inputs changed; rerun analyze."
        if name == "02_ablation" and not missing:
            hashes = {}
            for year in years:
                for method in methods:
                    score = read_json(report_dir / f"accuracy_{year}_{method}.json")
                    hashes.setdefault(year, set()).add(score["holdout_sha256"])
                    if digest(Path(score["map_path"])) != score["map_sha256"]:
                        reason = "An evaluated map changed; rerun classify."
            if any(len(values) != 1 for values in hashes.values()):
                reason = "Ablation methods do not share the frozen holdout."
        ready = not missing and reason is None
        path = figure_dir / f"{name}.png"
        if ready and render:
            renderer(ctx, path)
        figures.append({
            "figure": name, "status": "rendered" if ready and render else ("ready" if ready else "pending"),
            "path": str(path) if ready and render else None, "missing": missing, "reason": reason,
        })
    result = {"source": source, "figures": figures}
    write_json(report_dir / "figures.json", result)
    lines = [
        "# B/C/D 实施与成果报告", "",
        f"分析来源：`{source}`；年份：{years[0]}—{years[1]}。", "",
        "## 当前状态", "",
        "本报告按当前磁盘输入生成。历史已入库报告不代表本机已完成重跑；测试数据不作为研究结果。",
        "", "| 图组 | 状态 |", "| --- | --- |",
    ]
    for figure in figures:
        lines.append(f"| {figure['figure']} | {figure['status']} |")
    if inventory:
        lines += ["", "## 输入与依赖", ""]
        for item in inventory:
            lines.append(f"- {item['task']}: {item['status']}")
            for missing in item.get("missing", []):
                lines.append(f"  - `{missing}`")
    if summary:
        lines += [
            "", "## 扩张分析", "",
            f"共同有效观测面积：{summary['common_area_km2']:.6f} km²。",
            f"新增斑块：{summary['new_patch_count']}；LEI 外环宽度：{summary['lei_buffer_m']:g} m。",
            f"街镇面积平衡：{summary['area_balance']['is_balanced']}。",
            "", "各类型新增面积（km²）：", "",
        ]
        for name, value in summary["lei_area_km2"].items():
            lines.append(f"- {name}: {value:.6f}")
        if summary["migration"]:
            lines += ["", f"建设用地面积重心迁移：{summary['migration']['distance_m']:.2f} m。"]
        lines += ["", "地形及外部因子：", ""]
        lines += [f"- {item['name']}: {item['status']} (`{item['path']}`)" for item in summary["factors"]]
    scores = []
    for year in years:
        for method in methods:
            path = report_dir / f"accuracy_{year}_{method}.json"
            if path.exists():
                scores.append(read_json(path))
    if scores:
        lines += ["", "## 分类对比", "", "| 年份 | 方法 | OA | Kappa | 建设类 F1 | 覆盖率 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for score in scores:
            kappa = f"{score['kappa']:.4f}" if score["kappa"] is not None else "undefined"
            lines.append(f"| {score['year']} | {score['method']} | {score['oa']:.4f} | {kappa} | "
                         f"{score['f1']['1']:.4f} | {score['coverage']:.4f} |")
    if detector:
        lines += ["", "## 驱动因子空间关联", "", f"GeoDetector 状态：{detector['status']}。"]
        if detector["status"] == "computed":
            lines += [f"共同完整网格：{detector['n']}。", "", "| 因子 | q | 置换 p |",
                      "| --- | --- | --- |"]
            lines += [f"| {row['factor']} | {row['q']:.4f} | {row['p_permutation']} |" for row in detector["factors"]]
    lines += [
        "", "## 方法与解释边界", "",
        "- A 的 19 维特征保持现有配置；nir_std 是局部标准差，不宣称为 GLCM 对比度或熵。",
        "- B 使用训练地块分组交叉验证，holdout 不参与调参或伪标签训练。OA 不保证提升。",
        "- 留出集经光谱纯度过滤，属于内部一致性评估；仍需独立外部样本核验地图精度。",
        "- LEI=100×旧建设用地与可观测外环交叠面积/可观测外环面积；>50 填充，(0,50] 边缘，0 飞地。",
        "- 动态度 K=净增/期初建设面积/年数×100；期初为零时留空。UEII=净增/法定面积/年数×100。",
        "- 景观 PD 单位为斑块/100ha；LPI 为最大斑块占景观面积；AI 为单计数四邻接/理论最大邻接。",
        "- FRAC=2ln(0.25×周长米)/ln(面积平方米)，报告面积加权 FRAC_AM；像元网格指标与精确裁剪面积分开。",
        "- GeoDetector 在同一完整网格样本上计算，因子均值按像元中心聚合；稀疏交互分层可抬高 q。",
        "- 普通置换 p 未修正空间自相关，只能作为探索性关联；河道、道路与规划需核对来源和年份。",
        "- 1992 年耕地/林草混淆限制四类转移解释；不得据两期数据推断中间政策节点的扩张速率突变。",
        "- 本机缺失的真实数据或可选依赖保留为待运行项；不生成替代影像、虚构指标或归因结论。",
    ]
    for figure in figures:
        if figure["status"] == "rendered":
            relative = Path(figure["path"]).relative_to(ctx.root) if Path(figure["path"]).is_relative_to(ctx.root) else Path(figure["path"])
            lines += ["", f"### {figure['figure']}", "", f"图件：`{relative.as_posix()}`"]
    report_path = report_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
