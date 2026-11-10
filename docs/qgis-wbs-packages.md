# QGIS 与并发开发工作包拆解表 (W01 - W28)

- **编制基线**：开发基线 1.0 (2026-10-29)
- **角色定义**：
  - `L`：统筹与集成 (Lead & Integration)
  - `D`：数据与样本 (Data & Samples)
  - `C`：核心算法 (Core Algorithm)
  - `Q`：QGIS 工程与制图 (QGIS Engineering)
  - `T`：测试与验收 (Testing & Verification)

---

## 阶段划分与里程碑 (Milestones & Gates)

| 阶段 | 建议周期 | 工作包 | 阶段门 | 目标产出 |
| :--- | :--- | :--- | :--- | :--- |
| **P0 基线冻结** | D1 - D2 | W01 - W04 | G0 契约冻结 | 科学口径、schema、双环境探针与合成数据工厂基线 |
| **P1 骨架与数据** | D3 - D5 | W05 - W12 | G1 纵向骨架闭环 | 配置只读解析、工程骨架、公共网格、QML样式、表单规则与样本冻结 |
| **P2 样本和核心** | D6 - D9 | W13 - W16 | G2 样本与核心通过 | RF模型审计、MLC基线、512窗口推理、表单只读绑定与Sieve矢量化 |
| **P3 联调与算法** | D10 - D12 | W17 - W21 | G3 可靠性通过 | 独立精度门禁协议、变化相交统计、统计join、四图QPT与真加载校验 |
| **P4 正式运行** | D13 - D15 | W22 - W23 | G4 科学成果通过 | 双期正式模型训练与推理、独立验证混淆矩阵、街镇面积平衡审计 |
| **P5 交付复跑** | D16 - D18 | W24 - W28 | G5 交付签认 | 跨路径/平台迁移测试、完整交付包、新根目录复跑与总分支归档 |

---

## 28 个工作包详细清单 (Work Breakdown Structure)

| ID | 工作包名称 | 阶段 | 主责/复核 | 依赖 | 可改文件/输出物 | 验收标准与核心证据 |
| :--- | :--- | :---: | :---: | :--- | :--- | :--- |
| **W01** | 核验源码、历史外置证据、真实输入与范围 | P0 | L / T | 无 | `reports/acceptance/` 初始审计记录 | 澄清 9b76a68f 提交的现有核心与外置成果状态，标明 NOT RUN |
| **W02** | 冻结路径、qgz、图层 ID、schema、字段映射 | P0 | L / C | W01 | `configs/project.toml`, schema 协议 | 统一 .qgz、稳定 `logical_id`、15 列街镇字段与 5 类色彩配置 |
| **W03** | QGIS 与离线双环境探针和实测清单 | P0 | C / Q | W01 | `reports/acceptance/environment-probe.json` | 隔离记录 Conda(rs-city) 与 QGIS 内置 Python、GDAL、PROJ 版本 |
| **W04** | 合成栅格、边界、样本、统计及手算期望值 | P0 | T / D | W02 | `tests/fixtures/factory.py`, UT01~UT12 | 8×8 / 16×16 微型合成数据闭环，手算 3600m² 变化统计平衡 |
| **W05** | 只读配置解析、路径解析与输入预检脚本 | P1 | Q / C | W02, W03 | `qgis/scripts/build_project.py` (预检模块) | 无副作用解析配置，环境变量 > .env > 默认，缺项列完整清单 |
| **W06** | 工程装配骨架、图层组与稳定 logical_id | P1 | Q / T | W04, W05 | `qgis/scripts/build_project.py` (装配模块) | 7 大图层组树形结构，稳定 logical_id 属性，不依赖动态图层名 |
| **W07** | 输入 catalog、边界标准化与来源许可登记 | P1 | D / T | W01 | `data/catalog/`, 许可报告 | scenes/boundaries 表头与稳定 unit_id 检查，无空几何/重叠 |
| **W08** | 既有公共网格、QA/SR 核心审计与补测 | P1 | D / C | W02, W07 | `src/rs_urban/preprocess.py`, 测试 | EPSG:32648, 30m 对齐，`mask==1` 严格三态判定，排除 Cirrus/Fill |
| **W09** | 四类/变化 QML、NoData 与源配置一致检查 | P1 | Q / D | W02, W04 | `qgis/styles/*.qml`, 测试 | 4 类与 4 类色表/代码与 project.toml 逐像元、逐字段完全一致 |
| **W10** | 十维特征适配审计及无效向量测试 | P1 | C / D | W04, W08 | `src/rs_urban/samples.py` | 10 维固定顺序，任何维度 NoData/分母为 0 则整向量为 -9999.0 |
| **W11** | 样本表单、解译手册、两期标注交叉复核 | P1 | D / Q | W02, W07, W08 | `qgis/forms/sample_form_rules.json`, 手册 | year/class_id/sample_id/group_id/interpreter 完整约束 |
| **W12** | 分组冻结、提取表、泄漏检查、split 摘要 | P1 | D / C | W10, W11 | `src/rs_urban/samples.py`, split.json | 25% GroupShuffleSplit，组与像元交集严格为空，每类 ≥8 组 |
| **W13** | RF 复用审计及 MLC 新增、训练内验证与元数据 | P2 | C / T | W10, W12 | `src/rs_urban/classify.py`, meta.json | RF (300树, min_samples_leaf=2) 兼容保存，MLC 基线实现与元数据 |
| **W14** | 512 窗口推理、边缘窗口与重载一致性 | P2 | C / T | W13 | `src/rs_urban/classify.py` | 512×512 内存控制在 10MB 块级，边缘尺寸自适应，NoData 守恒 |
| **W15** | 样本表单绑定与冻结只读、编辑行为测试 | P2 | Q / D | W06, W11 | `qgis/forms/sample_labels.qml`, 测试 | 值映射 1~5，split 只读，同组同类约束，未保存编辑提示正常 |
| **W16** | Sieve、raw/final 对照与分类矢量检查 | P2 | C / D | W04, W14 | `src/rs_urban/evaluate.py` | GDAL Sieve 4 像元 8 邻域 (<4)，raw/final NoData 布局完全一致 |
| **W17** | 独立评价协议、混淆矩阵与科学门禁 | P3 | T / C | W12, W16 | `evaluation_protocol.json`, 混淆矩阵 | 行真列测，final OA > 0.75 严格不等式校验，建设 F1 目标监控 |
| **W18** | 共同有效掩膜、变化编码与几何统计审计 | P3 | C / D | W04, W16 | `src/rs_urban/analyze.py` | valid_common 仅 mask==1，未舍入相交面积分摊，空观测留空 |
| **W19** | 统计 join、真实成果接入与工程清单 | P3 | Q / D | W06, W09, W14, W18 | `qgis/scripts/join_statistics.py` | 字符串 unit_id 关联（严格区分 "001" 与 "1"），拒绝重复/缺失 |
| **W20** | 四张 QPT 布局、批量导出与地图核对 | P3 | Q / T | W09, W18, W19 | `qgis/layouts/*.qpt`, `export_layouts.py` | 4 布局 A4 横向 300dpi，固定 map/legend/scale/north/title/source ID |
| **W21** | PyQGIS 真加载、重复构建与故障检查 | P3 | T / L | W15, W17, W18, W19 | `qgis/scripts/check_project.py` | 独立 QgsProject 遍历来源/CRS/波段/字段，临时文件同盘重命名 |
| **W22** | 正式双期运行与冻结独立评价证据 | P4 | C / T | W12, W17, W21 | `reports/acceptance/` 真实运行包 | 首次触碰最终 holdout，未舍入 OA 判定，生成两期正式模型证据 |
| **W23** | 正式变化统计、面积平衡与限制说明 | P4 | D / T | W18, W22 | `outputs/tables/township_change_1992_2021.csv` | 9 街镇面积守恒验证，容差 ≤ max(1e-6 km², 面积×1e-6) |
| **W24** | 中文路径、迁移、只读目录和环境兼容测试 | P5 | T / Q | W19, W21 | 迁移测试日志 | 移至含中文、空格与新根目录，相对路径自动解析，无坏图层 |
| **W25** | 工程交付包、环境说明与重建/回退说明 | P5 | Q / L | W20, W24 | `xindu_urban_delivery/` 打包结构 | 包含 .qgz、脚本、样式、模板、成果与说明，脱敏绝对路径 |
| **W26** | 新根目录复跑、四图与全清单签认 | P5 | T / L | W20, W23, W25 | `run-manifest.json` 终版签认 | 纯净环境由脚本一键从头复现并生成 4 张高清专题图 |
| **W27** | 用户手册、开发说明、答辩与过程材料 | P5 | L / 全体 | W01 起持续 | `docs/user-manual.md`, 答辩材料 | 整理研究背景、科学口径、操作步骤、已知局限与学术总结 |
| **W28** | 主分支整合、标签与证据归档 | P5 | L / T | W26, W27 | Git Tag `v1.0.0-release` | 所有证据 hash 锁定，工作区分支保护与归档入库 |
