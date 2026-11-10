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

LAYOUT_LAYERS = {
    "lulc_1992": ["lulc_1992_final", "townships", "study_area"],
    "lulc_2021": ["lulc_2021_final", "townships", "study_area"],
    "urban_change": ["change", "townships", "study_area"],
    "township_change": ["township_stats", "townships", "study_area"],
}

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




def _apply_paletted_from_qml(lyr, qml_path: Path) -> bool:
    """按 QML 中的 colorPalette 直接构造调色板渲染器。

    loadNamedStyle 在无 GUI 的 QgsApplication 里对 paletted 渲染器不生效，
    这里显式构造 QgsPalettedRasterRenderer，保证导出图与 QGIS 里看到的一致。
    """
    try:
        import xml.etree.ElementTree as _ET

        from qgis.core import (  # type: ignore
            QgsPalettedRasterRenderer,
            QgsRasterLayer,
        )
        from qgis.PyQt.QtGui import QColor

        if not isinstance(lyr, QgsRasterLayer):
            return False
        root = _ET.parse(qml_path).getroot()
        entries = root.findall(".//paletteEntry")
        if not entries:
            return False
        classes = []
        for e in entries:
            val = int(e.get("value"))
            color = QColor(e.get("color"))
            alpha = int(e.get("alpha", "255"))
            color.setAlpha(alpha)
            classes.append(QgsPalettedRasterRenderer.Class(val, color, e.get("label", "")))
        renderer = QgsPalettedRasterRenderer(lyr.dataProvider(), 1, classes)
        renderer.setNodataColor(QColor(0, 0, 0, 0))
        lyr.setRenderer(renderer)
        return True
    except Exception:
        return False


def _township_intensity_layer(by_logical: Dict[str, Any], repo_root: Path):
    """镇街边界 + 变化统计 CSV 的内存连接层，用于镇街强度专题图。

    township_stats 是纯 CSV（无几何），直接绑到地图项渲染不出东西，
    这里把 annual_intensity_pct 连到街镇多边形上并按分级着色。
    """
    try:
        import csv as _csv

        from qgis.core import (  # type: ignore
            QgsFeature,
            QgsField,
            QgsGraduatedSymbolRenderer,
            QgsProject,
            QgsRendererRange,
            QgsStyle,
            QgsSymbol,
            QgsVectorLayer,
        )
        from qgis.PyQt.QtCore import QVariant  # type: ignore

        towns = by_logical.get("townships")
        stats_csv = repo_root / "outputs" / "tables" / "township_change_1992_2021.csv"
        if towns is None or not stats_csv.exists():
            return None
        with stats_csv.open(encoding="utf-8-sig") as fh:
            stats = {row["name"]: float(row["annual_intensity_pct"]) for row in _csv.DictReader(fh)}
        if not stats:
            return None

        mem = QgsVectorLayer("Polygon?crs=EPSG:32648", "镇街扩张强度", "memory")
        prov = mem.dataProvider()
        prov.addAttributes([QgsField("name", QVariant.String), QgsField("intensity", QVariant.Double)])
        mem.updateFields()
        feats = []
        for f in towns.getFeatures():
            name = f["name"]
            if name not in stats:
                continue
            nf = QgsFeature(mem.fields())
            nf.setGeometry(f.geometry())
            nf["name"] = name
            nf["intensity"] = stats[name]
            feats.append(nf)
        if not feats:
            return None
        prov.addFeatures(feats)
        mem.updateExtents()

        vals = sorted(stats.values())
        lo, hi = vals[0], vals[-1]
        step = (hi - lo) / 5 if hi > lo else 0.01
        ranges = []
        ramp = QgsStyle.defaultStyle().colorRamp("Reds")
        for i in range(5):
            a = lo + step * i
            b = lo + step * (i + 1)
            sym = QgsSymbol.defaultSymbol(mem.geometryType())
            if ramp is not None:
                sym.setColor(ramp.color(0.15 + 0.17 * i))
            ranges.append(QgsRendererRange(a, b, sym, f"{a:.2f} – {b:.2f} %"))
        mem.setRenderer(QgsGraduatedSymbolRenderer("intensity", ranges))
        QgsProject.instance().addMapLayer(mem, False)
        return mem
    except Exception:
        return None

def assign_layout_layers(layout, layout_name: str) -> None:
    """把 manifest 中对应 logical_id 的图层绑定到布局的地图项，并缩放到图层范围。

    qpt 模板里的地图项是空 LayerSet，不绑定就只会导出空白图框。
    """
    from qgis.core import QgsLayoutItemMap, QgsProject, QgsRectangle  # type: ignore

    wanted = LAYOUT_LAYERS.get(layout_name)
    if not wanted:
        return
    proj = QgsProject.instance()
    by_logical = {}
    for lyr in proj.mapLayers().values():
        lid = lyr.customProperty("practice3/logical_id")
        if lid:
            by_logical[lid] = lyr
    # 按 manifest 应用 QML 样式，否则栅格只用默认单波段灰度渲染
    manifest_path = proj.fileName() and Path(proj.fileName()).parent / "project_manifest.json"
    styles: Dict[str, str] = {}
    if manifest_path and Path(manifest_path).exists():
        try:
            import json as _json

            manifest = _json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            styles = {it["logical_id"]: it.get("style") for it in manifest.get("layers", [])}
        except Exception:
            styles = {}
    repo_root = Path(proj.fileName()).parent.parent if proj.fileName() else Path(".")

    for lid, lyr in by_logical.items():
        style_rel = styles.get(lid)
        if not style_rel:
            continue
        qml = repo_root / style_rel
        if qml.exists():
            lyr.loadNamedStyle(str(qml))
            _apply_paletted_from_qml(lyr, qml)

    layers = [by_logical[k] for k in wanted if k in by_logical]
    if layout_name == "township_change":
        intensity = _township_intensity_layer(by_logical, repo_root)
        if intensity is not None:
            layers = [intensity] + [l for l in layers if l.name() != " township_stats"]
    if not layers:
        return

    extent = None
    for lyr in layers:
        e = lyr.extent()
        if e.isNull():
            continue
        if extent is None:
            extent = QgsRectangle(e)
        else:
            extent.combineExtentWith(e)

    for item in layout.items():
        if isinstance(item, QgsLayoutItemMap):
            item.setLayers(layers)
            if extent is not None and not extent.isNull():
                item.zoomToExtent(extent)
            item.updateBoundingRect()

def export_layouts(
    project_path: Path | str,
    export_dir: Optional[Path | str] = None,
    only: Optional[str] = None,
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
    targets = {k: v for k, v in LAYOUT_EXPORT_MAP.items() if only is None or k == only}
    for layout_name, png_name in targets.items():
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

            from qgis.core import QgsPrintLayout, QgsReadWriteContext  # type: ignore
            from qgis.PyQt.QtXml import QDomDocument  # type: ignore

            for item in items:
                if item.status != "PASS":
                    continue
                # 直接从 qpt 模板构造布局：项目内嵌布局在无 GUI 环境下渲染不稳定
                qpt_path = layouts_dir / f"{item.layout_name}.qpt"
                doc = QDomDocument()
                doc.setContent(qpt_path.read_text(encoding="utf-8"))
                layout = QgsPrintLayout(proj)
                layout.readXml(doc.documentElement(), doc, QgsReadWriteContext())
                layout.setName(item.layout_name)
                if not layout:
                    item.status = "FAIL"
                    item.details = f"Layout '{item.layout_name}' not found in QGIS project"
                    errors.append(item.details)
                    continue

                assign_layout_layers(layout, item.layout_name)

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
    parser.add_argument("--layout", default=None, help="只导出指定布局")
    args = parser.parse_args()

    # 布局导出依赖已初始化的 QgsApplication；未初始化时 QgsProject 读取与渲染会挂起。
    _app = None
    try:
        from qgis.core import QgsApplication  # type: ignore

        _app = QgsApplication.instance() or QgsApplication([], False)
        _app.initQgis()
    except ImportError:
        _app = None

    try:
        report = export_layouts(args.project, args.export_dir, only=args.layout)
    finally:
        if _app is not None:
            _app.exitQgis()
    print(f"Export Layouts Status: {report.status}")
    for itm in report.items:
        print(f"  [{itm.status}] {itm.layout_name} -> {itm.target_png} ({itm.details})")
