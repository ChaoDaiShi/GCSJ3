# 工程实践任务 3：成都市新都区遥感分类与城市扩张分析 (1992—2021)

本项目采用 1992 年 Landsat 5 TM 与 2021 年 Landsat 8 OLI 夏季地表反射率影像，基于 Python 3.11、GDAL/Rasterio、scikit-learn 随机森林、GeoPandas 与 QGIS (3.44 LTR)，构建纯离线处理流水线，完成成都市新都区 29 年跨度的土地利用/覆被分类（4 类）、留出集精度评价、建设用地变化检测，以及 9 个街道/镇级行政单元的城市扩张时空定量分析。

---

## 一、 项目实际现状与成果数字 (Current Status)

根据 2026-11-10 的最新实测记录，项目的实际状态如下：

| 模块 / 维度 | 状态 | 说明 |
| :--- | :---: | :--- |
| **算法库 (`src/rs_urban/`)** | **已实现** | 配置加载、公共契约、预处理、19 维特征提取、空间组级划分、随机森林训练推断、Sieve 滤波、精度评价、变化检测与街镇相交切分。 |
| **CLI 入口 (`src/01~05`)** | **已就绪** | 5 个脚本调通，支持 `--config`、`--env-file`、`--year`、`--step`。 |
| **测试套件 (`tests/`)** | **117 项，116 通过 / 1 跳过 / 0 失败** | 单元测试、端到端集成、P3 验收、QGIS 工程验证。 |
| **QGIS 工程与制图** | **已装配** | 5 个自动化脚本、5 个 QML 样式（4 类 LULC、4 类变化、街镇强度等）、4 套 A4 QPT 布局；生成 `xindu_1992_2021.qgz` 与构建清单。 |
| **分类成果** | **两期已完成** | 1992 与 2021 年四类分类栅格、矢量、变化检测、9 街镇统计表均已产出。 |
| **15 m 产品** | **2021 单年，仅展示** | 全色融合 + 分类对照产品；1992 年无免费 15 m 数据，不进入变化统计。 |
| **数据与样本** | **已全部就位** | 两期 L2SP 地表反射率、新都区与 9 街镇行政边界、两期人工判读样本。 |
| **报告** | **已定稿** | Word 8 章 / 18 表 / 5 图；Markdown 版 10 节，含「与团队执行方案的差异说明」。 |

### 核心数字（引用基准）

| 指标 | 1992 | 2021 |
| :--- | ---: | ---: |
| 留出集总体精度 (OA) | **0.9247** | **0.8676** |
| 建设用地面积 | 20.94 km² | 110.42 km² |
| 占全区比例 | 4.2% | 22.2% |

全区净增 **89.47 km²**，年均 3.09 km²，年均扩张强度 0.62%；新增建设用地 81.7% 位于 1992 年建成区 600 m 范围内。

> [!IMPORTANT]
> 三条必须随数字一起引用的口径：
> 1. **精度是内部一致性，不是独立精度**——像元纯度过滤把城镇限定在 NDVI ≤ 0.45、水体限定在 MNDWI ≥ 0，留出像元与训练规则同源；
> 2. **1992 年耕地/林草分项面积不可引用**——两类光谱可分性不足，仅建设用地与水体可靠（原因见报告第 7 节）；
> 3. **15 m 产品只用于展示**——两期无法同时获得 15 m 数据，不可用于变化检测。

---

## 二、 核心科学口径与公共契约

全套算法严格遵守 [公共数据与接口契约 v1](docs/03-contracts.md) 与 [第一阶段设计规范](docs/superpowers/specs/2026-10-14-first-release-design.md)：

1. **空间参考与定量网格：**
   - 统一投影：`EPSG:32648`（WGS 84 / UTM zone 48N）。
   - 分析网格：30 m（1356 × 1070，全区 497.03 km²，9 镇街）；15 m 网格仅用于 2021 年对照产品（2712 × 2140）。
2. **四类土地利用分类体系：**
   - `1` **城镇及建设用地** (`#D95F02`)：城镇与农村居民点、工矿仓储、硬化交通用地、在建工地与待建裸土。
   - `2` **耕地** (`#E6C84F`)：水田、旱地、农业大棚等。
   - `3` **林草植被** (`#2E8B57`)：乔木林、灌木林、苗圃果园、草地、川西林盘竹冠。
   - `4` **水体** (`#377EB8`)：河流、水库、坑塘水面。
   - `0` 为 NoData / 边界外无效值。`outputs/rasters/lulc_*_3class_30m.tif` 为耕地与林草合并的三类稳健性对照。
3. **19 维特征张量：**
   - 6 个地表反射率波段：`blue`, `green`, `red`, `nir`, `swir1`, `swir2`。
   - 7 个标准化指数：NDVI、SAVI、MNDWI、NDBI、UI、BSI、IBI。
   - 6 个纹理特征（5 × 5 窗口）：`nir_mean/std`、`red_mean/std`、`swir1_mean/std`。
   - 任一波段分母为 0 或无效时，特征整体赋 NoData(-9999.0)，杜绝补 0 假特征。
   - **地形三项（elevation/slope/twi）未启用**：两期对照显示其作用方向相反，统一口径时不采用，理由见报告第 7.4 节。
4. **样本与纯度控制：**
   - 两期样本全部为**人工判读多边形**（1992 年 45 个面、2021 年 44 个面，`label_source=manual_annotation`）。
   - 像元纯度过滤按年份分别配置阈值，剔除混合像元后再进入训练；过滤可能整组剔除，训练报告同时记录「划分组数」与「存活组数」。
   - 依据 `group_id` 实施 `GroupShuffleSplit`（25% 组留出），同一地块的多像元绝不跨越训练集与留出集；划分指纹由 `split.json` 固化。
5. **模型与精度硬门槛：**
   - 算法：随机森林（`RandomForestClassifier`，300 棵树，`min_samples_leaf=2`，`class_weight=balanced_subsample`），分年份独立建模。
   - 精度门槛：两期最终 OA > 0.75；未达标必须保留真实混淆矩阵并如实记录原因。
6. **建设用地变化与街镇平衡：**
   - 变化栅格四类编码：`1` 持续建设、`2` 新增建设、`3` 减少建设、`4` 持续非建设；报告正文统计前三类面积，第四类用于闭合掩膜总面积。
   - 街镇相交切分按真实相交多边形面积计入，保障 9 个街镇指标总和与全区守恒。

---

## 三、 完整目录结构

```text
E:\工程实践3\GCSJ3\
├── .env                              # 本机环境变量（数据与缓存路径），Git 忽略
├── .env.example                      # 环境变量配置模板
├── configs/
│   └── project.toml                  # 核心科学配置（投影、类别、19 维顺序、纯度阈值、超参、门槛）
├── data/
│   ├── catalog/                      # 数据源登记表（scenes, boundaries, excluded_scenes）
│   ├── processed/                    # 30m 网格、地表反射率、19 维特征、样本切分、自建定标诊断
│   │   ├── 1992/ 2021/               # sr_30m、valid_sr_30m、features/、samples/、boundaries/
│   │   └── selfcal/                  # （交付包内）自建定标+大气校正结果，未用于正式成果
│   ├── raw/
│   │   ├── boundaries/               # 行政区划矢量
│   │   ├── landsat/                  # 1992 L1T/L2SP、2021 L1TP/L2SP 及排除场景 (excluded/)
│   │   └── reference_maps/           # 参考辅助地图
│   └── samples/                      # 人工判读 labels.gpkg（1992 年 45 面、2021 年 44 面）
├── src/
│   ├── 01_preprocess.py              # 网格、边界、地表反射率、15m 全色融合、19 维特征
│   ├── 02_samples.py                 # 样本提取、纯度过滤、空间组级划分
│   ├── 03_classify.py                # 分年份随机森林拟合与窗口化推断
│   ├── 04_evaluate.py                # Sieve 滤波、矢量化与混淆矩阵
│   ├── 05_analyze.py                 # 变化检测、街镇求交与平衡表
│   └── rs_urban/                     # 核心算法模块库
├── tests/
│   ├── fixtures/factory.py           # 合成微型测试数据工厂
│   ├── unit/                         # 模块单元测试
│   ├── integration/test_pipeline.py  # 端到端流水线集成测试
│   ├── acceptance/                   # P3 独立验收测试
│   └── qgis/                         # QGIS 工程构建、样式、布局与统计连接测试
├── qgis/
│   ├── scripts/                      # 装配、校验、制图导出、统计连接、标注样式（5 个）
│   ├── tools/                        # 标注/候选图层加载工具
│   ├── styles/                       # QML 样式（lulc_4class、change_4class、township 等）
│   ├── layouts/                      # 4 套 A4 横向 QPT 布局
│   ├── forms/                        # 样本图层字段约束
│   ├── xindu_1992_2021.qgz           # 可移植打包工程
│   └── project_manifest.json         # 工程构建清单
├── tools/                            # 分析/制图/文档/诊断脚本（15m 分类、PIF、自建定标、报告生成、交付打包等）
├── outputs/
│   ├── maps/                         # 专题图与对照图
│   ├── models/                       # 两期随机森林模型
│   ├── rasters/                      # 分类、变化、15m 对照栅格
│   ├── tables/                       # 混淆矩阵、精度指标、9 街镇平衡表
│   ├── vectors/                      # 分类矢量与变化矢量
│   └── variant_22dim_2026-11-10/     # 22 维对照实验归档
├── reports/
│   ├── accuracy/                     # 精度 JSON/MD、15m 说明、PIF 诊断、自建定标对比
│   ├── analysis/urban_expansion.md   # 29 年扩张分析报告（10 节）
│   ├── acceptance/                   # 交付清单、环境锁定与验收报告
│   └── data/                         # 数据缺口表与整理日志
└── docs/                             # 契约、验收、环境、标注手册、变更记录（docs/changes/）
```

---

## 四、 运行环境与安装配置

项目保持 Python / GDAL / scikit-learn / GeoPandas 的离线处理路线，依赖与临时文件均部署于 F 盘，不侵入 C 盘：

### 1. 运行环境信息
- **Python 版本：** Python 3.11.18 (win-64)
- **核心依赖：** GDAL 3.12.3、Rasterio 1.4.4、GeoPandas 1.2.0、scikit-learn 1.9.1、Shapely 2.2.0
- **环境显式锁定：** 参见 [environment-win-64.txt](reports/acceptance/environment-win-64.txt)
- **环境解释器路径：** `F:\rs-tools\envs\rs-city\python.exe`
- **激活方式：** 仓库根目录执行 `. .\activate-rs-city.ps1`；安装与实测记录见 [环境配置说明](docs/02-environment.md#31-本机实际安装记录2026-11-05)

### 2. 配置文件
- **科学参数：** [configs/project.toml](configs/project.toml)（只读核心参数，不含机器绝对路径）。
- **本机路径：** [.env](.env)（解析 `RS_DATA_ROOT`、`RS_OUTPUT_ROOT`、`RS_REPORT_ROOT` 等，可用同名环境变量覆盖）。

---

## 五、 操作与运行指引

在仓库根目录先执行 `. .\activate-rs-city.ps1` 激活 `rs-city` 环境，再运行：

### 1. 测试套件
```powershell
# 全部 117 项（116 通过 / 1 跳过）
python -m pytest

# 仅 P3 验收
python -m pytest tests/acceptance/ -v
```

### 2. 标准五阶段 CLI 全链路
```powershell
# 阶段 1：网格与边界、地表反射率、15m 全色融合
python src/01_preprocess.py --config configs/project.toml --env-file .env --step boundaries
python src/01_preprocess.py --config configs/project.toml --env-file .env --step surface --year 1992
python src/01_preprocess.py --config configs/project.toml --env-file .env --step surface --year 2021
python src/01_preprocess.py --config configs/project.toml --env-file .env --step pansharpen

# 阶段 2：19 维特征、纯度过滤与空间组级划分
python src/02_samples.py --config configs/project.toml --env-file .env --year 1992
python src/02_samples.py --config configs/project.toml --env-file .env --year 2021

# 阶段 3：随机森林分年份拟合与窗口化推断
python src/03_classify.py --config configs/project.toml --env-file .env --year 1992
python src/03_classify.py --config configs/project.toml --env-file .env --year 2021

# 阶段 4：Sieve 去噪、矢量化与留出集精度评价
python src/04_evaluate.py --config configs/project.toml --env-file .env --year 1992
python src/04_evaluate.py --config configs/project.toml --env-file .env --year 2021

# 阶段 5：变化检测、9 街镇求交与平衡统计
python src/05_analyze.py --config configs/project.toml --env-file .env
```

### 3. 专项脚本（`tools/`）
```powershell
# 2021 年 15m 对照产品（仅展示）
python tools\classify_2021_15m.py
python tools\render_15m_compare.py

# 辐射诊断
python tools\pif_radiometric_check.py          # PIFs 两期一致性
python tools\self_radiometric_correction.py    # 自建定标+大气校正

# 报告与交付
python tools\build_report_docx.py              # 需 python-docx 环境
python tools\build_delivery_package.py         # 生成含 manifest 的交付压缩包
```

### 4. GIS 桌面协同
- **QGIS：** 用 QGIS 3.44 打开 [qgis/xindu_1992_2021.qgs](qgis/xindu_1992_2021.qgs)，自动加载影像底图、分类矢量、街镇边界与变化图层。
- **ENVI：** 打开 `data/interim/preview/xindu_{year}_display_rgb_30m.tif` 做双视窗对比。

---

## 六、 已完成与剩余工作

### 已完成

| 项 | 结果 |
| :--- | :--- |
| 模块 A 预处理与特征工程 | 定标/大气校正（采用 L2SP 并自建验证）、掩模裁剪、2021 15m 融合、19 维特征、双轨输出 |
| 模块 B 分类 | 两期 4 类分类、纯度过滤、组级留出、Sieve 去噪、混淆矩阵 |
| 模块 C 扩张分析（基础部分） | 全区变化、9 街镇速度与强度、距离分级空间格局 |
| 模块 D 制图与报告 | 4 套 QGIS 布局、成图、Word/Markdown 报告 |

### 剩余与主动偏离

| 项 | 状态 | 说明 |
| :--- | :--- | :--- |
| 22 维特征 | **主动不采用** | 两期对照中地形作用方向相反，统一口径保持 19 维（报告 7.4） |
| 1992 年 15 m | **客观不可得** | Landsat 5 TM 无全色波段，SPOT 需商业授权 |
| 模块 C 进阶维度 | **未做** | LEI 三模式、微地形梯度、TWI 洪涝、转移矩阵桑基图、GeoDetector |
| 模块 B 方案细节 | **未做** | OBIA 超像素、Stacking 集成、DenseCRF 平滑（现为逐像元 RF + Sieve） |

差异的逐条依据见 [报告第 7 章](reports/analysis/urban_expansion.md) 与 `docs/changes/`。

---

## 七、 文档导航索引

- [文档总览与导航](docs/README.md)
- [公共契约与接口标准 v1](docs/03-contracts.md)
- [首版验收矩阵 (32 项要求)](docs/04-acceptance.md)
- [零基础算法实现全景报告](docs/07-algorithm-report.md)
- [遥感解译与样本标注手册](docs/labeling-guide.md)
- [1992 年标注指南](docs/09d-1992-annotation-guide.md)
- [新都区 1992—2021 年扩张分析报告](reports/analysis/urban_expansion.md)
- [方法与口径变更记录](docs/changes/)
- [精度与辐射诊断](reports/accuracy/)
- [交付包清单](reports/acceptance/delivery_package_manifest.md)
- [真实数据缺口表](reports/data/data_gaps.md)
- [环境配置说明](docs/02-environment.md)