"""样本处理与多波段特征提取命令行入口脚本（P1-B）。

步骤 02（02_samples.py）：
1. 基于预处理后的 6 波段地表反射率影像计算 4 项关键遥感光谱指数（NDVI、NDBI、MNDWI、BSI），构建 10 波段特征栅格；
2. 依据空间地块单元（group_id）与地类编码（class_id）执行分层分组随机划分（GroupShuffleSplit）；
3. 严格提取训练集（train.csv）与独立留出验证集（holdout.csv），杜绝空间自相关导致的样本泄露；
4. 冻结划分元数据并生成独立性检验审计报告。

使用示例：
  python src/02_samples.py --config configs/project.toml --env-file .env --year 1992
  python src/02_samples.py --config configs/project.toml --env-file .env --year 2021
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 将源码目录 src 添加至系统模块搜索路径
repo_root = Path(__file__).resolve().parents[1]
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rs_urban.config import add_common_args, load_context
from rs_urban.samples import build_samples


def parse_args() -> argparse.Namespace:
    """解析样本提取与特征构建任务的命令行参数。

    Returns:
        argparse.Namespace: 包含配置文件路径、环境变量文件路径及目标年份的参数命名空间。
    """
    parser = argparse.ArgumentParser(
        description="提取 10 波段光谱/指数特征并按空间组分层抽取训练与留出样本集。"
    )
    # 添加通用配置参数：--config 与 --env-file
    add_common_args(parser)
    # 添加目标年份参数，限定为 1992 或 2021
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        choices=[1992, 2021],
        help="目标分析年份（1992 或 2021）。",
    )
    return parser.parse_args()


def main() -> None:
    """样本处理流程入口函数。

    加载项目上下文，调用 build_samples 完成特征栅格合成与样本集分组抽取，并打印输出结果路径清单。
    """
    args = parse_args()
    ctx = load_context(args.config, args.env_file)
    print(f"Executing sample processing pipeline for year {args.year}...")

    # 执行端到端样本处理流水线
    sample_data = build_samples(ctx, args.year)

    # 汇报输出生成的文件路径
    print(f"Sample processing completed successfully for year {args.year}:")
    print(f"  Features 30m raster:       {sample_data.features}")
    print(f"  Valid features raster:     {sample_data.valid_features}")
    print(f"  Training samples CSV:      {sample_data.train}")
    print(f"  Holdout samples CSV:       {sample_data.holdout}")
    print(f"  Split metadata:            {sample_data.split}")


if __name__ == "__main__":
    main()
