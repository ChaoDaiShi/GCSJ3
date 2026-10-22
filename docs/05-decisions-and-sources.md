# 决策、未决输入与官方依据

更新日期：2026-10-14。用户材料原文保留在 [original-selection.txt](references/original-selection.txt)，仅作为需求来源，不代表其中所有数据已取得或结论已实测。

## 1. 已确定的项目决策

| 编号 | 决策 | 理由 |
| --- | --- | --- |
| DEC-01 | 第一阶段为完整首版，覆盖预处理至街镇扩张分析 | 用户本轮明确选择 |
| DEC-02 | 本轮仅初始化和文档，停止于开发之前 | 用户明确要求 |
| DEC-03 | 采用Python/GDAL/QGIS/RF/GeoPandas离线路线 | 延续提供的选型，不扩展为Web平台 |
| DEC-04 | 定量比较统一30m；2021另交15m RGB融合 | 保持跨期统计口径，区分真实融合与重采样 |
| DEC-05 | 2021边界统一作用于两个年份 | 避免行政单元变化混入土地变化 |
| DEC-06 | 训练和最终评价按空间地块分组隔离 | 避免相邻像元泄漏；不以评价集选参 |
| DEC-07 | 变化基于共同有效分类范围 | 云和NoData不能当作非建设地表 |
| DEC-08 | 配置采用TOML；本机路径放.env；依赖放environment.yml | Python3.11可用标准库tomllib，配置职责清楚 |
| DEC-09 | 六条并发线，公共类型/配置由I独占 | 模块可独立开发，减少共享文件冲突 |
| DEC-10 | 类1使用“建设用地”这一可穷尽分类口径，包含城乡建筑地表 | 避免农村居民点无类可归；报告不等同法定城市建成区 |

## 2. 仍须由真实输入或教师解决的事项

以下是明确的数据/口径任务，不阻止本轮初始化，也不能被写成“已完成”。

| 项目 | 当前事实 | 负责人及下一步 | 影响 |
| --- | --- | --- | --- |
| “17波段”“17+9波段” | 只有用户转述，未见任务书原始解释 | I向教师确认是原始波段、特征数还是给定产品 | 不重复波段凑数；如是硬性特征要求先修订设计 |
| 15m是否要求分类图 | 当前方案按融合显示图交付，分类保持30m | I确认教师的最终栅格要求 | 若强制15m分类，需单独定义模型和可比统计，不能放大标签冒充 |
| 指定日期与季节 | 请求1992-08-16和2021-02-05，尚未找到实际产品 | A检索并登记；改日期须记录教师决定 | 影响场景可用性与物候解释 |
| 两期实际场景 | 当前数据目录为空 | A从USGS下载并核验L2及匹配L1 | 影响真实预处理与全链路 |
| 教师县区数据链接 | 本附件没有真实下载链接 | A取得1990/2021原件并核实CRS | 影响研究区基准 |
| 2021街镇完整边界 | 原材料提出9单元，未提供可用文件 | A核实来源、年份、编码与多边形 | 影响街镇统计验收 |
| 建设用地与城镇建成区口径 | 当前以遥感建设地表完整分类，非行政建成区统计 | B在判读手册明确，I核对课程要求 | 如仅统计城镇，须补充可复现城镇范围定义 |
| 样本与历史依据 | 当前无标签 | B按历史影像/可信参考资料分年份标注 | 影响训练和独立评价可信度 |
| OA>75% | 是目标，没有实测值 | D在真实独立留出集评价两个年份 | 未达标即完整首版不能验收通过 |
| 有效观测覆盖 | 还没有影像可计算比例 | A/E报告单期与共同有效覆盖，教师判断是否满足研究任务 | 不凭空设定“已完整覆盖”，不外推到缺测区域 |

## 3. 本轮核查的官方资料

| 来源 | 在项目中支持的决定 |
| --- | --- |
| [USGS Collection 2 Surface Reflectance](https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-reflectance) | L2 SR的30m产品定位与B8不在SR产品中 |
| [USGS Level-2缩放说明](https://www.usgs.gov/faqs/how-do-i-use-a-scale-factor-landsat-level-2-science-products) | 反射率乘数0.0000275、偏移-0.2 |
| [USGS QA波段](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands) | QA_PIXEL/QA_RADSAT含义及传感器差异 |
| [USGS Landsat4-7产品指南](https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/s3fs-public/atoms/files/LSDS-1618_Landsat-4-7_C2-L2-ScienceProductGuide-v3.pdf) | TM QA_PIXEL位2未使用等产品定义 |
| [USGS Level-1数据转换](https://www.usgs.gov/landsat-missions/using-usgs-landsat-level-1-data-product) | MTL逐波段系数与太阳高度角处理 |
| [GDAL Warp](https://gdal.org/en/stable/programs/gdalwarp.html) | 投影、范围、网格和重采样 |
| [GDAL Pansharpen](https://gdal.org/en/stable/programs/gdal_pansharpen.html) | 全色锐化工具与波段输入 |
| [GDAL Sieve](https://gdal.org/en/stable/programs/gdal_raster_sieve.html) | 小斑块处理与非零有效掩膜 |
| [scikit-learn RandomForestClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html) | 主分类器参数与训练预测接口 |
| [scikit-learn GroupShuffleSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html) | 按组划分；分层需由本项目按类组织 |
| [GeoPandas Overlay](https://geopandas.org/en/stable/docs/user_guide/set_operations.html) | 街镇与变化面空间相交 |
| [QGIS下载](https://qgis.org/download/) | Windows桌面与3.44 LTR入口 |
| [Miniforge官方仓库](https://github.com/conda-forge/miniforge) | conda-forge环境管理 |

官网链接用于技术依据，不证明当前机器已经安装这些版本，也不证明已经取得新都区业务数据。实际依赖版本以未来安装后导出的清单为准。
