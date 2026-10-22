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
