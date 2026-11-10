# 变更记录：分类体系由 5 类改为 4 类

| 项目 | 内容 |
| --- | --- |
| 变更日期 | 2026-11-09 |
| 变更类型 | 分类体系变更（删去「裸地」类，类别名对齐方案） |
| 影响范围 | 配置、评价脚本与报告表头、QGIS 样式、标注手册、验收测试、相关文档 |
| 触发原因 | 用户确认：按《团队执行方案》采用 **4 类**（方案 §4.1 编码 1—4），代码原为 5 类 |
| 审查状态 | 待组内复核 |

---

## 1. 变更内容

| 项 | 变更前 | 变更后 |
| --- | --- | --- |
| 类别数 | 5 | **4** |
| 编码 | 1—5 | **1—4** |
| 名称 | 建设用地 / 耕地 / 其他植被 / 水域 / 裸地 | **城镇及建设用地 / 耕地 / 林草植被 / 水体** |
| 配色 | 五色（含 `#B69C7D`） | 四色，去掉裸地色 |
| 混淆矩阵 | 5×5 | **4×4** |
| QGIS 样式 | `qgis/styles/lulc_5class.qml` | `qgis/styles/lulc_4class.qml` |

## 2. 改动清单

| 文件 | 改动 |
| --- | --- |
| `configs/project.toml` | `class_order = [1,2,3,4]`；`[[classes]]` 改为 4 条并按方案命名；删除「裸地」条目 |
| `src/rs_urban/evaluate.py` | 混淆矩阵与指标函数默认 `class_order` 改为 `[1,2,3,4]`；报告表头与类别名改为**从 `[[classes]]` 配置动态生成**（原来写死 5 类名与表头） |
| `src/rs_urban/analyze.py` | 变化编码注释中的非建设范围 `[2..5]` → `[2..4]`（逻辑本身与类别数无关） |
| `qgis/styles/lulc_4class.qml` | 新建，4 类 + NoData 透明；删除 `lulc_5class.qml` |
| `docs/labeling-guide.md` | 表格重写为 4 类；新增 **§1.1 原「裸地」归并规则** |
| `docs/report-template.md` | §3.1 改 4 类；两张混淆矩阵改 4 列 |
| `docs/03-contracts.md`、`04-acceptance.md`、`07-algorithm-report.md`、`qgis-development-guide.md`、`qgis-wbs-packages.md`、`README.md`、`docs/README.md` | 「五类」→「四类」，类别名对齐 |
| 测试（`test_accuracy_products.py`、`test_classify.py`、`test_config.py`、`test_evaluate.py`、`test_pipeline.py`、`test_qml_styles.py`、`fixtures/factory.py`） | 期望值由 5 类改 4 类；fixture 样本数 120 → 96、组数 40 → 32、矩阵 5×5 → 4×4 |

关键实现改进：`evaluate.py` 的表头与类别名原先硬编码 5 类，现在由 `[[classes]]` 生成。**以后再改类别数，只需改配置**，不会出现「配置 4 类、报告 5 列」的错位。

## 3. 「裸地」怎么处理（本次最需要审的一条）

裸地在四类体系下并入类别 1 或 2，规则写入 `labeling-guide.md` §1.1：

| 情形 | 归入 |
| --- | --- |
| 在建工地、推平待建地、已开挖未铺装地基 | **1 城镇及建设用地** |
| 翻耕裸露农田、冬水田干涸田面、收割后裸露田 | **2 耕地** |
| 枯水期河床砂石滩 | 常水位岸线内 → **4 水体**；岸线外滩涂 → **2 耕地** |
| 坡耕地土坎、浅丘裸露土坡 | **2 耕地** |

红线：不得新造第 5 类，四类之外的编码一律视为样本错误。

**风险提示**：新都区枯水期（2021-02）河滩与在建工地确实存在与耕地的光谱混淆，归并规则是**解译约定**，不是光谱可分性结论。四类体系下这部分误差会转移到「耕地 ↔ 城镇」的混淆上，报告里应作为不确定性说明，而不是隐藏。方案痛点 3（冬闲田 vs 在建工地）正是靠 IBI/BSI 特征来缓解，这也是 22 维特征里保留 BSI、IBI 的原因。

## 4. 验证

```
python -m pytest -p no:cacheprovider -q
→ 109 passed, 7 failed, 1 skipped
```

7 个失败与本次变更无关，全部是下游成果未生成：`reports/analysis/urban_expansion.md`、`reports/data/data_gaps.md`、QGIS 工程尚未构建。属于进度问题。

新增/更新的关键断言：

- `test_config_classes_and_features_consistency`：配置中恰为 4 类且名称顺序正确；
- `test_lulc_4class_palette_matches_config`：QML 色值与配置逐项一致；
- `test_v2_q01/q02/q03`：4×4 混淆矩阵与 OA 门槛判定；
- `test_v2_s01_labels_schema_and_classes`：四类定义一致。

## 5. 复核清单

1. `grep -rn "裸地" src/ configs/` 应为空（文档中解释归并规则的除外）；
2. `python -m pytest tests/unit/test_config.py tests/qgis/test_qml_styles.py -q` 应为全绿；
3. QGIS 中加载任意 `lulc_*_final_30m.tif`，图例应为 4 类、编号 1—4、无空档；
4. 打开 `configs/project.toml`，确认 `class_order` 与 `[[classes]]` 都是 4 条且编码连续；
5. 抽查评价报告表头列数 = 4 + 4（样本数/精确率/召回率/F1）。

## 6. 回退方法

- `git checkout -- configs/project.toml src/rs_urban/evaluate.py src/rs_urban/analyze.py` 及测试文件；
- 恢复 `qgis/styles/lulc_5class.qml`（可从 Git 历史取回）并删除 `lulc_4class.qml`；
- 文档按反向替换即可（五类 ↔ 四类）。本变更**不涉及任何已生成的栅格成果**，回退无数据损失。

## 7. 遗留影响

- 已有的 30 m / 15 m / 22 维特征产物不受影响（它们与类别数无关）；
- 尚未生成 `labels.gpkg` 与训练样本，因此**不存在需要重标的历史样本**——这是改类别数的最佳时机，越晚成本越高；
- 后续 02—05 阶段按 4 类执行。