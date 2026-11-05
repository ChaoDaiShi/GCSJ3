"""城市扩张与时空演变分析命令行入口脚本（05_analyze.py）。

步骤 05（P1-E）：
1. 建立 1992 年与 2021 年最终分类栅格的共同有效观测掩膜（valid_common），排查云阴影与无效像元干扰；
2. 构建 4 类城市建设用地动态转移栅格（持续建设、新增建设、减少建设、持续非建设）并输出带标准色表的 GeoTIFF；
3. 将变化栅格矢量化为 GeoPackage 图层，并与 2021 年街镇行政区划矢量执行空间叠加（Spatial Overlay）；
4. 统计区级与街镇级建设用地规模、年均扩张速率、扩张强度指标，并严格执行“全区总量 = 各街镇分量之和”的面积平衡核验。

使用示例：
  python src/05_analyze.py --config configs/project.toml --env-file .env
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 确保脚本运行时能直接定位到 src 目录下的 rs_urban 模块包
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rs_urban.config import add_common_args, load_context
from rs_urban.analyze import analyze_change


def main(argv: list[str] | None = None) -> int:
    """变化分析主流程入口。

    Args:
        argv: 命令行参数列表，若为 None 则从命令行解析。

    Returns:
        int: 执行状态码，0 表示正常完成。
    """
    parser = argparse.ArgumentParser(
        description="分析 1992 年至 2021 年间成都市新都区的城市扩张进程与地类转移时空特征。"
    )
    # 添加标准通用参数 --config 和 --env-file
    add_common_args(parser)

    args = parser.parse_args(argv)

    # 加载统一配置上下文
    ctx = load_context(config_path=args.config, env_file=args.env_file)
    # 调用核心变化分析流程
    result = analyze_change(ctx=ctx)

    print("Urban change analysis completed successfully:")
    print(f"  Change raster: {result.raster}")
    print(f"  Change vectors: {result.vectors}")
    print(f"  Township statistics: {result.townships}")
    print(f"  District statistics: {result.district}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
