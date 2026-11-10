"""Test suite for QGIS build_project and check_project automation (W05, W06, W21)."""

from __future__ import annotations

import json
import sys
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
SCRIPTS_DIR = REPO_ROOT / "qgis" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_project import build_project
from check_project import check_project


def test_build_project_development_mode(tmp_path: Path):
    """Verifies that build_project creates valid .qgz and manifest in development mode."""
    config_file = REPO_ROOT / "configs" / "project.toml"
    project_out = tmp_path / "xindu_test.qgz"

    report = build_project(
        config_path=config_file,
        project_path=project_out,
        mode="development",
    )

    assert report.status == "PASSED"
    assert project_out.is_file()

    manifest_file = tmp_path / "project_manifest.json"
    assert manifest_file.is_file()

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["project"] == "xindu_test.qgz"
    assert manifest["target_crs"] == "EPSG:32648"
    assert len(manifest["layouts"]) == 4


def test_check_project_inspects_built_project(tmp_path: Path):
    """Verifies that check_project independently validates the built project."""
    config_file = REPO_ROOT / "configs" / "project.toml"
    project_out = tmp_path / "xindu_test.qgz"

    # First build project
    build_project(
        config_path=config_file,
        project_path=project_out,
        mode="development",
    )

    # Now run independent check
    manifest_file = tmp_path / "project_manifest.json"
    check_rep = check_project(project_out, manifest_file)

    assert check_rep.passed is True
    assert check_rep.status == "PASSED"
    assert check_rep.failed_checks == 0
    assert any(c.check_id == "CHK_PROJ_CRS" and c.status == "PASS" for c in check_rep.checks)
    assert any(c.check_id == "CHK_PROJ_LAYOUTS" and c.status == "PASS" for c in check_rep.checks)


def test_build_project_release_blocks_when_inputs_missing(tmp_path: Path):
    """Verifies that release mode strictly blocks (BLOCKED/FAILED) if required inputs are absent."""
    config_file = REPO_ROOT / "configs" / "project.toml"
    project_out = tmp_path / "xindu_release_test.qgz"

    # 真实成果已生成时 release 模式应当放行；要验证"缺输入即拦截"，
    # 需构造一个只有 configs/ 的空仓库，让必填输入全部缺失。
    empty_repo = tmp_path / "empty_repo"
    (empty_repo / "configs").mkdir(parents=True)
    shutil.copy2(config_file, empty_repo / "configs" / "project.toml")

    report = build_project(
        config_path=empty_repo / "configs" / "project.toml",
        project_path=project_out,
        mode="release",
    )

    assert report.status in ["BLOCKED", "FAILED"]
    assert len(report.missing_inputs) > 0
