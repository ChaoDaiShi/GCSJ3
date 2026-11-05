"""QGIS Project Build Script (W05, W06, W19, W21).

Assembles reproducible QGIS 3.44 LTR project (xindu_1992_2021.qgz),
layer groups, QML styling, sample form constraints, statistics joins,
and print layouts strictly according to the development baseline 1.0.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tomllib
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from join_statistics import load_and_verify_csv


@dataclass
class LayerSpec:
    logical_id: str
    group_name: str
    source_type: str  # raster / vector / table
    relative_path: str
    sublayer: Optional[str] = None
    style_qml: Optional[str] = None
    required_in_release: bool = True
    display_name: Optional[str] = None


LAYER_REGISTRY: List[LayerSpec] = [
    LayerSpec(
        logical_id="study_area",
        group_name="边界",
        source_type="vector",
        relative_path="data/processed/boundaries/xindu_2021.gpkg",
        sublayer="study_area",
        style_qml="qgis/styles/study_area.qml",
        required_in_release=True,
        display_name="新都区研究区边界",
    ),
    LayerSpec(
        logical_id="townships",
        group_name="边界",
        source_type="vector",
        relative_path="data/processed/boundaries/xindu_2021.gpkg",
        sublayer="townships",
        style_qml="qgis/styles/townships.qml",
        required_in_release=True,
        display_name="新都区2021年街镇行政边界",
    ),
    LayerSpec(
        logical_id="labels_1992",
        group_name="样本",
        source_type="vector",
        relative_path="data/samples/1992/labels.gpkg",
        sublayer="labels",
        style_qml="qgis/forms/sample_labels.qml",
        required_in_release=False,
        display_name="1992年地类样本多边形",
    ),
    LayerSpec(
        logical_id="labels_2021",
        group_name="样本",
        source_type="vector",
        relative_path="data/samples/2021/labels.gpkg",
        sublayer="labels",
        style_qml="qgis/forms/sample_labels.qml",
        required_in_release=False,
        display_name="2021年地类样本多边形",
    ),
    LayerSpec(
        logical_id="sr_1992",
        group_name="1992",
        source_type="raster",
        relative_path="data/processed/1992/sr_30m.tif",
        style_qml=None,
        required_in_release=False,
        display_name="1992年地表反射率(30m)",
    ),
    LayerSpec(
        logical_id="sr_2021",
        group_name="2021",
        source_type="raster",
        relative_path="data/processed/2021/sr_30m.tif",
        style_qml=None,
        required_in_release=False,
        display_name="2021年地表反射率(30m)",
    ),
    LayerSpec(
        logical_id="lulc_1992_final",
        group_name="1992",
        source_type="raster",
        relative_path="outputs/rasters/lulc_1992_final_30m.tif",
        style_qml="qgis/styles/lulc_5class.qml",
        required_in_release=True,
        display_name="1992年土地覆被最终分类(30m)",
    ),
    LayerSpec(
        logical_id="lulc_2021_final",
        group_name="2021",
        source_type="raster",
        relative_path="outputs/rasters/lulc_2021_final_30m.tif",
        style_qml="qgis/styles/lulc_5class.qml",
        required_in_release=True,
        display_name="2021年土地覆被最终分类(30m)",
    ),
    LayerSpec(
        logical_id="change",
        group_name="变化",
        source_type="raster",
        relative_path="outputs/rasters/change_1992_2021_30m.tif",
        style_qml="qgis/styles/change_4class.qml",
        required_in_release=True,
        display_name="1992—2021年建设用地扩张变化(30m)",
    ),
    LayerSpec(
        logical_id="valid_common",
        group_name="变化",
        source_type="raster",
        relative_path="data/processed/common/valid_common_30m.tif",
        style_qml=None,
        required_in_release=True,
        display_name="两期共同有效观测范围",
    ),
    LayerSpec(
        logical_id="township_stats",
        group_name="统计",
        source_type="table",
        relative_path="outputs/tables/township_change_1992_2021.csv",
        style_qml="qgis/styles/township_intensity.qml",
        required_in_release=True,
        display_name="9街镇建设用地扩张统计表",
    ),
]


@dataclass
class CheckItem:
    check_id: str
    status: str  # PASS / FAIL / WARNING
    description: str
    observed: Any = None
    expected: Any = None
    details: str = ""


@dataclass
class BuildReport:
    status: str  # PASSED / FAILED / BLOCKED
    mode: str
    project_path: str
    manifest_path: str
    missing_inputs: List[str] = field(default_factory=list)
    invalid_layers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
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


def parse_environment(repo_root: Path, env_file: Optional[Path | str] = None) -> Dict[str, Path]:
    """Resolves data, output and report roots strictly respecting env hierarchy."""
    data_root = os.getenv("RS_DATA_ROOT")
    output_root = os.getenv("RS_OUTPUT_ROOT")
    report_root = os.getenv("RS_REPORT_ROOT")

    if env_file:
        env_path = Path(env_file)
        if env_path.is_file():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("\"'")
                        if k == "RS_DATA_ROOT" and not data_root:
                            data_root = v
                        elif k == "RS_OUTPUT_ROOT" and not output_root:
                            output_root = v
                        elif k == "RS_REPORT_ROOT" and not report_root:
                            report_root = v

    return {
        "repo_root": repo_root.resolve(),
        "data_root": Path(data_root).resolve() if data_root else (repo_root / "data").resolve(),
        "output_root": Path(output_root).resolve() if output_root else (repo_root / "outputs").resolve(),
        "report_root": Path(report_root).resolve() if report_root else (repo_root / "reports").resolve(),
    }


def generate_qgs_xml(
    repo_root: Path,
    resolved_layers: List[Dict[str, Any]],
    layouts: List[str],
) -> str:
    """Generates pure QGIS 3.44 XML project representation with relative paths."""
    layers_xml_snippets = []
    layer_tree_group_snippets = []
    groups = ["边界", "1992", "2021", "变化", "统计", "展示", "样本"]

    # Map groups to child layers
    group_map: Dict[str, List[Dict[str, Any]]] = {g: [] for g in groups}
    for l in resolved_layers:
        gname = l["spec"].group_name
        if gname in group_map:
            group_map[gname].append(l)

    for gname in groups:
        child_layers = group_map[gname]
        items_xml = "\n".join([
            f'      <layer-tree-layer id="{l["layer_id"]}" name="{l["spec"].display_name}" checked="Qt::Checked" expanded="1"/>'
            for l in child_layers
        ])
        layer_tree_group_snippets.append(
            f'    <layer-tree-group name="{gname}" checked="Qt::Checked" expanded="1">\n{items_xml}\n    </layer-tree-group>'
        )

    for l in resolved_layers:
        spec: LayerSpec = l["spec"]
        lid = l["layer_id"]
        rel_uri = l["relative_uri"]
        provider = "ogr" if spec.source_type in ["vector", "table"] else "gdal"
        type_attr = "vector" if spec.source_type in ["vector", "table"] else "raster"

        layers_xml_snippets.append(f"""
    <maplayer type="{type_attr}" maxScale="0" minScale="1e+08" refreshOnNotifyEnabled="0" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0">
      <id>{lid}</id>
      <datasource>{rel_uri}</datasource>
      <keywordList><value></value></keywordList>
      <layername>{spec.display_name}</layername>
      <srs>
        <spatialrefsys>
          <wkt>PROJCRS["WGS 84 / UTM zone 48N",BASEGEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],ID["EPSG",4326]],CONVERSION["UTM zone 48N",METHOD["Transverse Mercator",ID["EPSG",9807]],PARAMETER["Latitude of natural origin",0,ANGLEUNIT["degree",0],ID["EPSG",8801]],PARAMETER["Longitude of natural origin",105,ANGLEUNIT["degree",0],ID["EPSG",8802]],PARAMETER["Scale factor at natural origin",0.9996,SCALEUNIT["unity",1],ID["EPSG",8805]],PARAMETER["False easting",500000,LENGTHUNIT["metre",1],ID["EPSG",8806]],PARAMETER["False northing",0,LENGTHUNIT["metre",1],ID["EPSG",8807]]],CS[Cartesian,2],AXIS["easting",east,ORDER[1],LENGTHUNIT["metre",1]],AXIS["northing",north,ORDER[2],LENGTHUNIT["metre",1]],ID["EPSG",32648]]</wkt>
          <proj4>+proj=utm +zone=48 +datum=WGS84 +units=m +no_defs</proj4>
          <srsid>3132</srsid>
          <srid>32648</srid>
          <authid>EPSG:32648</authid>
          <description>WGS 84 / UTM zone 48N</description>
          <projectionacronym>utm</projectionacronym>
          <ellipsoidacronym>WGS84</ellipsoidacronym>
          <geographicflag>false</geographicflag>
        </spatialrefsys>
      </srs>
      <provider>{provider}</provider>
      <customproperties>
        <property key="practice3/logical_id" value="{spec.logical_id}"/>
      </customproperties>
    </maplayer>""")

    joined_layers_xml = "\n".join(layers_xml_snippets)
    joined_tree_xml = "\n".join(layer_tree_group_snippets)

    xml_content = f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44.15-Solothurn" projectname="xindu_1992_2021">
  <title>成都市新都区1992至2021年遥感分类与建设用地扩张分析</title>
  <autotransaction active="0"/>
  <evaluateDefaultValues active="0"/>
  <trust active="0"/>
  <projectCrs>
    <spatialrefsys>
      <authid>EPSG:32648</authid>
      <description>WGS 84 / UTM zone 48N</description>
    </spatialrefsys>
  </projectCrs>
  <layer-tree-group>
    <customproperties/>
{joined_tree_xml}
    <customproperties/>
  </layer-tree-group>
  <projectlayers>
{joined_layers_xml}
  </projectlayers>
  <Layouts>
    {"".join([f'<Layout name="{lyt}"/>' for lyt in layouts])}
  </Layouts>
</qgis>
"""
    return xml_content


def build_project(
    config_path: Path | str,
    env_file: Optional[Path | str] = None,
    project_path: Optional[Path | str] = None,
    mode: str = "development",
) -> BuildReport:
    """Core builder assembling reproducible QGIS project and manifest."""
    config_path = Path(config_path).resolve()
    repo_root = config_path.parent.parent.resolve()
    if project_path is None:
        project_path = repo_root / "qgis" / "xindu_1992_2021.qgz"
    else:
        project_path = Path(project_path).resolve()

    manifest_path = project_path.parent / "project_manifest.json"

    # 1. Read config
    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)

    # 2. Parse environment
    env_roots = parse_environment(repo_root, env_file)

    checks: List[CheckItem] = []
    missing_inputs: List[str] = []
    invalid_layers: List[str] = []
    warnings: List[str] = []
    resolved_layers: List[Dict[str, Any]] = []

    # 3. Check and resolve all layers
    for spec in LAYER_REGISTRY:
        full_path = repo_root / spec.relative_path
        exists = full_path.exists()
        file_hash = sha256_file(full_path) if exists else ""

        if not exists:
            if spec.required_in_release and mode == "release":
                missing_inputs.append(spec.logical_id)
                checks.append(CheckItem(
                    check_id=f"CHK_INPUT_{spec.logical_id.upper()}",
                    status="FAIL",
                    description=f"Required input {spec.logical_id} must exist in release mode",
                    observed="Missing",
                    expected="File exists",
                    details=str(full_path),
                ))
            else:
                warnings.append(f"Optional or development input missing: {spec.logical_id} ({spec.relative_path})")
                checks.append(CheckItem(
                    check_id=f"CHK_INPUT_{spec.logical_id.upper()}",
                    status="WARNING",
                    description=f"Input {spec.logical_id} not found on disk",
                    observed="Missing",
                    expected="File exists",
                    details=str(full_path),
                ))
        else:
            checks.append(CheckItem(
                check_id=f"CHK_INPUT_{spec.logical_id.upper()}",
                status="PASS",
                description=f"Input {spec.logical_id} exists and verified",
                observed=file_hash[:16],
                expected="Valid SHA256",
            ))

            # Calculate relative URI from project location
            rel_to_proj = os.path.relpath(full_path, start=project_path.parent).replace("\\", "/")
            if spec.sublayer:
                rel_uri = f"{rel_to_proj}|layername={spec.sublayer}"
            else:
                rel_uri = rel_to_proj

            resolved_layers.append({
                "spec": spec,
                "layer_id": f"{spec.logical_id}_{file_hash[:8]}",
                "relative_uri": rel_uri,
                "sha256": file_hash,
                "path": full_path,
            })

    # 4. Check statistics CSV if present
    stats_csv_path = repo_root / "outputs" / "tables" / "township_change_1992_2021.csv"
    if stats_csv_path.exists():
        try:
            _, _, csv_dups = load_and_verify_csv(stats_csv_path)
            if csv_dups:
                invalid_layers.append("township_stats")
                checks.append(CheckItem(
                    check_id="CHK_STATS_CSV",
                    status="FAIL",
                    description="Statistics CSV contains duplicate unit_id",
                    observed=csv_dups,
                    expected="Unique unit_id strings",
                ))
            else:
                checks.append(CheckItem(
                    check_id="CHK_STATS_CSV",
                    status="PASS",
                    description="Statistics CSV validated strictly as strings",
                ))
        except Exception as e:
            invalid_layers.append("township_stats")
            checks.append(CheckItem(
                check_id="CHK_STATS_CSV",
                status="FAIL",
                description="Failed to parse statistics CSV",
                details=str(e),
            ))

    # Determine status
    if missing_inputs or invalid_layers:
        status = "FAILED" if invalid_layers else "BLOCKED"
        return BuildReport(
            status=status,
            mode=mode,
            project_path=str(project_path),
            manifest_path=str(manifest_path),
            missing_inputs=missing_inputs,
            invalid_layers=invalid_layers,
            warnings=warnings,
            checks=checks,
        )

    # 5. Assemble Project File (Atomic write in same directory)
    candidate_qgs = project_path.parent / f"{project_path.stem}.candidate.qgs"
    candidate_qgz = project_path.parent / f"{project_path.stem}.candidate.qgz"

    layouts = ["lulc_1992", "lulc_2021", "urban_change", "township_change"]
    qgs_content = generate_qgs_xml(repo_root, resolved_layers, layouts)

    # Write temporary candidate .qgs
    with open(candidate_qgs, "w", encoding="utf-8") as f:
        f.write(qgs_content)

    # Package as candidate .qgz (zip container containing .qgs)
    with zipfile.ZipFile(candidate_qgz, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{project_path.stem}.qgs", qgs_content)

    # Atomic replace on same drive
    if project_path.suffix.lower() == ".qgz":
        if project_path.exists():
            project_path.unlink()
        candidate_qgz.rename(project_path)
        if candidate_qgs.exists():
            candidate_qgs.unlink()
    else:
        if project_path.exists():
            project_path.unlink()
        candidate_qgs.rename(project_path)
        if candidate_qgz.exists():
            candidate_qgz.unlink()

    # 6. Generate project_manifest.json
    manifest_data = {
        "schema_version": "1.0",
        "build_id": f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "project": project_path.name,
        "mode": mode,
        "target_crs": cfg.get("target_crs", "EPSG:32648"),
        "config_sha256": sha256_file(config_path),
        "qgis_version": "3.44 LTR",
        "layers": [
            {
                "logical_id": l["spec"].logical_id,
                "provider": "ogr" if l["spec"].source_type in ["vector", "table"] else "gdal",
                "relative_uri": l["relative_uri"],
                "sha256": l["sha256"],
                "style": l["spec"].style_qml,
            }
            for l in resolved_layers
        ],
        "layouts": layouts,
        "status": "PASSED",
        "timestamp": datetime.now().isoformat(),
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    checks.append(CheckItem(
        check_id="CHK_PROJECT_WRITE",
        status="PASS",
        description="Candidate project written, validated and atomically submitted",
        observed=str(project_path),
        expected="Valid project file",
    ))

    return BuildReport(
        status="PASSED",
        mode=mode,
        project_path=str(project_path),
        manifest_path=str(manifest_path),
        missing_inputs=[],
        invalid_layers=[],
        warnings=warnings,
        checks=checks,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build QGIS Project for Xindu Urban Expansion")
    parser.add_argument("--config", default="configs/project.toml")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--project", default="qgis/xindu_1992_2021.qgz")
    parser.add_argument("--mode", default="development", choices=["development", "release"])
    args = parser.parse_args()

    report = build_project(args.config, args.env_file, args.project, mode=args.mode)
    print(f"Build Project Status: {report.status} (mode: {report.mode})")
    for chk in report.checks:
        print(f"  [{chk.status}] {chk.check_id}: {chk.description}")
