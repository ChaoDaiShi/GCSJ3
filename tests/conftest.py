"""Pytest configuration and shared test fixtures.

Only adds src/ to sys.path for test imports.
All fixtures write strictly to pytest's tmp_path temporary directory;
never connect to or mutate real data/ or outputs/ directories.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
import pytest

# Add src to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fixtures.factory import (
    create_change_fixture,
    create_feature_fixture,
    create_grouped_samples_fixture,
    create_metric_fixture,
    create_scaling_fixture,
)


@pytest.fixture(autouse=True)
def isolate_environment():
    """Preserve and restore os.environ so tests do not leak environment variables."""
    old_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(old_env)


@pytest.fixture(autouse=True)
def isolate_rs_environment(monkeypatch: pytest.MonkeyPatch):
    """Ensure unit tests do not leak RS_* environment variables into each other."""
    for key in ["RS_DATA_ROOT", "RS_OUTPUT_ROOT", "RS_REPORT_ROOT", "RS_SCRATCH_ROOT", "GDAL_CACHEMAX", "CPL_TMPDIR"]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def repo_root() -> Path:
    """Return repository root path."""
    return REPO_ROOT


@pytest.fixture
def scaling_fixture(tmp_path: Path) -> dict[str, Any]:
    """Provide scaling_fixture created in a pytest temp directory."""
    return create_scaling_fixture(tmp_path / "scaling")


@pytest.fixture
def feature_fixture(tmp_path: Path) -> dict[str, Any]:
    """Provide feature_fixture created in a pytest temp directory."""
    return create_feature_fixture(tmp_path / "feature")


@pytest.fixture
def grouped_samples_fixture(tmp_path: Path) -> dict[str, Any]:
    """Provide grouped_samples_fixture created in a pytest temp directory."""
    return create_grouped_samples_fixture(tmp_path / "samples")


@pytest.fixture
def metric_fixture(tmp_path: Path) -> dict[str, Any]:
    """Provide metric_fixture created in a pytest temp directory."""
    return create_metric_fixture(tmp_path / "metric")


@pytest.fixture
def change_fixture(tmp_path: Path) -> dict[str, Any]:
    """Provide change_fixture created in a pytest temp directory."""
    return create_change_fixture(tmp_path / "change")

# 10 维（波段 + 4 指数）配置：合成小数据没有 DEM，无法计算地形特征
TEN_DIM_FEATURES = [
    "blue", "green", "red", "nir", "swir1", "swir2",
    "ndvi", "ndbi", "mndwi", "bsi",
]


def write_ten_dim_config(repo_root: Path, dest: Path) -> Path:
    """把仓库配置复制到临时路径，并把特征清单改成 10 维（去掉纹理与地形）。

    合成测试数据缺少 DEM，直接跑 22 维会因缺少 DEM 失败；这里只改特征清单，
    其余配置（网格、缩放、类别、门槛）保持与真实工程一致。
    """
    import re

    text = (Path(repo_root) / "configs" / "project.toml").read_text(encoding="utf-8")
    order_block = "order = [" + ", ".join(f'"{n}"' for n in TEN_DIM_FEATURES) + "]"
    text = re.sub(r"(\[features\]\n(?:#[^\n]*\n)?)order = \[[^\]]*\]", r"\1" + order_block, text, count=1)
    text = re.sub(r"(\[feature_stack\]\n(?:#[^\n]*\n)?)order = \[[^\]]*\]", r"\1" + order_block, text, count=1)
    dest = Path(dest)
    dest.write_text(text, encoding="utf-8")
    return dest
