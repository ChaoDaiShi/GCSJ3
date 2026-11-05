"""后处理平滑、矢量化制图与独立精度评价命令行入口脚本（P1-D）。

步骤 04（04_evaluate.py）：
1. 分类后处理：采用 GDAL SieveFilter 滤除细碎斑块（< 4 个像元），消除“椒盐噪声”并严格保持边界与 NoData 区域；
2. 矢量化导出：将最终分类栅格转为多边形矢量，裁剪至新都区法定行政边界，输出带 UTF-8 编码的 ESRI Shapefile 成果；
3. 独立精度评价：严格基于空间独立的留出样本集（holdout.csv）统计原始与后处理后分类结果的 5x5 混淆矩阵；
4. 计算总体精度（OA）、各类精确率（Precision）、召回率（Recall）及 F1 分数，并硬性核验准入门槛（OA > 0.75）。

使用示例：
  python src/04_evaluate.py --config configs/project.toml --env-file .env --year 1992
  python src/04_evaluate.py --config configs/project.toml --env-file .env --year 2021
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 将根目录和 src 目录添加到模块搜索路径中
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rs_urban.config import add_common_args, load_context
from rs_urban.evaluate import finalize_evaluate


def build_parser() -> argparse.ArgumentParser:
    """构建后处理与精度评估命令的参数解析器。

    Returns:
        argparse.ArgumentParser: 命令行解析器。
    """
    parser = argparse.ArgumentParser(
        description="应用小斑块筛分滤波、矢量化裁剪以及独立验证集精度评定工具。"
    )
    # 添加标准通用参数 --config 和 --env-file
    add_common_args(parser)
    # 添加目标年份参数
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="待评价的目标年份（例如 1992 或 2021）。",
    )
    return parser


def main() -> int:
    """精度评价与后处理流水线的主入口函数。

    Returns:
        int: 运行状态码，0 表示成功，1 表示发生异常。
    """
    parser = build_parser()
    args = parser.parse_args()

    # 初始化配置上下文
    ctx = load_context(args.config, args.env_file)

    try:
        print(f"[INFO] Finalizing and evaluating classification for year {args.year}...")
        # 触发执行滤波、矢量化与混淆矩阵精度核算
        eval_data = finalize_evaluate(ctx, args.year)
        print(f"[SUCCESS] Final raster: {eval_data.final}")
        print(f"[SUCCESS] Shapefile: {eval_data.vectors}")
        print(f"[SUCCESS] Accuracy report: {eval_data.report}")
        print(f"[METRIC] Raw OA: {eval_data.oa_raw:.4f}, Final OA: {eval_data.oa_final:.4f}")
        return 0

    except Exception as e:
        print(f"[ERROR] Evaluation failed for year {args.year}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
