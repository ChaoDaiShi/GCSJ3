"""配置加载与 ProjectContext 构建模块。

统一管理所有子任务的参数解析与路径定位，规范如下：
1. 通用参数约定：
   所有 5 个处理脚本均支持两个通用参数：
     --config <path>    project.toml 配置文件路径（默认为仓库根目录下的 configs/project.toml）
     --env-file <path>  .env 环境配置文件路径（默认为仓库根目录下的 .env）

2. 专用参数规范：
   - 01_preprocess.py: --config, --env-file, --step (boundaries|surface|pansharpen), --year (1992|2021)
   - 02_samples.py:    --config, --env-file, --year (1992|2021)
   - 03_classify.py:   --config, --env-file, --year (1992|2021)
   - 04_evaluate.py:   --config, --env-file, --year (1992|2021)
   - 05_analyze.py:    --config, --env-file

3. 环境变量优先级机制：
   系统环境变量 (os.environ) > .env 文件配置 > .env.example 默认声明。
   所有相对路径均统一解析为基于仓库根目录的绝对路径，确保在不同工作目录下执行的一致性。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any
import tomllib
from dotenv import dotenv_values

from rs_urban.contracts import ProjectContext

# 在 .env.example 中声明的标准环境变量默认值
DEFAULT_ENV_VARS = {
    "RS_DATA_ROOT": "./data",
    "RS_OUTPUT_ROOT": "./outputs",
    "RS_REPORT_ROOT": "./reports",
    "RS_SCRATCH_ROOT": "./.cache/processing",
    "GDAL_CACHEMAX": "512",
}


def get_repo_root() -> Path:
    """获取代码仓库的绝对根路径。

    Returns:
        Path: 仓库根目录的 Path 对象。
    """
    return Path(__file__).resolve().parents[2]


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """向 ArgumentParser 解析器注册通用的 --config 与 --env-file 命令行选项。

    Args:
        parser (argparse.ArgumentParser): 待配置的目标参数解析器。
    """
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/project.toml"),
        help="科学计算与工程配置文件 project.toml 路径（支持绝对路径或相对仓库根目录的路径）",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="环境变量配置文件 .env 路径（支持绝对路径或相对仓库根目录的路径）",
    )


def load_context(
    config_path: Path,
    env_file: Path,
    root_dir: Path | None = None,
) -> ProjectContext:
    """加载 TOML 配置文件与环境变量，构建统一的 ProjectContext 项目上下文容器。

    环境变量解析优先级：
      1. 当前进程系统环境变量 (os.environ)；
      2. env_file (.env) 中指定的键值对；
      3. 系统内建的兜底默认值 (DEFAULT_ENV_VARS)。

    所有相对路径统一相对于仓库根路径 (root) 进行解析转换，避免在不同当前工作目录（CWD）下调用时产生歧义。

    Args:
        config_path (Path): project.toml 配置文件路径。
        env_file (Path): .env 环境配置文件路径。
        root_dir (Path | None, optional): 显式指定的根目录。若为 None 则自动定位仓库根目录。

    Returns:
        ProjectContext: 组装完毕的全局项目上下文对象。
    """
    # 确定项目仓库根路径
    root = (Path(root_dir).resolve() if root_dir is not None else get_repo_root())

    # 解析 config_path：若为相对路径，则绑定到根目录
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = (root / config_path).resolve()
    else:
        config_path = config_path.resolve()

    # 解析 env_file：若为相对路径，则绑定到根目录
    env_file = Path(env_file)
    if not env_file.is_absolute():
        env_file = (root / env_file).resolve()
    else:
        env_file = env_file.resolve()

    # 从 .env 文件中读取键值对（若文件存在）
    file_vars: dict[str, str] = {}
    if env_file.exists():
        parsed = dotenv_values(env_file)
        file_vars = {k: v for k, v in parsed.items() if v is not None}

    # 按优先级逐项确定环境变量的值
    resolved_env: dict[str, str] = {}
    for key, default_val in DEFAULT_ENV_VARS.items():
        if key in os.environ and os.environ[key] != "":
            resolved_env[key] = os.environ[key]
        elif key in file_vars and file_vars[key] != "":
            resolved_env[key] = file_vars[key]
        else:
            resolved_env[key] = default_val

    # 内部辅助函数：将路径字符串转换为相对于仓库根目录的绝对 Path
    def resolve_path(val: str) -> Path:
        p = Path(val)
        return (root / p).resolve() if not p.is_absolute() else p.resolve()

    # 计算出核心目录的绝对路径
    data_path = resolve_path(resolved_env["RS_DATA_ROOT"])
    outputs_path = resolve_path(resolved_env["RS_OUTPUT_ROOT"])
    reports_path = resolve_path(resolved_env["RS_REPORT_ROOT"])
    scratch_path = resolve_path(resolved_env["RS_SCRATCH_ROOT"])
    gdal_cachemax = resolved_env["GDAL_CACHEMAX"]

    # 将解析出的路径与配置写回当前进程环境变量，以便底层的 GDAL/PROJ 及外部子进程统一读取
    os.environ["RS_DATA_ROOT"] = str(data_path)
    os.environ["RS_OUTPUT_ROOT"] = str(outputs_path)
    os.environ["RS_REPORT_ROOT"] = str(reports_path)
    os.environ["RS_SCRATCH_ROOT"] = str(scratch_path)
    os.environ["GDAL_CACHEMAX"] = str(gdal_cachemax)
    os.environ["CPL_TMPDIR"] = str(scratch_path)

    # 确保缓存工作目录存在
    scratch_path.mkdir(parents=True, exist_ok=True)

    # 以二进制只读方式加载 TOML 配置文件
    with open(config_path, "rb") as f:
        config_data: dict[str, Any] = tomllib.load(f)

    return ProjectContext(
        root=root,
        data=data_path,
        outputs=outputs_path,
        reports=reports_path,
        scratch=scratch_path,
        config=config_data,
    )
