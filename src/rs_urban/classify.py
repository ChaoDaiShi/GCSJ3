"""随机森林模型训练与全景滑动窗口分类推理模块（P1-C）。

主要功能与科学处理流程：
1. train_classifier:
   - 严格在训练集（train.csv）上拟合随机森林分类器（RandomForestClassifier），严禁触碰或泄露留出验证集；
   - 采用均衡抽样子集权重（balanced_subsample）与配置好的超参数（如树木棵数 n_estimators、叶子最小样本数 min_samples_leaf 等）；
   - 校验训练集特征列与配置顺序的一致性；
   - 计算训练集及划分元数据的 SHA256 哈希签名，构建标准化模型持久化包与训练审计元数据。

2. predict_raster_windowed:
   - 采用分块流式滑动窗口（iter_windows）对整景 10 波段特征栅格执行无缝推理预测；
   - 严格核对特征栅格与有效掩膜的空间参考、仿射变换及行列号一致性；
   - 仅对有效像元（valid_features == 1 且数值有限且非 NoData）代入模型预测，无效像元赋为 0（NoData）；
   - 输出 Byte 类型的原始土地利用分类栅格（lulc_{year}_raw_30m.tif），并写入与配置一致的标准 RGBA 色彩映射表。

3. train_predict:
   - 串联模型训练、模型文件序列化（joblib）、训练审计 JSON 记录与全景栅格推理预测。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

import joblib
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from sklearn.ensemble import RandomForestClassifier

from rs_urban.contracts import ClassificationData, ProjectContext


def hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    """将十六进制颜色字符串（例如 '#D95F02'）转换为 8 位 RGBA 四元组。

    Args:
        hex_color (str): 形如 '#RRGGBB' 或 'RRGGBB' 的颜色代码。

    Returns:
        tuple[int, int, int, int]: 对应的 (R, G, B, 255) 整数元组。
    """
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (r, g, b, 255)


def build_colormap(
    classes_config: list[dict[str, Any]],
    nodata_code: int = 0,
) -> dict[int, tuple[int, int, int, int]]:
    """根据地类配置列表构建兼容 Rasterio / GDAL 的色彩映射字典（Color Table）。

    Args:
        classes_config (list[dict[str, Any]]): 包含 code 和 color 字段的地类字典列表。
        nodata_code (int, optional): 无效像元编码。默认为 0（映射为全透明）。

    Returns:
        dict[int, tuple[int, int, int, int]]: 像元值到 RGBA 四元组的映射字典。
    """
    colormap: dict[int, tuple[int, int, int, int]] = {nodata_code: (0, 0, 0, 0)}
    for cls in classes_config:
        code = int(cls["code"])
        color_hex = cls["color"]
        colormap[code] = hex_to_rgba(color_hex)
    return colormap


def iter_windows(width: int, height: int, chunk_size: int = 512) -> Iterator[Window]:
    """生成覆盖整个二维栅格空间范围的固定大小矩形分块窗口迭代器。

    有效避免大尺寸高维遥感栅格一次性载入内存导致 OOM（内存溢出）。

    Args:
        width (int): 栅格总列数（宽度）。
        height (int): 栅格总行数（高度）。
        chunk_size (int, optional): 分块边长（像元数）。默认为 512。

    Yields:
        Iterator[Window]: rasterio.windows.Window 分块窗口对象。
    """
    for y in range(0, height, chunk_size):
        h = min(chunk_size, height - y)
        for x in range(0, width, chunk_size):
            w = min(chunk_size, width - x)
            yield Window(x, y, w, h)


def train_classifier(
    train_csv_path: Path,
    split_json_path: Path,
    config: dict[str, Any],
    year: int,
) -> tuple[RandomForestClassifier, dict[str, Any], dict[str, Any]]:
    """仅基于训练样本集 train.csv 训练随机森林分类器，杜绝接触留出测试集。

    训练规范与流程：
    1. 校验输入文件存在性与字段完整性；
    2. 按 config["features"]["order"] 严格提取 10 项特征列，构建训练特征矩阵 X 与目标地类 y；
    3. 读取模型超参数（树木棵数、叶节点最小样本数、最大特征数比例、类别权重、并发线程数等），实例化 RandomForestClassifier；
    4. 拟合分类器模型；
    5. 读取或计算划分元数据 split.json 与 train.csv 的 SHA256 哈希值；
    6. 组装标准模型保存结构 model_dict 及训练审计记录 report_dict。

    Args:
        train_csv_path (Path): 训练样本 train.csv 路径。
        split_json_path (Path): 划分元数据 split.json 路径。
        config (dict[str, Any]): 项目全局配置字典。
        year (int): 目标训练年份。

    Returns:
        tuple[RandomForestClassifier, dict[str, Any], dict[str, Any]]:
            - 训练好的随机森林分类器实例；
            - 待保存的模型封装字典；
            - 训练过程元数据审计字典。

    Raises:
        FileNotFoundError: 当输入文件缺失时抛出。
        KeyError: 当必要字段或配置缺失时抛出。
        ValueError: 当配置了不支持的分类算法时抛出。
    """
    if not train_csv_path.exists():
        raise FileNotFoundError(f"Training dataset not found: {train_csv_path}")
    if not split_json_path.exists():
        raise FileNotFoundError(f"Split metadata not found: {split_json_path}")

    # 读取训练样本表格
    train_df = pd.read_csv(train_csv_path)

    # 校验是否包含地类目标标签列
    if "class_id" not in train_df.columns:
        raise KeyError(f"Missing required 'class_id' column in {train_csv_path}")

    # 校验特征列完整性
    feature_order = list(config["features"]["order"])
    missing_features = [col for col in feature_order if col not in train_df.columns]
    if missing_features:
        raise KeyError(
            f"Training dataset {train_csv_path} is missing configured feature columns: {missing_features}"
        )

    # 提取特征矩阵 X 和目标地类标签 y
    X = train_df[feature_order].to_numpy(dtype=np.float32)
    y = train_df["class_id"].to_numpy(dtype=np.int32)

    # 读取模型配置
    model_cfg = config.get("model", {})
    algorithm = model_cfg.get("algorithm", "random_forest")
    if algorithm != "random_forest":
        raise ValueError(
            f"Unsupported algorithm '{algorithm}' in config. Only 'random_forest' is supported."
        )

    random_seed = config.get("random_seed", 42)
    n_estimators = model_cfg.get("n_estimators", 300)
    min_samples_leaf = model_cfg.get("min_samples_leaf", 2)
    max_features = model_cfg.get("max_features", "sqrt")
    class_weight = model_cfg.get("class_weight", "balanced_subsample")
    n_jobs = model_cfg.get("n_jobs", -1)

    # 实例化并拟合随机森林分类器
    estimator = RandomForestClassifier(
        n_estimators=n_estimators,
        min_samples_leaf=min_samples_leaf,
        max_features=max_features,
        class_weight=class_weight,
        n_jobs=n_jobs,
        random_state=random_seed,
    )
    estimator.fit(X, y)

    # 提取与计算哈希签名
    with open(split_json_path, "r", encoding="utf-8") as f:
        split_meta_obj = json.load(f)
    split_sha256 = split_meta_obj.get("split_sha256")
    if not split_sha256:
        split_bytes = split_json_path.read_bytes()
        split_sha256 = hashlib.sha256(split_bytes).hexdigest()

    train_bytes = train_csv_path.read_bytes()
    train_sha256 = hashlib.sha256(train_bytes).hexdigest()

    # 获取地类编码集合
    configured_classes = [int(c["code"]) for c in config.get("classes", [])]
    class_codes = configured_classes if configured_classes else sorted(int(c) for c in np.unique(y))

    # 按照契约声明封装模型字典
    model_dict: dict[str, Any] = {
        "estimator": estimator,
        "feature_names": feature_order,
        "class_codes": class_codes,
        "year": int(year),
        "config": model_cfg,
        "split_sha256": split_sha256,
    }

    # 统计各类训练样本像元数与独立地块组数
    pixels_per_class = {
        int(k): int(v) for k, v in train_df["class_id"].value_counts().sort_index().items()
    }
    groups_per_class: dict[int, int] = {}
    if "group_id" in train_df.columns:
        for cls_code in sorted(train_df["class_id"].unique()):
            groups_per_class[int(cls_code)] = int(
                train_df[train_df["class_id"] == cls_code]["group_id"].nunique()
            )
        num_groups = int(train_df["group_id"].nunique())
    else:
        num_groups = 0

    # 组装训练报告元数据
    report_dict: dict[str, Any] = {
        "schema_version": 1,
        "year": int(year),
        "num_training_groups": num_groups,
        "num_training_pixels": int(len(train_df)),
        "pixels_per_class": pixels_per_class,
        "groups_per_class": groups_per_class,
        "feature_names": feature_order,
        "model_parameters": {
            "algorithm": algorithm,
            "n_estimators": n_estimators,
            "min_samples_leaf": min_samples_leaf,
            "max_features": max_features,
            "class_weight": class_weight,
            "n_jobs": n_jobs,
            "random_state": random_seed,
        },
        "split_sha256": split_sha256,
        "train_csv_sha256": train_sha256,
        "train_input_summary": {
            "train_csv": str(train_csv_path),
            "split_json": str(split_json_path),
        },
    }

    return estimator, model_dict, report_dict


def predict_raster_windowed(
    features_path: Path,
    valid_features_path: Path,
    output_raw_path: Path,
    estimator: RandomForestClassifier,
    feature_names: list[str],
    classes_config: list[dict[str, Any]],
    float_nodata: float = -9999.0,
    class_nodata: int = 0,
    chunk_size: int = 512,
) -> None:
    """采用滑动窗口机制逐块对 10 波段特征栅格执行模型推理，生成分类 Byte 栅格并写入色彩映射表。

    空间一致性核查：
    - 检查 features_path 与 valid_features_path 的坐标系、仿射变换及尺寸是否严格一致；
    - 检查波段数量与波段描述是否与配置的 feature_names 一致。

    Args:
        features_path (Path): 10 波段特征栅格 GeoTIFF 路径。
        valid_features_path (Path): 特征有效掩膜 GeoTIFF 路径。
        output_raw_path (Path): 输出的原始分类栅格路径。
        estimator (RandomForestClassifier): 训练好的随机森林模型。
        feature_names (list[str]): 特征波段名称列表。
        classes_config (list[dict[str, Any]]): 地类配置列表（用于构建色表）。
        float_nodata (float, optional): 浮点型无效值。默认为 -9999.0。
        class_nodata (int, optional): 分类结果中的无效值编码。默认为 0。
        chunk_size (int, optional): 分块边长。默认为 512。

    Raises:
        FileNotFoundError: 当栅格文件缺失时抛出。
        ValueError: 当空间网格参数不匹配或波段描述与预期不符时抛出。
    """
    if not features_path.exists():
        raise FileNotFoundError(f"Features raster not found: {features_path}")
    if not valid_features_path.exists():
        raise FileNotFoundError(f"Valid features raster not found: {valid_features_path}")

    with rasterio.open(features_path) as feat_src, rasterio.open(valid_features_path) as valid_src:
        # 核查空间参考与栅格规格一致性
        if feat_src.crs != valid_src.crs:
            raise ValueError(
                f"CRS mismatch: features ({feat_src.crs}) vs valid_features ({valid_src.crs})"
            )
        if feat_src.transform != valid_src.transform:
            raise ValueError(
                f"Transform mismatch: features ({feat_src.transform}) vs valid_features ({valid_src.transform})"
            )
        if (feat_src.width, feat_src.height) != (valid_src.width, valid_src.height):
            raise ValueError(
                f"Dimension mismatch: features ({feat_src.width}x{feat_src.height}) "
                f"vs valid_features ({valid_src.width}x{valid_src.height})"
            )

        # 核对波段描述顺序
        if feat_src.descriptions and all(feat_src.descriptions):
            descriptions_list = list(feat_src.descriptions)
            if descriptions_list != feature_names:
                raise ValueError(
                    f"Band descriptions {descriptions_list} in {features_path} "
                    f"do not match expected feature order {feature_names}"
                )

        if feat_src.count != len(feature_names):
            raise ValueError(
                f"Band count mismatch: features raster has {feat_src.count} bands, "
                f"expected {len(feature_names)} ({feature_names})"
            )

        output_raw_path.parent.mkdir(parents=True, exist_ok=True)

        # 配置输出栅格元数据（单波段、Byte、Deflate压缩、分块瓦片存储）
        profile = {
            "driver": "GTiff",
            "count": 1,
            "dtype": rasterio.uint8,
            "nodata": class_nodata,
            "crs": feat_src.crs,
            "transform": feat_src.transform,
            "width": feat_src.width,
            "height": feat_src.height,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }

        with rasterio.open(output_raw_path, "w", **profile) as out_dst:
            # 窗口滑动迭代推理
            for window in iter_windows(feat_src.width, feat_src.height, chunk_size=chunk_size):
                feat_block = feat_src.read(window=window)  # 形状: (count, win_h, win_w)
                valid_block = valid_src.read(1, window=window)  # 形状: (win_h, win_w)

                # 识别当前窗口内的有效像元
                valid_mask = (valid_block == 1)
                for b_idx in range(feat_block.shape[0]):
                    band_slice = feat_block[b_idx]
                    valid_mask &= np.isfinite(band_slice) & (band_slice != float_nodata)

                out_block = np.full((window.height, window.width), class_nodata, dtype=np.uint8)

                # 若窗口内存在有效像元，转置后批量预测
                if np.any(valid_mask):
                    X_window = feat_block[:, valid_mask].T
                    preds = estimator.predict(X_window)
                    out_block[valid_mask] = preds.astype(np.uint8)

                out_dst.write(out_block, 1, window=window)

            # 写入色彩映射表
            colormap = build_colormap(classes_config=classes_config, nodata_code=class_nodata)
            out_dst.write_colormap(1, colormap)


def train_predict(ctx: ProjectContext, year: int) -> ClassificationData:
    """执行阶段 P1-C 的随机森林模型训练与全景栅格推理完整流水线。

    Args:
        ctx (ProjectContext): 项目运行上下文。
        year (int): 目标年份（如 1992 或 2021）。

    Returns:
        ClassificationData: 包含模型保存路径和预测栅格路径的数据契约对象。

    Raises:
        ValueError: 当指定的年份不在配置声明中时抛出。
    """
    if year not in ctx.config.get("years", [1992, 2021]):
        raise ValueError(
            f"Requested year {year} is not declared in project.toml years: {ctx.config.get('years')}"
        )

    # 标准输入路径
    train_csv = ctx.data / "processed" / "samples" / str(year) / "train.csv"
    split_json = ctx.data / "processed" / "samples" / str(year) / "split.json"
    features_raster = ctx.data / "processed" / str(year) / "features_30m.tif"
    valid_features_raster = ctx.data / "processed" / str(year) / "valid_features_30m.tif"

    # 标准输出路径
    model_path = ctx.outputs / "models" / str(year) / "rf.joblib"
    raw_raster = ctx.outputs / "rasters" / f"lulc_{year}_raw_30m.tif"
    report_json = ctx.reports / "accuracy" / f"training_{year}.json"

    # 1. 严格使用训练集训练模型
    estimator, model_dict, report_dict = train_classifier(
        train_csv_path=train_csv,
        split_json_path=split_json,
        config=ctx.config,
        year=year,
    )

    # 2. 持久化保存模型包
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model_dict, model_path)

    # 格式化相对路径并记录审计报告
    def fmt_path(p: Path) -> str:
        try:
            return str(p.relative_to(ctx.root))
        except ValueError:
            return str(p)

    report_dict["train_input_summary"]["features_raster"] = fmt_path(features_raster)
    report_dict["train_input_summary"]["valid_features_raster"] = fmt_path(valid_features_raster)

    report_json.parent.mkdir(parents=True, exist_ok=True)
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    # 3. 滑动窗口预测全景分类栅格
    feature_names = list(ctx.config["features"]["order"])
    classes_config = list(ctx.config.get("classes", []))
    float_nodata = float(ctx.config.get("float_nodata", -9999.0))
    class_nodata = int(ctx.config.get("class_nodata", 0))

    predict_raster_windowed(
        features_path=features_raster,
        valid_features_path=valid_features_raster,
        output_raw_path=raw_raster,
        estimator=estimator,
        feature_names=feature_names,
        classes_config=classes_config,
        float_nodata=float_nodata,
        class_nodata=class_nodata,
    )

    return ClassificationData(year=int(year), model=model_path, raw=raw_raster)
