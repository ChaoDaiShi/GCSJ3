"""城市扩张时空演变与街镇变化分析模块（P1-E）。

主要功能与科学处理流程：
1. compute_change_raster:
   - 构建 1992 年与 2021 年最终土地分类的“共同有效观测掩膜”（valid_common）：
     只有当像元落入法定研究区内，且两期分类结果均为合法分类值（1..5）时才视为有效对比；
     任一期存在云、阴影或无数据时均标记为无效像元（0），绝不虚假判定为建设用地的新增或减少；
   - 提取 4 类建设用地动态变化编码：
     * 1 = 持续建设（1 -> 1）
     * 2 = 新增建设（非建设 [2..5] -> 1）
     * 3 = 减少建设（1 -> 非建设 [2..5]）
     * 4 = 持续非建设（非建设 [2..5] -> 非建设 [2..5]）
     * 0 = NoData（研究区外或任一期无效）

2. vectorize_change_raster:
   - 将 4 类变化栅格矢量化为多边形矢量图层，关联标准中文分类名称。

3. calculate_change_statistics:
   - 与 2021 年街镇行政区划矢量图层执行空间几何叠加（Spatial Overlay Intersection）；
   - 计算各行政单元的指标：
     * total_area_km2: 行政单元法定边界总面积
     * comparable_area_km2: 两期共同有效观测覆盖的实际可比面积
     * valid_ratio: 空间数据有效覆盖度比率
     * built_1992_km2 / built_2021_km2: 1992 及 2021 年的建设用地面积
     * persistent_km2 / added_km2 / lost_km2 / net_km2: 持续、新增、减少与净增建设用地面积
     * annual_net_km2: 年均净增扩张速率（净增量 / 历时年数 29 年）
     * annual_intensity_pct: 年均扩张强度指数（(净增量 / (历时年数 * 辖区总面积)) * 100%）
   - 面积平衡核验（Area Balance Check）：严格核查“各街镇可比面积之和 == 全区可比面积”与“各街镇净增量之和 == 全区净增量”，容差控制在 1e-6 平方公里内。

4. analyze_change:
   - 调度执行两期变化分析流水线，输出变化栅格、GPKG 图层、统计表格与 JSON 审计摘要。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize, shapes
from shapely.geometry import shape

from rs_urban.contracts import ChangeData, ProjectContext

# 标准 4 类变化类别编码与其规范中文名称
CHANGE_NAMES = {
    1: "持续建设",
    2: "新增建设",
    3: "减少建设",
    4: "持续非建设",
}

# 变化栅格色彩映射表：0=透明背景, 1=持续建设(橙色), 2=新增建设(红色), 3=减少建设(蓝色), 4=持续非建设(灰色)
CHANGE_COLORMAP = {
    0: (0, 0, 0, 0),
    1: (217, 95, 2, 255),
    2: (228, 26, 28, 255),
    3: (55, 126, 184, 255),
    4: (179, 179, 179, 255),
}

# 输出统计 CSV 表格的标准字段顺序
TABLE_FIELDNAMES = [
    "unit_id",
    "name",
    "unit_type",
    "boundary_year",
    "total_area_km2",
    "comparable_area_km2",
    "valid_ratio",
    "built_1992_km2",
    "built_2021_km2",
    "persistent_km2",
    "added_km2",
    "lost_km2",
    "net_km2",
    "annual_net_km2",
    "annual_intensity_pct",
]


def compute_change_raster(
    final_1992: np.ndarray,
    final_2021: np.ndarray,
    in_study_area: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """计算两期土地分类的 4 分类时空转移栅格与共同有效像元掩膜。

    变化栅格编码规范：
      - 0 = NoData（任一期缺失/无效，或在研究区外部）
      - 1 = 持续建设（1992年为建设用地，2021年仍为建设用地）
      - 2 = 新增建设（1992年为非建设用地 [2..4]，2021年转为建设用地 1）
      - 3 = 减少建设（1992年为建设用地 1，2021年转为非建设用地 [2..4]）
      - 4 = 持续非建设（1992年为非建设用地，2021年仍为非建设用地）

    共同有效观测掩膜（valid_common）编码规范：
      - 1   = 共同有效（两期在研究区内均有明确的地类分类 1..5）
      - 0   = 研究区内无效（任一期或两期均缺失或为 NoData）
      - 255 = 研究区外部

    Args:
        final_1992 (np.ndarray): 1992 年最终分类矩阵（uint8）。
        final_2021 (np.ndarray): 2021 年最终分类矩阵（uint8）。
        in_study_area (np.ndarray): 标记像元是否位于研究区内部的布尔矩阵。

    Returns:
        tuple[np.ndarray, np.ndarray]:
            - change_grid: uint8 变化栅格矩阵（取值 0..4）；
            - valid_common_grid: uint8 共同有效观测掩膜矩阵（取值 0, 1, 255）。
    """
    valid_1992 = (final_1992 >= 1) & (final_1992 <= 5)
    valid_2021 = (final_2021 >= 1) & (final_2021 <= 5)
    both_valid = valid_1992 & valid_2021 & in_study_area

    # 变化栅格默认初始化为 0 (NoData)
    change_grid = np.zeros_like(final_1992, dtype=np.uint8)

    # 1: 持续建设 (1 -> 1)
    mask_persistent = both_valid & (final_1992 == 1) & (final_2021 == 1)
    change_grid[mask_persistent] = 1

    # 2: 新增建设 ([2..5] -> 1)
    mask_added = both_valid & (final_1992 >= 2) & (final_2021 == 1)
    change_grid[mask_added] = 2

    # 3: 减少建设 (1 -> [2..5])
    mask_lost = both_valid & (final_1992 == 1) & (final_2021 >= 2)
    change_grid[mask_lost] = 3

    # 4: 持续非建设 ([2..5] -> [2..5])
    mask_nonbuilt = both_valid & (final_1992 >= 2) & (final_2021 >= 2)
    change_grid[mask_nonbuilt] = 4

    # 构建共同有效掩膜栅格
    valid_common_grid = np.full_like(final_1992, 255, dtype=np.uint8)
    valid_common_grid[in_study_area & both_valid] = 1
    valid_common_grid[in_study_area & ~both_valid] = 0

    return change_grid, valid_common_grid


def vectorize_change_raster(
    change_grid: np.ndarray,
    transform: rasterio.Affine,
    crs: str = "EPSG:32648",
) -> gpd.GeoDataFrame:
    """将有效变化栅格（类别 1..4）转换为多边形矢量 GeoDataFrame。

    Args:
        change_grid (np.ndarray): 变化栅格数组。
        transform (rasterio.Affine): 栅格仿射变换参数。
        crs (str, optional): 目标空间参考坐标系。默认为 "EPSG:32648"。

    Returns:
        gpd.GeoDataFrame: 包含 change_id、change_name 和 geometry 字段的多边形矢量数据。
    """
    mask = (change_grid >= 1) & (change_grid <= 4)
    if not np.any(mask):
        return gpd.GeoDataFrame(columns=["change_id", "change_name", "geometry"], crs=crs)

    shapes_gen = shapes(change_grid, mask=mask, transform=transform)
    records = []
    for geom_dict, val in shapes_gen:
        val_int = int(val)
        if val_int in CHANGE_NAMES:
            records.append({
                "change_id": val_int,
                "change_name": CHANGE_NAMES[val_int],
                "geometry": shape(geom_dict),
            })

    if not records:
        return gpd.GeoDataFrame(columns=["change_id", "change_name", "geometry"], crs=crs)

    return gpd.GeoDataFrame(records, crs=crs)


def calculate_change_statistics(
    gdf_change: gpd.GeoDataFrame,
    gdf_study_area: gpd.GeoDataFrame,
    gdf_townships: gpd.GeoDataFrame,
    elapsed_years: int = 29,
    boundary_year: int = 2021,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """通过空间几何叠加分析（Spatial Overlay）计算全区及各街镇的城市扩张指标，并执行严密的面积平衡核验。

    计算指标包括：
    - total_area_km2: 行政边界多边形几何面积；
    - comparable_area_km2: 共同有效观测的实际比对覆盖面积；
    - valid_ratio: 有效比率（可比面积 / 辖区总面积）；
    - built_1992_km2 = 持续建设面积 + 减少建设面积；
    - built_2021_km2 = 持续建设面积 + 新增建设面积；
    - net_km2 = 新增建设面积 - 减少建设面积；
    - annual_net_km2 = net_km2 / elapsed_years；
    - annual_intensity_pct = (net_km2 / (elapsed_years * total_area_km2)) * 100%。

    面积平衡性检验逻辑：
    - sum(街镇可比面积) 与 全区可比面积 之差 ≤ 容差；
    - sum(街镇净增面积) 与 全区净增面积 之差 ≤ 容差；
    - 容差取 max(1e-6, 全区面积 * 1e-6)。

    Args:
        gdf_change (gpd.GeoDataFrame): 变化图斑矢量。
        gdf_study_area (gpd.GeoDataFrame): 全区法定边界矢量。
        gdf_townships (gpd.GeoDataFrame): 街镇行政区划矢量。
        elapsed_years (int, optional): 历时年数。默认为 29（1992 至 2021）。
        boundary_year (int, optional): 行政边界基准年份。默认为 2021。

    Returns:
        tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
            - townships_df: 各街镇扩张变化统计表；
            - district_df: 全区综合扩张变化统计表；
            - stats_summary: 包含完整面积核对证据的审计摘要字典。
    """
    crs = gdf_study_area.crs

    # 将变化图斑严格裁剪至全区研究区边界内部
    study_area_geom = (
        gdf_study_area.geometry.union_all()
        if hasattr(gdf_study_area.geometry, "union_all")
        else gdf_study_area.geometry.unary_union
    )
    if not gdf_change.empty:
        gdf_change_clipped = gpd.clip(gdf_change, study_area_geom)
    else:
        gdf_change_clipped = gpd.GeoDataFrame(columns=["change_id", "change_name", "geometry"], crs=crs)

    # 1. 统计全区指标（District statistics）
    district_total_area_km2 = study_area_geom.area / 1e6

    area_id = str(gdf_study_area["area_id"].iloc[0]) if "area_id" in gdf_study_area.columns else "510114"
    district_name = str(gdf_study_area["name"].iloc[0]) if "name" in gdf_study_area.columns else "成都市新都区"

    if not gdf_change_clipped.empty:
        gdf_change_clipped["area_km2"] = gdf_change_clipped.geometry.area / 1e6
        dist_comp_km2 = gdf_change_clipped["area_km2"].sum()
        dist_p_km2 = gdf_change_clipped[gdf_change_clipped["change_id"] == 1]["area_km2"].sum()
        dist_a_km2 = gdf_change_clipped[gdf_change_clipped["change_id"] == 2]["area_km2"].sum()
        dist_l_km2 = gdf_change_clipped[gdf_change_clipped["change_id"] == 3]["area_km2"].sum()
    else:
        dist_comp_km2 = 0.0
        dist_p_km2 = 0.0
        dist_a_km2 = 0.0
        dist_l_km2 = 0.0

    dist_valid_ratio = dist_comp_km2 / district_total_area_km2 if district_total_area_km2 > 0 else 0.0
    dist_built_1992 = dist_p_km2 + dist_l_km2
    dist_built_2021 = dist_p_km2 + dist_a_km2
    dist_net_km2 = dist_a_km2 - dist_l_km2
    dist_annual_net_km2 = dist_net_km2 / elapsed_years if elapsed_years > 0 else 0.0
    dist_annual_intensity = (
        (dist_net_km2 / (elapsed_years * district_total_area_km2)) * 100
        if (elapsed_years > 0 and district_total_area_km2 > 0)
        else 0.0
    )

    district_row = {
        "unit_id": area_id,
        "name": district_name,
        "unit_type": "district",
        "boundary_year": boundary_year,
        "total_area_km2": round(district_total_area_km2, 6),
        "comparable_area_km2": round(dist_comp_km2, 6),
        "valid_ratio": round(dist_valid_ratio, 6),
        "built_1992_km2": round(dist_built_1992, 6),
        "built_2021_km2": round(dist_built_2021, 6),
        "persistent_km2": round(dist_p_km2, 6),
        "added_km2": round(dist_a_km2, 6),
        "lost_km2": round(dist_l_km2, 6),
        "net_km2": round(dist_net_km2, 6),
        "annual_net_km2": round(dist_annual_net_km2, 6),
        "annual_intensity_pct": round(dist_annual_intensity, 6),
    }
    district_df = pd.DataFrame([district_row], columns=TABLE_FIELDNAMES)

    # 2. 空间几何叠加统计街镇指标（Township statistics via spatial overlay）
    township_rows: list[dict[str, Any]] = []

    if not gdf_change_clipped.empty and not gdf_townships.empty:
        # 执行相交叠加操作
        inter = gpd.overlay(gdf_change_clipped, gdf_townships, how="intersection")
        inter["area_km2"] = inter.geometry.area / 1e6
    else:
        inter = gpd.GeoDataFrame()

    for _, t_row in gdf_townships.iterrows():
        u_id = str(t_row["unit_id"])
        u_name = str(t_row["name"])
        u_type = str(t_row.get("unit_type", "town"))
        t_geom = t_row.geometry
        t_total_area_km2 = t_geom.area / 1e6

        if not inter.empty and u_id in inter["unit_id"].values:
            t_inter = inter[inter["unit_id"] == u_id]
            t_comp_km2 = t_inter["area_km2"].sum()
            t_p_km2 = t_inter[t_inter["change_id"] == 1]["area_km2"].sum()
            t_a_km2 = t_inter[t_inter["change_id"] == 2]["area_km2"].sum()
            t_l_km2 = t_inter[t_inter["change_id"] == 3]["area_km2"].sum()
        else:
            t_comp_km2 = 0.0
            t_p_km2 = 0.0
            t_a_km2 = 0.0
            t_l_km2 = 0.0

        if t_comp_km2 == 0.0:
            # 当该街镇无有效可比面积时，依据契约将变化指标置空
            row_dict = {
                "unit_id": u_id,
                "name": u_name,
                "unit_type": u_type,
                "boundary_year": boundary_year,
                "total_area_km2": round(t_total_area_km2, 6),
                "comparable_area_km2": 0.0,
                "valid_ratio": 0.0,
                "built_1992_km2": "",
                "built_2021_km2": "",
                "persistent_km2": "",
                "added_km2": "",
                "lost_km2": "",
                "net_km2": "",
                "annual_net_km2": "",
                "annual_intensity_pct": "",
            }
        else:
            t_valid_ratio = t_comp_km2 / t_total_area_km2 if t_total_area_km2 > 0 else 0.0
            t_built_1992 = t_p_km2 + t_l_km2
            t_built_2021 = t_p_km2 + t_a_km2
            t_net_km2 = t_a_km2 - t_l_km2
            t_annual_net_km2 = t_net_km2 / elapsed_years if elapsed_years > 0 else 0.0
            t_annual_intensity = (
                (t_net_km2 / (elapsed_years * t_total_area_km2)) * 100
                if (elapsed_years > 0 and t_total_area_km2 > 0)
                else 0.0
            )

            row_dict = {
                "unit_id": u_id,
                "name": u_name,
                "unit_type": u_type,
                "boundary_year": boundary_year,
                "total_area_km2": round(t_total_area_km2, 6),
                "comparable_area_km2": round(t_comp_km2, 6),
                "valid_ratio": round(t_valid_ratio, 6),
                "built_1992_km2": round(t_built_1992, 6),
                "built_2021_km2": round(t_built_2021, 6),
                "persistent_km2": round(t_p_km2, 6),
                "added_km2": round(t_a_km2, 6),
                "lost_km2": round(t_l_km2, 6),
                "net_km2": round(t_net_km2, 6),
                "annual_net_km2": round(t_annual_net_km2, 6),
                "annual_intensity_pct": round(t_annual_intensity, 6),
            }

        township_rows.append(row_dict)

    townships_df = pd.DataFrame(township_rows, columns=TABLE_FIELDNAMES)

    # 3. 严格执行面积平衡性核查（Area Balance Verification）
    t_comp_sum = sum(r["comparable_area_km2"] for r in township_rows)
    t_p_sum = sum(r["persistent_km2"] for r in township_rows if r["persistent_km2"] != "")
    t_a_sum = sum(r["added_km2"] for r in township_rows if r["added_km2"] != "")
    t_l_sum = sum(r["lost_km2"] for r in township_rows if r["lost_km2"] != "")
    t_net_sum = sum(r["net_km2"] for r in township_rows if r["net_km2"] != "")

    tolerance_km2 = max(1e-6, district_total_area_km2 * 1e-6)
    discrepancy_comp_km2 = abs(t_comp_sum - dist_comp_km2)
    discrepancy_net_km2 = abs(t_net_sum - dist_net_km2)
    is_balanced = (discrepancy_comp_km2 <= tolerance_km2) and (discrepancy_net_km2 <= tolerance_km2)

    # 汇总平衡检验数据结构
    stats_summary = {
        "schema_version": 1,
        "boundary_year": boundary_year,
        "elapsed_years": elapsed_years,
        "area_unit": "km2",
        "district_summary": district_row,
        "township_count": len(township_rows),
        "townships_summary": township_rows,
        "area_balance_check": {
            "township_comparable_area_sum": round(t_comp_sum, 6),
            "district_comparable_area": round(dist_comp_km2, 6),
            "township_persistent_sum": round(t_p_sum, 6),
            "district_persistent": round(dist_p_km2, 6),
            "township_added_sum": round(t_a_sum, 6),
            "district_added": round(dist_a_km2, 6),
            "township_lost_sum": round(t_l_sum, 6),
            "district_lost": round(dist_l_km2, 6),
            "township_net_sum": round(t_net_sum, 6),
            "district_net": round(dist_net_km2, 6),
            "discrepancy_comparable_km2": round(discrepancy_comp_km2, 9),
            "discrepancy_net_km2": round(discrepancy_net_km2, 9),
            "tolerance_km2": round(tolerance_km2, 9),
            "is_balanced": bool(is_balanced),
        },
        "coverage_notes": "共同有效掩膜仅在两期均有有效观测（非NoData）且在研究区内时计算，云或数据缺失像元不判定为新增或减少。",
    }

    return townships_df, district_df, stats_summary


def analyze_change(ctx: ProjectContext) -> ChangeData:
    """执行阶段 P1-E 城市扩张分析的主入口函数。

    处理步骤：
    1. 读取 1992 与 2021 年最终土地利用分类栅格及法定边界矢量；
    2. 计算 4 类变化栅格与共同有效掩膜；
    3. 输出 valid_common_30m.tif 掩膜；
    4. 导出带有专属标准色表的 change_1992_2021_30m.tif 栅格；
    5. 矢量化变化区域并导出为 GeoPackage（urban_change.gpkg）；
    6. 计算全区及各街镇的年均净增速率与年均扩张强度；
    7. 输出 township_change_1992_2021.csv、district_change_1992_2021.csv 与 statistics.json。

    Args:
        ctx (ProjectContext): 项目运行上下文。

    Returns:
        ChangeData: 包含变化栅格、矢量及统计表格路径的数据契约对象。

    Raises:
        FileNotFoundError: 当必要输入文件缺失时抛出。
        ValueError: 当两期分类栅格的空间规格不一致时抛出。
    """
    # 标准输入路径
    final_1992_path = ctx.outputs / "rasters" / "lulc_1992_final_30m.tif"
    final_2021_path = ctx.outputs / "rasters" / "lulc_2021_final_30m.tif"
    boundaries_path = ctx.data / "processed" / "boundaries" / "xindu_2021.gpkg"
    aoi_path = ctx.data / "processed" / "grids" / "aoi_30m.tif"

    if not final_1992_path.exists():
        raise FileNotFoundError(f"1992 final classification raster not found: {final_1992_path}")
    if not final_2021_path.exists():
        raise FileNotFoundError(f"2021 final classification raster not found: {final_2021_path}")
    if not boundaries_path.exists():
        raise FileNotFoundError(f"Administrative boundaries GPKG not found: {boundaries_path}")

    # 标准输出路径
    valid_common_path = ctx.data / "processed" / "common" / "valid_common_30m.tif"
    change_raster_path = ctx.outputs / "rasters" / "change_1992_2021_30m.tif"
    vectors_path = ctx.outputs / "vectors" / "change" / "urban_change.gpkg"
    townships_csv_path = ctx.outputs / "tables" / "township_change_1992_2021.csv"
    district_csv_path = ctx.outputs / "tables" / "district_change_1992_2021.csv"
    statistics_json_path = ctx.reports / "analysis" / "statistics.json"

    # 1. 读取并校验两期输入栅格规格一致性
    with rasterio.open(final_1992_path) as src_1992, rasterio.open(final_2021_path) as src_2021:
        if (src_1992.width, src_1992.height) != (src_2021.width, src_2021.height):
            raise ValueError(
                f"Dimension mismatch: 1992 ({src_1992.width}x{src_1992.height}) vs 2021 ({src_2021.width}x{src_2021.height})"
            )
        if src_1992.transform != src_2021.transform:
            raise ValueError(f"Transform mismatch: 1992 ({src_1992.transform}) vs 2021 ({src_2021.transform})")
        if src_1992.crs != src_2021.crs:
            raise ValueError(f"CRS mismatch: 1992 ({src_1992.crs}) vs 2021 ({src_2021.crs})")

        f1992 = src_1992.read(1)
        f2021 = src_2021.read(1)
        meta = src_1992.meta.copy()

    # 读取行政边界图层
    gdf_study_area = gpd.read_file(boundaries_path, layer="study_area")
    gdf_townships = gpd.read_file(boundaries_path, layer="townships")

    # 获取全区掩膜数组
    if aoi_path.exists():
        with rasterio.open(aoi_path) as aoi_src:
            in_study_area = (aoi_src.read(1) == 1)
    else:
        in_study_area = rasterize(
            gdf_study_area.geometry,
            out_shape=(meta["height"], meta["width"]),
            transform=meta["transform"],
            fill=0,
            default_value=1,
            all_touched=True,
        ) == 1

    # 2. 计算 4 类变化栅格与共同有效掩膜
    change_grid, valid_common_grid = compute_change_raster(
        final_1992=f1992,
        final_2021=f2021,
        in_study_area=in_study_area,
    )

    # 3. 输出共同有效掩膜栅格 valid_common_30m.tif
    valid_common_path.parent.mkdir(parents=True, exist_ok=True)
    meta_common = meta.copy()
    meta_common.update(dtype=rasterio.uint8, nodata=255, count=1)
    with rasterio.open(valid_common_path, "w", **meta_common) as dst_common:
        dst_common.write(valid_common_grid, 1)

    # 4. 输出变化分析栅格 change_1992_2021_30m.tif 并附加色彩映射表
    change_raster_path.parent.mkdir(parents=True, exist_ok=True)
    meta_change = meta.copy()
    meta_change.update(dtype=rasterio.uint8, nodata=0, count=1)
    with rasterio.open(change_raster_path, "w", **meta_change) as dst_change:
        dst_change.write(change_grid, 1)
        dst_change.write_colormap(1, CHANGE_COLORMAP)

    # 5. 变化栅格矢量化为 GeoPackage 图层
    gdf_change = vectorize_change_raster(
        change_grid=change_grid,
        transform=meta["transform"],
        crs=str(meta["crs"]),
    )

    # 保存至 urban_change.gpkg (图层名: change)
    vectors_path.parent.mkdir(parents=True, exist_ok=True)
    study_area_geom = (
        gdf_study_area.geometry.union_all()
        if hasattr(gdf_study_area.geometry, "union_all")
        else gdf_study_area.geometry.unary_union
    )
    if not gdf_change.empty:
        gdf_change_clipped = gpd.clip(gdf_change, study_area_geom)
        gdf_urban_change = gdf_change_clipped.dissolve(by=["change_id", "change_name"], as_index=False)
        gdf_urban_change["area_km2"] = gdf_urban_change.geometry.area / 1e6
    else:
        gdf_urban_change = gpd.GeoDataFrame(columns=["change_id", "change_name", "geometry", "area_km2"], crs=meta["crs"])

    gdf_urban_change.to_file(vectors_path, layer="change", driver="GPKG")

    # 6. 计算街镇与全区指标统计
    elapsed_years = int(ctx.config.get("analysis", {}).get("elapsed_years", 29))
    boundary_year = int(ctx.config.get("boundary_reference_year", 2021))

    townships_df, district_df, stats_summary = calculate_change_statistics(
        gdf_change=gdf_change,
        gdf_study_area=gdf_study_area,
        gdf_townships=gdf_townships,
        elapsed_years=elapsed_years,
        boundary_year=boundary_year,
    )

    # 7. 导出 CSV 统计表格
    townships_csv_path.parent.mkdir(parents=True, exist_ok=True)
    townships_df.to_csv(townships_csv_path, index=False, encoding="utf-8")

    district_csv_path.parent.mkdir(parents=True, exist_ok=True)
    district_df.to_csv(district_csv_path, index=False, encoding="utf-8")

    # 8. 输出统计审计 JSON 文件
    statistics_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(statistics_json_path, "w", encoding="utf-8") as f:
        json.dump(stats_summary, f, indent=2, ensure_ascii=False)

    return ChangeData(
        raster=change_raster_path,
        vectors=vectors_path,
        townships=townships_csv_path,
        district=district_csv_path,
    )
