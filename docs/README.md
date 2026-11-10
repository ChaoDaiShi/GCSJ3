# 文档导航

- **开发基线**：1.0 (2026-10-29 核验更新)
- **范围**：第一阶段完整首版与 QGIS 自动化工程集成
- **技术路线**：离线遥感科学计算流水线（Python/GDAL/scikit-learn/GeoPandas）与可复现 QGIS 工程协作（QGIS 3.44 LTR，不引入插件架构）。

---

## 核心开发文档索引

| 文档 | 解决的问题 |
| :--- | :--- |
| **[QGIS 开发与接口全景指南](qgis-development-guide.md)** | **【本阶段总纲】** 包含 20 章与 3 个附录的完整 QGIS 工程实现、科学口径、状态机、多阶段并发与可移植验收规范 |
| **[QGIS 与并发工作包拆解表 (W01-W28)](qgis-wbs-packages.md)** | 28 个可派工工作包明细、依赖拓扑、主责/复核、交付物与阶段门限 (G0-G5) |
| [完整首版设计](superpowers/specs/2026-10-14-first-release-design.md) | 离线遥感核心算法设计、研究口径与科学约束 |
| [并发开发计划](superpowers/plans/2026-10-14-first-release-parallel-plan.md) | 各工作线分工协作与阶段里程碑规划 |
| [数据目录与登记](01-data-layout.md) | 遥感影像、行政区划矢量、参考地图、真实标注样本目录布局 |
| **[数据文件使用规范与回退手册](08-data-usage-and-rollback.md)** | **【队友必读】** 数据现状核对、解压与登记步骤、七条铁律、常见错误处置、三级回退（快照/Git/重解压） |
| [2026-10-29 边界补充说明](boundary-supplement-2026-10-29.md) | 四个补充数据包的筛选、候选县界与参考地图入口、年份及坐标系限制 |
| [变更记录：15m 全色锐化改 Gram-Schmidt](changes/2026-11-09-pansharpen-gram-schmidt.md) | 融合算法由 Brovey 换为 GSA 的公式、波段范围约束、验证数据与复核/回退步骤 |
| [变更记录：新增 22 维特征堆栈](changes/2026-11-09-feature-stack-22dim.md) | `--step features` 的 22 维定义、TWI 汇流实现、DEM 平滑与纹理口径取舍、与 10 维训练口径的关系 |
| [变更记录：分类体系改为 4 类](changes/2026-11-09-four-class-switch.md) | 5 类→4 类的配置/评价/QGIS/文档同步，裸地归并规则与风险说明 |
| [样本标注手册（QGIS）](09-sample-annotation-sop.md) | labels.gpkg 的图层名/字段/坐标系要求、四类判读、group_id 编码、自检命令 |
| [样本标注手册（ArcGIS）](09b-sample-annotation-arcgis.md) | ArcGIS Pro/ArcMap 建库、2%–98% 拉伸、字段类型、批量填属性、锁文件处理 |
| **[手工标注作业单（64 组）](11-manual-annotation-worksheet.md)** | **【照这个做】**四类八组两年的逐组操作、去哪找、怎么认、自检与编号表 |
| [候选样本复核手册](10-candidate-review-sop.md) | 机器候选面（每类 15 个）的逐条复核流程与判断标准 |
| [环境配置说明](02-environment.md) | 本机变量与科学参数分离原则、F 盘离线独立环境与 QGIS 环境隔离指南 |
| [公共数据与接口契约](03-contracts.md) | 30m 公共网格、四类代码、四类变化、十维特征向量与 CLI 调用接口规范 |
| [可执行验收矩阵](04-acceptance.md) | 科学门禁（OA>0.75）、面积平衡、数据完整性及测试验证标准 |
| [决策与技术来源](05-decisions-and-sources.md) | 遥感传感器、GDAL 算法、USGS 规范与团队角色定义依据 |
| [样本解译与标注指南](labeling-guide.md) | 四类地物在 Landsat 5/8 假彩色与真彩色下的判读准则与 group_id 空间分组规范 |
| [城市扩张学术报告模板](report-template.md) | 29 年新都区城市扩张分析学术报告的标准框架与统计口径 |
| **[零基础算法实现全景报告](07-algorithm-report.md)** | **【通俗算法全解】** 面向零基础读者的全流程算法生活化比喻、数学公式、工程实现细节与防作弊机制全解 |

---

## 开发与验收使用指南

1. **总览与架构**：开发与审查人员首先阅读 [QGIS 开发全景指南](qgis-development-guide.md) 与 [公共数据与接口契约](03-contracts.md)。
2. **任务认领与派工**：按 [工作包拆解表](qgis-wbs-packages.md) 认领 W01 至 W28 切片，执行前明确可改文件、接口规范与验收断言，严禁跨模块越权修改。
3. **环境隔离规范**：严格遵守两套环境隔离原则，离线科学计算运行于 `F:\rs-tools\envs\rs-city`（Conda 环境），QGIS 工程构建与真加载运行于 QGIS 3.44 LTR 内置 Python 环境或通过标准化文件契约交互。
4. **科学门禁**：最终留出集 (Holdout) 仅在 W22 独立评价阶段一次性读取，严格遵循行真列测与未舍入 OA > 0.75 准则。
| [changes/2026-11-09-feature-19dim-22dim-comparison.md](changes/2026-11-09-feature-19dim-22dim-comparison.md) | 10 / 22 / 19 维特征对照，地形特征空间泄漏的证据与决策 |
| [changes/2026-11-09-2021-summer-scene-and-label-check.md](changes/2026-11-09-2021-summer-scene-and-label-check.md) | 2021 夏季影像入库、换季重跑结果、城镇样本错误的证据与候选面生成 |

成果报告（Word）：`reports/新都区建设用地扩张遥感分析报告_1992-2021.docx`，由 `tools/build_report_docx.py` 生成。
| [09c-manual-annotation-summer-2026-11.md](09c-manual-annotation-summer-2026-11.md) | 人工重标操作手册详版（QGIS 逐步操作、判读标准、校验导入、常见问题、时间安排）；Word 版见 `reports/新都区地类样本人工标注操作手册.docx` |
| [09d-1992-annotation-guide.md](09d-1992-annotation-guide.md) | 1992 年样本标注指南（单页版：画多大、怎么画、怎么保存、NDVI 参考值） |
| [changes/2026-11-10-1992-class23-anomaly.md](changes/2026-11-10-1992-class23-anomaly.md) | 1992 年耕地/林草分类异常的判定依据与处理方式（保留四类、如实记录、阈值敏感性证据） |
| [changes/2026-11-10-15m-product.md](changes/2026-11-10-15m-product.md) | 2021 年 15 m 分类对照产品的制作方法、限制与产物清单 |
| [changes/2026-11-10-plan-differences.md](changes/2026-11-10-plan-differences.md) | 报告新增「与团队执行方案的差异说明」；22 维对照重跑与结论修正 |
| [changes/2026-11-10-self-radiometric-correction.md](changes/2026-11-10-self-radiometric-correction.md) | 自建辐射定标 + 大气校正的实现、与 L2SP 的量化对比与不替换结论 |
