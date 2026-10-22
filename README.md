# 工程实践任务 3：新都区遥感分类与城市扩张分析

采用 1992 年 Landsat 5 TM 与 2021 年 Landsat 8 OLI 数据，以 Python、GDAL、QGIS、随机森林和 GeoPandas 完成遥感分类及街道（镇）级城市扩张分析。

**当前状态：项目骨架和开发文档已初始化，业务开发未开始。** 用户已明确第一阶段是完整首版，包含预处理、分类、评价、扩张分析及成果输出。本次交付到初始化为止。

## 从这里开始

1. [文档导航](docs/README.md)：阅读顺序及交付状态。
2. [第一阶段完整首版设计](docs/superpowers/specs/2026-10-14-first-release-design.md)：范围、技术路线和科学口径。
3. [多阶段并发开发计划](docs/superpowers/plans/2026-10-14-first-release-parallel-plan.md)：P0 公共契约、六条并行工作线、集成和验收。
4. [数据存放与获取](docs/01-data-layout.md)：遥感影像、行政边界、参考地图及样本位置。
5. [环境配置](docs/02-environment.md)：`.env`、科学配置、F 盘环境与安装步骤。
6. [公共数据与接口契约](docs/03-contracts.md)和[验收矩阵](docs/04-acceptance.md)：后续各模块共同遵守的标准。

## 目录

```text
F:\工程实践3\
├── .env                         本机环境变量，已生成，Git 忽略
├── .env.example                 可提交的环境变量模板
├── environment.yml              Python/GIS 依赖声明，尚未安装
├── configs/project.toml         投影、波段、类别、模型及统计参数
├── data/
│   ├── catalog/                 数据登记表（模板与本机空表）
│   ├── raw/landsat/             两期原始遥感影像
│   ├── raw/boundaries/          县区、街道及镇边界
│   ├── raw/reference_maps/      参考底图、影像或矢量地图
│   ├── interim/                可重算的中间数据
│   ├── processed/              标准网格、预处理数据和样本表
│   └── samples/                QGIS 标注的真实样本
├── src/                        仅说明文件；五个核心入口尚未创建
├── tests/                      仅说明文件；测试尚未实现
├── qgis/                       QGIS 工程与制图说明
├── outputs/                    栅格、矢量、表格、模型及地图成果
├── reports/                    数据验收、精度和扩张分析报告
└── docs/                       设计、并发计划、接口与验收文档
```

默认目录均在 F 盘。文件夹中的 `.gitkeep` 仅用于保留空目录，不是数据。

## 当前可以做什么

- 查阅并分派开发计划；将真实数据按目录说明放入项目；填写 `data/catalog/*.csv`。
- 修改 `.env` 中本机数据目录，或审阅 `configs/project.toml` 中的研究参数。

当前**不能运行分析流程**：没有业务脚本、已安装项目环境、遥感影像、边界、标注样本或模型。文档中的运行命令是未来接口约定，未在本次执行。

Git 已在当前目录初始化为 `main` 分支；本轮不创建提交或配置远程仓库。
