# QGIS 工程约定

后续使用 QGIS 3.44 LTR 进行样本标注、图层检查和制图；此次不安装 QGIS、不生成空壳工程。

- 统一工程文件：`qgis/xindu_1992_2021.qgz`，由 F 工作线维护。
- 工程坐标系：EPSG:32648；工程内尽量保存相对路径。
- 样本编辑：B 工作线维护 `data/samples/1992/labels.gpkg` 和 `data/samples/2021/labels.gpkg`；F 只引用样本，不另建副本。
- 图例编码与配色来自 `configs/project.toml`，两个年份保持一致。
- 在线底图仅用于辅助定位；不能作为 1992 年地物标签依据，也不能替代 2021 年街镇边界。
- 最终地图放 `outputs/maps/`，工程、样本与生成地图不进入 Git。
