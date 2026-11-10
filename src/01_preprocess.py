"""预处理阶段（P1-A）的命令行入口脚本。

本脚本负责解析命令行参数并调度执行遥感影像预处理与矢量边界制备任务，包括：
1. 边界与网格制备（--step boundaries）：提取县界与街镇边界，构建标准 30m 与 15m 分析网格及研究区二值掩膜；
2. 地表反射率预处理（--step surface --year <year>）：处理指定年份的 Landsat Level-2 影像，执行 QA 掩膜、辐射定标与重采样；
3. 全色锐化增强（--step pansharpen）：针对 2021 年 Landsat 8 影像执行 15m Gram-Schmidt 融合（仅供制图与可视化）。

使用示例：
  python src/01_preprocess.py --config configs/project.toml --env-file .env --step boundaries
  python src/01_preprocess.py --config configs/project.toml --env-file .env --step surface --year 1992
  python src/01_preprocess.py --config configs/project.toml --env-file .env --step surface --year 2021
  python src/01_preprocess.py --config configs/project.toml --env-file .env --step pansharpen
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 将仓库根目录及 src 目录加入 Python 搜索路径，确保直接执行脚本时能正确导入 rs_urban 模块
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rs_urban.config import add_common_args, load_context
from rs_urban.preprocess import (
    build_feature_stack,
    pansharpen_2021,
    prepare_boundaries,
    preprocess_year,
)


def build_parser() -> argparse.ArgumentParser:
    """构建预处理阶段的命令行参数解析器。

    Returns:
        argparse.ArgumentParser: 配置好通用参数与预处理专用参数的解析器对象。
    """
    parser = argparse.ArgumentParser(
        description="新都区城市扩张分析遥感影像与矢量边界预处理工具。"
    )
    # 添加通用配置参数：--config 与 --env-file
    add_common_args(parser)
    # 添加预处理步骤选择参数
    parser.add_argument(
        "--step",
        choices=["boundaries", "surface", "pansharpen", "features"],
        required=True,
        help="要执行的预处理步骤：'boundaries'（边界与网格制备）、'surface'（地表反射率处理）、'pansharpen'（全色锐化）、'features'（21 维特征堆栈）。",
    )
    # 添加年份参数（当步骤为 surface / features 时必填）
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="目标处理年份（当 --step 为 'surface' 或 'features' 时必填，如 1992 或 2021）。",
    )
    return parser


def main() -> int:
    """预处理主程序入口。

    负责解析命令行参数、加载项目上下文环境，并根据指定的 --step 派发执行相应的预处理子流程。

    Returns:
        int: 执行状态码，0 表示成功，1 表示发生错误。
    """
    parser = build_parser()
    args = parser.parse_args()

    # 校验依赖关系：执行 surface / features 步骤时必须提供 --year 参数
    if args.step in ("surface", "features") and args.year is None:
        parser.error(f"--year is required when --step is '{args.step}'.")

    # 根据 TOML 配置文件和 .env 文件加载全局项目上下文配置
    ctx = load_context(args.config, args.env_file)

    try:
        if args.step == "boundaries":
            # 步骤 1：处理行政区划边界与标准网格定义
            print("[INFO] Preparing standard administrative boundaries and grids...")
            gpkg = prepare_boundaries(ctx)
            print(f"[SUCCESS] Boundaries and grids prepared: {gpkg}")

        elif args.step == "surface":
            # 步骤 2：针对单期 Landsat Level-2 数据进行地表反射率定标、去云及重采样
            print(f"[INFO] Preprocessing surface reflectance for year {args.year}...")
            prepared = preprocess_year(ctx, args.year)
            print(f"[SUCCESS] Surface reflectance preprocessed for {args.year}: {prepared.sr}")

        elif args.step == "pansharpen":
            # 步骤 3：针对 2021 年数据开展 15m 分辨率全色锐化融合（用于底图标注与目视解译参考）
            print("[INFO] Performing 15m pansharpening for year 2021...")
            pan_path = pansharpen_2021(ctx)
            print(f"[SUCCESS] Pansharpened image produced: {pan_path}")

        elif args.step == "features":
            # 步骤 4：构建 21 维特征堆栈（6 波段 + 7 指数 + 6 纹理 + 高程 + 坡度）
            print(f"[INFO] Building feature stack for year {args.year}...")
            feat_path = build_feature_stack(ctx, args.year)
            print(f"[SUCCESS] Feature stack produced: {feat_path}")

        return 0

    except Exception as e:
        print(f"[ERROR] Preprocessing failed on step '{args.step}': {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
