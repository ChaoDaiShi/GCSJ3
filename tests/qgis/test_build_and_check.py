"""Test suite for QGIS build_project and check_project automation (W05, W06, W21)."""

from __future__ import annotations

import json
import sys
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

    # In clean repo without real raster outputs generated, release mode must block
    report = build_project(
        config_path=config_file,
        project_path=project_out,
        mode="release",
    )

    # Since outputs/rasters/lulc_1992_final_30m.tif etc. do not exist on disk,
    # release mode MUST report BLOCKED and list missing inputs per contract!
    assert report.status in ["BLOCKED", "FAILED"]
    assert len(report.missing_inputs) > 0
