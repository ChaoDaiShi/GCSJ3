"""分类后处理、矢量化制图与独立精度评价模块（P1-D）。

主要功能与科学处理流程：
1. sieve_classification:
   - 应用 GDAL SieveFilter 算法滤除孤立微小杂斑（连通度 connectivity=8，像元阈值 threshold_pixels=4）；
   - 显式传入有效像元二值掩膜，严格保护 NoData（值 0）边界，消除分类结果的“椒盐噪声”。

2. vectorize_and_clip:
   - 将滤波后的最终分类栅格进行连通域多边形矢量化；
   - 与新都区法定行政边界（study_area）执行精确几何求交裁剪（intersection），剔除边缘溢出区域；
   - 计算各图斑面积（平方公里），导出标准的 ESRI Shapefile 矢量文件集合，并显式生成 UTF-8 的 .cpg 编码定义文件。

3. calculate_confusion_matrix & calculate_class_metrics:
   - 基于空间完全独立的留出验证集（holdout.csv）生成 5x5 混淆矩阵（建设用地、耕地、其他植被、水域、裸地）；
   - 计算总体精度（OA）、各类精确率（Precision）、召回率（Recall）与 F1 分数。

4. check_accuracy_threshold:
   - 严格执行准入门槛核验：要求最终分类总体精度必须严格大于 0.75（OA > 0.75，0.75 本身按未达标处理）。

5. finalize_evaluate:
   - 串联后处理、矢量化裁剪、独立精度评价指标核算、CSV 报表导出与 Markdown/JSON 评估报告编写。
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

# 若当前环境中存在 GDAL/PROJ 资源共享目录，自动配置环境变量以便正确加载投影定义
_prefix = Path(sys.prefix)
_gdal_share = _prefix / "Library" / "share" / "gdal"
if "GDAL_DATA" not in os.environ and _gdal_share.exists():
    os.environ["GDAL_DATA"] = str(_gdal_share)
_proj_share = _prefix / "Library" / "share" / "proj"
if "PROJ_DATA" not in os.environ and _proj_share.exists():
    os.environ["PROJ_DATA"] = str(_proj_share)

import geopandas as gpd
import numpy as np
import rasterio
from osgeo import gdal
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import shape

from rs_urban.contracts import EvaluationData, ProjectContext


# ---------------------------------------------------------------------------
# 1. 精度评价指标计算与门槛检验（Metric Calculations and Threshold Verification）
# ---------------------------------------------------------------------------

def calculate_confusion_matrix(
    y_true: list[int] | np.ndarray,
    y_pred: list[int] | np.ndarray,
    class_order: list[int] = [1, 2, 3, 4, 5],
) -> tuple[list[list[int]], float]:
    """计算 5x5 混淆矩阵与总体分类精度（Overall Accuracy, OA）。

    混淆矩阵定义规范：
      - 行（Rows）：地面真实类别（Ground Truth）；
      - 列（Columns）：算法预测类别（Predicted Class）。
      - 主对角线元素表示预测正确的样本数。

    总体精度计算公式：
      OA = 预测正确的像元总数 / 总样本数

    Args:
        y_true (list[int] | np.ndarray): 真实地类标签序列。
        y_pred (list[int] | np.ndarray): 模型预测地类标签序列。
        class_order (list[int], optional): 地类编码排列顺序。默认为 [1, 2, 3, 4, 5]。

    Returns:
        tuple[list[list[int]], float]:
            - matrix: 5x5 混淆矩阵（二维嵌套整数列表）；
            - oa: 总体精度浮点数（0.0 至 1.0）。
    """
    n_classes = len(class_order)
    class_to_idx = {c: i for i, c in enumerate(class_order)}
    matrix = [[0] * n_classes for _ in range(n_classes)]

    for t, p in zip(y_true, y_pred):
        if t in class_to_idx and p in class_to_idx:
            matrix[class_to_idx[t]][class_to_idx[p]] += 1

    total_samples = sum(sum(row) for row in matrix)
    correct_samples = sum(matrix[i][i] for i in range(n_classes))
    oa = correct_samples / total_samples if total_samples > 0 else 0.0

    return matrix, oa


def calculate_class_metrics(
    matrix: list[list[int]],
    class_order: list[int] = [1, 2, 3, 4, 5],
) -> list[dict[str, Any]]:
    """根据混淆矩阵计算每个类别的精确率、召回率、F1 分数及样本支持量。

    计算公式：
      - Precision（查准率） = TP / (TP + FP)  [对应列求和]
      - Recall（查全率）    = TP / (TP + FN)  [对应行求和，即 Support]
      - F1-Score（调和均值） = 2 * (Precision * Recall) / (Precision + Recall)

    Args:
        matrix (list[list[int]]): 混淆矩阵二维列表。
        class_order (list[int], optional): 地类编码列表。默认为 [1, 2, 3, 4, 5]。

    Returns:
        list[dict[str, Any]]: 包含各类别指标的字典列表。
    """
    n_classes = len(class_order)
    metrics: list[dict[str, Any]] = []

    for i, class_id in enumerate(class_order):
        support = sum(matrix[i])
        pred_total = sum(matrix[r][i] for r in range(n_classes))
        tp = matrix[i][i]

        precision = tp / pred_total if pred_total > 0 else 0.0
        recall = tp / support if support > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        metrics.append({
            "class_id": class_id,
            "support": support,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        })

    return metrics


def check_accuracy_threshold(oa: float, threshold: float = 0.75) -> bool:
    """硬性校验总体精度是否达标：要求 OA 必须严格大于指定阈值。

    契约规定：final.oa > 0.75（若恰好等于 0.75 亦视为未达标）。

    Args:
        oa (float): 实际总体精度。
        threshold (float, optional): 准入门槛。默认为 0.75。

    Returns:
        bool: True 表示达标通过，False 表示未达标。
    """
    return oa > threshold


# ---------------------------------------------------------------------------
# 2. 筛分后处理滤波（GDAL Sieve）
# ---------------------------------------------------------------------------

def sieve_classification(
    raw_arr: np.ndarray,
    threshold_pixels: int = 4,
    connectivity: int = 8,
    nodata_val: int = 0,
) -> np.ndarray:
    """使用 GDAL SieveFilter 滤除连通像元数小于 threshold_pixels 的孤立细碎杂斑。

    处理要点：
    - 在内存（MEM 驱动）中创建数据源与掩膜数据源；
    - 显式构建并传入二值有效掩膜（raw_arr != nodata_val），严防算法将 NoData 背景与前景斑块合并；
    - 执行后重新将原始 NoData 位置强制写回为 nodata_val，确保边界严格保持。

    Args:
        raw_arr (np.ndarray): 原始预测分类二维矩阵（uint8）。
        threshold_pixels (int, optional): 筛分面积阈值（单位：像元数）。默认为 4。
        connectivity (int, optional): 像素邻域连通度（4 或 8）。默认为 8。
        nodata_val (int, optional): 无效背景编码。默认为 0。

    Returns:
        np.ndarray: 滤波平滑后的 uint8 分类结果矩阵。
    """
    height, width = raw_arr.shape
    drv = gdal.GetDriverByName("MEM")

    ds_src = drv.Create("", width, height, 1, gdal.GDT_Byte)
    ds_src.GetRasterBand(1).WriteArray(raw_arr)

    # 显式生成有效像元掩膜（有效像元为 1，NoData 背景为 0）
    valid_mask = (raw_arr != nodata_val).astype(np.uint8)
    ds_mask = drv.Create("", width, height, 1, gdal.GDT_Byte)
    ds_mask.GetRasterBand(1).WriteArray(valid_mask)

    ds_dst = drv.Create("", width, height, 1, gdal.GDT_Byte)

    # 调用 GDAL 原生 SieveFilter 算法
    gdal.SieveFilter(
        ds_src.GetRasterBand(1),
        ds_mask.GetRasterBand(1),
        ds_dst.GetRasterBand(1),
        threshold_pixels,
        connectivity,
    )

    filtered_arr = ds_dst.GetRasterBand(1).ReadAsArray()

    # 严格保证原本为 NoData 的位置不受平滑影响
    filtered_arr[raw_arr == nodata_val] = nodata_val

    return filtered_arr.astype(np.uint8)


# ---------------------------------------------------------------------------
# 3. 栅格矢量化与法定边界裁剪（Vectorization and Study Area Clipping）
# ---------------------------------------------------------------------------

def vectorize_and_clip(
    raster_arr: np.ndarray,
    transform: Affine,
    crs: str,
    study_area_geom: Any,
    year: int,
    class_names: dict[int, str],
    output_shp: Path,
    nodata_val: int = 0,
) -> Path:
    """将分类栅格转化为多边形矢量图层，裁剪至法定研究区范围，并输出 ESRI Shapefile。

    处理要点：
    - 遍历提取有效像元连通域多边形；
    - 与研究区几何边界执行空间交集（intersection），过滤边缘残留碎片；
    - 计算图斑面积（平方公里）；
    - 输出 Shapefile 格式并显式生成 UTF-8 编码的 .cpg 文件，杜绝中文属性乱码。

    Args:
        raster_arr (np.ndarray): 平滑后的分类栅格数组。
        transform (Affine): 栅格仿射变换参数。
        crs (str): 空间坐标系标识。
        study_area_geom (Any): 研究区边界 Shapely 几何对象。
        year (int): 成果归属年份。
        class_names (dict[int, str]): 类别编码至类别中文名称的映射字典。
        output_shp (Path): 输出 Shapefile 文件的绝对路径。
        nodata_val (int, optional): 背景值。默认为 0。

    Returns:
        Path: 输出的 .shp 文件路径。
    """
    mask = raster_arr != nodata_val
    records = []

    # 提取所有非 NoData 图斑的几何与属性
    for geom_dict, val in shapes(raster_arr, mask=mask, transform=transform):
        class_id = int(val)
        if class_id == nodata_val:
            continue

        poly = shape(geom_dict)
        # 与法定行政边界求交裁剪
        if study_area_geom is not None:
            poly = poly.intersection(study_area_geom)
            if poly.is_empty:
                continue

        area_km2 = poly.area / 1e6
        records.append({
            "class_id": class_id,
            "class_name": class_names.get(class_id, f"Class_{class_id}"),
            "year": int(year),
            "area_km2": float(area_km2),
            "geometry": poly,
        })

    output_shp.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        gdf = gpd.GeoDataFrame(
            columns=["class_id", "class_name", "year", "area_km2", "geometry"],
            crs=crs,
        )
    else:
        gdf = gpd.GeoDataFrame(records, crs=crs)

    # 保存为 ESRI Shapefile
    gdf.to_file(output_shp, driver="ESRI Shapefile", encoding="utf-8")

    # 写入 .cpg 编码描述文件，确保 GIS 软件识别 UTF-8
    cpg_path = output_shp.with_suffix(".cpg")
    cpg_path.write_text("UTF-8\n", encoding="utf-8")

    return output_shp


# ---------------------------------------------------------------------------
# 4. 统计表格与评价报告导出（Report and Table Exporters）
# ---------------------------------------------------------------------------

def export_confusion_matrix_csv(
    csv_path: Path,
    matrix: list[list[int]],
    class_order: list[int] = [1, 2, 3, 4, 5],
) -> Path:
    """将混淆矩阵导出为带有标准表头的 CSV 格式表格。

    表头规范：true_class, pred_1, pred_2, pred_3, pred_4, pred_5

    Args:
        csv_path (Path): 导出文件路径。
        matrix (list[list[int]]): 5x5 混淆矩阵数据。
        class_order (list[int], optional): 类别排序。默认为 [1, 2, 3, 4, 5]。

    Returns:
        Path: 导出的 CSV 文件路径。
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["true_class"] + [f"pred_{c}" for c in class_order]

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i, c in enumerate(class_order):
            writer.writerow([c, *matrix[i]])

    return csv_path


def export_metrics_csv(
    csv_path: Path,
    metrics: list[dict[str, Any]],
) -> Path:
    """将各类别精度指标导出为 CSV 表格（含精确率、召回率、F1 和样本支持量）。

    Args:
        csv_path (Path): 导出路径。
        metrics (list[dict[str, Any]]): 各类别指标字典列表。

    Returns:
        Path: 导出的 CSV 文件路径。
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["class_id", "precision", "recall", "f1", "support"]

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in metrics:
            writer.writerow(row)

    return csv_path


# 开启 GDAL 异常模式
gdal.UseExceptions()


def generate_evaluation_report(
    json_path: Path,
    md_path: Path,
    year: int,
    oa_raw: float,
    oa_final: float,
    matrix_raw: list[list[int]],
    matrix_final: list[list[int]],
    metrics_raw: list[dict[str, Any]],
    metrics_final: list[dict[str, Any]],
    total_samples: int,
    total_groups: int,
    oa_threshold: float = 0.75,
    f1_target: float = 0.75,
) -> None:
    """输出 JSON 与 Markdown 双格式的精度评定分析报告。

    内容涵盖：原始/最终总体精度对比、硬性门槛判定结果、建设用地核心 F1 分数、完整混淆矩阵及各类查准查全指标。

    Args:
        json_path (Path): 输出 JSON 报告路径。
        md_path (Path): 输出 Markdown 报告路径。
        year (int): 评价年份。
        oa_raw (float): 原始预测总体精度。
        oa_final (float): 最终平滑后总体精度。
        matrix_raw (list[list[int]]): 原始混淆矩阵。
        matrix_final (list[list[int]]): 最终混淆矩阵。
        metrics_raw (list[dict[str, Any]]): 原始类别指标。
        metrics_final (list[dict[str, Any]]): 最终类别指标。
        total_samples (int): 留出验证集样本总像元数。
        total_groups (int): 留出验证集独立地块组数。
        oa_threshold (float, optional): 总体精度准入门槛。默认为 0.75。
        f1_target (float, optional): 建设用地目标 F1 阈值。默认为 0.75。
    """
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    passed_oa = check_accuracy_threshold(oa_final, oa_threshold)

    built_up_f1 = next((m["f1"] for m in metrics_final if m["class_id"] == 1), 0.0)
    passed_f1 = built_up_f1 >= f1_target

    # JSON 文件中保留完整精度的浮点数值
    report_dict = {
        "year": year,
        "total_samples": total_samples,
        "total_groups": total_groups,
        "oa_raw": float(oa_raw),
        "oa_final": float(oa_final),
        "oa_threshold": float(oa_threshold),
        "passed_oa_threshold": bool(passed_oa),
        "built_up_f1_target": float(f1_target),
        "built_up_f1_final": float(built_up_f1),
        "passed_f1_target": bool(passed_f1),
        "matrix_raw": matrix_raw,
        "matrix_final": matrix_final,
        "metrics_raw": metrics_raw,
        "metrics_final": metrics_final,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    md_lines = [
        f"# {year} 年土地覆盖分类独立精度评价报告",
        "",
        f"- **评价年份：** {year}",
        f"- **独立留出样本总数：** {total_samples} 像元",
        f"- **空间地块组数：** {total_groups} 组",
        f"- **原始分类总体精度 Overall Accuracy (OA) (Raw)：** {oa_raw:.4f}",
        f"- **最终分类总体精度 Overall Accuracy (OA) (Final)：** {oa_final:.4f}",
        f"- **硬性准入门槛 (OA > {oa_threshold})：** {'通过 (PASS)' if passed_oa else '未达标 (FAIL)'}",
        f"- **建设用地 F1 目标 (F1 ≥ {f1_target})：** {built_up_f1:.4f} ({'达标' if passed_f1 else '未达标'})",
        "",
        "## 1. 最终分类混淆矩阵 (Final Confusion Matrix)",
        "",
        "| 真实类别 \\ 预测类别 | 建设用地(1) | 耕地(2) | 其他植被(3) | 水域(4) | 裸地(5) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    class_names_map = {1: "建设用地(1)", 2: "耕地(2)", 3: "其他植被(3)", 4: "水域(4)", 5: "裸地(5)"}
    for i, row in enumerate(matrix_final):
        row_str = " | ".join(str(v) for v in row)
        md_lines.append(f"| {class_names_map[i+1]} | {row_str} |")

    md_lines.extend([
        "",
        "## 2. 最终分类各类指标 (Final Class Metrics)",
        "",
        "| 类别代码 | 类别名称 | Precision | Recall | F1-Score | Support |",
        "| :---: | :--- | :---: | :---: | :---: | :---: |",
    ])

    for m in metrics_final:
        cid = m["class_id"]
        cname = class_names_map.get(cid, str(cid))
        md_lines.append(f"| {cid} | {cname} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['support']} |")

    md_lines.append("")
    md_path.write_text("\n".join(md_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. 流水线执行主入口：finalize_evaluate
# ---------------------------------------------------------------------------

def finalize_evaluate(ctx: ProjectContext, year: int) -> EvaluationData:
    """执行阶段 P1-D 的后处理平滑、矢量化裁剪以及独立验证集精度评定全流程。

    执行步骤：
    1. 读取原始预测分类栅格 lulc_{year}_raw_30m.tif；
    2. 执行 GDAL Sieve 滤波平滑微小杂斑，输出最终分类栅格 lulc_{year}_final_30m.tif；
    3. 矢量化并根据新都区法定边界求交裁剪，输出 lulc_{year}.shp；
    4. 读取独立留出验证集 holdout.csv，核算原始与最终分类的混淆矩阵与精度指标；
    5. 导出各类 CSV 统计表格与 JSON/Markdown 精度评定报告。

    Args:
        ctx (ProjectContext): 项目运行上下文。
        year (int): 目标年份。

    Returns:
        EvaluationData: 包含成果栅格路径、矢量路径、评价报告路径及 OA 指标的数据契约对象。

    Raises:
        FileNotFoundError: 当必要的前置原始预测文件、留出集或边界矢量缺失时抛出。
        ValueError: 当留出验证集为空时抛出。
    """
    raw_path = ctx.outputs / "rasters" / f"lulc_{year}_raw_30m.tif"
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw classification raster not found: {raw_path}")

    holdout_csv = ctx.data / "processed" / "samples" / str(year) / "holdout.csv"
    if not holdout_csv.exists():
        raise FileNotFoundError(f"Holdout samples CSV not found: {holdout_csv}")

    split_json_path = ctx.data / "processed" / "samples" / str(year) / "split.json"
    total_groups = 0
    if split_json_path.exists():
        with open(split_json_path, "r", encoding="utf-8") as f:
            split_meta = json.load(f)
            total_groups = len(split_meta.get("holdout_groups", []))

    # 读取用于裁剪的研究区边界
    ref_year = ctx.config.get("boundary_reference_year", 2021)
    bnd_path = ctx.data / "processed" / "boundaries" / f"xindu_{ref_year}.gpkg"
    study_area_geom = None
    if bnd_path.exists():
        gdf_study = gpd.read_file(bnd_path, layer="study_area")
        study_area_geom = gdf_study.union_all() if hasattr(gdf_study, "union_all") else gdf_study.unary_union
    else:
        raise FileNotFoundError(f"Study area boundary file not found: {bnd_path}")

    # 读取原始预测栅格数据
    with rasterio.open(raw_path) as src:
        raw_arr = src.read(1)
        meta = src.meta.copy()
        crs_str = src.crs.to_string() if src.crs else "EPSG:32648"
        transform = src.transform

    # 读取后处理滤波配置
    post_cfg = ctx.config.get("postprocess", {})
    sieve_thresh = int(post_cfg.get("sieve_threshold_pixels", 4))
    connectivity = int(post_cfg.get("connectivity", 8))

    # 1. 执行 GDAL Sieve 杂斑滤波
    final_arr = sieve_classification(
        raw_arr=raw_arr,
        threshold_pixels=sieve_thresh,
        connectivity=connectivity,
        nodata_val=0,
    )

    # 保存最终分类栅格
    final_dir = ctx.outputs / "rasters"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / f"lulc_{year}_final_30m.tif"

    meta.update({
        "dtype": "uint8",
        "nodata": 0,
        "count": 1,
    })
    with rasterio.open(final_path, "w", **meta) as dst:
        dst.write(final_arr, 1)

    # 2. 栅格转矢量并裁剪至研究区
    class_map = {item["code"]: item["name"] for item in ctx.config.get("classes", [])}
    vector_dir = ctx.outputs / "vectors" / str(year)
    shp_path = vector_dir / f"lulc_{year}.shp"

    vectorize_and_clip(
        raster_arr=final_arr,
        transform=transform,
        crs=crs_str,
        study_area_geom=study_area_geom,
        year=year,
        class_names=class_map,
        output_shp=shp_path,
        nodata_val=0,
    )

    # 3. 读取独立留出验证集样本并抽取原始与平滑后的分类预测值
    holdout_samples: list[dict[str, Any]] = []
    with open(holdout_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            holdout_samples.append({
                "class_id": int(row["class_id"]),
                "row": int(row["row"]),
                "col": int(row["col"]),
                "group_id": row.get("group_id", ""),
            })

    if not holdout_samples:
        raise ValueError(f"Holdout CSV is empty: {holdout_csv}")

    y_true = [s["class_id"] for s in holdout_samples]
    y_raw = [int(raw_arr[s["row"], s["col"]]) for s in holdout_samples]
    y_final = [int(final_arr[s["row"], s["col"]]) for s in holdout_samples]

    eval_cfg = ctx.config.get("evaluation", {})
    class_order = eval_cfg.get("class_order", [1, 2, 3, 4, 5])
    oa_threshold = float(eval_cfg.get("overall_accuracy_strictly_greater_than", 0.75))
    f1_target = float(eval_cfg.get("built_up_f1_target", 0.75))

    matrix_raw, oa_raw = calculate_confusion_matrix(y_true, y_raw, class_order)
    matrix_final, oa_final = calculate_confusion_matrix(y_true, y_final, class_order)

    metrics_raw = calculate_class_metrics(matrix_raw, class_order)
    metrics_final = calculate_class_metrics(matrix_final, class_order)

    # 4. 导出 CSV 混淆矩阵与指标明细表
    tables_dir = ctx.outputs / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    export_confusion_matrix_csv(tables_dir / f"confusion_{year}_raw.csv", matrix_raw, class_order)
    export_confusion_matrix_csv(tables_dir / f"confusion_{year}_final.csv", matrix_final, class_order)
    export_metrics_csv(tables_dir / f"metrics_{year}_raw.csv", metrics_raw)
    export_metrics_csv(tables_dir / f"metrics_{year}_final.csv", metrics_final)

    # 5. 输出综合评定 JSON 与 Markdown 报告
    rep_dir = ctx.reports / "accuracy"
    rep_dir.mkdir(parents=True, exist_ok=True)
    json_path = rep_dir / f"evaluation_{year}.json"
    md_path = rep_dir / f"evaluation_{year}.md"

    generate_evaluation_report(
        json_path=json_path,
        md_path=md_path,
        year=year,
        oa_raw=oa_raw,
        oa_final=oa_final,
        matrix_raw=matrix_raw,
        matrix_final=matrix_final,
        metrics_raw=metrics_raw,
        metrics_final=metrics_final,
        total_samples=len(y_true),
        total_groups=total_groups,
        oa_threshold=oa_threshold,
        f1_target=f1_target,
    )

    return EvaluationData(
        year=year,
        final=final_path,
        vectors=shp_path,
        report=md_path,
        oa_raw=oa_raw,
        oa_final=oa_final,
    )
