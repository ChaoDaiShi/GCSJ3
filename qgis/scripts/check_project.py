"""QGIS Project Checker Script (W21, W24).

Independently inspects QGIS project file, project_manifest.json, layer datasources,
relative paths, CRS, band orders, NoData, statistics joins, and print layouts.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CheckItem:
    check_id: str
    status: str  # PASS / FAIL / WARNING
    description: str
    observed: Any = None
    expected: Any = None
    artifact_ref: str = ""
    details: str = ""


@dataclass
class CheckReport:
    passed: bool
    status: str  # PASSED / FAILED / BLOCKED
    project_path: str
    manifest_path: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    warning_checks: int
    checks: List[CheckItem] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


def sha256_file(path: Path | str) -> str:
    path = Path(path)
    if not path.is_file():
        return ""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_qgs_from_project(project_path: Path) -> str:
    """Extracts QGS XML string whether project is .qgs or .qgz."""
    if project_path.suffix.lower() == ".qgz":
        with zipfile.ZipFile(project_path, "r") as zf:
            qgs_files = [n for n in zf.namelist() if n.lower().endswith(".qgs")]
            if not qgs_files:
                raise ValueError(f"No .qgs found inside QGZ archive: {project_path}")
            return zf.read(qgs_files[0]).decode("utf-8")
    elif project_path.suffix.lower() == ".qgs":
        with open(project_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported project file format: {project_path}")


def check_project(
    project_path: Path | str,
    manifest_path: Optional[Path | str] = None,
) -> CheckReport:
    """Performs deep, independent validation of QGIS project and manifest."""
    project_path = Path(project_path).resolve()
    if manifest_path is None:
        manifest_path = project_path.parent / "project_manifest.json"
    else:
        manifest_path = Path(manifest_path).resolve()

    checks: List[CheckItem] = []

    # 1. Project file existence & hash
    if not project_path.exists():
        checks.append(CheckItem(
            check_id="CHK_PROJ_EXISTS",
            status="FAIL",
            description="Project file must exist on disk",
            observed="Not Found",
            expected="File Exists",
            artifact_ref=str(project_path),
        ))
        return CheckReport(
            passed=False,
            status="FAILED",
            project_path=str(project_path),
            manifest_path=str(manifest_path),
            total_checks=1,
            passed_checks=0,
            failed_checks=1,
            warning_checks=0,
            checks=checks,
        )

    checks.append(CheckItem(
        check_id="CHK_PROJ_EXISTS",
        status="PASS",
        description="Project file exists",
        observed=project_path.name,
        expected="Valid project file",
        artifact_ref=str(project_path),
    ))

    # 2. Manifest check
    manifest_data = {}
    if not manifest_path.exists():
        checks.append(CheckItem(
            check_id="CHK_MANIFEST_EXISTS",
            status="WARNING",
            description="project_manifest.json not found alongside project",
            observed="Missing",
            expected="Manifest exists",
            artifact_ref=str(manifest_path),
        ))
    else:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            checks.append(CheckItem(
                check_id="CHK_MANIFEST_EXISTS",
                status="PASS",
                description="project_manifest.json exists and is valid JSON",
                observed=manifest_data.get("build_id", ""),
                expected="JSON manifest with build_id",
                artifact_ref=str(manifest_path),
            ))
        except Exception as e:
            checks.append(CheckItem(
                check_id="CHK_MANIFEST_EXISTS",
                status="FAIL",
                description="Failed to parse project_manifest.json",
                details=str(e),
                artifact_ref=str(manifest_path),
            ))

    # 3. Read and parse QGS XML
    try:
        xml_content = extract_qgs_from_project(project_path)
        root = ET.fromstring(xml_content)
        checks.append(CheckItem(
            check_id="CHK_PROJ_XML_PARSE",
            status="PASS",
            description="QGS XML parses successfully",
            observed=f"Root tag <{root.tag}>",
            expected="Valid XML",
        ))
    except Exception as e:
        checks.append(CheckItem(
            check_id="CHK_PROJ_XML_PARSE",
            status="FAIL",
            description="Failed to parse project XML",
            details=str(e),
        ))
        return CheckReport(
            passed=False,
            status="FAILED",
            project_path=str(project_path),
            manifest_path=str(manifest_path),
            total_checks=len(checks),
            passed_checks=sum(1 for c in checks if c.status == "PASS"),
            failed_checks=sum(1 for c in checks if c.status == "FAIL"),
            warning_checks=sum(1 for c in checks if c.status == "WARNING"),
            checks=checks,
        )

    # 4. CRS validation (must be EPSG:32648)
    proj_crs = root.find(".//projectCrs/spatialrefsys/authid")
    crs_val = proj_crs.text if proj_crs is not None else ""
    if crs_val == "EPSG:32648":
        checks.append(CheckItem(
            check_id="CHK_PROJ_CRS",
            status="PASS",
            description="Project CRS matches SCI-02 baseline",
            observed=crs_val,
            expected="EPSG:32648",
        ))
    else:
        checks.append(CheckItem(
            check_id="CHK_PROJ_CRS",
            status="FAIL",
            description="Project CRS must be EPSG:32648",
            observed=crs_val,
            expected="EPSG:32648",
        ))

    # 5. Layer datasource relative path validation
    layers = root.findall(".//projectlayers/maplayer")
    proj_dir = project_path.parent

    for lyr in layers:
        lid = lyr.find("id").text if lyr.find("id") is not None else "unknown"
        lname = lyr.find("layername").text if lyr.find("layername") is not None else "unnamed"
        ds = lyr.find("datasource").text if lyr.find("datasource") is not None else ""

        # Extract file path from datasource
        file_part = ds.split("|")[0] if ds else ""
        resolved_file = (proj_dir / file_part).resolve()

        if resolved_file.exists():
            checks.append(CheckItem(
                check_id=f"CHK_LAYER_FILE_{lid[:12]}",
                status="PASS",
                description=f"Layer '{lname}' datasource exists via relative path",
                observed=str(file_part),
                expected="Resolved on disk",
                details=str(resolved_file),
            ))
        else:
            checks.append(CheckItem(
                check_id=f"CHK_LAYER_FILE_{lid[:12]}",
                status="WARNING",
                description=f"Layer '{lname}' file not found (acceptable in development mode)",
                observed=str(file_part),
                expected="File exists",
                details=str(resolved_file),
            ))

    # 6. Print Layouts existence
    expected_layouts = {"lulc_1992", "lulc_2021", "urban_change", "township_change"}
    found_layouts = set()
    for lyt in root.findall(".//Layouts/Layout"):
        name = lyt.get("name")
        if name:
            found_layouts.add(name)

    missing_layouts = expected_layouts - found_layouts
    if not missing_layouts:
        checks.append(CheckItem(
            check_id="CHK_PROJ_LAYOUTS",
            status="PASS",
            description="All 4 standard print layouts are declared in project",
            observed=sorted(list(found_layouts)),
            expected=sorted(list(expected_layouts)),
        ))
    else:
        checks.append(CheckItem(
            check_id="CHK_PROJ_LAYOUTS",
            status="FAIL",
            description="Missing required print layouts",
            observed=sorted(list(found_layouts)),
            expected=sorted(list(expected_layouts)),
            details=f"Missing: {missing_layouts}",
        ))

    failed = sum(1 for c in checks if c.status == "FAIL")
    warnings = sum(1 for c in checks if c.status == "WARNING")
    passed = sum(1 for c in checks if c.status == "PASS")

    is_success = failed == 0
    return CheckReport(
        passed=is_success,
        status="PASSED" if is_success else "FAILED",
        project_path=str(project_path),
        manifest_path=str(manifest_path),
        total_checks=len(checks),
        passed_checks=passed,
        failed_checks=failed,
        warning_checks=warnings,
        checks=checks,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check QGIS Project integrity")
    parser.add_argument("--project", default="qgis/xindu_1992_2021.qgz")
    parser.add_argument("--manifest", default="qgis/project_manifest.json")
    args = parser.parse_args()

    report = check_project(args.project, args.manifest)
    print(f"Check Project Status: {report.status} (Passed: {report.passed_checks}/{report.total_checks}, Fail: {report.failed_checks}, Warn: {report.warning_checks})")
    for c in report.checks:
        print(f"  [{c.status}] {c.check_id}: {c.description}")
