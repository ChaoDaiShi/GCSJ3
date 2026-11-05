"""Layout Export Script (W20).

Validates and exports the 4 standard thematic maps:
1. lulc_1992 -> outputs/maps/lulc_1992.png
2. lulc_2021 -> outputs/maps/lulc_2021.png
3. urban_change -> outputs/maps/urban_change_1992_2021.png
4. township_change -> outputs/maps/township_change.png
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


REQUIRED_ITEMS = ["map_main", "legend_main", "scale_main", "north_main", "title_text", "source_text"]

LAYOUT_EXPORT_MAP = {
    "lulc_1992": "lulc_1992.png",
    "lulc_2021": "lulc_2021.png",
    "urban_change": "urban_change_1992_2021.png",
    "township_change": "township_change.png",
}


@dataclass
class ExportItem:
    layout_name: str
    target_png: str
    status: str  # PASS / FAIL / SKIPPED
    details: str = ""


@dataclass
class ExportReport:
    success: bool
    status: str  # PASSED / FAILED / BLOCKED
    export_dir: str
    items: List[ExportItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


def validate_qpt_template(qpt_path: Path) -> List[str]:
    """Inspects QPT XML to verify required layout items exist."""
    if not qpt_path.is_file():
        raise FileNotFoundError(f"Template not found: {qpt_path}")

    tree = ET.parse(qpt_path)
    root = tree.getroot()

    found_ids = set()
    for item in root.findall(".//LayoutItem"):
        item_id = item.get("id")
        if item_id:
            found_ids.add(item_id)

    missing = [req for req in REQUIRED_ITEMS if req not in found_ids]
    return missing


def export_layouts(
    project_path: Path | str,
    export_dir: Optional[Path | str] = None,
) -> ExportReport:
    """Exports layouts using PyQGIS if available, or validates templates in headless Python."""
    project_path = Path(project_path).resolve()
    repo_root = project_path.parent.parent.resolve()
    if export_dir is None:
        export_dir = repo_root / "outputs" / "maps"
    else:
        export_dir = Path(export_dir).resolve()

    export_dir.mkdir(parents=True, exist_ok=True)
    layouts_dir = repo_root / "qgis" / "layouts"

    items: List[ExportItem] = []
    errors: List[str] = []

    # 1. First validate all QPT templates
    for layout_name, png_name in LAYOUT_EXPORT_MAP.items():
        qpt_path = layouts_dir / f"{layout_name}.qpt"
        try:
            missing_items = validate_qpt_template(qpt_path)
            if missing_items:
                err = f"Template {qpt_path.name} is missing required items: {missing_items}"
                errors.append(err)
                items.append(ExportItem(layout_name, png_name, "FAIL", details=err))
            else:
                items.append(ExportItem(layout_name, png_name, "PASS", details="Template validated"))
        except Exception as e:
            err = f"Failed to validate template {qpt_path.name}: {e}"
            errors.append(err)
            items.append(ExportItem(layout_name, png_name, "FAIL", details=err))

    # 2. Check if PyQGIS is available to perform actual rendering
    pyqgis_available = False
    try:
        from qgis.core import QgsApplication, QgsLayoutExporter, QgsProject  # type: ignore
        pyqgis_available = True
    except ImportError:
        pass

    if pyqgis_available:
        try:
            proj = QgsProject.instance()
            proj.read(str(project_path))
            mgr = proj.layoutManager()

            for item in items:
                if item.status != "PASS":
                    continue
                layout = mgr.layoutByName(item.layout_name)
                if not layout:
                    item.status = "FAIL"
                    item.details = f"Layout '{item.layout_name}' not found in QGIS project"
                    errors.append(item.details)
                    continue

                exporter = QgsLayoutExporter(layout)
                settings = QgsLayoutExporter.ImageExportSettings()
                settings.dpi = 300
                out_png_path = export_dir / item.target_png

                res = exporter.exportToImage(str(out_png_path), settings)
                if res == QgsLayoutExporter.Success:
                    item.status = "PASS"
                    item.details = f"Exported: {out_png_path.name}"
                else:
                    item.status = "FAIL"
                    item.details = f"QgsLayoutExporter failed with code: {res}"
                    errors.append(item.details)
        except Exception as e:
            errors.append(f"PyQGIS export error: {e}")
    else:
        # In non-PyQGIS Python environment, mark that template validation passed
        for item in items:
            if item.status == "PASS":
                item.details += " (Awaiting QGIS 3.44 LTR runtime for physical PNG rendering)"

    success = len(errors) == 0
    return ExportReport(
        success=success,
        status="PASSED" if success else "FAILED",
        export_dir=str(export_dir),
        items=items,
        errors=errors,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export thematic maps from QGIS project layouts")
    parser.add_argument("--project", default="qgis/xindu_1992_2021.qgz")
    parser.add_argument("--export-dir", default="outputs/maps")
    args = parser.parse_args()

    report = export_layouts(args.project, args.export_dir)
    print(f"Export Layouts Status: {report.status}")
    for itm in report.items:
        print(f"  [{itm.status}] {itm.layout_name} -> {itm.target_png} ({itm.details})")
