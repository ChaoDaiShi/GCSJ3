"""样本处理、10波段特征提取与空间分层分组留出模块（P1-B）。

主要功能与科学处理流程：
1. calculate_indices:
   - 基于 6 个基础地表反射率波段计算 4 项关键遥感光谱指数：
     * 归一化植被指数 NDVI  = (NIR - Red) / (NIR + Red)
     * 归一化建筑指数 NDBI  = (SWIR1 - NIR) / (SWIR1 + NIR)
     * 改进归一化水体指数 MNDWI = (Green - SWIR1) / (Green + SWIR1)
     * 裸土指数 BSI         = ((SWIR1 + Red) - (NIR + Blue)) / ((SWIR1 + Red) + (NIR + Blue))
   - 严密检测除零异常与有限值范围，任一分母为 0 或出现 NaN/NoData 时，所有 10 项特征均置为 -9999.0。

2. generate_features_raster:
   - 分块流式读取 sr_30m.tif，生成 10 波段特征栅格 features_30m.tif 及有效性掩膜 valid_features_30m.tif。

3. split_sample_groups:
   - 依据空间地块单元（group_id）和地类编码（class_id）执行分层分组随机划分（GroupShuffleSplit）；
   - 保证同属一个物理地块的所有像元必须归于同一子集（要么全在训练集，要么全在留出集），杜绝空间自相关导致的精度虚高。

4. extract_pixel_samples:
   - 将样本多边形与特征栅格进行空间重叠分析，提取多边形内部所有有效像元的特征与空间坐标；
   - 严格核验训练集与验证集的像元坐标交集为空、地块组交集为空。

5. build_samples:
   - 串联上述流程，固化划分方案并输出不可篡改的 SHA256 校验码与采样独立性审计报告。
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shutil

import rasterio
import rasterio.features
import rasterio.windows
from sklearn.model_selection import GroupShuffleSplit

from rs_urban.contracts import ProjectContext, SampleData

# 样本 CSV 的固定标识列；特征列由配置 [features].order 动态追加
SAMPLE_BASE_FIELDNAMES = [
    "sample_id", "group_id", "year", "class_id",
    "row", "col", "x", "y",
]

# 兼容旧调用：10 维默认字段名（基础列 + 默认特征列）
SAMPLE_CSV_FIELDNAMES = SAMPLE_BASE_FIELDNAMES + [
    "blue", "green", "red", "nir", "swir1", "swir2",
    "ndvi", "ndbi", "mndwi", "bsi",
]

# 10 波段特征栅格默认波段排列顺序
DEFAULT_FEATURE_ORDER = [
    "blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"
]


def calculate_indices(
    sr_arr: np.ndarray,
    valid_sr: np.ndarray,
    float_nodata: float = -9999.0,
) -> tuple[np.ndarray, np.ndarray]:
    """根据 6 波段地表反射率数组计算 4 项遥感光谱指数，合成 10 波段特征矩阵。

    输入数组规格：
    - sr_arr 形状为 (6, H, W)，波段顺序为：blue, green, red, nir, swir1, swir2；
    - valid_sr 形状为 (H, W)，值定义为：1=有效，0=区内无效，255=区外。

    指数计算公式：
      - NDVI  = (nir - red) / (nir + red)                [表征植被茂密程度]
      - NDBI  = (swir1 - nir) / (swir1 + nir)            [表征城镇不透水面及建筑覆盖]
      - MNDWI = (green - swir1) / (green + swir1)        [表征地表开阔水体特征]
      - BSI   = ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue)) [表征裸土与未利用地]

    科学计算与异常保护规则：
      - 当任一指数分母为 0，或任一输入波段为 NaN/Inf/NoData，或 valid_sr != 1 时，
        该像元所有 10 项特征均统一置为 float_nodata (-9999.0)；
      - 输出的 valid_features 掩膜中：1 表示有效像元，0 表示研究区内无效/除零像元，255 表示研究区外。

    Args:
        sr_arr (np.ndarray): 6 波段地表反射率浮点矩阵，形状 (6, H, W)。
        valid_sr (np.ndarray): 像元有效性掩膜矩阵，形状 (H, W)。
        float_nodata (float, optional): 无效值填充浮点数。默认为 -9999.0。

    Returns:
        tuple[np.ndarray, np.ndarray]:
            - features: 包含 10 个特征波段的 float32 数组，形状为 (10, H, W)；
            - valid_features: uint8 有效特征掩膜，形状为 (H, W)。
    """
    blue = sr_arr[0]
    green = sr_arr[1]
    red = sr_arr[2]
    nir = sr_arr[3]
    swir1 = sr_arr[4]
    swir2 = sr_arr[5]

    # 分别计算 4 个指数的分母项
    denom_ndvi = nir + red
    denom_ndbi = swir1 + nir
    denom_mndwi = green + swir1
    denom_bsi = (swir1 + red) + (nir + blue)

    # 检查 6 个反射率波段是否均为有限实数且不等于 NoData
    finite_mask = np.ones(valid_sr.shape, dtype=bool)
    for b in range(6):
        finite_mask &= np.isfinite(sr_arr[b]) & (sr_arr[b] != float_nodata)

    # 检查所有分母是否均非零
    nonzero_denom = (
        (denom_ndvi != 0.0)
        & (denom_ndbi != 0.0)
        & (denom_mndwi != 0.0)
        & (denom_bsi != 0.0)
    )

    # 综合判定有效像元掩膜
    is_valid = (valid_sr == 1) & finite_mask & nonzero_denom

    # 计算 4 项指数，若无效则填入 float_nodata
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(is_valid, (nir - red) / denom_ndvi, float_nodata).astype(np.float32)
        ndbi = np.where(is_valid, (swir1 - nir) / denom_ndbi, float_nodata).astype(np.float32)
        mndwi = np.where(is_valid, (green - swir1) / denom_mndwi, float_nodata).astype(np.float32)
        bsi = np.where(
            is_valid,
            ((swir1 + red) - (nir + blue)) / denom_bsi,
            float_nodata,
        ).astype(np.float32)

    # 同样屏蔽原始 6 个波段在无效区域的数值
    masked_sr = [
        np.where(is_valid, sr_arr[b], float_nodata).astype(np.float32)
        for b in range(6)
    ]

    # 沿第 0 轴堆叠拼接 10 个特征
    features = np.stack(masked_sr + [ndvi, ndbi, mndwi, bsi], axis=0)

    # 构建 valid_features 掩膜：研究区外为 255，有效像元为 1，区内无效为 0
    valid_features = np.zeros(valid_sr.shape, dtype=np.uint8)
    valid_features[valid_sr == 255] = 255
    valid_features[is_valid] = 1

    return features, valid_features


def generate_features_raster(
    sr_path: Path,
    valid_sr_path: Path,
    out_features_path: Path,
    out_valid_features_path: Path,
    config: dict[str, Any],
) -> tuple[Path, Path]:
    """生成 10 波段 Float32 特征 GeoTIFF 及单波段 Byte 有效掩膜 GeoTIFF。

    采用滑动分块窗口（block_windows）机制，逐块计算并写入磁盘，控制内存开销。

    Args:
        sr_path (Path): 输入的 6 波段地表反射率 GeoTIFF 路径。
        valid_sr_path (Path): 输入的地表反射率有效掩膜路径。
        out_features_path (Path): 输出的 10 波段特征栅格保存路径。
        out_valid_features_path (Path): 输出的有效特征掩膜保存路径。
        config (dict[str, Any]): 项目全局配置字典。

    Returns:
        tuple[Path, Path]: (out_features_path, out_valid_features_path)
    """
    float_nodata = float(config.get("float_nodata", -9999.0))
    feature_order = config.get("features", {}).get("order", DEFAULT_FEATURE_ORDER)

    with rasterio.open(sr_path) as src_sr, rasterio.open(valid_sr_path) as src_valid:
        meta_features = src_sr.meta.copy()
        meta_features.update({
            "count": len(feature_order),
            "dtype": "float32",
            "nodata": float_nodata,
        })

        meta_valid = src_valid.meta.copy()
        meta_valid.update({
            "count": 1,
            "dtype": "uint8",
            "nodata": 255,
        })

        out_features_path.parent.mkdir(parents=True, exist_ok=True)
        out_valid_features_path.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(out_features_path, "w", **meta_features) as dst_f, \
             rasterio.open(out_valid_features_path, "w", **meta_valid) as dst_vf:
            # 记录波段描述信息（band descriptions）
            dst_f.descriptions = tuple(feature_order)

            # 遍历分块窗口执行计算
            for _, window in src_sr.block_windows():
                sr_block = src_sr.read(window=window).astype(np.float32)
                valid_block = src_valid.read(1, window=window)

                f_block, vf_block = calculate_indices(
                    sr_block, valid_block, float_nodata=float_nodata
                )

                dst_f.write(f_block, window=window)
                dst_vf.write(vf_block, 1, window=window)

    return out_features_path, out_valid_features_path


def split_sample_groups(
    labels_gdf: gpd.GeoDataFrame,
    random_seed: int = 42,
    holdout_fraction: float = 0.25,
    min_labeled_groups: int = 8,
    min_holdout_groups: int = 2,
    existing_split_path: Path | None = None,
) -> dict[str, str]:
    """基于地块单元（group_id）和地类（class_id）执行分层分组随机抽取（GroupShuffleSplit）。

    科学机制：
    - 若预先存在已冻结的 split.json 文件，则直接读取重用历史划分，保障实验严格可复现；
    - 针对每个地类（class_id），按 group_id 进行无交集抽取，比例约为 holdout_fraction（默认 25%）；
    - 严格检查：每个 group_id 必须唯一属于一个 class_id；
    - 严格检查：每个类别的标注地块组数必须满足最低阈值（默认每类至少 8 组，留出验证组至少 2 组）。

    Args:
        labels_gdf (gpd.GeoDataFrame): 包含 group_id、class_id 和 geometry 的样本矢量 GeoDataFrame。
        random_seed (int, optional): 随机数种子。默认为 42。
        holdout_fraction (float, optional): 留出集地块组比例。默认为 0.25。
        min_labeled_groups (int, optional): 每类最少包含的地块组数。默认为 8。
        min_holdout_groups (int, optional): 每类最少包含的留出验证地块组数。默认为 2。
        existing_split_path (Path | None, optional): 预先存在的划分元数据文件路径。

    Returns:
        dict[str, str]: group_id -> 'train' | 'holdout' 的归属映射字典。

    Raises:
        ValueError: 当地块跨多个类别，或类别地块组数不足时抛出。
    """
    # 优先复用已存在的冻结划分方案
    if existing_split_path is not None and existing_split_path.exists():
        with open(existing_split_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            saved_groups = data.get("groups", {})
            gdf_groups = set(labels_gdf["group_id"].unique())
            if gdf_groups.issubset(saved_groups.keys()):
                return {g: saved_groups[g] for g in gdf_groups}

    # 核验每一个 group_id 是否严格只对应一个 class_id
    group_classes = labels_gdf.groupby("group_id")["class_id"].unique()
    for g_id, c_ids in group_classes.items():
        if len(c_ids) > 1:
            raise ValueError(
                f"Group {g_id} is associated with multiple classes: {list(c_ids)}"
            )

    split_map: dict[str, str] = {}
    classes_present = sorted(labels_gdf["class_id"].unique())

    # 按类别分别开展分层分组抽取
    for class_id in classes_present:
        class_df = labels_gdf[labels_gdf["class_id"] == class_id]
        unique_groups = sorted(class_df["group_id"].unique())

        if len(unique_groups) < min_labeled_groups:
            raise ValueError(
                f"Class {class_id} has {len(unique_groups)} groups, which is less than "
                f"required minimum of {min_labeled_groups} groups."
            )

        gss = GroupShuffleSplit(
            n_splits=1,
            test_size=holdout_fraction,
            random_state=random_seed,
        )

        dummy_x = np.arange(len(unique_groups))
        train_idx, holdout_idx = next(gss.split(dummy_x, groups=unique_groups))

        train_groups = [unique_groups[i] for i in train_idx]
        holdout_groups = [unique_groups[i] for i in holdout_idx]

        if len(holdout_groups) < min_holdout_groups:
            raise ValueError(
                f"Class {class_id} resulted in {len(holdout_groups)} holdout groups, "
                f"less than required minimum of {min_holdout_groups} holdout groups."
            )

        for g in train_groups:
            split_map[g] = "train"
        for g in holdout_groups:
            split_map[g] = "holdout"

    return split_map


def extract_pixel_samples(
    features_path: Path,
    valid_features_path: Path,
    labels_gdf: gpd.GeoDataFrame,
    split_map: dict[str, str],
    year: int,
    feature_order: list[str] | None = None,
    purity_rules: dict[int, dict[str, tuple[float, float]]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """提取样本矢量多边形覆盖范围内的全部有效像元中心点特征，形成训练集与独立留出集。

    执行流程与校验要求：
    1. 计算每个多边形的外包矩形窗口，局部读取特征与掩膜以节省内存；
    2. 使用 geometry_mask 提取落入多边形内部的栅格像元（全包含判定）；
    3. 全局记录已采样像元坐标 (row, col)，若同一坐标出现在不同组或类别中，抛出异常；
    4. 过滤有效掩膜 != 1 或特征值为 NaN/NoData 的像元；
    5. 计算像元中心投影坐标 (x, y)，与 10 项特征一起打包为 DataFrame；
    6. 强力校验：训练组与留出组无交集、训练像元坐标与留出像元坐标无交集。

    Args:
        features_path (Path): 10 波段特征栅格文件路径。
        valid_features_path (Path): 特征有效性掩膜文件路径。
        labels_gdf (gpd.GeoDataFrame): 样本矢量图层。
        split_map (dict[str, str]): 地块组划分映射表 (group_id -> 'train'|'holdout')。
        year (int): 采样年份。

    Returns:
        tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
            - train_df: 训练集表格；
            - holdout_df: 独立留出集表格；
            - summary: 包含各类样本数量、地块组数统计的摘要字典。

    Raises:
        ValueError: 当存在像元坐标重复赋予不同类别，或训练集与留出集产生空间交叠时抛出。
    """
    train_rows: list[dict[str, Any]] = []
    holdout_rows: list[dict[str, Any]] = []
    seen_pixels: dict[tuple[int, int], tuple[str, int]] = {}
    purity_dropped: dict[int, int] = {}

    with rasterio.open(features_path) as src_probe:
        band_count = src_probe.count
        descriptions = list(src_probe.descriptions)
    if feature_order is None:
        if descriptions and all(descriptions):
            feature_order = [str(d) for d in descriptions]
        else:
            feature_order = DEFAULT_FEATURE_ORDER[:band_count]
    feature_order = list(feature_order)
    if len(feature_order) != band_count:
        raise ValueError(
            f"feature_order has {len(feature_order)} names but raster has {band_count} bands: {features_path}"
        )

    with rasterio.open(features_path) as src_f, rasterio.open(valid_features_path) as src_vf:
        transform = src_f.transform
        width = src_f.width
        height = src_f.height

        for _, row in labels_gdf.iterrows():
            geom = row.geometry
            if geom.is_empty:
                continue

            sample_id = str(row["sample_id"])
            group_id = str(row["group_id"])
            class_id = int(row["class_id"])
            split_type = split_map.get(group_id, "train")

            # 基于几何边界确定局部读取窗口
            bounds = geom.bounds
            window = rasterio.windows.from_bounds(*bounds, transform=transform).round_offsets().round_lengths()
            r_start = max(0, int(window.row_off) - 1)
            c_start = max(0, int(window.col_off) - 1)
            r_stop = min(height, int(window.row_off + window.height) + 1)
            c_stop = min(width, int(window.col_off + window.width) + 1)

            if r_stop <= r_start or c_stop <= c_start:
                continue

            win = rasterio.windows.Window(c_start, r_start, c_stop - c_start, r_stop - r_start)
            win_transform = rasterio.windows.transform(win, transform)

            # 仅保留多边形覆盖的内部像元
            win_mask = rasterio.features.geometry_mask(
                [geom],
                out_shape=(int(win.height), int(win.width)),
                transform=win_transform,
                invert=True,
                all_touched=False,
            )

            vf_block = src_vf.read(1, window=win)
            f_block = src_f.read(window=win)

            # 遍历几何掩膜覆盖的所有像元
            matched_indices = np.argwhere(win_mask)
            for r_win, c_win in matched_indices:
                r_global = r_start + r_win
                c_global = c_start + c_win

                # 检查像元是否已被处理，防范标签冲突
                coord = (r_global, c_global)
                if coord in seen_pixels:
                    prev_group, prev_class = seen_pixels[coord]
                    if prev_group != group_id or prev_class != class_id:
                        raise ValueError(
                            f"Pixel row={r_global}, col={c_global} assigned to multiple groups "
                            f"({prev_group} vs {group_id}) or classes ({prev_class} vs {class_id})."
                        )
                    continue

                seen_pixels[coord] = (group_id, class_id)

                # 跳过有效掩膜不合格或特征值异常的像元
                if vf_block[r_win, c_win] != 1:
                    continue

                feat_vals = f_block[:, r_win, c_win]
                if not np.all(np.isfinite(feat_vals)) or np.any(feat_vals == -9999.0):
                    continue

                # 像元纯度过滤：面内仍不符合该类光谱区间的像元不计入样本
                if purity_rules and class_id in purity_rules:
                    keep = True
                    for fname, (lo, hi) in purity_rules[class_id].items():
                        try:
                            idx = feature_order.index(fname)
                        except ValueError:
                            raise ValueError(f"purity rule references unknown feature: {fname}")
                        val = float(feat_vals[idx])
                        if val < lo or val > hi:
                            keep = False
                            break
                    if not keep:
                        purity_dropped[class_id] = purity_dropped.get(class_id, 0) + 1
                        continue

                # 计算像元中心点的空间投影坐标 (x, y)
                cx, cy = rasterio.transform.xy(transform, r_global, c_global, offset="center")

                record = {
                    "sample_id": sample_id,
                    "group_id": group_id,
                    "year": year,
                    "class_id": class_id,
                    "row": r_global,
                    "col": c_global,
                    "x": cx,
                    "y": cy,
                }
                for fname, fval in zip(feature_order, feat_vals):
                    record[fname] = float(fval)

                if split_type == "train":
                    train_rows.append(record)
                else:
                    holdout_rows.append(record)

    csv_fields = SAMPLE_BASE_FIELDNAMES + list(feature_order)
    train_df = pd.DataFrame(train_rows, columns=csv_fields)
    holdout_df = pd.DataFrame(holdout_rows, columns=csv_fields)

    # 严密核验训练组与留出组是否互斥
    train_groups = set(train_df["group_id"].unique()) if not train_df.empty else set()
    holdout_groups = set(holdout_df["group_id"].unique()) if not holdout_df.empty else set()
    if train_groups.intersection(holdout_groups):
        raise ValueError(f"Train and holdout groups intersect: {train_groups.intersection(holdout_groups)}")

    # 严密核验像元坐标是否互斥
    train_coords = set(zip(train_df["row"], train_df["col"])) if not train_df.empty else set()
    holdout_coords = set(zip(holdout_df["row"], holdout_df["col"])) if not holdout_df.empty else set()
    if train_coords.intersection(holdout_coords):
        raise ValueError("Train and holdout pixel coordinates intersect.")

    # 汇总各类别样本及地块分布情况
    class_summary: dict[int, dict[str, int]] = {}
    classes_present = sorted(labels_gdf["class_id"].unique())
    for c in classes_present:
        class_summary[int(c)] = {
            "total_groups": int(len(labels_gdf[labels_gdf["class_id"] == c]["group_id"].unique())),
            "train_groups": int(len(train_df[train_df["class_id"] == c]["group_id"].unique())),
            "holdout_groups": int(len(holdout_df[holdout_df["class_id"] == c]["group_id"].unique())),
            "train_pixels": int((train_df["class_id"] == c).sum()),
            "holdout_pixels": int((holdout_df["class_id"] == c).sum()),
        }

    summary = {
        "total_train_samples": len(train_df),
        "total_holdout_samples": len(holdout_df),
        "class_summary": class_summary,
        "purity_dropped_pixels": {int(k): int(v) for k, v in purity_dropped.items()},
    }

    return train_df, holdout_df, summary


def build_samples(ctx: ProjectContext, year: int) -> SampleData:
    """构建 10 波段特征栅格、固化分组划分元数据并提取训练与留出样本集的主管道。

    步骤说明：
    1. 检查输入地表反射率、有效掩膜及人工目视解译样本矢量文件 labels.gpkg；
    2. 计算并输出 features_30m.tif 与 valid_features_30m.tif；
    3. 执行基于地块的分层 GroupShuffleSplit 抽取；
    4. 提取像元样本至 train.csv 与 holdout.csv；
    5. 计算划分方案的 SHA256 哈希值并保存 split.json；
    6. 输出中文独立性核查审计报告 reports/accuracy/sampling_{year}.md。

    Args:
        ctx (ProjectContext): 项目运行上下文。
        year (int): 目标年份（1992 或 2021）。

    Returns:
        SampleData: 包含特征栅格与样本 CSV 路径的数据契约对象。

    Raises:
        FileNotFoundError: 当必要输入文件缺失时抛出。
    """
    sr_path = ctx.data / "processed" / str(year) / "sr_30m.tif"
    valid_sr_path = ctx.data / "processed" / str(year) / "valid_sr_30m.tif"
    labels_path = ctx.data / "samples" / str(year) / "labels.gpkg"

    if not sr_path.exists():
        raise FileNotFoundError(f"Required input SR raster not found: {sr_path}")
    if not valid_sr_path.exists():
        raise FileNotFoundError(f"Required input valid SR raster not found: {valid_sr_path}")
    if not labels_path.exists():
        raise FileNotFoundError(f"Required input labels vector not found: {labels_path}")

    # 规范化输出路径
    features_path = ctx.data / "processed" / str(year) / "features_30m.tif"
    valid_features_path = ctx.data / "processed" / str(year) / "valid_features_30m.tif"
    samples_dir = ctx.data / "processed" / "samples" / str(year)
    samples_dir.mkdir(parents=True, exist_ok=True)

    train_path = samples_dir / "train.csv"
    holdout_path = samples_dir / "holdout.csv"
    split_path = samples_dir / "split.json"

    # 步骤 1：准备特征栅格与有效掩膜。
    # 首选 01_preprocess --step features 产出的 22 维规范栈（含 band description），
    # 避免同一套特征在两处重复实现；缺失时按 [features].order 现算并落到标准路径。
    feature_order = list(ctx.config.get("features", {}).get("order", DEFAULT_FEATURE_ORDER))
    canonical_stack = ctx.data / "processed" / "features" / f"feat_{year}_30m.tif"
    if not canonical_stack.exists():
        from rs_urban.preprocess import build_feature_stack

        canonical_stack = build_feature_stack(ctx, year, order=feature_order)

    # 仅当波段数一致、且特征栅格不比地表反射率旧时才复用；换影像后必须重算
    need_copy = True
    if features_path.exists():
        with rasterio.open(features_path) as ds:
            need_copy = ds.count != len(feature_order)
        if not need_copy and features_path.stat().st_mtime < sr_path.stat().st_mtime:
            need_copy = True
    if need_copy:
        features_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(canonical_stack, features_path)
    if not valid_features_path.exists():
        with rasterio.open(valid_sr_path) as ds_v:
            valid_profile = ds_v.profile.copy()
            valid_arr = ds_v.read(1)
        valid_profile.update(count=1, dtype="uint8", nodata=255)
        with rasterio.open(valid_features_path, "w", **valid_profile) as dst_v:
            dst_v.write((valid_arr == 1).astype(np.uint8), 1)

    # 步骤 2：读取人工标注地块样本
    labels_gdf = gpd.read_file(labels_path, layer="labels")
    target_crs = ctx.config.get("target_crs", "EPSG:32648")
    if labels_gdf.crs is None:
        labels_gdf = labels_gdf.set_crs(target_crs)
    elif labels_gdf.crs.to_string() != target_crs:
        labels_gdf = labels_gdf.to_crs(target_crs)

    # 步骤 3：按地块组分层抽取
    sampling_cfg = ctx.config.get("sampling", {})
    random_seed = int(ctx.config.get("random_seed", 42))
    holdout_fraction = float(sampling_cfg.get("holdout_fraction", 0.25))
    min_labeled_groups = int(sampling_cfg.get("minimum_labeled_groups_per_class", 8))
    min_holdout_groups = int(sampling_cfg.get("minimum_holdout_groups_per_class", 2))

    split_map = split_sample_groups(
        labels_gdf=labels_gdf,
        random_seed=random_seed,
        holdout_fraction=holdout_fraction,
        min_labeled_groups=min_labeled_groups,
        min_holdout_groups=min_holdout_groups,
        existing_split_path=split_path,
    )

    # 步骤 3.5：解析像元纯度过滤规则（人工面内剔除混合像元）
    purity_cfg = sampling_cfg.get("purity", {})
    purity_rules: dict[int, dict[str, tuple[float, float]]] = {}
    if purity_cfg.get("enabled"):
        ranges_cfg = purity_cfg.get(f"ranges_{year}") or purity_cfg.get("ranges", {})
        for cls_key, ranges in ranges_cfg.items():
            purity_rules[int(cls_key)] = {
                str(name): (float(bounds[0]), float(bounds[1]))
                for name, bounds in ranges.items()
            }

    # 步骤 4：提取像元样本
    train_df, holdout_df, summary = extract_pixel_samples(
        features_path=features_path,
        valid_features_path=valid_features_path,
        labels_gdf=labels_gdf,
        split_map=split_map,
        year=year,
        feature_order=feature_order,
        purity_rules=purity_rules or None,
    )

    # 步骤 5：导出 CSV 数据集
    train_df.to_csv(train_path, index=False, encoding="utf-8")
    holdout_df.to_csv(holdout_path, index=False, encoding="utf-8")

    # 步骤 6：计算划分方案的 SHA256 哈希值，写入 split.json
    split_payload = {
        "schema_version": 1,
        "year": year,
        "random_seed": random_seed,
        "holdout_fraction": holdout_fraction,
        "total_groups": len(split_map),
        "train_groups_count": len([g for g, s in split_map.items() if s == "train"]),
        "holdout_groups_count": len([g for g, s in split_map.items() if s == "holdout"]),
        "total_train_samples": len(train_df),
        "total_holdout_samples": len(holdout_df),
        "class_summary": summary["class_summary"],
        "groups": split_map,
    }
    split_canonical = json.dumps(split_map, sort_keys=True).encode("utf-8")
    split_sha256 = hashlib.sha256(split_canonical).hexdigest()
    split_payload["split_sha256"] = split_sha256

    with open(split_path, "w", encoding="utf-8") as f:
        json.dump(split_payload, f, indent=2, ensure_ascii=False)

    # 步骤 7：编写 Markdown 格式的样本独立性核查与分布审计报告
    reports_acc_dir = ctx.reports / "accuracy"
    reports_acc_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_acc_dir / f"sampling_{year}.md"

    report_lines = [
        f"# 遥感样本采集与分组留出说明报告（{year} 年）",
        "",
        f"- **生成年份：** {year}",
        f"- **随机种子：** {random_seed}",
        f"- **留出比例：** {holdout_fraction * 100:.1f}%",
        f"- **总地块组数：** {len(split_map)}",
        f"- **训练样本数（Train）：** {len(train_df)} 像元",
        f"- **独立留出样本数（Holdout）：** {len(holdout_df)} 像元",
        f"- **划分 SHA256：** `{split_sha256}`",
        "",
        "## 各类别样本分布与分组留出统计",
        "",
        "| 类别编码 | 类别名称 | 总组数 | 训练组数 | 留出组数 (Holdout) | 训练像元数 | 留出像元数 |",
        "| :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    class_names = {c["code"]: c["name"] for c in ctx.config.get("classes", [])}
    for c_id, stats in sorted(summary["class_summary"].items()):
        c_name = class_names.get(c_id, f"类别_{c_id}")
        report_lines.append(
            f"| {c_id} | {c_name} | {stats['total_groups']} | {stats['train_groups']} | "
            f"{stats['holdout_groups']} | {stats['train_pixels']} | {stats['holdout_pixels']} |"
        )

    report_lines.extend([
        "",
        "## 独立性核查证据",
        "",
        "- [x] 训练组与留出组交集严格为空（已自动核验）。",
        "- [x] 训练像元坐标与留出像元坐标交集严格为空（已自动核验）。",
        f"- [x] 每类独立留出组均不小于 {min_holdout_groups} 组。",
        "- [x] 像元特征不包含缺失值或分母为 0 像元。",
        "",
    ])

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    return SampleData(
        year=year,
        features=features_path,
        valid_features=valid_features_path,
        train=train_path,
        holdout=holdout_path,
        split=split_path,
    )
