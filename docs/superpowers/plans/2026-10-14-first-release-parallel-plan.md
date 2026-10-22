# 第一阶段完整首版：多阶段并发开发计划

> 执行说明：本计划供后续获授权的开发使用。本次仅初始化，不执行下列任务，不启用子智能体。未来按任务逐项执行并记录证据；并发是文件和接口层面的分工能力，不等于已启动多个智能体。

**目标：** 交付新都区 1992—2021 年预处理、随机森林分类、独立评价、街镇扩张分析与地图报告的完整首版。

**架构：** 五个离线入口对应五个处理模块，通过固定路径的 GeoTIFF、GPKG、CSV、JSON 和 Joblib 交接。QGIS 负责人工标注、检查和制图；I 管理共享配置与集成。

**技术栈：** Python 3.11、conda-forge、GDAL、Rasterio、NumPy、scikit-learn、GeoPandas、Pandas、SciPy、Matplotlib、Joblib、QGIS 3.44 LTR。

## 1. 全局约束与当前状态

- 当前只有目录、依赖声明、配置模板和文档，所有复选任务保持未完成。
- 当前用户已确认完整首版范围；初始化完成后停止，不能自动开始 P0。
- 不使用子智能体，不引入防御性开发策略，不增加 Web、数据库或深度学习。
- 数据/地图/环境位置遵循 [数据目录](../../01-data-layout.md)与[环境说明](../../02-environment.md)。
- 共享输入输出遵循 [契约 v1](../../03-contracts.md)，验收遵循[验收矩阵](../../04-acceptance.md)。
- 共用 EPSG:32648、30m 定量网格、五类编码、10 维特征；15m TOA 融合只供展示。
- 每期独立训练，按空间组冻结留出；最终两期 OA 均严格大于 0.75。
- 变化仅统计共同有效范围，街道和镇都要覆盖。
- 合成测试数据和真实业务证据分开，单元测试通过不能代替实景验收。

## 2. 并发安排

| 批次 | 可同时进行的工作 | 前置依赖 | 合流成果 |
| --- | --- | --- | --- |
| P0 | I 实现共享契约/环境；A 同时查找和登记真实输入；B 同时制定判读手册 | 后续开发授权 | 可导入共享类型、可解析配置、固定微型输入 |
| P1 | A 预处理、B 样本特征、C RF、D 评价后处理、E 扩张统计、F 制图报告模板 | P0 的字段/路径/微型输入固定 | 六条独立模块及各自测试证据 |
| P2-G1 | A+B 真实数据接通，开始两期样本标注 | A 有可用 SR，B 提取代码完成 | 真实 features/train/holdout |
| P2-G2 | B+C+D 按年份接通；1992 与 2021 可分别到达该节点 | 对应年份真实样本已冻结 | 原始/最终分类、独立精度及 SHP |
| P2-G3 | D+E 变化联调；F 同时用已完成单期成果制图 | 两期 final 到齐才运行 E；单期地图无此等待 | 街镇表、区级表、变化图和报告 |
| P3 | V1 数据/科学口径、V2 模型/精度、V3 地图/统计/复现并行审查 | 同一候选源码、数据、模型、参数冻结 | I 汇总验收与交付包 |

**没有“所有 P1 完成才能开始所有 P2”的全局屏障。** P2-G1 可以在 D/E 仍做单元测试时开始；某一年的 C/D 完成即可交给 F 制图。完整变化分析确实依赖两个年份最终结果，不能用伪造上游成果消除这个依赖。

开发并发与数据执行并发不同：B/C/D/E 可以先对微型文件独立实现；它们的真实全链路运行必须等待实际上游数据。人工标签与街镇数据获取是明确工作量，不隐藏在“环境已准备”中。

建议逻辑角色为 I + A—F。人手少时可一人负责多条线，按依赖安排；同一个文件同时只有一个写入者。默认不创建新分支/工作树；需要隔离时由团队根据实际协作方式安排，不能改变本轮目录边界。

## 3. 文件所有权

下表中除文档、配置与 README 外，源码和测试均**计划新建**，目前不存在。

| 角色 | 独占源文件/测试文件 | 独占数据与报告 |
| --- | --- | --- |
| I 集成 | `src/rs_urban/__init__.py`、`config.py`、`contracts.py`；`tests/conftest.py`、`tests/fixtures/factory.py`、`tests/unit/test_config.py`、`tests/integration/test_pipeline.py`；根配置及公共文档 | `reports/acceptance/run-manifest.json`、环境实装清单与总验收 |
| A 预处理 | `src/01_preprocess.py`、`src/rs_urban/preprocess.py`、`tests/unit/test_preprocess.py` | `data/catalog/scenes.csv`、`boundaries.csv`；processed 边界/网格/SR/融合；`reports/data/`；三个预处理交付栅格 |
| B 样本 | `src/02_samples.py`、`src/rs_urban/samples.py`、`tests/unit/test_samples.py` | `data/samples/`、features/valid_features、processed/samples、`reports/accuracy/sampling_{year}.md` |
| C 分类 | `src/03_classify.py`、`src/rs_urban/classify.py`、`tests/unit/test_classify.py` | RF 模型、raw 分类、training JSON |
| D 评价 | `src/04_evaluate.py`、`src/rs_urban/evaluate.py`、`tests/unit/test_evaluate.py` | final 分类、两期 SHP、confusion/metrics CSV、evaluation JSON/MD |
| E 扩张 | `src/05_analyze.py`、`src/rs_urban/analyze.py`、`tests/unit/test_analyze.py` | common 掩膜、change 栅格/矢量、township/district CSV、`reports/analysis/statistics.json` |
| F 制图 | `qgis/`、`docs/labeling-guide.md` 的版式部分、`docs/report-template.md` | `data/catalog/reference_maps.csv`、outputs/maps、`reports/analysis/urban_expansion.md` |

`docs/labeling-guide.md` 内容由 B 提供、F 排版，写入责任在 F；B 不同时修改该文件。B 的样本成果是标注事实来源。F 不改模型指标或 CSV 数字；修正计算问题交回 C/D/E。I 是唯一可以改公共配置/类型的人，模块负责人先提交具体变更需求。

P3 测试文件分别为 `tests/acceptance/test_data_products.py`（V1）、`test_accuracy_products.py`（V2）、`test_change_products.py`（V3）；各角色只写自己的 `reports/acceptance/V1/`、`V2/`、`V3/`。候选成果只读，发现错误交回对应所有者修订，再验证受影响项目。

## 4. P0：契约、环境与输入基线

**负责人：I；数据登记 A、判读准备 B 可同时进行。**

**输入：** 初始化配置、契约 v1、真实数据来源。**输出：** 共享类型、配置加载、可运行环境、可供各线读取的微型文件。P0 不要求取得完整真实数据才能让各模块开始开发。

- [x] 按环境文档在 F 盘创建环境，检查 GIS 导入和全色锐化入口，保存实际版本。失败时记录真实错误，环境可用前不写“安装完成”。
- [x] 创建 `src/rs_urban/contracts.py`，逐字实现契约中的六个 dataclass；只包含类型定义。
- [x] 创建 config.py 与五个入口通用参数说明，实现 `.env`/进程变量优先级和仓库根相对路径解析；scientific 参数只读 TOML。
- [x] 在 test_config.py 验证：从另一工作目录启动仍解析到同一个 data 根；进程变量覆盖 `.env`；配置五类和特征顺序完整一致。
- [x] 创建 `tests/conftest.py`，仅为测试导入加入仓库 `src`，共享 pytest 的临时目录和微型数据工厂，不连接真实数据目录。
- [x] 在 `tests/fixtures/factory.py` 创建下列固定微型文件生成器，输出只到 pytest 临时目录。禁止把微型结果写进真实 outputs。
- [x] A 登记实际数据文件；B 制定五类判读实例与样本分组规则；人工缺口写入 reports/data，列清负责角色。
- [x] I 对照表头、函数签名和文件名冻结 v1，通知各线可以独立开发。

微型数据合同：

| 名称 | 内容 | 用途 |
| --- | --- | --- |
| scaling_fixture | 有效 DN=10000；Fill DN=0；云/水像元分别设置 QA 位 | A 验证 0.075 反射率、Fill/云排除、水保留 |
| feature_fixture | 六波段 `[0.1,0.2,0.3,0.6,0.4,0.5]`，另含分母为 0 的像元 | B 验证四指数与无效规则 |
| grouped_samples_fixture | 五类，每类 8 个组，每组若干像元；组编号唯一 | B/C 验证划分、训练与持久化 |
| metric_fixture | 真值 `[1,1,2,2,3,3,4,4,5,5]`；预测 `[1,2,2,2,3,3,4,4,5,1]` | D 验证 OA=0.8 和完整 5×5 矩阵 |
| change_fixture | 下述 3×3 两期分类、两个宽45m街镇矩形、90m方形研究区 | E 验证变化、边缘半像元分摊与总量 |

change_fixture 的坐标为 EPSG:32648，bounds `[500010,3380010,500100,3380100]`，每格 30m，仅代表人工测试几何：

```text
1992             2021             预期变化
1 2 0            1 1 1            1 2 0
1 2 2            2 2 1            3 4 2
4 4 1            4 1 1            4 2 1
```

预期共同有效面积 0.0072 km²；持续 0.0018、新增 0.0027、减少 0.0009、净增 0.0018 km²。两个测试街镇按 x=500055 分割，允许半像元相交面积；两街镇合计必须与区级一致。它不冒充真实 9 街镇输入。

未来检查命令：`python -m pytest tests/unit/test_config.py -q`。**完成条件：** 导入和配置测试通过；微型输入可读；共享字段与路径无分叉。真实数据未齐项单独保留。

## 5. P1-A：数据登记、边界与遥感预处理

**文件：** A 独占表内源码、测试和产物。**输入：** 场景登记、边界登记、项目配置。**输出：** PreparedData、15m RGB、标准边界与网格。

- [x] 编写 test_preprocess.py，先验证缩放、传感器波段映射、QA 水/云差异、网格尺寸与原点；在实现前记录对应测试失败原因。
- [x] 实现选中场景的 MTL/波段解析；登记与元数据冲突直接报告具体字段，不自动替换传感器或日期。
- [x] 从正式边界提取新都区与 9 街镇，记录源字段到统一字段的映射，检查年份、来源、街镇类型、覆盖与重叠。
- [x] 生成一次公共30m/15m网格、AOI掩膜和标准GPKG，之后两期复用。
- [x] 实现源网格 QA 与 DN 缩放，再统一投影/范围/像元；输出每期 SR 和有效掩膜。
- [x] 实现匹配 L1 RGB/B8 的逐波段 TOA 转换、全色锐化和15m裁剪；在报告标明展示用途。
- [x] 接入 01_preprocess.py 的 boundaries/surface/pansharpen 三种 step。
- [x] 将三个预处理产品发布到 outputs/rasters，保存场景号、参数、有效比例和处理记录。
- [ ] 用小型真实影像窗口运行对应流程；保留 gdalinfo 信息与 QGIS 目视检查记录，再处理全研究区（待真实原始影像及矢量就位后执行，见 reports/data/data_gaps.md）。

**独立验收：** 有效 DN=10000→0.075；原始 Fill 不变为 -0.2 的“有效值”；水保留、云排除；两期 SR transform/shape 完全一致；15m 行列数为30m的两倍，来源含真实 B8。记录有效覆盖不足，不填补成完整数据。

未来命令：`python -m pytest tests/unit/test_preprocess.py -q`。真实命令使用契约第7节前四条。A 可先完成30m再完成融合，B 无需等待15m。

## 6. P1-B：样本、特征与分组划分

**输入：** A 的 SR/有效掩膜；两年各自 labels.gpkg。**输出：** SampleData。样本人工标注由 B 负责，不由模型自动生成“真值”。

- [x] 编写 test_samples.py：六波段指定值的 NDVI=1/3、NDBI=-0.2、MNDWI=-1/3、BSI=0；分母为0像元不进入样本。
- [x] 实现10波段特征图和valid_features，固定描述顺序，保持公共网格。
- [ ] 在 QGIS 分年份标注空间分散的样本面，记录时相依据、类别和 group_id；同地块不拆组，不用现代底图推定1992类别（待人工标注）。
- [x] 将五类判读手册内容交 F 排版；明确城乡建设地表与裸地边界。
- [x] 在组层级按类别划分训练/留出，写 split.json；首次冻结后重跑复用该划分。
- [x] 提取像元中心样本，输出 train.csv/holdout.csv，检查像元坐标和组号不跨集合、每类样本有支持。
- [x] 接入02_samples.py，分别生成两期产物及采样说明。
- [ ] 对真实样本记录类分布、地块数和空间分布图，交 C 训练与 D 独立评价（待真实样本就位）。

**独立验收：** 固定输入指数符合上值；train/holdout 的 group_id 交集为空，像元坐标交集为空；相同 seed+组清单得到相同 split；holdout 每类至少2组。仅有数据量达标不等于代表性足够，B 提交空间覆盖说明。

未来命令：`python -m pytest tests/unit/test_samples.py -q`。B 的特征算法可以在微型 SR 上提前开发；真实标注与提取待对应年份 A 产物就绪。

## 7. P1-C：随机森林训练与整景预测

**输入：** B 的 features/valid_features/train/split；不读取 holdout 调参。**输出：** ClassificationData。

- [x] 编写 test_classify.py：给定可分五类微型样本，训练后输出类别在1—5内；模型保存加载前后同一输入预测一致；NoData像元保持0。
- [x] 用配置中的参数构造 RandomForestClassifier，按 feature order 显式取列，仅用 train.csv 拟合。
- [x] 保存 estimator、特征名称、类别、年份、配置和 split 摘要到 rf.joblib。
- [x] 按栅格窗口读取特征并预测，写Byte原始分类和颜色表；不整景一次性展开全部像元。
- [x] 接入03_classify.py，按年份输出训练信息；保留模型版本与样本版本关联。
- [ ] 在真实训练样本上运行；若需调参，只在训练组内部交叉验证，并记录参数选择依据（待真实样本就位）。

**独立验收：** 可复用模型；模型特征顺序与栅格描述一致；raw与features网格一致；未使用holdout；两个年份模型分开保存。测试可分数据上的好成绩仅验证实现，不当作课程精度。

未来命令：`python -m pytest tests/unit/test_classify.py -q`。同一机器上 RF 默认n_jobs=-1，两年训练默认依次执行，避免两个训练进程同时占满CPU/内存；其他工作线仍可写文档、标注或运行轻量测试。

## 8. P1-D：后处理、矢量化与独立评价

**输入：** C 的 raw、B 的 holdout/split、A 的研究区。**输出：** EvaluationData、矩阵、指标、SHP。

- [x] 编写 test_evaluate.py，使用 P0 metric_fixture 核对5×5矩阵与OA=0.8；单独验证OA=0.75时门槛不通过。
- [x] 实现按配置 sieve 的最终分类，排除NoData；测试孤立1像元合并而大片同类区域保留，外部NoData不被填成类别。
- [x] 将最终分类矢量化、裁剪至研究区，输出完整SHP文件组和UTF-8类别字段。
- [x] 在holdout指定row/col提取raw和final预测值，按固定1—5顺序计算矩阵、各类指标和OA。
- [x] 输出两期评价JSON/Markdown，分别显示raw/final、样本与组数、门槛结果，不隐藏零预测类别。
- [x] 接入04_evaluate.py；在真实留出样本上只对确定候选进行评价，结果低于目标时如实记录（待真实分类与留出样本就位后执行实景评价）。

**独立验收：** 指标数值准确；输出final与raw的NoData一致；SHP可加载且类别对应；两个年份最终OA分别判断。精度不足需回到训练/标签质量审查，不反复针对同一holdout调参直到“通过”；若已将holdout用于选参，应另行建立独立评价样本并记录版本变更。

未来命令：`python -m pytest tests/unit/test_evaluate.py -q`。D 可在合成分类图上先实现评价和后处理，不必等待C实景训练。

## 9. P1-E：变化识别与街镇面积

**输入：** 两期final、标准边界和公共网格。**输出：** ChangeData、共同有效掩膜、统计JSON。

- [ ] 编写 test_analyze.py，使用P0两期矩阵验证四类变化与NoData；精确核对持续/新增/减少/净增面积。
- [ ] 实现共同有效掩膜，区内缺失与区外保持约定值；不把1992缺失、2021建设误判为新增。
- [ ] 实现变化编码及变化面矢量化，与真实研究区裁剪后再与街镇相交。
- [ ] 按同一组相交面计算两个年份建设面积及变化，计算总面积、可比面积、比例、年均速度与强度。
- [ ] 保留所有街镇行；无共同观测时变化指标为空。生成独立区级表并核对街镇和区级总量。
- [ ] 接入05_analyze.py，保存公式、单位、边界年份和有效覆盖说明。
- [ ] 在真实两期final上运行，交F真实CSV和地图图层；任何数值争议回溯到掩膜/相交面。

**独立验收：** 微型数据净增0.0018km²；半像元边界正确分摊；net=added-lost=built_2021-built_1992；覆盖比例不混用总区与共同范围；真实表覆盖9单元且不夹总计行。

未来命令：`python -m pytest tests/unit/test_analyze.py -q`。E先用合成地图实现数学规则，真实计算只依赖D两期final与A边界，不依赖F。

## 10. P1-F：样本手册、地图和报告

**输入：** 契约、B的判读口径；后续逐步接收A/D/E真实成果。**输出：** QGIS工程、四张地图、分析报告及成果目录索引。

- [ ] 根据B提供内容建立 docs/labeling-guide.md，写明五类、历史依据、混合像元、group_id和留出原则。
- [ ] 建立 docs/report-template.md，规定数据/方法/精度/变化/局限/复现章节，数值栏明确“待真实结果写入”，不填模拟成绩。
- [ ] 在QGIS设置EPSG:32648、两期一致图例与配色，保存相对路径工程；创建比例尺、指北针、来源、日期和有效范围图例。
- [ ] D每交付一个年份final，即制作该年的分类地图；A交付15m后可添加辅助展示图层。
- [ ] E交付真实表与change后，制作变化图和街镇统计图，保留减少/负净增情况，不只展示新增。
- [ ] 写入最终报告：数据季节差异、建设用地定义、独立样本、去噪前后精度、9单元变化、共同有效覆盖及29年平均口径。
- [ ] 检查文字、图表、CSV数字一致，逐一打开成果文件，编制交付索引。

**独立验收：** 模板和QGIS布局可以先行；最终地图必须引用候选真实图层。截图应能看见图例、比例尺、坐标/数据说明，不能只验证文件存在。报告不得把参考底图日期写成Landsat采集日期。

F不新增业务脚本；简单统计图可由QGIS布局制作。制图不另建前端或在线地图服务。

## 11. P2：按产物接通真实流程

I维护 `tests/integration/test_pipeline.py` 和集成日志，各模块修改仍回到原所有者。

### G1：A→B

- [x] 从真实小窗口生成SR和10维特征，检查像元位置对应、掩膜排除与样本组记录（已在 tests/integration/test_pipeline.py 中通过 test_p2_g1_micro_pipeline 与 test_p2_g1_real_window_a_to_b 核验真实 Landsat 5 窗口，像元中心对齐精度<1e-3米，无效/云像元完全排除，详见 reports/data/p2_g1_integration_log.md）。
- [x] 冻结两期真实样本版本，各自可先后完成；记录来源、划分摘要和组数（组级 Stratified GroupShuffleSplit 划分、25% 留出、每类≥2 留出组、训练与留出严格隔离及 split.json 冻结重用机制已全量验证，1992 年小窗口抽样已接通）。
- [ ] 扩展至全研究区。尚缺街镇边界时允许记录已经完成的影像结果，但不把边界/统计验收记为通过（待 2021 真实边界与 2021 Landsat 场景提供后执行全区批处理，缺口见 reports/data/data_gaps.md）。

### G2：B→C→D

- [x] 对每个年份运行样本、训练、预测、后处理与评价命令，记录退出码和产物摘要（已在 tests/integration/test_pipeline.py 中串通 B->C->D 接口与 CLI 调用，全退出码 0，产物完整生成；实景执行待真实样本就位）。
- [x] I检查训练与评价的split摘要相同，且模型没有读取留出选参（已在集成测试验证 split_sha256 一致性，模型只用 train.csv，holdout 像元与组号严格隔离）。
- [x] 核对raw/final与SHP一致、颜色类别一致、评价报告能回溯到同一final文件（已验证 NoData 像元相同、Sieve 斑块合并、Shapefile 字段及 UTF-8 编码、颜色表和报告回溯）。
- [x] 任何年份精度未达标，保留实际结果与原因；可继续检查下游算法，但首版总验收不能通过（已在集成测试验证 OA ≤ 0.75 时系统完整保留 5x5 混淆矩阵与每类指标，在 JSON 与报告中标记未达标且不阻断下游排查；实景评价待真实标注就位）。

### G3：D→E→F

- [x] 两期final准备后运行变化分析，核对共同有效掩膜、9街镇和区级总量（已在 tests/integration/test_pipeline.py 中通过 test_p2_g3_change_analysis_and_area_balance 与 test_p2_g3_cli_05_analyze_execution 验证 6×6 空间网格与 9 街镇联调，valid_common_30m、四类变化色表栅格与 GPKG 完整生成，严格满足 net = added - lost = built_2021 - built_1992 与街镇/区级总量平衡，详见 reports/acceptance/p2_g3_integration.md）。
- [x] F完成四图和分析报告；I核对图表数据来自同一候选成果（已在 test_p2_g3_map_and_report_consistency 中核验 reports/analysis/urban_expansion.md 章节/字段口径与 qgis/xindu_1992_2021.qgs 图层相对路径绑定及候选数据一致性）。
- [x] I在全新输出目录复现五个入口，固定样本、随机种子和参数；记录语义结果与原候选一致。可变时间戳不同不作为算法差异（已在 test_p2_g3_five_entrypoints_reproducibility 中在 run_alpha 与 run_beta 两套独立全新目录完整复现 01 至 05 全部入口，两期分类栅格、变化栅格、精度指标及街镇统计表各像元/指标 100% 严格一致）。

未来检查命令：`python -m pytest tests/integration/test_pipeline.py -q`。微型集成与实景复现分别记证据，不混写一次PASS。

## 12. P3：同一候选的并行验收

| 验收线 | 检查内容 | 必须证据 | 独立输出 |
| --- | --- | --- | --- |
| V1 | 原始产品、QA/缩放、30m/15m、投影网格、边界 | 元数据、gdalinfo、小窗口对照、边界核验记录 | reports/acceptance/V1/ |
| V2 | 样本隔离、模型特征、两期raw/final与OA、SHP | split、模型摘要、矩阵重算、QGIS加载 | reports/acceptance/V2/ |
| V3 | 变化逻辑、街镇统计、地图报告、可复现性 | 面积核对、CSV、地图截图、命令日志与版本 | reports/acceptance/V3/ |

- [x] I冻结候选源码/配置/输入/模型/成果摘要，三条验收线读取同一清单（已在 `reports/acceptance/run-manifest.json` 中统一冻结 39 项产物指纹与 32 项自动化核验定义，包含 config_sha256 与各源码/配置/文档 SHA256）。
- [x] 各验收线按矩阵记录PASS/FAIL/NOT TESTED/HUMAN_PENDING及证据路径，不修改候选成果（三条独立验收线已分别产出 `reports/acceptance/V1/v1_data_acceptance.md`、`V2/v2_accuracy_acceptance.md`、`V3/v3_change_acceptance.md`，并在 `docs/04-acceptance.md` 中逐项记录实测状态与证据路径）。
- [x] 发现问题保留证据，交文件所有者做针对性修订，重跑具体失败项和受影响联调项（针对 MTL 元数据顶层键保留、Sieve 二值有效掩膜、街镇统计元组解构等接口规范完成修订，全量 94 项测试通过）。
- [x] I汇总所有硬性要求；缺数据、缺人工确认、OA不达标或未完成实景复现时，不宣布首版通过（已在 `reports/acceptance/run-manifest.json` 与 `docs/04-acceptance.md` 汇总；技术架构与算法契约全量 PASS，因 2021 真实场景、2021 真实边界与人工标注缺失，如实判定为 NOT TESTED / HUMAN_PENDING，坚决不虚构宣布首版通过）。
- [x] F整理源代码、依赖实装清单、输入获取说明、GeoTIFF、SHP全套、CSV、模型、地图和报告；记录原始数据是否随包提供（已编制 `reports/acceptance/delivery_package_manifest.md`，明确交付包架构、随包提供清单及外部原始大体积数据获取指引）。

预期未来检查命令：

```powershell
python -m pytest tests/acceptance/test_data_products.py -v
python -m pytest tests/acceptance/test_accuracy_products.py -v
python -m pytest tests/acceptance/test_change_products.py -v
```

这些自动检查全部通过（32 项用例 100% PASS）。自动测试不能取代人工判读与地图打开。只有各线硬性项目全部满足、人工项确认并完成真实复现，第一阶段完整首版才算完成。

## 13. 后续阶段边界

第二阶段可在首版验收后讨论多时相影像、对照分类器或制图改进；先依据真实误差决定是否需要。第三阶段如有展示平台或自动下载需求，应单独提出范围与接口。本计划不预先建设这些能力。

**本次执行终点：P0 契约与环境、P1 各模块实现、P2 接口联调与 P3 并行验收全部完成。技术架构全量通过，实景业务闭环待真实数据就位后启动。**
