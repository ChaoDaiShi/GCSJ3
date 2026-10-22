# 第一阶段公共数据与接口契约 v1

本文件和 `configs/project.toml` 是并发工作的共同基准。以下路径、结构、类型与函数均为**未来实现约定**。当前不存在对应业务 Python 文件。I 为契约唯一维护者；修改时同时通知受影响工作线并更新验收项。

## 1. 路径与网格

下文 `data/outputs/reports` 分别指 `.env` 中的三个根目录；源码、配置、文档固定在仓库根目录下。登记表和 JSON 中的数据路径用 `/`，数据路径相对 RS_DATA_ROOT；成果路径相对 RS_OUTPUT_ROOT；报告路径相对 RS_REPORT_ROOT，不能混用基准。

公共网格 `data/processed/grids/grid_30m.json` 字段：

| 字段 | 类型与含义 |
| --- | --- |
| schema_version | 整数 1 |
| crs | 字符串 `EPSG:32648` |
| bounds | `[xmin,ymin,xmax,ymax]`，米 |
| resolution | `[30,30]`，正数像元尺寸 |
| width / height | 正整数列数/行数 |
| transform | GDAL 六项顺序 `[xmin,30,0,ymax,0,-30]` |

A 从 2021 研究区投影后外包框按 30m 向外取整：xmin/ymin 向下，xmax/ymax 向上；宽高由范围除以 30 得出。15m 网格复用相同 bounds，宽高各为两倍，保存为 `grid_15m.json`。固定范围和宽高调用 GDAL Warp，避免各年份独立裁剪后尺寸不同。Rasterio 的 Affine 参数顺序与 GDAL 不同，必须通过 `Affine.from_gdal(*transform)` 转换。[GDAL Warp](https://gdal.org/en/stable/programs/gdalwarp.html)

研究区掩膜 `aoi_30m.tif`：Byte，研究区有交集的像元为 1（all_touched），其余为 0，不设 0 为 NoData。面积计算最终与真实行政边界相交，避免把触边像元全部面积计入。两期反射率和标签沿用这个网格。

## 2. 预处理交接

| 文件 | 类型/波段 | 所有者 → 使用方 |
| --- | --- | --- |
| `data/processed/boundaries/xindu_2021.gpkg` | study_area 与 townships 两个面图层，EPSG:32648 | A → B/E/F |
| `data/processed/grids/grid_30m.json`、`grid_15m.json` | 网格参数 | A → B/C/D/E |
| `data/processed/grids/aoi_30m.tif` | Byte 研究区掩膜 | A → B/E |
| `data/processed/{year}/sr_30m.tif` | Float32，6 波段，NoData=-9999 | A → B/F |
| `data/processed/{year}/valid_sr_30m.tif` | Byte，1 有效、0 区内无效、255 区外；NoData=255 | A → B/F |
| `data/processed/2021/pan_rgb_15m.tif` | Float32，R/G/B 三波段，NoData=-9999 | A → F |
| `reports/data/catalog.json`、`preprocess_1992.json`、`preprocess_2021.json`、`pansharpen_2021.json` | 来源、输入、网格、QA、有效比例、处理参数 | A → I/F |

边界 `study_area` 至少有 `area_id/name/reference_year`；`townships` 有 `unit_id/name/unit_type/reference_year`。unit_id 是保留前导零的字符串；unit_type 为 `street/town`。不得用顺序编号代替真实来源的行政编码而不说明映射。

QA 口径：Landsat 5 排除 QA_PIXEL 位 0/1/3/4/5；Landsat 8 额外排除位 2（卷云）；不直接要求 Clear 位为 1，不排除 Water 位。TM 位 2 未使用。QA_RADSAT 仅检查所选反射波段对应饱和位，TM 同时考虑 dropped pixel，OLI 考虑 terrain occlusion。具体位表参见 [USGS QA 规范](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands)及 [TM 产品指南](https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/s3fs-public/atoms/files/LSDS-1618_Landsat-4-7_C2-L2-ScienceProductGuide-v3.pdf)。

先在源网格将无效 DN 标记为 NoData，再进行连续反射率双线性重采样；QA/掩膜用最近邻重投影。最终有效条件为重投影后的有效掩膜为 1 且六个输出波段均非 NoData。记录各掩膜理由和比例，不对有效反射率进行未经说明的 0—1 截断。

15m 融合在同一 L1 场景内按 `TOA=(Mρ×DN+Aρ)/sin(太阳高度角)` 转换，Mρ/Aρ逐波段读取MTL，角度先转弧度，再用 B8 与 RGB 做全色锐化。B8 与 RGB 的 Fill/云像元排除，RGB 饱和按对应 QA_RADSAT 位排除；Landsat 8 的 QA_RADSAT 没有单独的 B8 饱和位，不能编造该标记，B8 质量另按实际产品说明核查并记录。QA 最近邻映射到 15m。报告标记 `radiometry=TOA`、`purpose=visualization`，不能标记为 SR 或训练特征。

## 3. 特征、样本与隔离

| 文件 | 规定 |
| --- | --- |
| `data/samples/{year}/labels.gpkg` | `labels` 图层，Polygon/MultiPolygon，EPSG:32648 |
| `data/processed/{year}/features_30m.tif` | Float32，固定 10 波段，NoData=-9999 |
| `data/processed/{year}/valid_features_30m.tif` | Byte，1/0/255 同上 |
| `data/processed/samples/{year}/train.csv` | 仅训练地块的有效像元 |
| `data/processed/samples/{year}/holdout.csv` | 仅冻结的独立评价地块的有效像元 |
| `data/processed/samples/{year}/split.json` | 每个 group 的 split、种子、分组数与每类像元数 |

样本面字段：`sample_id`（唯一字符串）、`group_id`（地块组字符串）、`year`（整数）、`class_id`（1—5）、`label_source`（标签依据）、`source_date`（依据时相）、`annotator`（标注人）、`split`（unassigned/train/holdout）。同一组仅一个类别，每类至少 8 组；空间不相连的地块分别分组，邻接且本质同一地块不得拆组。不同类别样本面不能重叠，标签须避开混合地物像元和云区。

B 按 class_id 分层，对每类 group_id 执行固定种子的 GroupShuffleSplit（25% 组留出），将结果合并为全年的划分，至少 2 组/类进入 holdout。分组发生在像元展开之前；`split.json` 冻结后，重新提取特征也必须沿用同一分组，不能因重跑换一套验证样本。[分组划分 API](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html)

样本 CSV 表头固定：

```csv
sample_id,group_id,year,class_id,row,col,x,y,blue,green,red,nir,swir1,swir2,ndvi,ndbi,mndwi,bsi
```

row/col 从 0 起，x/y 是 EPSG:32648 像元中心坐标；只提取中心落在样本面内的有效像元。重复像元不能跨组或跨 split。样本表不包含不完整特征。

指数公式（使用转换后的反射率）：

```text
NDVI  = (nir - red) / (nir + red)
NDBI  = (swir1 - nir) / (swir1 + nir)
MNDWI = (green - swir1) / (green + swir1)
BSI   = ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue))
```

分母为 0 或任一输入无效时，对应像元十个特征整体标为 NoData。有效性不能用“缺失指数填 0”替代。顺序来自配置的 `features.order`，模型保存相同顺序。

## 4. 分类、去噪与评价

| 文件 | 规定 | 所有者 |
| --- | --- | --- |
| `outputs/models/{year}/rf.joblib` | dict：`estimator/feature_names/class_codes/year/config/split_sha256` | C |
| `outputs/rasters/lulc_{year}_raw_30m.tif` | Byte，类别 1—5，NoData=0，公共 30m 网格 | C |
| `reports/accuracy/training_{year}.json` | 训练组数、像元数、模型参数、训练输入摘要；不含留出调参结果 | C |
| `outputs/rasters/lulc_{year}_final_30m.tif` | Byte，去噪后类别；NoData 范围保持不变 | D |
| `outputs/vectors/{year}/lulc_{year}.shp` | 成套 SHP，含 class_id/class_name/year/area_km2 | D |
| `outputs/tables/confusion_{year}_{variant}.csv` | variant 为 raw/final；行是真值，列是预测，顺序 1—5 | D |
| `outputs/tables/metrics_{year}_{variant}.csv` | class_id/precision/recall/f1/support | D |
| `reports/accuracy/evaluation_{year}.json`、`.md` | raw 与 final 评价、OA、各类指标、样本/组数、门槛结果 | D |

C 只读取 train.csv 训练，不读 holdout.csv 进行选参；按窗口预测以控制整景内存，输出颜色表。各年分别使用同一套初始参数，RandomForestClassifier 的 random_state 明确取配置根级 random_seed=42，其他参数取 model 表。D 对 raw 应用 GDAL Sieve，默认小于 4 像元的斑块处理、8 邻接；显式传入 `(raw != 0)` 的二值有效掩膜，禁止把掩膜值 255 直接作为有效逻辑。去噪后独立评价最终图，并与原始图对照。

SHP 输出 `.shp/.shx/.dbf/.prj/.cpg`；UTF-8 编码，字段名不超过 10 字符（上述字段已满足）。矢量化跳过 NoData，裁剪至真实研究区面，面积用平方米除以 1e6。保留未四舍五入的计算值，仅在显示/报告中舍入。

OA = 混淆矩阵对角和 / 样本总数；某类没有预测时 precision 记 0 并说明，不能删除该类别；若 holdout 缺类则评价不完整，不报告为五类合格。最终验收检查 `final.oa > 0.75`，0.75 本身不通过。

## 5. 变化及街镇表

`outputs/rasters/change_1992_2021_30m.tif` 为 Byte：0=NoData，1=持续建设，2=新增建设，3=减少建设，4=持续非建设。仅在两个 final 栅格均非 0 且研究区内时分类。

`data/processed/common/valid_common_30m.tif`：1=共同有效，0=区内任一期无效，255=区外，NoData=255。统计/矢量化使用布尔表达式 `mask == 1`。

`outputs/vectors/change/urban_change.gpkg` 图层 `change`，字段 `change_id/change_name/area_km2`，保存与研究区相交后的四种有效变化面。建设面积从相同变化面汇总，保持口径一致。

`outputs/tables/township_change_1992_2021.csv` 固定表头：

```csv
unit_id,name,unit_type,boundary_year,total_area_km2,comparable_area_km2,valid_ratio,built_1992_km2,built_2021_km2,persistent_km2,added_km2,lost_km2,net_km2,annual_net_km2,annual_intensity_pct
```

字段公式：`valid_ratio=comparable_area_km2/total_area_km2`；`built_1992=persistent+lost`；`built_2021=persistent+added`。net 和年均指标按设计文档公式。9 行街镇必须保留；共同有效面积为 0 时，comparable_area=0、valid_ratio=0，建设与变化指标留空并在报告说明“无共同有效观测”，不能写成真实零扩张。年份列为统一边界年份 2021。

`outputs/tables/district_change_1992_2021.csv` 使用同一表头，单独一行区级结果；不得把总计混入 9 行街镇表。逐街镇对几何求交后的总和与区级值核对，容差 `max(1e-6 km², 区级面积×1e-6)`。报告总边界面积与共同有效面积的差异。地图全部来自本轮成果，F 不重算另一套统计。

## 6. Python 模块接口

所有类型由 I 在未来的 `src/rs_urban/contracts.py` 实现。以下字段是完整的公开接口定义，内部实现自由决定；不要创建另一个同名类型。

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass
class ProjectContext:
    root: Path
    data: Path
    outputs: Path
    reports: Path
    scratch: Path
    config: dict[str, Any]

@dataclass
class PreparedData:
    year: int
    sr: Path
    valid_sr: Path
    grid: Path
    boundaries: Path

@dataclass
class SampleData:
    year: int
    features: Path
    valid_features: Path
    train: Path
    holdout: Path
    split: Path

@dataclass
class ClassificationData:
    year: int
    model: Path
    raw: Path

@dataclass
class EvaluationData:
    year: int
    final: Path
    vectors: Path
    report: Path
    oa_raw: float
    oa_final: float

@dataclass
class ChangeData:
    raster: Path
    vectors: Path
    townships: Path
    district: Path
```

| 模块 / 所有者 | 公开函数签名 | 行为 |
| --- | --- | --- |
| config.py / I | `load_context(config_path: Path, env_file: Path) -> ProjectContext` | 解析 TOML 与本机目录，设置已声明环境变量 |
| preprocess.py / A | `prepare_boundaries(ctx: ProjectContext) -> Path` | 读边界登记，输出标准 GPKG、网格和 AOI 掩膜；返回 GPKG |
| preprocess.py / A | `preprocess_year(ctx: ProjectContext, year: int) -> PreparedData` | 读选中场景，生成 30m SR 与掩膜 |
| preprocess.py / A | `pansharpen_2021(ctx: ProjectContext) -> Path` | 输出 15m RGB 融合；返回栅格路径 |
| samples.py / B | `build_samples(ctx: ProjectContext, year: int) -> SampleData` | 生成十维特征、冻结组划分、提取样本 |
| classify.py / C | `train_predict(ctx: ProjectContext, year: int) -> ClassificationData` | 训练 RF 并预测原始分类 |
| evaluate.py / D | `finalize_evaluate(ctx: ProjectContext, year: int) -> EvaluationData` | 去噪、矢量化、在 holdout 位置评价 raw/final |
| analyze.py / E | `analyze_change(ctx: ProjectContext) -> ChangeData` | 共同有效变化、矢量相交、街镇及区级表 |

各函数按上文固定路径读写，不依赖上一进程的内存对象；可单独运行。返回值方便测试，磁盘文件是跨任务交接依据。契约级错误直接指出具体文件与问题，保留原始异常信息；不设计重试队列、自动修复或替代数据链。

## 7. 命令行接口与产物发布

以下为**开发后**使用的 PowerShell 命令；现在尚不存在脚本：

```powershell
python .\src\01_preprocess.py --config .\configs\project.toml --env-file .\.env --step boundaries
python .\src\01_preprocess.py --config .\configs\project.toml --env-file .\.env --step surface --year 1992
python .\src\01_preprocess.py --config .\configs\project.toml --env-file .\.env --step surface --year 2021
python .\src\01_preprocess.py --config .\configs\project.toml --env-file .\.env --step pansharpen
python .\src\02_samples.py --config .\configs\project.toml --env-file .\.env --year 1992
python .\src\02_samples.py --config .\configs\project.toml --env-file .\.env --year 2021
python .\src\03_classify.py --config .\configs\project.toml --env-file .\.env --year 1992
python .\src\03_classify.py --config .\configs\project.toml --env-file .\.env --year 2021
python .\src\04_evaluate.py --config .\configs\project.toml --env-file .\.env --year 1992
python .\src\04_evaluate.py --config .\configs\project.toml --env-file .\.env --year 2021
python .\src\05_analyze.py --config .\configs\project.toml --env-file .\.env
```

`--step surface` 必须指定 year；boundaries/pansharpen 不使用 year。常规运行覆盖该模块的派生文件，不改 raw 或原始 labels；重跑前由负责人归档需要保留的候选成果。更新 split 必须是有记录的样本版本变更，普通运行沿用已冻结 split。

最终 A 将三个预处理栅格复制发布到 `outputs/rasters/xindu_1992_sr_30m.tif`、`xindu_2021_sr_30m.tif`、`xindu_2021_pan_rgb_15m.tif`，与 processed 文件字节一致。F 输出 `lulc_1992.png`、`lulc_2021.png`、`urban_change_1992_2021.png`、`township_change.png` 至 outputs/maps，并完成 `reports/analysis/urban_expansion.md`。

I 汇总 `reports/acceptance/run-manifest.json`：schema_version、run_id、started_at、finished_at、code_revision、input_catalogs、config_sha256、environment_file、commands、artifacts、checks；artifacts 每项含 root（data/outputs/reports）、相对 path、size_bytes、sha256。命令记录 exit_code 与日志路径；实际无 Git 提交时 code_revision 明确为 uncommitted 并另附源码摘要。清单只收录实际存在且本次产生或验证的文件。
