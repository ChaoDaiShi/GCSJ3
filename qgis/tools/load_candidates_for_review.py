"""在 QGIS 里加载「候选样本面」，按类别上色并带编号标签，供人工逐条复核。

用法：
1. QGIS 菜单 插件 → Python 控制台 → 「显示编辑器」→ 打开本文件 → 运行脚本；
2. 脚本会加载展示底图 + 边界 + 候选面（按类别 4 色、带 group_id 标签）；
3. 复核完成后（改 class_id、把不要的 keep 改成 0）保存，关闭 QGIS，交回整理。

不修改任何文件内容，只做加载与符号化。改属性请在 QGIS 里手工编辑。
"""

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsFillSymbol,
    QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.utils import iface

ROOT = r"E:\工程实践3\GCSJ3"
YEAR = 2021                      # 复核 1992 时改成 1992

CLASS_COLORS = {
    1: ("217,95,2", "城镇及建设用地"),
    2: ("230,200,79", "耕地"),
    3: ("46,139,87", "林草植被"),
    4: ("55,126,184", "水体"),
}


def add_raster(path: str, name: str):
    lyr = QgsRasterLayer(path, name)
    if not lyr.isValid():
        print("栅格打不开:", path)
        return None
    QgsProject.instance().addMapLayer(lyr)
    return lyr


def style_candidates(layer: QgsVectorLayer):
    """按 class_id 分类上色（半透明填充，能看见底图）。"""
    from qgis.core import (
        QgsCategorizedSymbolRenderer, QgsRendererCategory,
    )
    cats = []
    for cid, (rgb, label) in CLASS_COLORS.items():
        sym = QgsFillSymbol.createSimple({
            "color": f"{rgb},70",
            "outline_color": f"{rgb},255",
            "outline_width": "0.7",
        })
        cats.append(QgsRendererCategory(cid, sym, f"{cid} {label}"))
    layer.setRenderer(QgsCategorizedSymbolRenderer("class_id", cats))

    # 标签：group_id（复核时好记）
    settings = QgsPalLayerSettings()
    settings.fieldName = "group_id"
    settings.isExpression = False
    fmt = QgsTextFormat()
    fmt.setFont(QFont("Microsoft YaHei", 8))
    fmt.setSize(8)
    fmt.setColor(QColor(255, 255, 255))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.2)
    buf.setColor(QColor(0, 0, 0))
    fmt.setBuffer(buf)
    settings.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


project = QgsProject.instance()
try:
    from qgis.core import QgsCoordinateReferenceSystem
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:32648"))
except Exception as exc:  # noqa: BLE001
    print("坐标系设置失败：", exc)

add_raster(rf"{ROOT}\outputs\rasters\display\xindu_{YEAR}_truecolor_15m_rgb.tif", f"{YEAR} 真彩色")
add_raster(rf"{ROOT}\outputs\rasters\display\xindu_{YEAR}_falsecolor_30m_rgb.tif", f"{YEAR} 假彩色")

bounds = rf"{ROOT}\data\processed\boundaries\xindu_2021.gpkg"
for lname in ("townships",):
    lyr = QgsVectorLayer(f"{bounds}|layername={lname}", "镇街边界", "ogr")
    if lyr.isValid():
        lyr.renderer().setSymbol(QgsFillSymbol.createSimple({
            "color": "0,0,0,0", "outline_color": "60,60,60,255", "outline_width": "0.5",
        }))
        project.addMapLayer(lyr)

cand = QgsVectorLayer(
    rf"{ROOT}\data\samples\{YEAR}\labels_candidates.gpkg|layername=labels_candidates",
    f"候选面 {YEAR}", "ogr")
if cand.isValid():
    style_candidates(cand)
    project.addMapLayer(cand)
    print(f"候选面 {cand.featureCount()} 个已加载")
else:
    print("候选面打不开，先运行 tools/make_sample_candidates.py")

if iface and cand.isValid():
    iface.setActiveLayer(cand)

print("复核提示：属性表里用表达式筛 class_id，逐条「缩放至要素」看，"
      "类不对就改 class_id，该剔除的把 keep 改成 0。")