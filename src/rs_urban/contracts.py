"""公共数据契约与流程间传输数据结构定义模块。

本模块声明了各个并发与串行处理流水线之间传递的核心数据容器（Data Classes），
保证接口边界清晰、类型明确、属性统一。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProjectContext:
    """全局项目运行上下文环境容器。

    Attributes:
        root (Path): 项目仓库绝对根路径。
        data (Path): 数据根目录（对应 RS_DATA_ROOT）。
        outputs (Path): 成果输出根目录（对应 RS_OUTPUT_ROOT）。
        reports (Path): 分析与审计报告输出根目录（对应 RS_REPORT_ROOT）。
        scratch (Path): 临时与缓存数据存储目录（对应 RS_SCRATCH_ROOT）。
        config (dict[str, Any]): 自 project.toml 加载的全局科学计算与工程参数字典。
    """
    root: Path
    data: Path
    outputs: Path
    reports: Path
    scratch: Path
    config: dict[str, Any]


@dataclass
class PreparedData:
    """阶段 P1-A（预处理）输出的数据产物契约。

    Attributes:
        year (int): 目标预处理年份（如 1992 或 2021）。
        sr (Path): 经过辐射定标、QA 去云掩膜并重采样至标准 30m 网格的地表反射率多波段 GeoTIFF 路径。
        valid_sr (Path): 地表反射率有效像元掩膜栅格路径（1=有效，0=研究区内无效，255=研究区外）。
        grid (Path): 30m 标准网格规格 JSON 文件路径。
        boundaries (Path): 包含法定研究区边界和街镇边界的标准 GeoPackage 文件路径。
    """
    year: int
    sr: Path
    valid_sr: Path
    grid: Path
    boundaries: Path


@dataclass
class SampleData:
    """阶段 P1-B（特征与样本提取）输出的数据产物契约。

    Attributes:
        year (int): 目标处理年份。
        features (Path): 包含 6 个地表反射率波段及 4 个光谱指数（NDVI、NDBI、MNDWI、BSI）的 10 波段 30m 特征栅格路径。
        valid_features (Path): 10 波段特征栅格的综合有效掩膜路径（排除分母为 0 与无效像元）。
        train (Path): 训练集像元点特征 CSV 文件路径（含地类标签与各波段特征值）。
        holdout (Path): 空间独立留出验证集像元点特征 CSV 文件路径。
        split (Path): 空间分层分组抽取元数据与哈希校验记录 JSON 文件路径。
    """
    year: int
    features: Path
    valid_features: Path
    train: Path
    holdout: Path
    split: Path


@dataclass
class ClassificationData:
    """阶段 P1-C（模型训练与推理）输出的数据产物契约。

    Attributes:
        year (int): 目标分类年份。
        model (Path): 持久化的随机森林模型字典文件路径（.joblib）。
        raw (Path): 原始未滤波的全景预测土地利用/覆盖分类栅格路径（lulc_{year}_raw_30m.tif）。
    """
    year: int
    model: Path
    raw: Path


@dataclass
class EvaluationData:
    """阶段 P1-D（后处理与独立精度评价）输出的数据产物契约。

    Attributes:
        year (int): 评估年份。
        final (Path): 经 Sieve 滤波平滑后剔除孤立斑块的最终分类栅格路径（lulc_{year}_final_30m.tif）。
        vectors (Path): 经行政边界精确裁剪后的土地覆盖多边形矢量文件路径（ESRI Shapefile 格式）。
        report (Path): 独立精度评定报告文件路径（Markdown 格式）。
        oa_raw (float): 原始预测栅格在独立留出集上的总体精度（Overall Accuracy）。
        oa_final (float): 最终平滑栅格在独立留出集上的总体精度（Overall Accuracy）。
    """
    year: int
    final: Path
    vectors: Path
    report: Path
    oa_raw: float
    oa_final: float


@dataclass
class ChangeData:
    """阶段 P1-E（城市扩张与时空变化分析）输出的数据产物契约。

    Attributes:
        raster (Path): 四分类城市建设用地时空转移变化栅格路径（change_1992_2021_30m.tif）。
        vectors (Path): 变化区域融合多边形矢量图层文件路径（urban_change.gpkg）。
        townships (Path): 街镇级土地变化与建设用地年均扩张速率统计表路径（CSV 格式）。
        district (Path): 全区总计土地变化与扩张强度统计表路径（CSV 格式）。
    """
    raster: Path
    vectors: Path
    townships: Path
    district: Path
