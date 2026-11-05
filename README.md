# 工程实践任务 3：成都市新都区遥感分类与城市扩张分析 (1992—2021)

本项目采用 1992 年 Landsat 5 TM 与 2021 年 Landsat 8 OLI 遥感影像，基于 Python 3.11、GDAL/Rasterio、scikit-learn 随机森林、GeoPandas 与 QGIS (3.44 LTR)，构建纯离线处理流水线，实现成都市新都区 29 年跨度的土地利用/覆被分类（5 类）、精度独立评价、建设用地演变（4 类）以及 9 个街道/镇级行政单元的城市扩张时空演化定量分析。

---

## 一、 项目实际现状与成熟度 (Current Status)

根据项目最新开发与实测记录（2026-10-21 基线），项目的实际状态如下：

| 模块 / 维度 | 实际实现与验证状态 | 详情说明 |
| :--- | :---: | :--- |
| **算法库 (`src/rs_urban/`)** | **已全量实现 (100%)** | 包含配置加载、公共契约、预处理、特征提取与空间划分、随机森林训练推断、Sieve 滤波与精度评价、变化检测与街镇相交切分等全套核心模块。 |
| **CLI 入口 (`src/01~05`)** | **已全量就绪 (100%)** | 5 个标准命令行脚本均已调通，支持统一参数传参 (`--config`, `--env-file`, `--year`, `--step`)。 |
| **测试套件 (`tests/`)** | **116 项测试 100% PASS** | 覆盖 6 套单元测试 (`tests/unit/`)、端到端流水线集成测试 (`tests/integration/`)、P3 独立验收测试 (`tests/acceptance/`) 以及 QGIS 工程验证测试 (`tests/qgis/`)。 |
| **QGIS 工程与制图** | **全量装配自动化与测试通过 (100%)** | 包含 4 大自动化脚本 (`qgis/scripts/`)、5 大 QML 样式 (`qgis/styles/`)、4 套 A4 QPT 打印布局模板 (`qgis/layouts/`)、样本表单约束 (`qgis/forms/`) 以及 22 项测试 (`tests/qgis/`)。生成可移植工程 `xindu_1992_2021.qgz` 与构建清单 `project_manifest.json`。 |
| **成果报告体系** | **框架与审计完成** | 形成完整交付清单 (`reports/acceptance/delivery_package_manifest.md`)、32 项自动化核验清单 (`reports/acceptance/run-manifest.json`)、V1/V2/V3 独立验收报告及 29 年城市扩张分析报告框架 (`reports/analysis/urban_expansion.md`)。 |
| **原始影像数据整理** | **两期 L1 场景已归类** | 1992 年老版 L1T (`LT51290391992229BJC00`) 与 2021 年 L1TP (`LC08_L1TP_129039_20210205_20210303_02_T1`) 均已归类并登记至 `data/catalog/scenes.csv`；历史 129/044 错景已移出至 `excluded/` 并记录。已生成两期 30m 真彩对照预览图并由桌面 ENVI 5.6 成功联动双视窗加载。 |
| **真实业务数据缺口** | **待用户/教师提供** | **1. 2021 年新都区及 9 街镇官方行政边界**；<br>**2. 两期地表反射率 (SR) 数据**（现有为 L1 DN 产品，需获取 USGS L2 或增加辐射定标/大气校正）；<br>**3. 两期 QGIS 空间组级真值样本标注** (`data/samples/{year}/labels.gpkg`)。 |

> [!NOTE]
> 业务代码、流水线和测试套件已全部通过验证，具备端到端运行能力；当前全区真实全链路批处理仅受限于上述真实业务数据缺口（若直接运行预处理会如实提示缺少 2021 边界或选定 L2 场景）。

---

## 二、 核心科学口径与公共契约

全套算法严格遵守 [公共数据与接口契约 v1](docs/03-contracts.md) 与 [第一阶段设计规范](docs/superpowers/specs/2026-10-14-first-release-design.md)：

1. **空间参考与定量网格：**
   - 统一投影：`EPSG:32648` (WGS 84 / UTM zone 48N)。
   - 空间网格：30m 定量分析网格（外包框向外整除对齐，像元严格重合），15m 用于 2021 年 Landsat 8 全色融合展示。
2. **五类土地利用分类体系：**
   - `1` **建设用地** (`#D95F02`)：城镇与农村居民点、工矿仓储、硬化交通用地。
   - `2` **耕地** (`#E6C84F`)：水田、旱地、农业大棚等。
   - `3` **其他植被** (`#2E8B57`)：乔木林、灌木林、苗圃果园、草地。
   - `4` **水域** (`#377EB8`)：河流、水库、坑塘水面。
   - `5` **裸地** (`#B69C7D`)：平整待建地、未利用沙石裸地。
   - `0` 为 NoData / 边界外无效值。
3. **10 维光谱与指数特征：**
   - 6 个地表反射率波段：`blue`, `green`, `red`, `nir`, `swir1`, `swir2`。
   - 4 个标准化指数：$\text{NDVI}$ (植被), $\text{NDBI}$ (建筑), $\text{MNDWI}$ (水体), $\text{BSI}$ (裸土)。
   - 任一波段分母为 0 或无效时，10 维整体赋予 NoData (-9999.0)，杜绝补 0 假特征。
4. **样本独立性准则（防空间自相关泄漏）：**
   - 依据 `group_id` 实施 `GroupShuffleSplit`（25% 组留出），同一地块的多像元绝不跨越训练集与留出集。
   - 留出集划分指纹通过 `split.json` 固化，禁止根据留出集精度反向挑选模型参数。
5. **模型与精度硬门槛：**
   - 算法：随机森林 (`RandomForestClassifier`, 300 棵树, `min_samples_leaf=2`)，分年份独立建模。
   - 精度门槛：两期最终总体精度 $OA > 0.75$（0.7500 不通过）；若未达标必须保留真实混淆矩阵并如实记录原因。
6. **建设用地变化与街镇平衡：**
   - 4 种有效变化：`1` 持续建设、`2` 新增建设、`3` 减少建设、`4` 持续非建；任一期 NoData 赋值为 0，不虚构变化。
   - 街镇相交切分：相交边缘半像元按真实相交多边形面积计入，严格保障 9 个街镇各指标总和与全区指标面积守恒。

---

## 三、 完整目录结构

```text
F:\工程实践3\
├── .env                              # 本机环境变量（数据与缓存路径），Git 忽略
├── .env.example                      # 环境变量配置模板
├── configs/
│   └── project.toml                  # 核心科学配置（投影、类别、波段、超参、门槛）
├── data/
│   ├── catalog/                      # 数据源登记表（scenes, boundaries, excluded_scenes）
│   ├── interim/                      # 中间过程数据与真彩预览（preview/）
│   ├── processed/                    # 30m 标准网格、预处理反射率栅格与样本切分
│   ├── raw/
│   │   ├── boundaries/               # 历史 1990 与待补充 2021 行政区划矢量
│   │   ├── landsat/                  # 1992 (L1T)、2021 (L1TP) 及排除场景 (excluded/)
│   │   └── reference_maps/           # 参考辅助地图（栅格/矢量）
│   └── samples/                      # QGIS 标注的 labels.gpkg 真实样本
├── src/
│   ├── 01_preprocess.py              # CLI 入口 1：网格生成、SR 转换与全色融合
│   ├── 02_samples.py                 # CLI 入口 2：10 维特征计算与空间组级划分
│   ├── 03_classify.py                # CLI 入口 3：分年份随机森林拟合与整景推断
│   ├── 04_evaluate.py                # CLI 入口 4：Sieve 滤波、矢量化与混淆矩阵
│   ├── 05_analyze.py                 # CLI 入口 5：变化检测、街镇几何求交与平衡表
│   └── rs_urban/                     # 核心算法模块库（preprocess, samples, classify...）
├── tests/
│   ├── fixtures/factory.py           # 5 组合成微型测试数据工厂
│   ├── unit/                         # 6 大模块独立单元测试
│   ├── integration/test_pipeline.py  # P2 端到端流水线集成测试
│   ├── acceptance/                   # P3 独立验收测试（V1 数据, V2 精度, V3 变化）
│   └── qgis/                         # QGIS 工程构建、样式、布局与统计连接专项测试
├── qgis/
│   ├── scripts/                      # 工程装配、校验、制图导出与统计连接工具
│   ├── styles/                       # 5 大标准 QML 样式文件 (5类LULC, 4类变化, 街镇强度等)
│   ├── layouts/                      # 4 套标准 A4 横向 QPT 打印布局模板
│   ├── forms/                        # 样本图层字段约束配置与表单规则
│   ├── xindu_1992_2021.qgz           # QGIS 3.44 LTR 可移植打包工程
│   └── project_manifest.json         # 工程构建生成清单
├── outputs/
│   ├── maps/                         # 两期预览图、专题地图与 ENVI 联动截图
│   ├── models/                       # 1992 / 2021 随机森林二进制模型
│   ├── rasters/                      # 预处理 SR、LULC 分类与变化栅格
│   ├── tables/                       # 混淆矩阵、精度指标与 9 街镇扩张平衡表
│   └── vectors/                      # 分类成果 Shapefile 与变化矢量 GPKG
├── reports/
│   ├── acceptance/                   # 交付包清单、环境锁定清单与 V1/V2/V3 验收报告
│   ├── analysis/urban_expansion.md   # 29 年新都区城市扩张分析学术报告
│   └── data/                         # 数据到货缺口表与 2026-10-21 整理日志
└── docs/                             # QGIS 开发总纲、W01-W28 工作包拆解、契约及解译手册
```

---

## 四、 运行环境与安装配置

项目保持 Python / GDAL / scikit-learn / GeoPandas 的离线处理路线，所有依赖与临时文件均部署于 F 盘，不侵入 C 盘：

### 1. 运行环境信息
- **Python 版本：** Python 3.11.17 (win-64)
- **核心依赖：** GDAL 3.11、Rasterio 1.4、GeoPandas 1.2、scikit-learn 1.6、Shapely 2.1
- **环境显式锁定：** 参见 [environment-win-64.txt](reports/acceptance/environment-win-64.txt)
- **环境解释器路径：** `F:\rs-tools\envs\rs-city\python.exe`

### 2. 配置文件
- **科学参数：** [configs/project.toml](configs/project.toml)（只读核心参数，不包含机器绝对路径）。
- **本机路径与环境变量：** [.env](.env)（通过相对路径解析 `RS_DATA_ROOT`、`RS_OUTPUT_ROOT`、`RS_REPORT_ROOT` 等）。

---

## 五、 操作与运行指引

在激活 `rs-city` 环境的终端中运行以下命令：

### 1. 执行全量自动化测试套件
```powershell
# 运行全部 94 项自动化测试（单测、集成测试与验收测试）
python -m pytest

# 仅运行 P3 并行验收测试套件
python -m pytest tests/acceptance/ -v
```

### 2. 标准五阶段 CLI 全链路批处理流程
当真实业务数据全部就位后，按序执行以下命令即可产出全部矢量、栅格与报表成果：

```powershell
# -------------------------------------------------------------
# 阶段 1：空间网格与边界生成、表面反射率预处理与 15m 全色融合
# -------------------------------------------------------------
python src/01_preprocess.py --config configs/project.toml --env-file .env --step boundaries
python src/01_preprocess.py --config configs/project.toml --env-file .env --step surface --year 1992
python src/01_preprocess.py --config configs/project.toml --env-file .env --step surface --year 2021
python src/01_preprocess.py --config configs/project.toml --env-file .env --step pansharpen

# -------------------------------------------------------------
# 阶段 2：10 维特征计算与空间组级独立留出样本划分
# -------------------------------------------------------------
python src/02_samples.py --config configs/project.toml --env-file .env --year 1992
python src/02_samples.py --config configs/project.toml --env-file .env --year 2021

# -------------------------------------------------------------
# 阶段 3：随机森林分年份独立拟合与整景窗口化推断
# -------------------------------------------------------------
python src/03_classify.py --config configs/project.toml --env-file .env --year 1992
python src/03_classify.py --config configs/project.toml --env-file .env --year 2021

# -------------------------------------------------------------
# 阶段 4：GDAL Sieve 去噪滤波、Shapefile 矢量化与留出集精度评价
# -------------------------------------------------------------
python src/04_evaluate.py --config configs/project.toml --env-file .env --year 1992
python src/04_evaluate.py --config configs/project.toml --env-file .env --year 2021

# -------------------------------------------------------------
# 阶段 5：建设用地时空变化检测、9 街镇几何相交切分与面积平衡统计
# -------------------------------------------------------------
python src/05_analyze.py --config configs/project.toml --env-file .env
```

### 3. GIS 桌面协同与查看
- **QGIS 协同：** 使用 QGIS 3.44 打开 [qgis/xindu_1992_2021.qgs](qgis/xindu_1992_2021.qgs)，自动加载影像底图、分类矢量、街镇边界与变化图层。
- **ENVI 协同：** 使用已安装的 ENVI 5.6 打开 `data/interim/preview/xindu_{year}_display_rgb_30m.tif` 进行双视窗对比。

---

## 六、 待决事项与后续接入指引 (Action Items)

为使全套流水线输出正式的业务成果，需由用户或数据管理人员完成以下数据补充：

1. **补充 2021 年行政边界：**
   - 目标：新都区县级矢量（1 个面）与 2021 年 9 个街镇矢量（7 街道 2 镇）。
   - 放置路径：`data/raw/boundaries/county/2021/` 与 `data/raw/boundaries/townships/2021/`。
   - 属性要求：包含 `unit_id, name, unit_type, reference_year`，坐标系统一为 `EPSG:32648`。
   - 登记：在 `data/catalog/boundaries.csv` 中添加对应记录并将 `verification_status` 设为 `verified`。
2. **确认地表反射率数据方案：**
   - *方案 A（推荐）：* 从 USGS EarthExplorer 下载对应 129/039 轨号的 Landsat 5 与 Landsat 8 Collection 2 Level-2 (L2SP) 地表反射率产品解压至 `data/raw/landsat/{year}/level2/`；
   - *方案 B：* 在预处理流程中为现有的两期 Level-1 场景补充辐射定标与简易大气校正转换逻辑。
3. **完成 QGIS 人工样本标注：**
   - 依据 [遥感解译手册与标注指南](docs/labeling-guide.md)，在 QGIS 中结合原始影像对 5 类地类进行空间地块多边形标注。
   - 保存至 `data/samples/1992/labels.gpkg` 与 `data/samples/2021/labels.gpkg`（图层名 `labels`），确保每类至少 8 个独立地块组（`group_id`）。
4. **触发全流程执行并导出报告：**
   - 运行五阶段 CLI，核对 `outputs/tables/metrics_*.csv` 中 OA 是否突破 0.75，最后将真实统计数字更新至 `reports/analysis/urban_expansion.md`。

---

## 七、 文档导航索引

- [文档总览与导航](docs/README.md)
- [第一阶段设计规范](docs/superpowers/specs/2026-10-14-first-release-design.md)
- [公共契约与接口标准 v1](docs/03-contracts.md)
- [首版验收矩阵 (32项要求)](docs/04-acceptance.md)
- [QGIS 遥感解译与地块标注手册](docs/labeling-guide.md)
- [第一阶段交付包清单与成果说明书](reports/acceptance/delivery_package_manifest.md)
- [真实业务数据缺口表](reports/data/data_gaps.md)
- [数据整理与实测运行记录 (2026-10-21)](reports/data/2026-10-21-data-organization.md)
- [零基础算法实现全景报告](docs/07-algorithm-report.md)
- [新都区 1992—2021 年城市扩张分析学术报告](reports/analysis/urban_expansion.md)
