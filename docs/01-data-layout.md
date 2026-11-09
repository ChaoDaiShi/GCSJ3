# 遥感数据、地图数据与成果的存放位置

默认根目录为 `E:\工程实践3`。下表均为默认**实际目录**，空目录已建立。若把数据迁移到其他目录（例如空间不足时换到 `F:` 盘），只修改 `.env` 的 `RS_DATA_ROOT`，下级结构保持一致。

## 1. 遥感影像

| 数据 | 默认位置 | 每个场景至少保留 |
| --- | --- | --- |
| 1992 年 Landsat 5 Level-2 | `E:\工程实践3\data\raw\landsat\1992\level2\<product_id>\` | SR_B1、B2、B3、B4、B5、B7，QA_PIXEL、QA_RADSAT、MTL |
| 2021 年 Landsat 8 Level-2 | `E:\工程实践3\data\raw\landsat\2021\level2\<product_id>\` | SR_B2、B3、B4、B5、B6、B7，QA_PIXEL、QA_RADSAT、MTL |
| 2021 年 Landsat 8 Level-1 | `E:\工程实践3\data\raw\landsat\2021\level1\<product_id>\` | B2、B3、B4、B8，QA_PIXEL、QA_RADSAT、MTL |

`<product_id>` 是真实 USGS 产品号，不创建名为该占位表达式的目录，不自行改官方波段文件名。优先保留完整解压产品包及元数据。数据入口为 [USGS EarthExplorer](https://earthexplorer.usgs.gov/)，本项目不实现自动登录或下载。

首版按每期一个被选中的 L2 场景及一个匹配的 2021 L1 场景设计。若实际研究区需要多景拼接，由数据负责人提交范围变化，先补充拼接契约；不暗中将多景当单景处理。候选场景可以登记多条，最终选中状态唯一。

场景选择检查：采集日期、传感器、Collection 2、处理级别、WRS path/row、研究区覆盖、研究区内云量、L1/L2 同次采集。L1 与 L2 的产品号可能不同，应按采集日期/轨道/行号与元数据匹配，不能要求整个产品号相同。

## 2. 行政地图、参考地图

| 数据 | 默认位置 | 用途 |
| --- | --- | --- |
| 1990 年县区边界原件 | `E:\工程实践3\data\raw\boundaries\county\1990\` | 对照材料中的历史区划，记录差异 |
| 2021 年县区边界原件 | `E:\工程实践3\data\raw\boundaries\county\2021\` | 提取新都区研究范围 |
| 2021 年街道与镇边界原件 | `E:\工程实践3\data\raw\boundaries\townships\2021\` | 两期统一街镇统计单元 |
| 参考栅格地图/影像 | `E:\工程实践3\data\raw\reference_maps\raster\` | 辅助判读与制图 |
| 参考矢量地图 | `E:\工程实践3\data\raw\reference_maps\vector\` | 道路、水系等辅助判读 |
| QGIS 工程 | `E:\工程实践3\qgis\xindu_1992_2021.qgz` | 标注、检查和地图布局，未来由 F 创建 |

SHP 必须成套放置，保留同名 `.shp/.shx/.dbf/.prj`，有 `.cpg` 时一并保留。GPKG 保留完整文件及原图层名。坐标系必须从元数据核实，不能因显示位置不对便直接指定为 WGS84。需要重投影时生成 `processed` 文件，不覆盖原件。

县区数据不替代街镇多边形，街镇名称表或中心点也不替代街镇边界。须核验年份、9 个单元、街道/镇类型、编码、几何范围和区级覆盖；存在缺口、重叠、错年时记录真实情况并补齐数据，不自动修补为“合格”。地图在线瓦片只作辅助底图，不用于面积计算。

当前未确认可直接使用的 2021 年街镇 SHP。2026-10-29 补充包包含县界候选、市界和参考地图，筛选结果见[边界补充说明](boundary-supplement-2026-10-29.md)；来源和使用说明写入登记表。

2026-10-21 实际整理补充：老师提供的 1992 老版 L1T 保存在 `data/raw/landsat/1992/level1/LT51290391992229BJC00/`；2021 L1TP 保存在对应 `2021/level1/<product_id>/`；标称 1990 年全国县界保存在 `boundaries/county/1990/全国县级区划1990年shp/`。不覆盖新都的旧 129/044 L2 原件保存在 `data/raw/landsat/excluded/`，仅记入 `data/catalog/excluded_scenes.csv`，不放入活动 scenes.csv。L1T 登记采用原 MTL 的场景 ID，processing_level 如实写 L1T。具体文件及试运行状态以 [data/README.md](../data/README.md) 为准；这些 L1 原件不代表已取得冻结方案要求的 L2 SR 输入。

## 3. 登记表怎样填

本机表已按实际提供数据登记，当前状态以 `data/catalog/*.csv` 与 `data/README.md` 为准。模板位于相同目录的 `*.example.csv`，模板进入 Git，本机记录不进入 Git。

### scenes.csv

位置：`data/catalog/scenes.csv`。一行表示一个场景产品。

| 字段 | 规定 |
| --- | --- |
| year / sensor | 1992 或 2021；`LANDSAT_5` 或 `LANDSAT_8` |
| processing_level | 实际 MTL 值：L2SP、L2SR 或 L1TP；优先使用 Tier 1 |
| product_id / acquisition_date | 官方产品号；ISO 日期 `YYYY-MM-DD` |
| wrs_path / wrs_row | 原始轨道/行号，保留前导零的字符串 |
| scene_dir / mtl_path | 相对于 RS_DATA_ROOT，使用 `/`；MTL 同样从数据根目录解析 |
| paired_product_id | 2021 L1/L2 填对方产品号；1992 留空 |
| source_url / downloaded_at | 实际下载页面；带时区 ISO 时间 |
| selection_status | `candidate` 或 `selected`；最终每个产品用途仅一条 selected |

### boundaries.csv

位置：`data/catalog/boundaries.csv`。一行表示一个实际边界图层。

`dataset_id` 唯一；`reference_year` 为数据所代表年份；`admin_level` 为 `county` 或 `township`；`file_path` 相对 RS_DATA_ROOT；`layer_name` 为 GPKG 图层名，SHP 填文件主名；`source_crs` 填已核实 EPSG 或 WKT；`source_url`、`acquired_at`、`license_note` 记录来源；`verification_status` 为 `pending` 或 `verified`。导入时记录字段映射，统一为 `unit_id/name/unit_type/reference_year`。

### reference_maps.csv

位置：`data/catalog/reference_maps.csv`。`dataset_id` 唯一，`map_type` 为 `raster/vector`，`reference_date` 是地图实际对应日期，`file_path` 相对 RS_DATA_ROOT，`source_crs/source_url/license_note/usage` 记录投影、来源及用途。当前地图不能冒充历史地物真值。

## 4. 样本与中间数据

- 原始样本：`data/samples/1992/labels.gpkg`、`data/samples/2021/labels.gpkg`，图层名统一 `labels`。字段见[契约](03-contracts.md)。不在本次生成空白 GPKG。
- 处理中的各线临时文件：`data/interim/A/` 至 `data/interim/F/`，每条线只写自己的目录。
- 标准边界与网格：`data/processed/boundaries/`、`data/processed/grids/`。
- 预处理和特征栅格：`data/processed/1992/`、`data/processed/2021/`。
- 样本 CSV 与划分记录：`data/processed/samples/1992/`、`data/processed/samples/2021/`。
- 共同有效掩膜：`data/processed/common/valid_common_30m.tif`。

原始数据只读使用；预处理、标注和成果分开保存，便于复现每一步。

## 5. 输出位置

| 内容 | 默认目录 |
| --- | --- |
| 预处理、分类和变化 GeoTIFF | `E:\工程实践3\outputs\rasters\` |
| 两期 SHP 和变化 GPKG | `E:\工程实践3\outputs\vectors\` |
| 混淆矩阵、分类指标、街镇 CSV | `E:\工程实践3\outputs\tables\` |
| 两期 RF 模型 | `E:\工程实践3\outputs\models\` |
| 分类图、变化图、统计图 | `E:\工程实践3\outputs\maps\` |
| 数据、精度、分析、验收报告 | `E:\工程实践3\reports\data\`、`accuracy\`、`analysis\`、`acceptance\` |

实际遥感文件、地图、样本、模型、输出与本机登记表都被 `.gitignore` 排除。提交到 Git 的是模板、配置、文档和未来源码。交作业时由 F 整理成果包，不依赖 Git 保存大体积数据。
