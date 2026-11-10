"""用 PyQGIS 为人工标注图层配置符号与属性表单，并保存 .qml 样式。

    "<QGIS>/bin/python-qgis-ltr.bat" qgis\\scripts\\build_annotation_style.py

生成：
  data/samples/<year>/annotation_<year>.qml   分类符号 + class_id 下拉（值映射）
  并把样式写入 gpkg 的 layer_styles 表，打开即生效
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CLASSES = {
    1: ("城镇及建设用地", "#D95F02"),
    2: ("耕地", "#E6C84F"),
    3: ("林草植被", "#2E8B57"),
    4: ("水体", "#377EB8"),
}

QML_TEMPLATE = """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44" styleCategories="Symbology|Fields|Forms">
  <renderer-v2 type="categorizedSymbol" attr="class_id" enableorderby="0" forceraster="0" symbollevels="0">
    <categories>
{categories}
    </categories>
    <symbols>
{symbols}
    </symbols>
  </renderer-v2>
  <editform>
    <attributeEditorForm>
      <attributeEditorContainer name="标注" columnCount="1" groupBox="0" visibilityExpressionEnabled="0">
        <attributeEditorField name="class_id" showLabel="1" index="0"/>
        <attributeEditorField name="note" showLabel="1" index="1"/>
      </attributeEditorContainer>
    </attributeEditorForm>
  </editform>
  <fieldConfiguration>
    <field name="class_id" configurationFlags="NoFlag">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option name="map" type="List">
{map_entries}
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="note" configurationFlags="NoFlag">
      <editWidget type="TextEdit"/>
    </field>
  </fieldConfiguration>
</qgis>
"""


def symbol(idx: int, color: str) -> str:
    return f"""    <symbol type="fill" name="{idx}" alpha="0.35" clip_to_extent="1" force_rhr="0">
      <layer class="SimpleFill" enabled="1" locked="0" pass="0">
        <Option type="Map">
          <Option name="color" type="QString" value="{color}"/>
          <Option name="outline_color" type="QString" value="{color}"/>
          <Option name="outline_width" type="QString" value="0.6"/>
          <Option name="outline_style" type="QString" value="solid"/>
          <Option name="style" type="QString" value="solid"/>
        </Option>
      </layer>
    </symbol>"""


def main() -> None:
    print("start", flush=True)
    from qgis.core import QgsApplication, QgsVectorLayer

    print("imported", flush=True)

    app = QgsApplication.instance() or QgsApplication([], False)
    print("app created", flush=True)
    app.initQgis()
    print("qgis inited", flush=True)

    layers = []
    try:
        for year in (1992, 2021):
            gpkg = REPO / "data" / "samples" / str(year) / f"annotation_{year}.gpkg"
            qml = gpkg.with_suffix(".qml")
            cats, syms, entries = [], [], []
            for i, (cid, (name, color)) in enumerate(CLASSES.items()):
                cats.append(
                    f'      <category value="{cid}" symbol="{i}" label="{name}" type="int" render="1"/>'
                )
                syms.append(symbol(i, color))
                entries.append(
                    f'              <Option value="{cid}" type="int" key="{name}"/>'
                )
            text = QML_TEMPLATE.format(
                categories="\n".join(cats),
                symbols="\n".join(syms),
                map_entries="\n".join(entries),
            )
            qml.write_text(text, encoding="utf-8")
            print(f"{year}: qml written", flush=True)

            layer = QgsVectorLayer(f"{gpkg}|layername=labels_edit", f"annot_{year}", "ogr")
            print(f"{year}: 图层有效={layer.isValid()}", flush=True)
            msg, ok = layer.loadNamedStyle(str(qml))
            print(f"{year}: loadNamedStyle ok={ok} msg={msg.strip()}", flush=True)
            print(f"{year}: 渲染器={layer.renderer().type() if layer.renderer() else None}", flush=True)
            layers.append(layer)
    finally:
        # 先释放图层再退出，否则 GDAL provider 析构时会段错误
        for layer in layers:
            del layer
        layers.clear()
        import gc

        gc.collect()
        app.exitQgis()


if __name__ == "__main__":
    sys.exit(main())