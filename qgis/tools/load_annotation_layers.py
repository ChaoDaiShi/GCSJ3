"""QGIS 内一次性加载标注工程（在 QGIS 的 Python 控制台里运行）。

用法：
1. QGIS 菜单 插件 → Python 控制台（Plugins → Python Console）；
2. 点控制台左下角的「显示编辑器」按钮，打开编辑器面板；
3. 打开本文件（编辑器里 Ctrl+O），或把内容整段粘进去；
4. 点绿色三角「运行脚本（Run Script）」。

脚本会做：
- 加载 3 张「打开就清楚」的展示底图（已是 8 bit，无需设置拉伸）；
- 加载镇街边界与研究区，改成仅描边；
- 加载 data/samples/2021/labels.gpkg 的 labels 图层，设成半透明红面 + 红边；
- 给 year / label_source / annotator 设默认值，并打开「复用上次输入值」；
- 开启顶点捕捉，工程坐标系设为 EPSG:32648。

不修改任何数据文件，只改当前工程的图层与显示设置。
"""

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer,
    QgsFillSymbol, QgsDefaultValue,
)
from qgis.utils import iface

ROOT = r"E:\工程实践3\GCSJ3"
YEAR = 2021                      # 标 1992 时把这里改成 1992
LABELS = rf"{ROOT}\data\samples\{YEAR}\labels.gpkg"


def _add(vec_or_raster, name: str):
    """按名称去重后加入工程，返回图层对象。"""
    project = QgsProject.instance()
    existing = project.mapLayersByName(name)
    if existing:
        return existing[0]
    project.addMapLayer(vec_or_raster)
    vec_or_raster.setName(name)
    return vec_or_raster


def load_raster(path: str, name: str):
    lyr = QgsRasterLayer(path, name)
    if not lyr.isValid():
        print(f"[跳过] 栅格打不开：{path}")
        return None
    return _add(lyr, name)


def load_vector(path: str, layer: str, name: str):
    lyr = QgsVectorLayer(f"{path}|layername={layer}", name, "ogr")
    if not lyr.isValid():
        print(f"[跳过] 矢量打不开：{path} 图层 {layer}")
        return None
    return _add(lyr, name)


project = QgsProject.instance()

# 0. 工程坐标系
try:
    from qgis.core import QgsCoordinateReferenceSystem
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:32648"))
except Exception as exc:  # noqa: BLE001
    print("坐标系设置失败（可手动改）：", exc)

# 1. 展示底图（已烘焙拉伸，直接可见）
load_raster(rf"{ROOT}\outputs\rasters\display\xindu_{YEAR}_truecolor_15m_rgb.tif", f"{YEAR} 真彩色 15m")
load_raster(rf"{ROOT}\outputs\rasters\display\xindu_{YEAR}_falsecolor_30m_rgb.tif", f"{YEAR} 假彩色 30m")

# 2. 边界（仅描边）
townships = load_vector(rf"{ROOT}\data\processed\boundaries\xindu_2021.gpkg", "townships", "镇街边界")
if townships:
    townships.renderer().setSymbol(QgsFillSymbol.createSimple({
        "color": "0,0,0,0", "outline_color": "80,80,80,255", "outline_width": "0.6",
    }))
    townships.triggerRepaint()

study = load_vector(rf"{ROOT}\data\processed\boundaries\xindu_2021.gpkg", "study_area", "研究区范围")
if study:
    study.renderer().setSymbol(QgsFillSymbol.createSimple({
        "color": "0,0,0,0", "outline_color": "255,140,0,255", "outline_width": "1.0",
    }))
    study.triggerRepaint()

# 3. 标注图层
labels = load_vector(LABELS, "labels", f"标注 labels {YEAR}")
if labels:
    labels.renderer().setSymbol(QgsFillSymbol.createSimple({
        "color": "230,0,0,60", "outline_color": "200,0,0,255", "outline_width": "0.8",
    }))
    labels.triggerRepaint()

    # 默认值与「复用上次输入值」：少打字
    defaults = {
        "year": str(YEAR),
        "label_source": f"manual_{YEAR}",
    }
    for field_name, value in defaults.items():
        idx = labels.fields().indexOf(field_name)
        if idx < 0:
            continue
        try:
            labels.setDefaultValueDefinition(idx, QgsDefaultValue(value))
        except Exception as exc:  # noqa: BLE001
            print(f"[提示] {field_name} 默认值设置失败：", exc)

    try:
        cfg = labels.editFormConfig()
        for field_name in ("group_id", "class_id", "label_source", "annotator", "source_date"):
            idx = labels.fields().indexOf(field_name)
            if idx >= 0:
                cfg.setReuseLastValue(idx, True)
        labels.setEditFormConfig(cfg)
    except Exception as exc:  # noqa: BLE001
        print("[提示] 复用上次输入值设置失败：", exc)
else:
    print("labels 图层没加载上，检查文件是否存在：", LABELS)

# 4. 顶点捕捉
try:
    project.setTopologicalEditing(True)
    from qgis.core import QgsSnappingConfig, QgsTolerance
    snap = project.snappingConfig()
    snap.setEnabled(True)
    snap.setMode(QgsSnappingConfig.VertexAndSegment)
    snap.setType(QgsSnappingConfig.AllLayers)
    snap.setTolerance(10)
    snap.setUnits(QgsTolerance.Pixels)
    project.setSnappingConfig(snap)
except Exception as exc:  # noqa: BLE001
    print("[提示] 捕捉设置失败（可手动开）：", exc)

if iface:
    iface.mapCanvas().refresh()
print("完成：底图 + 边界 + labels 已就位，选 labels 图层点铅笔即可开画。")