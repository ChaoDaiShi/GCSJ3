# 交付包清单（F03）

- 生成日期：2026-11-09
- 项目：成都市新都区 1992—2021 年遥感分类与建设用地扩张分析（4 类体系）
- 坐标/网格：EPSG:32648，30 m 公共分析网格（15 m 仅作 2021 展示）

## 1. 配置与代码

| 路径 | 说明 |
| --- | --- |
| `configs/project.toml` | 主配置（CRS、网格、缩放系数、类别、特征、评价门槛） |
| `.env.example` / `.env` | 数据根目录与场景路径模板 |
| `environment.yml` / `reports/acceptance/environment-win-64.txt` | 依赖与实装版本锁定 |
| `src/01_preprocess.py` … `src/05_analyze.py` | 五阶段 CLI 入口 |
| `src/rs_urban/` | 预处理、样本、分类、评价、分析模块 |
| `tests/` | 单元 / 集成 / 验收 / QGIS 测试 |

## 2. 中间与最终栅格（`outputs/rasters/`）

| 文件 | 内容 | 规格 |
| --- | --- | --- |
| `xindu_1992_sr_30m.tif` | 1992 地表反射率 | 6 波段 Float32，NoData −9999，EPSG:32648，30 m |
| `xindu_2021_sr_30m.tif` | 2021 地表反射率 | 同上 |
| `xindu_2021_pan_rgb_15m.tif` | 2021 全色锐化展示影像 | 15 m，RGB |
| `xindu_1992_features_30m.tif` / `xindu_2021_features_30m.tif` | 特征栈 | 22 波段 |
| `lulc_1992_raw_30m.tif` / `lulc_2021_raw_30m.tif` | 随机森林原始分类 | 0–4 |
| `lulc_1992_final_30m.tif` / `lulc_2021_final_30m.tif` | Sieve 后处理成品 | 0–4，0 为 NoData |
| `change_1992_2021_30m.tif` | 四类变化 | 0–4 |

## 3. 矢量（`outputs/vectors/`）

| 文件 | 内容 |
| --- | --- |
| `1992/lulc_1992.shp` 全套（.shp/.shx/.dbf/.prj/.cpg） | 1992 分类面，UTF-8 |
| `2021/lulc_2021.shp` 全套 | 2021 分类面 |
| `change/urban_change.gpkg` | 四类变化面（持续建设 / 新增 / 减少 / 持续非建设） |

## 4. 统计表（`outputs/tables/`）

| 文件 | 内容 |
| --- | --- |
| `confusion_{1992,2021}_{raw,final}.csv` | 4×4 混淆矩阵 |
| `metrics_{1992,2021}_{raw,final}.csv` | 每类 precision/recall/F1 |
| `township_change_1992_2021.csv` | 9 个街镇的建成区与净增指标（15 列） |
| `district_change_1992_2021.csv` | 区级汇总 |

## 5. 地图（`outputs/maps/`，300 dpi PNG）

| 文件 | 内容 |
| --- | --- |
| `lulc_1992.png` | 1992 土地覆被现状图 |
| `lulc_2021.png` | 2021 土地覆被现状图 |
| `urban_change_1992_2021.png` | 建设用地变化图 |
| `township_change.png` | 街镇扩张强度分级图 |

## 6. 报告

| 文件 | 内容 |
| --- | --- |
| `reports/accuracy/evaluation_{1992,2021}.md/.json` | 精度评价（含未达标如实记录） |
| `reports/accuracy/sampling_{1992,2021}.md` | 样本与划分摘要 |
| `reports/analysis/urban_expansion.md` | 扩张分析报告（7 章，含局限性与结论限定） |
| `reports/analysis/statistics.json` | 分析数值机器可读版 |
| `reports/data/data_gaps.md` | 数据缺口登记 |
| `reports/data/preprocess_*.json`、`features_*.json`、`pansharpen_2021.json` | 各阶段元数据 |
| `reports/acceptance/environment-win-64.txt` | 环境实装记录 |
| `reports/acceptance/delivery_package_manifest.md` | 本文件 |

## 7. 模型与 QGIS 成果

| 文件 | 内容 |
| --- | --- |
| `outputs/models/1992/rf.joblib`、`outputs/models/2021/rf.joblib` | 分年份随机森林（含训练元数据） |
| `qgis/xindu_1992_2021.qgs` | QGIS 工程（相对路径，含 4 个打印布局） |
| `qgis/styles/*.qml` | 4 类分类、变化、街镇强度的符号化样式 |
| `qgis/layouts/*.qpt` | 4 个出图模板 |

## 8. 未纳入交付（明确排除）

- 原始卫星影像（按契约留在 Git 与交付包之外，路径见 `.env`）。
- `data/processed/` 全量中间产物（可由 01/02 阶段重算）。
- 样本标注的可视化底图 (`outputs/rasters/display/`) 属辅助文件，随包提供但不作为成果引用。

## 9. 复现方式

```powershell
cd 'E:\工程实践3\GCSJ3'
. .\activate-rs-city.ps1
python -X utf8 src\01_preprocess.py --config configs\project.toml --env-file .env --step boundaries
python -X utf8 src\01_preprocess.py --config configs\project.toml --env-file .env --step surface --year 2021
python -X utf8 src\01_preprocess.py --config configs\project.toml --env-file .env --step surface --year 1992
python -X utf8 src\01_preprocess.py --config configs\project.toml --env-file .env --step features --year 2021
python -X utf8 src\01_preprocess.py --config configs\project.toml --env-file .env --step features --year 1992
python -X utf8 src\02_samples.py  --config configs\project.toml --env-file .env --year 2021
python -X utf8 src\03_classify.py --config configs\project.toml --env-file .env --year 2021
python -X utf8 src\04_evaluate.py --config configs\project.toml --env-file .env --year 2021
python -X utf8 src\05_analyze.py --config configs\project.toml --env-file .env
```

地图重建：

```powershell
python -X utf8 qgis\scripts\build_project.py --config configs\project.toml --env-file .env --project qgis\xindu_1992_2021.qgs --mode release
& 'D:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' qgis\scripts\export_layouts.py --project qgis\xindu_1992_2021.qgs --export-dir outputs\maps
```

**注**：样本变更后必须先删 `data/processed/samples/<year>/split.json` 再跑 02。