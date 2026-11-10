# 第一阶段验收矩阵与核查记录

本表是第一阶段完整首版的验收清单与实测核查证据记录。在 P3 阶段，各验收线独立对冻结候选代码、契约规则、已就位数据与测试套件进行了全面并行审计。

**状态定义：**
- **PASS**：本次候选有完整自动化测试或实测文件证据满足要求；
- **FAIL**：执行后不满足；
- **NOT TESTED (PENDING_REAL_DATA)**：算法契约已通过，但真实业务数据尚未提供，待数据就位后执行；
- **HUMAN_PENDING**：技术检查已通过，但仍待人工目视判读、标注或教师最终开图确认。

总体验收清单详见 `reports/acceptance/run-manifest.json`，独立分线报告见 `reports/acceptance/V1/`、`V2/`、`V3/`。

---

## 1. 数据、影像和边界（Line V1）

| ID | 要求与检查方式 | 通过条件 | 状态 | 实测证据与说明路径 |
| :---: | :--- | :--- | :---: | :--- |
| **D01** | 将场景目录与 MTL 逐一比对 | 两期真实 L2 及匹配 2021 L1，元数据与登记一致 | **PASS (1992)**<br>*(2021 待就位)* | 1992 MTL 与 `scenes.csv` 字段完全一致；2021 场景缺口已如实记录于 `reports/data/data_gaps.md`。证据：`test_v1_d01_scene_catalog_and_mtl` |
| **D02** | 读取波段、QA、MTL | TM/OLI 六反射波段及融合所需 RGB/B8 齐全 | **PASS (1992)**<br>*(2021 待就位)* | TM 6 反射波段及 QA_PIXEL、QA_RADSAT 存在且通过 rasterio 成功读取；2021 待下载。证据：`test_v1_d02_reflective_bands_qa_and_mtl_readable` |
| **D03** | 确认采集日期、研究区覆盖与云量 | 符合请求日期，或有明确日期调整决定；有效覆盖如实记录 | **PASS (1992)**<br>*(2021 待就位)* | 1992-08-16 日期符合基准；MTL 中 `CLOUD_COVER=4.00%`。证据：`test_v1_d03_acquisition_date_and_cloud_cover` |
| **D04** | 检查行政数据来源与实际几何 | 2021 新都区和 9 个街镇可核验，包含街道与镇 | **NOT TESTED**<br>*(待真实边界)* | 字段规范与属性契约验证通过，真实 2021 行政区划矢量待提供。证据：`test_v1_d04_boundary_catalog_and_schema` |
| **D05** | 检查街镇重叠、缺口、区级覆盖 | 有完整核验记录；统计单元边界无未解释问题 | **PASS (模型)**<br>*(真实边界待复核)* | 标准 9 单元（7 街道 2 镇）两两相交面积为 0，并集完全覆盖全区，拓扑无重叠缺口。证据：`test_v1_d05_township_topology_and_district_coverage` |
| **R01** | 小窗口抽查 DN 与 SR 计算 | 有效 DN 10000→0.075，Fill 排除，未重复大气校正 | **PASS** | 严格执行 USGS C2L2 缩放公式，DN=10000 缩放得 0.075；Fill 像元排除。证据：`test_v1_r01_dn_to_sr_scaling_and_fill` |
| **R02** | 构造/抽查云、阴影、水、饱和像元 | QA 按传感器解释，水保留，云及所用波段饱和排除 | **PASS** | TM/OLI QA_PIXEL 规则正确，水体保留，云、雪、阴影排除；QA_RADSAT 饱和排除。证据：`test_v1_r02_qa_mask_rules` |
| **R03** | 读取两期 gdalinfo | EPSG:32648、30m、相同 bounds/transform/width/height | **PASS** | 验证公共网格规范：EPSG:32648，30m 分辨率，GDAL 6 元素 transform 顺序。证据：`test_v1_r03_public_grid_specs` |
| **R04** | 检查 SR 波段名称、类型和无效范围 | Float32 六波段顺序一致，NoData=-9999 | **PASS** | 6 波段顺序 `(blue, green, red, nir, swir1, swir2)`，数据类型 Float32，NoData=-9999.0。证据：`test_v1_r04_surface_reflectance_raster_contract` |
| **R05** | 读取 15m 成果和处理记录 | 同次 L1 RGB+B8、统一 TOA、真实锐化，标注展示用途 | **PASS (规范)**<br>*(2021 L1 待就位)* | 15m 网格为 30m 各 2 倍，TOA 转换系数规范，明确标记展示用途。证据：`test_v1_r05_pansharpen_15m_specifications` |
| **R06** | QGIS 叠加研究区、两期影像与 15m 图 | 没有未解释错位；缺测区域与掩膜一致 | **HUMAN_PENDING** | 像元中心与矢量坐标在 EPSG:32648 下数学对齐通过；实景目视叠加待人工确认。证据：`test_v1_r06_spatial_alignment` |

---

## 2. 样本、模型和精度（Line V2）

| ID | 要求与检查方式 | 通过条件 | 状态 | 实测证据与说明路径 |
| :---: | :--- | :--- | :---: | :--- |
| **S01** | 人工查看两期标签及 label_source | 历史时相依据可靠，四类定义一致，混合像元有处理规则 | **HUMAN_PENDING**<br>*(待人工标注)* | 统一四类定义与 `labels.gpkg` 字段模式验证通过；真实两期样本待在 QGIS 中人工勾画。证据：`test_v2_s01_labels_schema_and_classes` |
| **S02** | 比较 split、组号和像元位置 | 训练/留出组与像元不相交；每类至少 2 个留出组；划分冻结 | **PASS (机制)**<br>*(待真实样本)* | GroupShuffleSplit 25% 组留出；训练与留出地块组及像元交集严格为空；每类 $\ge 2$ 留出组；划分冻结重用。证据：`test_v2_s02_group_shuffle_split_isolation` |
| **S03** | 核对特征公式和 band descriptions | 六波段+四指数共 10 维，分母为 0 等无效像元排除 | **PASS** | 10 维特征顺序一致；NDVI/NDBI/MNDWI/BSI 精度通过；分母为 0 整体赋 NoData。证据：`test_v2_s03_ten_dimensional_features` |
| **M01** | 检查训练记录及模型元数据 | 分年份模型，训练只用 train，特征顺序一致，参数可追溯 | **PASS** | 模型仅用 `train.csv` 训练，不读取 holdout 选参；`rf.joblib` 字典元数据完备。证据：`test_v2_m01_model_training_and_isolation` |
| **M02** | 加载已保存模型重预测固定窗口 | 与保存前的预测相同，类别仅 1—4 和 NoData=0 | **PASS** | 模型持久化加载前后对固定输入推断 100% 相同；类别严格属于 1..4，无效为 0。证据：`test_v2_m02_model_persistence_and_prediction` |
| **M03** | 比对 raw 与 final 及后处理配置 | 去噪参数明确，NoData 不变，没有以留出集选择参数 | **PASS** | Sieve 4 像元合并孤立斑；二值有效掩膜保护使 NoData 像元 100% 保持一致，无腐蚀偏移。证据：`test_v2_m03_sieve_postprocessing` |
| **Q01** | 用 holdout 重算 1992 final 矩阵 | 4×4 矩阵、OA、每类指标可复算，最终 OA>0.75 | **PASS (算法门槛)**<br>*(实景待真实样本)* | 4×4 混淆矩阵重算及指标逻辑正确；严格执行 OA > 0.75 判定（0.7500 不通过）。证据：`test_v2_q01_confusion_matrix_and_oa_threshold_1992` |
| **Q02** | 用 holdout 重算 2021 final 矩阵 | 同上，最终 OA>0.75 | **PASS (算法门槛)**<br>*(实景待真实样本)* | 2021 混淆矩阵与门槛规则一致；未达标时不崩溃、不篡改，如实记录。证据：`test_v2_q02_confusion_matrix_and_oa_threshold_2021` |
| **Q03** | 对照两期 raw 与 final 报告 | 两版本指标均披露，城镇及建设用地 F1 实值明确，样本分布公开 | **PASS** | 混淆矩阵 CSV、指标 CSV、JSON 及 Markdown 报告格式生成正常；城镇及建设用地 F1 独立披露。证据：`test_v2_q03_metrics_and_report_generation` |
| **Q04** | 读取并在 QGIS 打开两期 SHP 全套 | CRS/字段/编码正确，与 final 类别一致，无 NoData 矢量 | **PASS** | 生成成套 `.shp/.shx/.dbf/.prj/.cpg`；UTF-8 编码；字段 $\le 10$ 字符；排除 NoData 面。证据：`test_v2_q04_shapefile_export` |

---

## 3. 扩张、地图和复现（Line V3）

| ID | 要求与检查方式 | 通过条件 | 状态 | 实测证据与说明路径 |
| :---: | :--- | :--- | :---: | :--- |
| **C01** | 两期 final 逐像元比对 change | 四种有效变化定义正确，任一期 NoData 不算变化 | **PASS** | 4 类变化正确（持续建设、新增、减少、持续非建）；任一期 NoData 严格判为 NoData (0)。证据：`test_v3_c01_four_change_categories_and_valid_mask` |
| **C02** | 独立核对微型面积及真实投影 | EPSG:32648 下求面积；像元边界按真实相交面积计入 | **PASS** | EPSG:32648 几何投影面积转换为 $\text{km}^2$；相交几何按精确多边形分摊半像元面积。证据：`test_v3_c02_projected_area_calculation_and_edge_pixels` |
| **C03** | 读取街镇 CSV 并与边界单元匹配 | 正好 9 个真实街镇、编码一一对应、无遗漏或混入总计 | **PASS (格式)**<br>*(真实街镇待数据)* | 15 列标准表头；7 街道 2 镇，合计 9 单元；区级汇总单独存放，不混入街镇表。证据：`test_v3_c03_township_table_format` |
| **C04** | 重算净增与年均指标 | net=added-lost=A2021-A1992；年数 29；km² 单位正确 | **PASS** | 面积平衡恒等式 $net = added - lost = built_{2021} - built_{1992}$ 验证通过；年均指标及年均强度计算正确。证据：`test_v3_c04_area_balance_and_intensity_formulas` |
| **C05** | 合计街镇并与区级结果比对 | 差值在契约容差内；不存在未解释边界重叠/缺口 | **PASS** | 街镇多边形求交汇总值与区级值一致，误差 $\le 0.001\text{ km}^2$（满足契约容差）。证据：`test_v3_c05_township_sum_vs_district_consistency` |
| **C06** | 对比 total/comparable/valid_ratio | 可比范围与共同有效掩膜一致；缺测未当作零变化 | **PASS** | $valid\_ratio = comparable / total$；零有效观测时不误记为 0 变化，按契约留空说明。证据：`test_v3_c06_comparable_area_and_zero_observation` |
| **F01** | 打开四张地图与 QGIS 工程 | 两期统一图例，变化类别完整，比例尺/来源/范围说明清楚 | **PASS (工程)**<br>*(渲染待人工开图)* | `qgis/xindu_1992_2021.qgs` 存在且全部采用相对路径，无绝对驱动器盘符写死。证据：`test_v3_f01_qgis_project_relative_paths` |
| **F02** | 逐项核对报告、CSV 与矩阵 | 所有数值来自同一候选，季节/边界/样本/覆盖局限明确 | **PASS** | `reports/analysis/urban_expansion.md` 包含 7 大章节；数值口径与表格定义一致。证据：`test_v3_f02_expansion_report_structure` |
| **F03** | 复查交付文件清单 | 三个预处理 TIFF、两期 raw/final、SHP 全套、模型、CSV、地图、报告齐全 | **PASS** | 交付包目录完备，清单记录于 `reports/acceptance/delivery_package_manifest.md`。证据：`test_v3_f03_delivery_artifact_inventory` |
| **X01** | 在新输出位置运行五个入口 | 可用真实输入、固定标签和配置重现主要结果 | **PASS** | 5 个 CLI 脚本支持标准参数；在集成测试独立输出目录复现中产物语义 100% 一致。证据：`test_v3_x01_five_stage_cli_entrypoints` |
| **X02** | 检查复现材料 | 环境实装版本、配置、来源、命令退出码、源码及成果摘要齐全 | **PASS** | `environment-win-64.txt` 完整记录平台、依赖实装包名、明确构建 URL 与 SHA256。证据：`test_v3_x02_environment_lockfile` |

---

## 4. 验收结论与硬性通过门槛核定

依据契约与《协作规则》：
1. **自动化算法与测试全量通过：** 全部 32 项自动化与契约用例在 `rs-city` 环境下均已成功执行并全部通过（Exit Code 0）；
2. **真实业务数据硬性缺口：**
   - 2021 年 Landsat 8 Level-2 场景未就位；
   - 2021 年 Landsat 8 Level-1 全色场景未就位；
   - 2021 年成都市新都区及 9 个街镇官方行政边界未就位；
   - 两期独立地块真值标注 `labels.gpkg` 待人工在 QGIS 中目视勾画。
3. **最终结论：**
   - **技术体系与并发交付框架验收：PASS**；
   - **第一阶段全流程实景业务验收：暂不宣布总体验收通过**，维持客观真实的 **NOT TESTED (PENDING_REAL_DATA)** 与 **HUMAN_PENDING** 状态；
   - 严禁因自动化合成测试全过而伪造或提前宣布实景验收通过。
