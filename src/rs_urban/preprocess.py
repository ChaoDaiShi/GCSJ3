"""遥感影像预处理与行政边界制备核心模块（P1-A）。

主要功能与科学处理流程：
1. prepare_boundaries:
   - 读取编目中登记的县级与街镇级行政区划矢量，统一重投影至目标投影坐标系（EPSG:32648，UTM Zone 48N）；
   - 标准化图层字段属性，生成标准的 GeoPackage 文件（含 study_area 与 townships 两个图层）；
   - 根据研究区外包框向外对齐（Snap Outward），计算标准 30m 与 15m 分析网格规范；
   - 栅格化县级法定边界，生成全覆盖的 30m 二值分析掩膜 aoi_30m.tif（内部为 1，外部为 0）。

2. preprocess_year:
   - 读取已编目的 USGS Landsat Level-2 地表反射率产品；
   - 解析并严格校验 MTL 元数据（严禁静默回退或自动篡改日期与传感器类型）；
   - 依据 USGS Collection 2 规范解析 QA_PIXEL 与 QA_RADSAT 掩膜像元质量（过滤云、阴影、积雪及饱和像元，保留水体）；
   - 执行地表反射率定标（DN * 0.0000275 - 0.2），特别保护 Fill 像元（确保 DN=0 不会被错误定标为 -0.2）；
   - 将有效掩膜（最近邻插值）与反射率数据（双线性插值）重投影至标准 30m 网格；
   - 叠合研究区 AOI 掩膜与多波段有效性，生成 6 波段 sr_30m.tif 与单波段有效性掩膜 valid_sr_30m.tif。

3. pansharpen_2021:
   - 读取 2021 年 Landsat 8 Level-1 数据（RGB 与 Pan 波段）；
   - 根据太阳高度角与定标参数将 DN 转换为大气顶层反射率（TOA Reflectance）；
   - 采用 Gram-Schmidt 自适应（GSA）算法执行 15m 全色锐化融合，生成 pan_rgb_15m.tif，严格标注为仅用于可视化与目视解译。

4. build_feature_stack:
   - 基于 6 波段反射率、DEM 与有效性掩膜，生成 21 维特征堆栈（6 波段 + 7 指数 + 6 纹理 + 高程 + 坡度）；
   - 纹理只统计窗口内有效像元；TWI 需汇流累积量，属分析阶段，不在本步骤计算。
"""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any

# 若当前运行环境中存在 GDAL/PROJ 共享资源目录，自动设置环境变量以便读取坐标系定义
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
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.warp import reproject
from scipy.ndimage import uniform_filter
from shapely.geometry import box

from rs_urban.contracts import PreparedData, ProjectContext


# ---------------------------------------------------------------------------
# 1. 网格规格计算与外扩对齐（Grid computation and snapping）
# ---------------------------------------------------------------------------

def compute_grid_specs(
    raw_bounds: tuple[float, float, float, float] | list[float],
    resolution: float = 30.0,
    crs: str = "EPSG:32648",
    bounds_snap_resolution: float | None = None,
) -> dict[str, Any]:
    """根据数据契约第 1 节计算标准外扩对齐网格参数。

    空间外包矩形遵循向外对齐规则：
    - xmin / ymin 采用向下取整（floor），确保完全包含矢量边界；
    - xmax / ymax 采用向上取整（ceil），确保边缘像元不被裁剪；
    - bounds_snap_resolution 为边界对齐基准步长（默认为 resolution，通常为 30m）；
    - 仿射变换矩阵遵循 GDAL 6 参数定义顺序：[xmin, res, 0, ymax, 0, -res]。

    Args:
        raw_bounds (tuple[float, float, float, float] | list[float]): 原始边界四至 [xmin, ymin, xmax, ymax]。
        resolution (float, optional): 网格空间分辨率（单位：米）。默认为 30.0。
        crs (str, optional): 目标空间参考坐标系标识（EPSG 字符串）。默认为 "EPSG:32648"。
        bounds_snap_resolution (float | None, optional): 边界对齐的步长基准。若为 None 则使用 resolution。

    Returns:
        dict[str, Any]: 包含网格版本、坐标系、对齐边界、行列数及 GDAL 变换参数的字典。
    """
    snap_res = float(bounds_snap_resolution if bounds_snap_resolution is not None else resolution)
    res = float(resolution)

    xmin, ymin, xmax, ymax = raw_bounds
    # 向外整除扩展对齐坐标
    xmin_snap = math.floor(xmin / snap_res) * snap_res
    ymin_snap = math.floor(ymin / snap_res) * snap_res
    xmax_snap = math.ceil(xmax / snap_res) * snap_res
    ymax_snap = math.ceil(ymax / snap_res) * snap_res

    # 计算对齐后的栅格宽度与高度（像元数）
    width = int(round((xmax_snap - xmin_snap) / res))
    height = int(round((ymax_snap - ymin_snap) / res))
    # GDAL 格式的 6 参数仿射变换参数：[左上角X, X分辨率, 旋转X, 左上角Y, 旋转Y, Y分辨率(负数)]
    transform = [xmin_snap, res, 0.0, ymax_snap, 0.0, -res]

    return {
        "schema_version": 1,
        "crs": crs,
        "bounds": [xmin_snap, ymin_snap, xmax_snap, ymax_snap],
        "resolution": [res, res],
        "width": width,
        "height": height,
        "transform": transform,
    }


# ---------------------------------------------------------------------------
# 2. MTL 元数据解析与严格核验（MTL and Metadata Parsing）
# ---------------------------------------------------------------------------

def parse_mtl_metadata(mtl_path: Path) -> dict[str, str]:
    """解析 USGS Landsat MTL 文本格式元数据文件为平铺字典。

    逐行扫描 MTL 文件，解析类似 KEY = VALUE 的字段，并过滤掉分组标记和空白行。

    Args:
        mtl_path (Path): MTL 文本文件的路径。

    Returns:
        dict[str, str]: 包含所有元数据键值对的扁平字典。

    Raises:
        FileNotFoundError: 当 MTL 文件不存在时抛出。
    """
    if not mtl_path.exists():
        raise FileNotFoundError(f"MTL file does not exist: {mtl_path}")

    meta: dict[str, str] = {}
    with open(mtl_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            # 跳过控制行与空行
            if not line or line in ("END", "GROUP = L1_METADATA_FILE", "END_GROUP = L1_METADATA_FILE"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                key = k.strip()
                val = v.strip().strip('"').strip("'")
                if key not in meta:
                    meta[key] = val
    return meta


def validate_scene_metadata(catalog_entry: dict[str, Any], mtl_meta: dict[str, str]) -> None:
    """严格核对编目记录（scenes.csv）与实际影像 MTL 文件中的元数据。

    核验字段包含：
    - 传感器标识（SPACECRAFT_ID 与 sensor）
    - 成像日期（DATE_ACQUIRED 与 acquisition_date）
    - 产品标识符（LANDSAT_PRODUCT_ID 与 product_id）
    - 处理级别（PROCESSING_LEVEL 与 processing_level）

    若发现任何一项不匹配，立即中断并报错，绝不执行静默修正。

    Args:
        catalog_entry (dict[str, Any]): scenes.csv 中记录的编目信息字典。
        mtl_meta (dict[str, str]): 自 MTL 文本文件解析出的元数据字典。

    Raises:
        ValueError: 当编目信息与 MTL 元数据存在任何不一致时抛出。
    """
    cat_sensor = catalog_entry.get("sensor")
    mtl_sensor = mtl_meta.get("SPACECRAFT_ID")
    if cat_sensor and mtl_sensor and cat_sensor.upper() != mtl_sensor.upper():
        raise ValueError(
            f"Metadata validation error: sensor mismatch (catalog '{cat_sensor}' != MTL '{mtl_sensor}')"
        )

    cat_date = catalog_entry.get("acquisition_date")
    mtl_date = mtl_meta.get("DATE_ACQUIRED")
    if cat_date and mtl_date and cat_date != mtl_date:
        raise ValueError(
            f"Metadata validation error: acquisition_date mismatch (catalog '{cat_date}' != MTL '{mtl_date}')"
        )

    cat_prod_id = catalog_entry.get("product_id")
    mtl_prod_id = mtl_meta.get("LANDSAT_PRODUCT_ID")
    if cat_prod_id and mtl_prod_id and cat_prod_id != mtl_prod_id:
        raise ValueError(
            f"Metadata validation error: product_id mismatch (catalog '{cat_prod_id}' != MTL '{mtl_prod_id}')"
        )

    cat_level = catalog_entry.get("processing_level")
    mtl_level = mtl_meta.get("PROCESSING_LEVEL")
    if cat_level and mtl_level and cat_level != mtl_level:
        raise ValueError(
            f"Metadata validation error: processing_level mismatch (catalog '{cat_level}' != MTL '{mtl_level}')"
        )


def get_sensor_band_files(sensor: str, bands: list[int], standard_order: list[str]) -> dict[str, str]:
    """根据传感器类型建立标准波段名称与 USGS 文件命名前缀的映射关系。

    例如：
    - standard_order: ["blue", "green", "red", "nir", "swir1", "swir2"]
    - bands: [2, 3, 4, 5, 6, 7] (Landsat 8)
    返回: {"blue": "SR_B2", "green": "SR_B3", ...}

    Args:
        sensor (str): 传感器代号（如 LANDSAT_5 或 LANDSAT_8）。
        bands (list[int]): 对应的波段序号列表。
        standard_order (list[str]): 标准波段名称列表。

    Returns:
        dict[str, str]: 波段标准名至文件特征后缀字符串的映射字典。
    """
    mapping: dict[str, str] = {}
    for name, band_num in zip(standard_order, bands):
        mapping[name] = f"SR_B{band_num}"
    return mapping


# ---------------------------------------------------------------------------
# 3. QA 像元掩膜与地表反射率定标（QA Masking and Radiometric Scaling）
# ---------------------------------------------------------------------------

def mask_qa_pixel(qa: np.ndarray, sensor: str) -> np.ndarray:
    """根据 USGS Collection 2 QA_PIXEL 逐位定义判定像元是否有效。

    过滤规则（遵循数据契约第 2 节）：
    - 排除填充值 Fill（bit 0）
    - 排除扩张云 Dilated Cloud（bit 1）
    - 排除云 Cloud（bit 3）
    - 排除云阴影 Cloud Shadow（bit 4）
    - 排除积雪 Snow（bit 5）
    - 对于 Landsat 8/9（OLI）：额外排除卷云 Cirrus（bit 2）
    - 对于 Landsat 5（TM）：bit 2 未使用，不执行排除
    - 水体（bit 7）：严格保留，绝不当作无效像元排除
    - 晴空（bit 6）：仅作参考，不要求必须为 1

    Args:
        qa (np.ndarray): QA_PIXEL 整数栅格矩阵。
        sensor (str): 传感器标识（LANDSAT_5 / TM / LANDSAT_8 / OLI 等）。

    Returns:
        np.ndarray: 布尔型矩阵，True 表示像元质量合格（有效），False 表示受污染或无效。
    """
    sensor_clean = sensor.upper()
    if sensor_clean in ("LANDSAT_8", "LANDSAT_9", "OLI"):
        # Landsat 8/9: 组合需要排除的位 (0, 1, 2, 3, 4, 5)
        exclude_bits = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5)
    else:
        # Landsat 5 TM: 组合需要排除的位 (0, 1, 3, 4, 5)
        exclude_bits = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4) | (1 << 5)

    # 若任一排除位为 1，则与运算结果非 0；因此 == 0 代表所有排除位均为 0（有效）
    return (qa & exclude_bits) == 0


def mask_qa_radsat(radsat: np.ndarray, sensor: str) -> np.ndarray:
    """解析 USGS QA_RADSAT 辐射饱和与扫描丢失标志位。

    Args:
        radsat (np.ndarray): QA_RADSAT 整数栅格矩阵。
        sensor (str): 传感器标识。

    Returns:
        np.ndarray: 布尔型矩阵，True 表示未出现饱和与数据异常。
    """
    sensor_clean = sensor.upper()
    if sensor_clean in ("LANDSAT_8", "LANDSAT_9", "OLI"):
        # bit 1..6 为波段 2..7 饱和位；bit 11 为地形遮挡位
        exclude_mask = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 6) | (1 << 11)
    else:
        # Landsat 5 TM: bit 0..4, 6 对应波段 1..5, 7 饱和；bit 7 为扫描线丢弃像元 (dropped pixel)
        exclude_mask = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 6) | (1 << 7)

    return (radsat & exclude_mask) == 0


def mask_and_scale_surface_reflectance(
    dn: np.ndarray,
    qa_pixel: np.ndarray,
    sensor: str,
    scale: float = 0.0000275,
    offset: float = -0.2,
    nodata_val: float = -9999.0,
    qa_radsat: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """将原始数字量化值（DN）线性定标为地表反射率，同时确保无效像元与 Fill 像元受到保护。

    重要物理逻辑：
    - Landsat C2 L2 产品的定标公式为: SR = DN * 0.0000275 - 0.2。
    - 如果盲目将原始影像的全景矩阵代入公式，未成像的填充区（DN=0）会被算成 -0.2，
      这不仅造成科学错误，还会破坏后续指数计算。
    - 因此必须优先识别 Fill（DN==0 或 QA bit 0==1）以及 QA 判定的无效像元，
      将其赋值为指定的 nodata_val（-9999.0），仅对有效像元执行物理定标。

    Args:
        dn (np.ndarray): 原始波段 DN 整数矩阵。
        qa_pixel (np.ndarray): 对应的 QA_PIXEL 矩阵。
        sensor (str): 传感器标识。
        scale (float, optional): 反射率增益系数。默认为 0.0000275。
        offset (float, optional): 反射率偏置。默认为 -0.2。
        nodata_val (float, optional): 浮点型 NoData 占位符。默认为 -9999.0。
        qa_radsat (np.ndarray | None, optional): 可选的辐射饱和矩阵。

    Returns:
        tuple[np.ndarray, np.ndarray]:
            - sr: float32 地表反射率矩阵，无效区域赋值为 nodata_val；
            - valid_mask: uint8 掩膜矩阵（1=有效，0=无效）。
    """
    # 判定是否属于填充区
    is_fill = (dn == 0) | ((qa_pixel & 1) != 0)
    # 根据云、阴影等位判定 QA 是否有效
    qa_valid = mask_qa_pixel(qa_pixel, sensor)

    valid_mask = (~is_fill) & qa_valid
    if qa_radsat is not None:
        radsat_valid = mask_qa_radsat(qa_radsat, sensor)
        valid_mask = valid_mask & radsat_valid

    # 仅对有效像元执行定标，无效区域填入 -9999.0，严格避免 DN=0 变成 -0.2
    sr = np.where(valid_mask, dn.astype(np.float32) * scale + offset, nodata_val)
    return sr.astype(np.float32), valid_mask.astype(np.uint8)


def convert_dn_to_toa(
    dn: np.ndarray,
    mult: float,
    add: float,
    sun_elevation_deg: float,
    nodata_val: float = -9999.0,
) -> np.ndarray:
    """将 Landsat Level-1 DN 值转换为大气顶层（TOA）反射率。

    计算公式：
      TOA = (DN * mult + add) / sin(sun_elevation)

    Args:
        dn (np.ndarray): Level-1 原始 DN 数组。
        mult (float): 反射率乘乘数（REFLECTANCE_MULT_BAND_x）。
        add (float): 反射率加偏置（REFLECTANCE_ADD_BAND_x）。
        sun_elevation_deg (float): 成像时的太阳高度角（单位：度）。
        nodata_val (float, optional): 无效值填充。默认为 -9999.0。

    Returns:
        np.ndarray: float32 格式的 TOA 反射率数组。

    Raises:
        ValueError: 当太阳高度角非正时抛出。
    """
    sin_elev = math.sin(math.radians(sun_elevation_deg))
    if sin_elev <= 0:
        raise ValueError(f"Invalid sun elevation angle: {sun_elevation_deg} deg")

    is_fill = dn == 0
    toa = np.where(
        is_fill,
        nodata_val,
        (dn.astype(np.float32) * mult + add) / sin_elev,
    )
    return toa.astype(np.float32)


# ---------------------------------------------------------------------------
# 4. 步骤实现：行政边界制备（prepare_boundaries）
# ---------------------------------------------------------------------------

def prepare_boundaries(ctx: ProjectContext) -> Path:
    """读取行政边界登记编目，统一投影并生成标准 GeoPackage、网格规格与 AOI 掩膜。

    执行流程：
    1. 从 data/catalog/boundaries.csv 中匹配并加载指定基准年份（如 2021 年）的县区级与街镇级矢量；
    2. 检查并将其统一重投影至目标坐标系 EPSG:32648；
    3. 标准化属性表结构：
       - study_area 图层包含字段：area_id, name, reference_year, geometry
       - townships 图层包含字段：unit_id, name, unit_type ('street' 或 'town'), reference_year, geometry
    4. 输出统一矢量文件 data/processed/boundaries/xindu_2021.gpkg；
    5. 计算研究区外包框对齐的 30m 与 15m 网格，并保存为 grid_30m.json 和 grid_15m.json；
    6. 栅格化全区边界生成 30m 掩膜 aoi_30m.tif（研究区内为 1，外部为 0）。

    Args:
        ctx (ProjectContext): 全局项目运行上下文。

    Returns:
        Path: 生成的标准边界 GeoPackage 文件路径。

    Raises:
        FileNotFoundError: 当边界编目或原始矢量文件缺失时抛出。
    """
    boundaries_csv = ctx.data / "catalog" / "boundaries.csv"
    if not boundaries_csv.exists():
        raise FileNotFoundError(f"Boundaries catalog not found: {boundaries_csv}")

    target_crs = ctx.config.get("target_crs", "EPSG:32648")
    ref_year = ctx.config.get("boundary_reference_year", 2021)
    res_30 = float(ctx.config.get("analysis_resolution_m", 30))
    res_15 = float(ctx.config.get("display_resolution_m", 15))

    # 读取边界编目表，查找匹配基准年份的县区界与街镇界记录
    county_row = None
    townships_row = None

    with open(boundaries_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            admin_lvl = row.get("admin_level", "").strip()
            verif = row.get("verification_status", "").strip()
            year_val = int(row.get("reference_year", ref_year))
            if admin_lvl == "county" and year_val == ref_year:
                if verif in ("verified", "candidate") or county_row is None:
                    county_row = row
            elif admin_lvl == "township" and year_val == ref_year:
                if verif in ("verified", "candidate") or townships_row is None:
                    townships_row = row

    if county_row is None:
        raise FileNotFoundError(
            f"No registered county boundary for year {ref_year} found in {boundaries_csv}"
        )
    if townships_row is None:
        raise FileNotFoundError(
            f"No registered townships boundary for year {ref_year} found in {boundaries_csv}"
        )

    # 规范化文件绝对路径
    county_path = ctx.data / county_row["file_path"].replace("data/", "", 1) if county_row["file_path"].startswith("data/") else ctx.data / county_row["file_path"]
    townships_path = ctx.data / townships_row["file_path"].replace("data/", "", 1) if townships_row["file_path"].startswith("data/") else ctx.data / townships_row["file_path"]

    if not county_path.exists():
        raise FileNotFoundError(f"County boundary file does not exist: {county_path}")
    if not townships_path.exists():
        raise FileNotFoundError(f"Townships boundary file does not exist: {townships_path}")

    # 使用 GeoPandas 读取矢量图层
    gdf_county = gpd.read_file(county_path, layer=county_row.get("layer_name") or None)
    gdf_townships = gpd.read_file(townships_path, layer=townships_row.get("layer_name") or None)

    # 统一转换坐标系至 EPSG:32648
    if gdf_county.crs is None:
        gdf_county.set_crs(county_row.get("source_crs", target_crs), inplace=True)
    if gdf_county.crs.to_string() != target_crs:
        gdf_county = gdf_county.to_crs(target_crs)

    if gdf_townships.crs is None:
        gdf_townships.set_crs(townships_row.get("source_crs", target_crs), inplace=True)
    if gdf_townships.crs.to_string() != target_crs:
        gdf_townships = gdf_townships.to_crs(target_crs)

    # 标准化全区边界属性表（study_area 图层）
    area_id_col = next((c for c in ["area_id", "district_code", "PAC", "code"] if c in gdf_county.columns), None)
    name_col = next((c for c in ["name", "district_name", "NAME", "NAME_CH"] if c in gdf_county.columns), None)

    std_county = gpd.GeoDataFrame({
        "area_id": gdf_county[area_id_col].astype(str) if area_id_col else "510114",
        "name": gdf_county[name_col].astype(str) if name_col else "新都区",
        "reference_year": int(ref_year),
        "geometry": gdf_county.geometry,
    }, crs=target_crs)

    # 标准化街镇边界属性表（townships 图层）
    t_id_col = next((c for c in ["unit_id", "code", "PAC", "township_code"] if c in gdf_townships.columns), None)
    t_name_col = next((c for c in ["name", "township_name", "NAME", "NAME_CH"] if c in gdf_townships.columns), None)
    t_type_col = next((c for c in ["unit_type", "type", "type_code", "T_TYPE"] if c in gdf_townships.columns), None)

    def determine_unit_type(val: Any, name_val: str) -> str:
        """判定街镇单元类型是街道（street）还是镇（town）。"""
        s = str(val).lower() if val is not None else ""
        if "street" in s or "街道" in str(name_val):
            return "street"
        return "town"

    unit_ids = []
    unit_names = []
    unit_types = []
    for idx, row in gdf_townships.iterrows():
        uid = str(row[t_id_col]) if t_id_col else f"{idx+1:02d}"
        uname = str(row[t_name_col]) if t_name_col else f"Unit_{idx+1}"
        utype = determine_unit_type(row[t_type_col] if t_type_col else None, uname)
        unit_ids.append(uid)
        unit_names.append(uname)
        unit_types.append(utype)

    std_townships = gpd.GeoDataFrame({
        "unit_id": unit_ids,
        "name": unit_names,
        "unit_type": unit_types,
        "reference_year": int(ref_year),
        "geometry": gdf_townships.geometry,
    }, crs=target_crs)

    # 导出至标准 GeoPackage
    out_bnd_dir = ctx.data / "processed" / "boundaries"
    out_bnd_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = out_bnd_dir / f"xindu_{ref_year}.gpkg"

    if gpkg_path.exists():
        gpkg_path.unlink()

    std_county.to_file(gpkg_path, layer="study_area", driver="GPKG")
    std_townships.to_file(gpkg_path, layer="townships", driver="GPKG")

    # 计算 30m 与 15m 标准外扩对齐网格参数
    bounds = tuple(std_county.total_bounds)
    grid_30 = compute_grid_specs(bounds, resolution=res_30, crs=target_crs)
    grid_15 = compute_grid_specs(bounds, resolution=res_15, crs=target_crs, bounds_snap_resolution=res_30)

    out_grid_dir = ctx.data / "processed" / "grids"
    out_grid_dir.mkdir(parents=True, exist_ok=True)
    (out_grid_dir / "grid_30m.json").write_text(json.dumps(grid_30, indent=2), encoding="utf-8")
    (out_grid_dir / "grid_15m.json").write_text(json.dumps(grid_15, indent=2), encoding="utf-8")

    # 栅格化研究区边界生成 aoi_30m.tif（all_touched=True，内部为 1，外部为 0）
    width = grid_30["width"]
    height = grid_30["height"]
    transform_affine = Affine.from_gdal(*grid_30["transform"])

    shapes = [(geom, 1) for geom in std_county.geometry]
    aoi_arr = rasterize(
        shapes=shapes,
        out_shape=(height, width),
        transform=transform_affine,
        fill=0,
        default_value=1,
        all_touched=True,
        dtype=np.uint8,
    )

    aoi_path = out_grid_dir / "aoi_30m.tif"
    with rasterio.open(
        aoi_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=target_crs,
        transform=transform_affine,
        nodata=None,
    ) as dst:
        dst.write(aoi_arr, 1)

    return gpkg_path


# ---------------------------------------------------------------------------
# 5. 步骤实现：地表反射率预处理（preprocess_year）
# ---------------------------------------------------------------------------

def preprocess_year(ctx: ProjectContext, year: int) -> PreparedData:
    """针对指定年份处理 Landsat Level-2 影像，生成标准地表反射率栅格与有效掩膜。

    产出文件：
    - data/processed/{year}/sr_30m.tif (Float32, 6波段: Blue, Green, Red, NIR, SWIR1, SWIR2; NoData=-9999.0)
    - data/processed/{year}/valid_sr_30m.tif (Byte, 1=有效, 0=区内无效, 255=区外)
    - 同步发布成果到 outputs/rasters/xindu_{year}_sr_30m.tif
    - 记录元数据报告 reports/data/preprocess_{year}.json

    Args:
        ctx (ProjectContext): 项目运行上下文。
        year (int): 目标年份（如 1992 或 2021）。

    Returns:
        PreparedData: 包含处理后文件路径的数据契约对象。

    Raises:
        FileNotFoundError: 当相关编目、影像或前置边界文件缺失时抛出。
        ValueError: 当传感器配置不受支持或元数据校验失败时抛出。
    """
    scenes_csv = ctx.data / "catalog" / "scenes.csv"
    if not scenes_csv.exists():
        raise FileNotFoundError(f"Scenes catalog not found: {scenes_csv}")

    # 从 scenes.csv 中检索目标年份且状态为 selected 的 L2 产品
    selected_scene = None
    with open(scenes_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row.get("year", 0)) == year:
                lvl = row.get("processing_level", "").upper()
                if lvl in ("L2SP", "L2SR"):
                    status = row.get("selection_status", "").lower()
                    if status == "selected" or selected_scene is None:
                        selected_scene = row

    if selected_scene is None:
        raise FileNotFoundError(f"No selected Level-2 scene found for year {year} in {scenes_csv}")

    scene_dir_rel = selected_scene["scene_dir"]
    mtl_path_rel = selected_scene["mtl_path"]

    scene_dir = ctx.data / (scene_dir_rel.replace("data/", "", 1) if scene_dir_rel.startswith("data/") else scene_dir_rel)
    mtl_path = ctx.data / (mtl_path_rel.replace("data/", "", 1) if mtl_path_rel.startswith("data/") else mtl_path_rel)

    if not scene_dir.exists():
        raise FileNotFoundError(f"Scene directory does not exist: {scene_dir}")
    if not mtl_path.exists():
        raise FileNotFoundError(f"MTL file does not exist: {mtl_path}")

    # 解析并严格核对 MTL 元数据与编目表
    mtl_meta = parse_mtl_metadata(mtl_path)
    validate_scene_metadata(selected_scene, mtl_meta)

    # 读取前置生成的标准 30m 网格规格与 AOI 掩膜
    grid_path = ctx.data / "processed" / "grids" / "grid_30m.json"
    aoi_path = ctx.data / "processed" / "grids" / "aoi_30m.tif"
    if not grid_path.exists() or not aoi_path.exists():
        raise FileNotFoundError("Grids and AOI mask must be prepared first via prepare_boundaries().")

    with open(grid_path, "r", encoding="utf-8") as f:
        grid_30 = json.load(f)

    target_crs = grid_30["crs"]
    target_width = grid_30["width"]
    target_height = grid_30["height"]
    target_transform = Affine.from_gdal(*grid_30["transform"])

    with rasterio.open(aoi_path) as aoi_src:
        aoi_mask = aoi_src.read(1)

    # 读取预处理配置参数
    img_cfg = ctx.config.get("imagery", {})
    scale_factor = float(img_cfg.get("surface_reflectance_scale", 0.0000275))
    offset = float(img_cfg.get("surface_reflectance_offset", -0.2))
    band_order = img_cfg.get("band_order", ["blue", "green", "red", "nir", "swir1", "swir2"])
    nodata_float = float(ctx.config.get("float_nodata", -9999.0))
    mask_nodata = int(ctx.config.get("mask_nodata", 255))

    sensor = selected_scene["sensor"].upper()
    if sensor in ("LANDSAT_5", "TM"):
        bands_cfg = img_cfg.get("landsat5_bands", [1, 2, 3, 4, 5, 7])
    elif sensor in ("LANDSAT_8", "LANDSAT_9", "OLI"):
        bands_cfg = img_cfg.get("landsat8_bands", [2, 3, 4, 5, 6, 7])
    else:
        raise ValueError(f"Unsupported sensor in configuration: {sensor}")

    band_file_map = get_sensor_band_files(sensor, bands_cfg, band_order)

    # 寻找 QA 质量波段文件
    qa_pixel_file = next(scene_dir.glob("*_QA_PIXEL.TIF"), None) or next(scene_dir.glob("*_QA_PIXEL.tif"), None)
    if qa_pixel_file is None:
        raise FileNotFoundError(f"QA_PIXEL band not found in {scene_dir}")

    qa_radsat_file = next(scene_dir.glob("*_QA_RADSAT.TIF"), None) or next(scene_dir.glob("*_QA_RADSAT.tif"), None)

    # 读取原始 QA_PIXEL 栅格
    with rasterio.open(qa_pixel_file) as qa_src:
        qa_pixel_native = qa_src.read(1)
        qa_crs = qa_src.crs
        qa_transform = qa_src.transform

    qa_radsat_native = None
    if qa_radsat_file is not None and qa_radsat_file.exists():
        with rasterio.open(qa_radsat_file) as radsat_src:
            qa_radsat_native = radsat_src.read(1)

    # 计算原始空间分辨率下的有效像元掩膜
    is_fill_qa = (qa_pixel_native & 1) != 0
    valid_qa = mask_qa_pixel(qa_pixel_native, sensor)
    native_valid_mask = (~is_fill_qa) & valid_qa
    if qa_radsat_native is not None:
        native_valid_mask = native_valid_mask & mask_qa_radsat(qa_radsat_native, sensor)

    # 使用最近邻插值（Nearest Neighbor）将掩膜重投影至标准 30m 网格，避免类别混淆
    reprojected_valid_mask = np.zeros((target_height, target_width), dtype=np.uint8)
    reproject(
        source=native_valid_mask.astype(np.uint8),
        destination=reprojected_valid_mask,
        src_transform=qa_transform,
        src_crs=qa_crs,
        dst_transform=target_transform,
        dst_crs=target_crs,
        resampling=Resampling.nearest,
    )

    # 逐波段读取、定标并使用双线性插值（Bilinear）重投影连续的地表反射率数据
    sr_reprojected_bands: list[np.ndarray] = []

    for band_name in band_order:
        band_suffix = band_file_map[band_name]
        band_file = next(scene_dir.glob(f"*{band_suffix}.TIF"), None) or next(scene_dir.glob(f"*{band_suffix}.tif"), None)
        if band_file is None:
            raise FileNotFoundError(f"Band file for {band_name} ({band_suffix}) not found in {scene_dir}")

        with rasterio.open(band_file) as b_src:
            dn_native = b_src.read(1)
            b_crs = b_src.crs
            b_transform = b_src.transform

        # 在原始投影空间执行地表反射率定标并实施 Fill 保护
        scaled_sr_native, band_valid = mask_and_scale_surface_reflectance(
            dn=dn_native,
            qa_pixel=qa_pixel_native,
            sensor=sensor,
            scale=scale_factor,
            offset=offset,
            nodata_val=nodata_float,
            qa_radsat=qa_radsat_native,
        )

        # 双线性插值重采样至标准 30m 网格
        reprojected_sr = np.full((target_height, target_width), nodata_float, dtype=np.float32)
        reproject(
            source=scaled_sr_native,
            destination=reprojected_sr,
            src_transform=b_transform,
            src_crs=b_crs,
            src_nodata=nodata_float,
            dst_transform=target_transform,
            dst_crs=target_crs,
            dst_nodata=nodata_float,
            resampling=Resampling.bilinear,
        )
        sr_reprojected_bands.append(reprojected_sr)

    # 堆叠合成 6 波段反射率数组：形状为 (6, height, width)
    sr_stack = np.stack(sr_reprojected_bands, axis=0)

    # 根据契约第二节构建最终的有效像元掩膜 valid_sr_30m：
    # 1 = 研究区内部且所有 6 个反射率波段均有效且 QA 通过；
    # 0 = 研究区内部但受云、阴影污染或无数据；
    # 255 = 研究区外部。
    bands_valid = np.all((sr_stack != nodata_float) & (~np.isnan(sr_stack)), axis=0)
    all_valid_condition = (reprojected_valid_mask == 1) & bands_valid

    valid_sr_arr = np.full((target_height, target_width), mask_nodata, dtype=np.uint8)
    valid_sr_arr[aoi_mask == 1] = np.where(all_valid_condition[aoi_mask == 1], 1, 0)

    # 将 valid_sr_arr != 1 的区域在反射率堆栈中全部置为 nodata_float (-9999.0)
    sr_stack[:, valid_sr_arr != 1] = nodata_float

    # 保存 6 波段地表反射率文件 data/processed/{year}/sr_30m.tif
    out_year_dir = ctx.data / "processed" / str(year)
    out_year_dir.mkdir(parents=True, exist_ok=True)
    sr_path = out_year_dir / "sr_30m.tif"
    valid_sr_path = out_year_dir / "valid_sr_30m.tif"

    with rasterio.open(
        sr_path,
        "w",
        driver="GTiff",
        height=target_height,
        width=target_width,
        count=len(band_order),
        dtype="float32",
        crs=target_crs,
        transform=target_transform,
        nodata=nodata_float,
    ) as dst:
        dst.write(sr_stack)
        for idx, bname in enumerate(band_order, start=1):
            dst.set_band_description(idx, bname)

    # 保存有效像元掩膜 data/processed/{year}/valid_sr_30m.tif
    with rasterio.open(
        valid_sr_path,
        "w",
        driver="GTiff",
        height=target_height,
        width=target_width,
        count=1,
        dtype="uint8",
        crs=target_crs,
        transform=target_transform,
        nodata=mask_nodata,
    ) as dst:
        dst.write(valid_sr_arr, 1)

    # 同步发布一份只读副本至 outputs/rasters/xindu_{year}_sr_30m.tif
    out_raster_dir = ctx.outputs / "rasters"
    out_raster_dir.mkdir(parents=True, exist_ok=True)
    pub_sr_path = out_raster_dir / f"xindu_{year}_sr_30m.tif"
    shutil.copy2(sr_path, pub_sr_path)

    # 统计数据质量并输出 JSON 审计报告
    rep_dir = ctx.reports / "data"
    rep_dir.mkdir(parents=True, exist_ok=True)
    aoi_total_pixels = int(np.sum(aoi_mask == 1))
    valid_pixel_count = int(np.sum(valid_sr_arr == 1))
    valid_ratio = round(valid_pixel_count / aoi_total_pixels, 6) if aoi_total_pixels > 0 else 0.0

    report_data = {
        "year": year,
        "product_id": selected_scene["product_id"],
        "sensor": sensor,
        "acquisition_date": selected_scene["acquisition_date"],
        "crs": target_crs,
        "bounds": grid_30["bounds"],
        "width": target_width,
        "height": target_height,
        "bands": band_order,
        "total_aoi_pixels": aoi_total_pixels,
        "valid_pixels": valid_pixel_count,
        "valid_ratio": valid_ratio,
        "nodata_float": nodata_float,
        "mask_nodata": mask_nodata,
    }
    (rep_dir / f"preprocess_{year}.json").write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    boundaries_gpkg = ctx.data / "processed" / "boundaries" / f"xindu_{ctx.config.get('boundary_reference_year', 2021)}.gpkg"

    return PreparedData(
        year=year,
        sr=sr_path,
        valid_sr=valid_sr_path,
        grid=grid_path,
        boundaries=boundaries_gpkg,
    )


# ---------------------------------------------------------------------------
# 6. 步骤实现：2021 年全色锐化（pansharpen_2021）
# ---------------------------------------------------------------------------

def pansharpen_2021(ctx: ProjectContext) -> Path:
    """对 2021 年 Landsat 8 Level-1 数据执行 Gram-Schmidt 全色锐化，生成 15m 真彩色高分影像。

    注意：本产物仅用于制图背景展示与目视解译参考（radiometry=TOA, purpose=visualization），
    绝不参与土地分类模型的训练与特征输入！

    融合算法：Gram-Schmidt 自适应（GSA, Gram-Schmidt Adaptive）
      设 RGB 三波段（B4/B3/B2）的 TOA 反射率为 MS_i，B8 全色 TOA 反射率为 Pan：
      1. 用 2×2 块平均把 Pan 降到 30m 得到 Pan_low，同样块平均 MS_i 得到 MS_i_low；
      2. 最小二乘回归 Pan_low ≈ w0 + Σ w_i·MS_i_low，得到「模拟低分全色」
         Pan_sim = w0 + Σ w_i·MS_i；
      3. 细节残差 Δ = Pan - Pan_sim 携带 15m 高频信息；
      4. 逐波段增益 g_i = cov(MS_i, Pan_sim) / var(Pan_sim)，保持各波段与全色的光谱比例；
      5. MS_i_sharp = MS_i + g_i·Δ。
      当 var(Pan_sim) 极小时（例如整幅常数影像）g_i 取 0，输出退化为原多光谱，
      不注入任何虚构纹理。

      波段范围约束：B8 全色波段为 0.50—0.68 μm，只覆盖 B2/B3/B4。因此本步骤仅融合
      RGB 三波段；B5（NIR）与 B6/B7（SWIR）不做 15m 光谱外推，分类仍使用 30m 全波段。

    Args:
        ctx (ProjectContext): 项目运行上下文。

    Returns:
        Path: 输出的 15m 锐化融合 GeoTIFF 路径（data/processed/2021/pan_rgb_15m.tif）。

    Raises:
        FileNotFoundError: 当相关文件不存在时抛出。
    """
    scenes_csv = ctx.data / "catalog" / "scenes.csv"
    if not scenes_csv.exists():
        raise FileNotFoundError(f"Scenes catalog not found: {scenes_csv}")

    # 读取 2021 年选定的 L1TP 级影像
    selected_l1 = None
    with open(scenes_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row.get("year", 0)) == 2021:
                lvl = row.get("processing_level", "").upper()
                if lvl == "L1TP":
                    status = row.get("selection_status", "").lower()
                    if status == "selected" or selected_l1 is None:
                        selected_l1 = row

    if selected_l1 is None:
        raise FileNotFoundError(f"No selected Level-1 scene found for 2021 in {scenes_csv}")

    scene_dir_rel = selected_l1["scene_dir"]
    mtl_path_rel = selected_l1["mtl_path"]
    scene_dir = ctx.data / (scene_dir_rel.replace("data/", "", 1) if scene_dir_rel.startswith("data/") else scene_dir_rel)
    mtl_path = ctx.data / (mtl_path_rel.replace("data/", "", 1) if mtl_path_rel.startswith("data/") else mtl_path_rel)

    if not scene_dir.exists():
        raise FileNotFoundError(f"L1 scene directory does not exist: {scene_dir}")
    if not mtl_path.exists():
        raise FileNotFoundError(f"L1 MTL file does not exist: {mtl_path}")

    mtl_meta = parse_mtl_metadata(mtl_path)
    validate_scene_metadata(selected_l1, mtl_meta)

    sun_elev = float(mtl_meta.get("SUN_ELEVATION", 45.0))

    # 读取 15m 网格规格
    grid_15_path = ctx.data / "processed" / "grids" / "grid_15m.json"
    if not grid_15_path.exists():
        raise FileNotFoundError("grid_15m.json must be prepared first via prepare_boundaries().")

    with open(grid_15_path, "r", encoding="utf-8") as f:
        grid_15 = json.load(f)

    target_crs = grid_15["crs"]
    w15 = grid_15["width"]
    h15 = grid_15["height"]
    transform_15 = Affine.from_gdal(*grid_15["transform"])

    img_cfg = ctx.config.get("imagery", {})
    rgb_band_nums = img_cfg.get("pan_rgb_bands", [4, 3, 2])  # 对应红、绿、蓝波段序号
    pan_band_num = int(img_cfg.get("pan_band", 8))          # 全色波段序号 (Band 8)
    nodata_float = float(ctx.config.get("float_nodata", -9999.0))

    # 逐波段读取 RGB 波段并重投影至 15m 网格
    reprojected_rgb_15m: list[np.ndarray] = []
    for bnum in rgb_band_nums:
        bfile = next(scene_dir.glob(f"*_B{bnum}.TIF"), None) or next(scene_dir.glob(f"*_B{bnum}.tif"), None)
        if bfile is None:
            raise FileNotFoundError(f"L1 Band {bnum} not found in {scene_dir}")

        mult = float(mtl_meta.get(f"REFLECTANCE_MULT_BAND_{bnum}", 2.0e-5))
        add = float(mtl_meta.get(f"REFLECTANCE_ADD_BAND_{bnum}", -0.1))

        with rasterio.open(bfile) as b_src:
            dn_native = b_src.read(1)
            b_crs = b_src.crs
            b_trans = b_src.transform

        # 转换为大气顶层反射率（TOA）
        toa_native = convert_dn_to_toa(dn_native, mult, add, sun_elev, nodata_val=nodata_float)

        # 双线性插值重采样至 15m 网格
        toa_15m = np.full((h15, w15), nodata_float, dtype=np.float32)
        reproject(
            source=toa_native,
            destination=toa_15m,
            src_transform=b_trans,
            src_crs=b_crs,
            src_nodata=nodata_float,
            dst_transform=transform_15,
            dst_crs=target_crs,
            dst_nodata=nodata_float,
            resampling=Resampling.bilinear,
        )
        reprojected_rgb_15m.append(toa_15m)

    # 读取并转换 15m 全色波段 (Band 8)
    pan_file = next(scene_dir.glob(f"*_B{pan_band_num}.TIF"), None) or next(scene_dir.glob(f"*_B{pan_band_num}.tif"), None)
    if pan_file is None:
        raise FileNotFoundError(f"L1 Pan Band {pan_band_num} not found in {scene_dir}")

    pan_mult = float(mtl_meta.get(f"REFLECTANCE_MULT_BAND_{pan_band_num}", 2.0e-5))
    pan_add = float(mtl_meta.get(f"REFLECTANCE_ADD_BAND_{pan_band_num}", -0.1))

    with rasterio.open(pan_file) as p_src:
        pan_dn_native = p_src.read(1)
        p_crs = p_src.crs
        p_trans = p_src.transform

    pan_toa_native = convert_dn_to_toa(pan_dn_native, pan_mult, pan_add, sun_elev, nodata_val=nodata_float)
    pan_15m = np.full((h15, w15), nodata_float, dtype=np.float32)
    reproject(
        source=pan_toa_native,
        destination=pan_15m,
        src_transform=p_trans,
        src_crs=p_crs,
        src_nodata=nodata_float,
        dst_transform=transform_15,
        dst_crs=target_crs,
        dst_nodata=nodata_float,
        resampling=Resampling.bilinear,
    )

    # 执行 Gram-Schmidt 自适应（GSA）全色锐化融合
    r_15, g_15, b_15 = reprojected_rgb_15m[0], reprojected_rgb_15m[1], reprojected_rgb_15m[2]
    ms_15 = np.stack([r_15, g_15, b_15], axis=0)

    # 确定有效像元掩膜（各波段均有数据且为有限值）
    valid_mask = (
        (r_15 != nodata_float) & (g_15 != nodata_float) & (b_15 != nodata_float) & (pan_15m != nodata_float)
        & np.isfinite(r_15) & np.isfinite(g_15) & np.isfinite(b_15) & np.isfinite(pan_15m)
    )

    def block_mean_2x(arr: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """将 15m 栅格按 2×2 块平均降到 30m，只统计掩膜内像元。

        Returns:
            tuple[np.ndarray, np.ndarray]: 降采样结果，以及该像元是否至少有 1 个有效子像元。
        """
        h2, w2 = arr.shape[0] // 2, arr.shape[1] // 2
        blocks = arr[: h2 * 2, : w2 * 2].reshape(h2, 2, w2, 2)
        mblocks = mask[: h2 * 2, : w2 * 2].reshape(h2, 2, w2, 2).astype(np.float32)
        num = np.where(mblocks > 0, blocks, 0.0).sum(axis=(1, 3))
        den = mblocks.sum(axis=(1, 3))
        out = np.zeros((h2, w2), dtype=np.float64)
        ok = den > 0
        out[ok] = num[ok] / den[ok]
        return out, ok

    # 1. 模拟低分全色：把 Pan 与各 MS 波段块平均到 30m
    pan_low, pan_low_ok = block_mean_2x(pan_15m.astype(np.float64), valid_mask)
    ms_low = np.stack(
        [block_mean_2x(ms_15[i].astype(np.float64), valid_mask)[0] for i in range(3)], axis=0
    )

    # 2. 最小二乘回归 Pan_low ≈ w0 + Σ w_i·MS_i_low
    reg_ok = pan_low_ok.copy()
    for i in range(3):
        reg_ok &= np.isfinite(ms_low[i])

    if int(reg_ok.sum()) < 4:
        raise ValueError(
            f"Insufficient valid pixels for Gram-Schmidt regression: {int(reg_ok.sum())} < 4"
        )

    design = np.stack(
        [np.ones(int(reg_ok.sum()), dtype=np.float64)] + [ms_low[i][reg_ok] for i in range(3)],
        axis=1,
    )
    coef, _residuals, _rank, _sv = np.linalg.lstsq(design, pan_low[reg_ok], rcond=None)
    gs_intercept = float(coef[0])
    gs_weights = [float(v) for v in coef[1:]]

    # 3. 在 15m 网格上重建模拟全色，残差即待注入的高频细节
    pan_sim = gs_intercept + sum(gs_weights[i] * ms_15[i] for i in range(3))
    delta = pan_15m - pan_sim

    # 4. 逐波段增益 g_i = cov(MS_i, Pan_sim) / var(Pan_sim)
    fit_mask = valid_mask & np.isfinite(pan_sim) & np.isfinite(delta)
    if not fit_mask.any():
        raise ValueError("No valid pixel available for Gram-Schmidt gain estimation")

    pan_sel = pan_sim[fit_mask].astype(np.float64)
    mean_pan = float(pan_sel.mean())
    var_pan = float(pan_sel.var())
    gs_gains: list[float] = []
    for i in range(3):
        band = ms_15[i][fit_mask].astype(np.float64)
        cov = float(np.mean((band - band.mean()) * (pan_sel - mean_pan)))
        gs_gains.append(cov / var_pan if var_pan > 1e-12 else 0.0)

    # 5. 注入高频细节；var(Pan_sim) 过小时增益为 0，输出退化为原多光谱
    stack_15m = np.stack(
        [np.where(fit_mask, ms_15[i] + gs_gains[i] * delta, nodata_float) for i in range(3)],
        axis=0,
    ).astype(np.float32)

    # 保存 15m 融合栅格
    out_dir = ctx.data / "processed" / "2021"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pan_path = out_dir / "pan_rgb_15m.tif"

    with rasterio.open(
        out_pan_path,
        "w",
        driver="GTiff",
        height=h15,
        width=w15,
        count=3,
        dtype="float32",
        crs=target_crs,
        transform=transform_15,
        nodata=nodata_float,
    ) as dst:
        dst.write(stack_15m)
        dst.set_band_description(1, "red")
        dst.set_band_description(2, "green")
        dst.set_band_description(3, "blue")

    # 同步发布至 outputs 目录
    out_raster_dir = ctx.outputs / "rasters"
    out_raster_dir.mkdir(parents=True, exist_ok=True)
    pub_pan_path = out_raster_dir / "xindu_2021_pan_rgb_15m.tif"
    shutil.copy2(out_pan_path, pub_pan_path)

    # 记录元数据报告
    rep_dir = ctx.reports / "data"
    rep_dir.mkdir(parents=True, exist_ok=True)
    report_data = {
        "radiometry": "TOA",
        "purpose": "visualization",
        "fusion_algorithm": "Gram-Schmidt (GSA)",
        "product_id": selected_l1["product_id"],
        "sun_elevation_deg": sun_elev,
        "resolution": 15,
        "width": w15,
        "height": h15,
        "rgb_bands": rgb_band_nums,
        "pan_band": pan_band_num,
        "nodata_val": nodata_float,
        "gs_intercept": gs_intercept,
        "gs_weights": gs_weights,
        "gs_gains": gs_gains,
        "valid_pixels": int(fit_mask.sum()),
        "band_scope_note": "B8(0.50-0.68um) 仅覆盖 B2/B3/B4；NIR 与 SWIR 未做 15m 外推",
    }
    (rep_dir / "pansharpen_2021.json").write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    return out_pan_path


# ---------------------------------------------------------------------------
# 7. 步骤实现：21 维特征堆栈（build_feature_stack）
# ---------------------------------------------------------------------------

# 默认特征顺序：6 个反射率波段 + 7 项光谱指数 + 6 项局部纹理 + 高程 + 坡度 + TWI = 22 维
DEFAULT_FEATURE_STACK_ORDER: list[str] = [
    "blue", "green", "red", "nir", "swir1", "swir2",
    "ndvi", "savi", "mndwi", "ndbi", "ui", "bsi", "ibi",
    "nir_mean", "nir_std", "red_mean", "red_std", "swir1_mean", "swir1_std",
    "elevation", "slope", "twi",
]

# 供报告与复核使用的公式清单（写入 sidecar JSON，避免文档与实现脱节）
FEATURE_FORMULAS: dict[str, str] = {
    "ndvi": "(nir - red) / (nir + red)",
    "savi": "1.5 * (nir - red) / (nir + red + 0.5)",
    "mndwi": "(green - swir1) / (green + swir1)",
    "ndbi": "(swir1 - nir) / (swir1 + nir)",
    "ui": "(swir2 - nir) / (swir2 + nir)",
    "bsi": "((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue))",
    "ibi": "(Tb - Tv) / (Tb + Tv), Tb = 2*swir1/(swir1+nir), Tv = nir/(nir+red) + green/(green+swir1)",
    "texture": "窗口内有效像元均值与标准差（uniform_filter，默认 5×5）",
    "elevation": "DEM 双线性重投影至 30m 网格（米）",
    "slope": "arctan(hypot(dz/dx, dz/dy))，单位：度",
    "twi": "ln(a / tanβ)，a = 汇流累积量×30m，tanβ 取下限 1e-3",
}


# ---------------------------------------------------------------------------
# 7.1 TWI（地形湿度指数）所需的 DEM 水文辅助函数
# ---------------------------------------------------------------------------

_D8_NEIGHBORS: list[tuple[int, int, float]] = [
    (-1, -1, math.sqrt(2.0)), (-1, 0, 1.0), (-1, 1, math.sqrt(2.0)),
    (0, -1, 1.0), (0, 1, 1.0),
    (1, -1, math.sqrt(2.0)), (1, 0, 1.0), (1, 1, math.sqrt(2.0)),
]


def _smooth_dem(dem: np.ndarray, valid: np.ndarray, window: int, nodata: float) -> np.ndarray:
    """对 DEM 做有效像元均值平滑，抑制 ASTER GDEM 在 30m 尺度的噪声。"""
    if window <= 1:
        return dem
    weight = valid.astype(np.float32)
    filled = np.where(valid, dem, 0.0).astype(np.float32)
    wsum = uniform_filter(weight, size=window, mode="nearest")
    dsum = uniform_filter(filled, size=window, mode="nearest")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(valid & (wsum > 0), dsum / np.maximum(wsum, 1e-6), nodata).astype(np.float32)
    return out


def _fill_depressions(dem: np.ndarray, valid: np.ndarray, eps: float = 1e-4) -> np.ndarray:
    """Priority-Flood 填洼（Barnes et al., 2014），保证每个内陆像元都有严格下坡邻域。

    Args:
        dem (np.ndarray): 高程矩阵 (H, W)，无效像元可为任意值。
        valid (np.ndarray): 有效像元掩膜 (H, W)。
        eps (float): 抬升步长（米），用于打破平坦面。

    Returns:
        np.ndarray: 填洼后的 float64 高程矩阵。
    """
    import heapq

    hgt, wid = dem.shape
    filled = np.where(valid, dem, np.nan).astype(np.float64)
    closed = ~valid
    heap: list[tuple[float, int, int]] = []

    def push(i: int, j: int) -> None:
        closed[i, j] = True
        heapq.heappush(heap, (float(filled[i, j]), i, j))

    for i in range(hgt):
        for j in (0, wid - 1):
            if not closed[i, j]:
                push(i, j)
    for j in range(wid):
        for i in (0, hgt - 1):
            if not closed[i, j]:
                push(i, j)

    while heap:
        z, i, j = heapq.heappop(heap)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ni, nj = i + di, j + dj
                if 0 <= ni < hgt and 0 <= nj < wid and not closed[ni, nj]:
                    closed[ni, nj] = True
                    zn = filled[ni, nj]
                    if zn <= z:
                        zn = z + eps
                        filled[ni, nj] = zn
                    heapq.heappush(heap, (float(zn), ni, nj))

    return filled


def _d8_downstream(filled: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """按最陡下降法确定每个像元的下游像元（平坦索引，-1 表示无下游）。"""
    hgt, wid = filled.shape
    best = np.full((hgt, wid), -1, dtype=np.int64)
    best_slope = np.zeros((hgt, wid), dtype=np.float64)
    rows, cols = np.indices((hgt, wid))

    for di, dj, dist in _D8_NEIGHBORS:
        nr, nc = rows + di, cols + dj
        inside = (nr >= 0) & (nr < hgt) & (nc >= 0) & (nc < wid)
        nb = np.full((hgt, wid), np.nan, dtype=np.float64)
        nb[inside] = filled[nr[inside], nc[inside]]
        slope = (filled - nb) / dist
        better = valid & inside & np.isfinite(nb) & (slope > best_slope)
        best_slope = np.where(better, slope, best_slope)
        best = np.where(better, nr * wid + nc, best)

    return best


def _flow_accumulation(downstream: np.ndarray, filled: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """按高程从高到低累加上游像元数（D8 单流向）。"""
    hgt, wid = filled.shape
    flat_valid = np.flatnonzero(valid.ravel())
    order = flat_valid[np.argsort(-filled.ravel()[flat_valid], kind="stable")]

    acc = np.where(valid.ravel(), 1.0, 0.0).tolist()
    ds = downstream.ravel().tolist()
    for cell in order.tolist():
        target = ds[cell]
        if target >= 0:
            acc[target] += acc[cell]

    return np.asarray(acc, dtype=np.float64).reshape(hgt, wid)


def _compute_twi(
    dem: np.ndarray,
    valid: np.ndarray,
    cell_size: float,
    nodata: float,
) -> np.ndarray:
    """计算地形湿度指数 TWI = ln(a / tanβ)。

    Args:
        dem (np.ndarray): 已平滑的高程矩阵（米）。
        valid (np.ndarray): 有效像元掩膜。
        cell_size (float): 像元边长（米）。
        nodata (float): 无效填充值。

    Returns:
        np.ndarray: TWI 矩阵，无效像元为 nodata。
    """
    if not valid.any():
        raise ValueError("No valid DEM pixel available for TWI computation")

    filled = _fill_depressions(dem, valid)
    downstream = _d8_downstream(filled, valid)
    accumulation = _flow_accumulation(downstream, filled, valid)

    safe_dem = np.where(valid, dem, np.nan)
    grad_y, grad_x = np.gradient(safe_dem, cell_size, cell_size)
    slope_rad = np.arctan(np.hypot(grad_x, grad_y))
    tan_beta = np.maximum(np.tan(np.where(np.isfinite(slope_rad), slope_rad, 0.0)), 1e-3)

    specific_area = accumulation * cell_size  # 单位面积 m²/m
    with np.errstate(divide="ignore", invalid="ignore"):
        twi = np.log(specific_area / tan_beta)

    return np.where(valid & np.isfinite(twi), twi, nodata).astype(np.float32)


def _compute_terrain_arrays(
    dem_path: Path,
    dst_transform,
    dst_crs,
    height: int,
    width: int,
    float_nodata: float,
    dem_smooth_window: int,
    twi_buffer_cells: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """计算高程、坡度与 TWI 三项地形特征。

    TWI 在向外扩 ``twi_buffer_cells`` 的窗口上做填洼 + D8 汇流后再裁回主网格，
    以减少研究区边界处的汇水缺失。

    Returns:
        tuple: (dem, slope, twi, dem_valid)
    """
    res_x = abs(dst_transform.a)
    res_y = abs(dst_transform.e)

    dem = np.full((height, width), float_nodata, dtype=np.float32)
    with rasterio.open(dem_path) as ds:
        reproject(
            source=ds.read(1).astype(np.float32),
            destination=dem,
            src_transform=ds.transform,
            src_crs=ds.crs,
            src_nodata=ds.nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=float_nodata,
            resampling=Resampling.bilinear,
        )
    dem_valid = np.isfinite(dem) & (dem != float_nodata)

    dem = _smooth_dem(dem, dem_valid, dem_smooth_window, float_nodata)

    grad_y, grad_x = np.gradient(np.where(dem_valid, dem, np.nan), res_y, res_x)
    slope = np.degrees(np.arctan(np.hypot(grad_x, grad_y))).astype(np.float32)
    slope = np.where(dem_valid, slope, float_nodata).astype(np.float32)

    pad_transform = dst_transform @ Affine.translation(-twi_buffer_cells, -twi_buffer_cells)
    pad_h = height + 2 * twi_buffer_cells
    pad_w = width + 2 * twi_buffer_cells
    dem_pad = np.full((pad_h, pad_w), float_nodata, dtype=np.float32)
    with rasterio.open(dem_path) as ds:
        reproject(
            source=ds.read(1).astype(np.float32),
            destination=dem_pad,
            src_transform=ds.transform,
            src_crs=ds.crs,
            src_nodata=ds.nodata,
            dst_transform=pad_transform,
            dst_crs=dst_crs,
            dst_nodata=float_nodata,
            resampling=Resampling.bilinear,
        )
    dem_pad_valid = np.isfinite(dem_pad) & (dem_pad != float_nodata)
    dem_pad = _smooth_dem(dem_pad, dem_pad_valid, dem_smooth_window, float_nodata)
    twi_pad = _compute_twi(dem_pad, dem_pad_valid, res_x, float_nodata)
    twi = twi_pad[
        twi_buffer_cells : twi_buffer_cells + height,
        twi_buffer_cells : twi_buffer_cells + width,
    ].copy()
    twi = np.where(
        dem_valid & np.isfinite(twi) & (twi != float_nodata), twi, float_nodata
    ).astype(np.float32)
    return dem, slope, twi, dem_valid



def build_feature_stack(
    ctx: ProjectContext,
    year: int,
    order: list[str] | None = None,
    out_stack: Path | None = None,
    out_valid: Path | None = None,
) -> Path:
    """构建指定年份的 21 维特征堆栈，供分类组直接取用。

    特征构成（顺序由配置 `[feature_stack].order` 决定，默认 21 维）：
      1. 6 个地表反射率波段：blue / green / red / nir / swir1 / swir2；
      2. 7 项光谱指数：NDVI、SAVI、MNDWI、NDBI、UI、BSI、IBI；
      3. 6 项局部纹理：NIR / Red / SWIR1 在 5×5 窗口内的均值与标准差；
      4. 2 项地形：DEM 高程（米）与坡度（度）。

    科学口径：
      - 反射率与指数沿用 `samples.calculate_indices()` 的公式与 NoData 规则，本模块只做扩展，
        两处公式一致性由 `tests/unit/test_preprocess.py` 的对照用例守护；
      - 纹理统计只统计有效像元（以 uniform_filter 求有效像元加权均值与方差），
        不会把 -9999 的无效值混入邻域平均；
      - 全部波段统一使用 valid_sr_30m.tif 的像元有效性，任一输入无效则该像元所有特征置 NoData；
      - TWI（地形湿度指数）不在本步骤计算：它需要汇流累积量，属于水文分析，由分析阶段负责。

    Args:
        ctx (ProjectContext): 项目运行上下文。
        year (int): 年份，需已存在 processed/<year>/sr_30m.tif。

    Returns:
        Path: 特征堆栈路径 data/processed/features/feat_<year>_30m.tif。

    Raises:
        FileNotFoundError: 反射率、有效性掩膜、DEM 或网格文件缺失。
        ValueError: 配置的特征名单与可计算特征不匹配。
    """
    sr_path = ctx.data / "processed" / str(year) / "sr_30m.tif"
    valid_path = ctx.data / "processed" / str(year) / "valid_sr_30m.tif"
    if not sr_path.exists():
        raise FileNotFoundError(f"Surface reflectance raster not found: {sr_path}")
    if not valid_path.exists():
        raise FileNotFoundError(f"Valid surface reflectance mask not found: {valid_path}")

    fs_cfg = ctx.config.get("feature_stack", {})
    if order is None:
        order = list(fs_cfg.get("order", DEFAULT_FEATURE_STACK_ORDER))
    order = list(order)
    # 只有请求地形特征时才需要 DEM；只用波段/指数/纹理时（如小样本单测）不强制 DEM
    needs_terrain = any(n in ("elevation", "slope", "twi") for n in order)
    texture_window = int(fs_cfg.get("texture_window", 5))
    dem_rel = fs_cfg.get("dem_path")
    if needs_terrain and not dem_rel:
        raise FileNotFoundError("feature_stack.dem_path is not configured in project.toml")

    dem_path = None
    if needs_terrain:
        dem_path = Path(dem_rel)
        if not dem_path.is_absolute():
            dem_path = ctx.data / (dem_rel.replace("data/", "", 1) if dem_rel.startswith("data/") else dem_rel)
        if not dem_path.exists():
            raise FileNotFoundError(f"DEM raster not found: {dem_path}")

    float_nodata = float(ctx.config.get("float_nodata", -9999.0))
    eps = 1e-6

    with rasterio.open(sr_path) as src:
        sr = src.read().astype(np.float32)
        height, width = src.height, src.width
        profile = src.profile.copy()
        dst_transform = src.transform
        dst_crs = src.crs

    with rasterio.open(valid_path) as src:
        valid_sr = src.read(1)

    is_valid = valid_sr == 1
    for b in range(sr.shape[0]):
        is_valid &= np.isfinite(sr[b]) & (sr[b] != float_nodata)

    blue, green, red, nir, swir1, swir2 = (sr[i] for i in range(6))

    def ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
        """按有效掩膜计算比值，分母过小或无效时置 NoData。"""
        safe = is_valid & (np.abs(denominator) > eps)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(safe, numerator / denominator, float_nodata).astype(np.float32)

    t_b = ratio(2.0 * swir1, swir1 + nir)
    t_v_raw = ratio(nir, nir + red) + ratio(green, green + swir1)
    t_v_raw = np.where(is_valid, t_v_raw, float_nodata).astype(np.float32)

    indices: dict[str, np.ndarray] = {
        "ndvi": ratio(nir - red, nir + red),
        "savi": ratio(1.5 * (nir - red), nir + red + 0.5),
        "mndwi": ratio(green - swir1, green + swir1),
        "ndbi": ratio(swir1 - nir, swir1 + nir),
        "ui": ratio(swir2 - nir, swir2 + nir),
        "bsi": ratio((swir1 + red) - (nir + blue), (swir1 + red) + (nir + blue)),
        "ibi": ratio(t_b - t_v_raw, t_b + t_v_raw),
    }

    def texture_stats(band: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """计算窗口内有效像元的局部均值与标准差。"""
        weight = is_valid.astype(np.float32)
        filled = np.where(is_valid, band, 0.0).astype(np.float32)
        wsum = uniform_filter(weight, size=texture_window, mode="nearest")
        bsum = uniform_filter(filled, size=texture_window, mode="nearest")
        bsq = uniform_filter(filled * filled, size=texture_window, mode="nearest")
        with np.errstate(divide="ignore", invalid="ignore"):
            mean = np.where(wsum > 0, bsum / wsum, float_nodata)
            var = np.where(wsum > 0, bsq / wsum - mean * mean, float_nodata)
        std = np.sqrt(np.clip(np.where(np.isfinite(var), var, 0.0), 0.0, None))
        mean = np.where(is_valid, mean, float_nodata).astype(np.float32)
        std = np.where(is_valid, std, float_nodata).astype(np.float32)
        return mean, std

    texture: dict[str, np.ndarray] = {}
    for band_name, band_arr in (("nir", nir), ("red", red), ("swir1", swir1)):
        mean_arr, std_arr = texture_stats(band_arr)
        texture[f"{band_name}_mean"] = mean_arr
        texture[f"{band_name}_std"] = std_arr

    # DEM：主网格用于高程与坡度；带缓冲窗口用于 TWI 汇流（缓冲可减少边界汇水缺失）
    dem_smooth_window = int(fs_cfg.get("dem_smooth_window", 5))
    twi_buffer_cells = int(fs_cfg.get("twi_buffer_cells", 67))
    res_x = abs(dst_transform.a)
    res_y = abs(dst_transform.e)

    dem = slope = twi = None
    if needs_terrain:
        dem, slope, twi, dem_valid = _compute_terrain_arrays(
            dem_path=dem_path,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            height=height,
            width=width,
            float_nodata=float_nodata,
            dem_smooth_window=dem_smooth_window,
            twi_buffer_cells=twi_buffer_cells,
        )
        is_valid = is_valid & dem_valid

    values: dict[str, np.ndarray] = {
        "blue": blue, "green": green, "red": red, "nir": nir, "swir1": swir1, "swir2": swir2,
        **indices, **texture,
    }
    if needs_terrain:
        values.update({"elevation": dem, "slope": slope, "twi": twi})

    unknown = [name for name in order if name not in values]
    if unknown:
        raise ValueError(f"Unknown feature names in feature_stack.order: {unknown}")

    stack = np.stack(
        [np.where(is_valid, values[name], float_nodata) for name in order], axis=0
    ).astype(np.float32)

    if out_stack is not None:
        out_path = Path(out_stack)
    else:
        out_dir = ctx.data / "processed" / "features"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"feat_{year}_30m.tif"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    profile.update(count=len(order), dtype="float32", nodata=float_nodata)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(stack)
        for idx, name in enumerate(order, start=1):
            dst.set_band_description(idx, name)

    # 可选：同时写出 uint8 有效特征掩膜（1=有效，0=无效）
    if out_valid is not None:
        valid_profile = profile.copy()
        valid_profile.update(count=1, dtype="uint8", nodata=255)
        Path(out_valid).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_valid, "w", **valid_profile) as dst_v:
            dst_v.write(is_valid.astype(np.uint8), 1)

    # 发布副本，供分类/制图直接取用（仅在写规范路径时执行，避免重复拷贝）
    if out_stack is None:
        out_raster_dir = ctx.outputs / "rasters"
        out_raster_dir.mkdir(parents=True, exist_ok=True)
        pub_path = out_raster_dir / f"xindu_{year}_features_30m.tif"
        shutil.copy2(out_path, pub_path)

    rep_dir = ctx.reports / "data"
    rep_dir.mkdir(parents=True, exist_ok=True)
    report_data = {
        "year": int(year),
        "feature_count": len(order),
        "feature_order": order,
        "texture_window": texture_window,
        "dem_smooth_window": dem_smooth_window,
        "dem_path": str(dem_rel),
        "formulas": FEATURE_FORMULAS,
        "valid_pixels": int(is_valid.sum()),
        "nodata_val": float_nodata,
        "width": int(width),
        "height": int(height),
        "crs": str(dst_crs),
        "slope_deg_p50": (
            float(np.median(slope[is_valid])) if needs_terrain and is_valid.any() else None
        ),
        "elevation_m_p50": (
            float(np.median(dem[is_valid])) if needs_terrain and is_valid.any() else None
        ),
        "twi_p50": float(np.median(twi[is_valid])) if needs_terrain and is_valid.any() else None,
        "twi_buffer_cells": twi_buffer_cells,
        "twi_note": "Priority-Flood 填洼 + D8 单流向汇流；缓冲 2km 后按主网格裁切",
    }
    (rep_dir / f"features_{year}.json").write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return out_path
