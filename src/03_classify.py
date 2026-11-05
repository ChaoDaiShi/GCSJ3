"""随机森林土地利用与覆盖分类命令行入口脚本（03_classify.py）。

步骤 03（P1-C）：
1. 严格使用训练集样本（train.csv）训练随机森林分类模型（RandomForestClassifier），绝对禁止引入留出集样本；
2. 记录模型训练超参数、特征重要度及训练集样本分布特征并持久化为模型文件与元数据报告；
3. 采用滑动窗口分块流式预测整景 10 波段特征栅格，生成原始分类栅格（lulc_{year}_raw_30m.tif）并写入标准色彩映射表。

使用示例：
  python src/03_classify.py --config configs/project.toml --env-file .env --year 1992
  python src/03_classify.py --config configs/project.toml --env-file .env --year 2021
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 确保脚本被直接调用时将 src 路径添加至模块搜索路径中
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rs_urban.config import add_common_args, load_context
from rs_urban.classify import train_predict


def main(argv: list[str] | None = None) -> int:
    """分类任务执行入口。

    Args:
        argv: 可选的命令行参数列表，若为 None 则从 sys.argv 读取。

    Returns:
        int: 退出状态码，0 表示正常完成。
    """
    parser = argparse.ArgumentParser(
        description="训练随机森林分类器并基于滑动窗口预测整景原始土地利用/覆盖（LULC）栅格。"
    )
    # 添加标准通用参数 --config 和 --env-file
    add_common_args(parser)
    # 添加目标年份参数
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="待分类的目标年份（例如 1992 或 2021）",
    )

    args = parser.parse_args(argv)

    # 加载项目全局上下文对象
    ctx = load_context(config_path=args.config, env_file=args.env_file)
    # 调用分类核心流水线：模型训练与整景推理
    result = train_predict(ctx=ctx, year=args.year)

    print(f"Classification completed successfully for year {result.year}")
    print(f"  Model saved to: {result.model}")
    print(f"  Raw raster saved to: {result.raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
