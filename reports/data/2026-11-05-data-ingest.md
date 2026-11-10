# 2026-11-05 真实数据入库与运行验证

## 1. 入库内容

从 `E:\工程实践3\搜集的数据`（用户已解压）复制到 `data/raw`，原件保留原位不动。复制后 104 个文件、约 3.1 GB，逐文件 SHA-256 写入 `.cache/raw-manifest.csv`。

| 原目录 | 入库位置 | 文件数 | 大小 (MB) |
| --- | --- | ---: | ---: |
| `LC08_L2SP_129039_20210205_20210303_02_T1` | `raw/landsat/2021/level2/` 同名 | 27 | 922.2 |
| `LC08_L1TP_129039_20210205_20210303_02_T1` | `raw/landsat/2021/level1/` 同名 | 24 | 1129.3 |
| `LT51290391992229BJC00_MTL` | `raw/landsat/1992/level1/LT51290391992229BJC00/` | 12 | 371.5 |
| `LT05_L2SP_129044_19920816_20200914_02_T1_ANG` | `raw/landsat/excluded/LT05_L2SP_129044_19920816_20200914_02_T1/` | 27 | 790.2 |
| `全国县级区划1990年shp` | `raw/boundaries/county/1990/全国县级区划1990年shp/` | 6 | 9.5 |

## 2. 登记表

- `catalog/scenes.csv`：2021 L2SP（selected）、2021 L1TP（selected）、1992 L1T（candidate）三行。
- `catalog/excluded_scenes.csv`：129/044 的 1992 L2SP 一行，注明为排除场景。
- `catalog/boundaries.csv`：1990 年全国县级区划一行（`reference_year=1990`、`verification_status=pending`）。
- 未知来源 URL 与下载时间留空，不编造。

## 3. 实测核验

| 检查 | 结果 |
| --- | --- |
| 编目表与 MTL 的 sensor / date / product_id / processing_level | 三行全部一致 |
| 2021 L2 必需波段 SR_B2—B7、QA_PIXEL | 齐全 |
| 2021 L2 影像 | 7681 × 7811，EPSG:32648，30 m |
| 2021 L1 B8 | 15361 × 15621，EPSG:32648，15 m |
| 2021 L2 云量（MTL `CLOUD_COVER`） | 0.42% |
| 2021 L2 QA_PIXEL 填充区占比 | 32.48%（幅宽外角点，正常） |
| 1990 县界 | EPSG:4326，2848 个县；含新都县 `CODE1990=510125` |

## 4. 两个阻塞项（均须外部补件）

1. **2021 年县区面 + 9 个街镇面缺失。** `prepare_boundaries()` 要求 `boundaries.csv` 中同时存在 `reference_year=2021` 的 `county` 行与 `township` 行，且街镇必须是面状图层。当前只有 1990 年县界（无街镇面）。
   - 失败信息：`No registered county boundary for year 2021` / `Grids and AOI mask must be prepared first via prepare_boundaries()`。
2. **1992 年缺 129/039 的 L2 地表反射率产品。** `preprocess_year()` 只接受 `L2SP`/`L2SR`；现有 129/039 只有 L1T（DN），129/044 的 L2 云量 100% 且不覆盖新都。
   - 失败信息：`No selected Level-2 scene found for year 1992`。

## 5. 当前可运行范围

`data/processed/grids/` 未生成前，`surface`、`pansharpen` 均无法执行；`02_samples`—`05_analyze` 依赖上游产物，同样阻塞。环境本身与编目核对均通过。

## 6. 回退方式

- 原件仍在 `E:\工程实践3\搜集的数据`，可随时重新复制。
- `raw` 是否被改动：比对 `.cache/raw-manifest.csv`（131 条 SHA-256）。
- 登记表：`data/catalog/*.csv` 有误可删除重写；三张表都可从 `.example.csv` 与本文档恢复。

---

# 2026-11-06 补件：1992 年 L2 与候选资料评估

## 7. 1992 年 L2 入库

用户下载 `LT05_L2SP_129039_19920816_20200914_02_T1` 后复制入库：

- 位置：`raw/landsat/1992/level2/LT05_L2SP_129039_19920816_20200914_02_T1/`，27 个文件、596 MB。
- 登记：`scenes.csv` 新增该行并置 `selected`；原 `LT51290391992229BJC00`（L1T）降为 `candidate`，仅作对照。
- 核验：编目与 MTL 的 product_id / processing_level / spacecraft / date 一致；`SR_B1`—`SR_B5`、`SR_B7`、`QA_PIXEL`、`QA_RADSAT` 齐全；7821×7091、EPSG:32648、30 m；包围盒 `103.24~105.70, 29.33~31.26` 覆盖新都。
- 基线：`.cache/raw-manifest.csv` 更新为 131 条，`raw` 合计 3.73 GB。

## 8. 候选资料评估：`D:\BaiduNetdiskDownload\全国地理基础信息数据库`

结论：**不可用于本项目边界步骤**。

| 检查项 | 实测 |
| --- | --- |
| 数据性质 | 1:400 万国家基础地理信息；县级行政界线 3407 个**面**、地级市面、县级居民地**点** |
| 乡镇/街道图层 | 全库文件名检索无「乡镇 / 街道 / town」相关文件，**不存在街镇面** |
| 是否含新都 | 有，`ADCODE99=510125`，`NAME99=新都县` |
| 坐标系 | 图层**无 `.prj`**，需人工指定 EPSG:4326 |
| 几何精度 | 新都面 498.8 km² vs 1990 年县界 518.6 km²；IoU 0.833；36.5 km² 落在 1990 县界之外（边界位移约 1—2 km） |

1:400 万的概化边界与 30 m 像元不匹配：36.5 km² 相当于约 4 万个像元的研究区归属错误，面积统计不可用；且街镇面完全缺失，`prepare_boundaries()` 的硬条件无法满足。

**仍然只缺一项：** 2021 年面状县区界 + 9 个街镇面（建议 1:1 万—1:10 万，带 `.prj`，街镇层含名称与街道/镇类型字段）。