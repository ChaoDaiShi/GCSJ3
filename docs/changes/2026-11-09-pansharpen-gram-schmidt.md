# 变更记录：2021 年 15m 全色锐化由 Brovey 改为 Gram-Schmidt（GSA）

| 项目 | 内容 |
| --- | --- |
| 变更日期 | 2026-11-09 |
| 变更类型 | 算法替换（同一产物的融合算法） |
| 影响范围 | 仅 `--step pansharpen`，产物路径、波段数、命名、元数据标注均不变 |
| 触发原因 | 团队执行方案 §3.1 与报告大纲 §2.2 明确要求 **Gram-Schmidt**；原实现为 Brovey，不符合方案 |
| 审查状态 | 待组内复核（本文件即复核依据） |

---

## 1. 背景

《成都市新都区遥感分类与多维城市扩张分析_团队执行方案》两处指定融合算法：

- 正文 §3.1：「先使用 **Gram-Schmidt (GS) 全色锐化算法**将 30m 多光谱波段与 Band 8 (15m 全色波段) 融合，输出 15m 交付成果」；
- 表 12 报告大纲 §2.2：「2021年15m **Gram-Schmidt** 全色锐化融合」。

原代码实现的是 Brovey 变换（`I=(R+G+B)/3`，各波段按 `band/I × Pan` 缩放）。Brovey 对城市高亮地物（彩钢瓦屋顶、裸露砂石滩、在建工地）易过饱和偏色，而这三类正是新都区分类的难点，故按方案要求替换。

## 2. 变更清单

| 文件 | 位置 | 变更 |
| --- | --- | --- |
| `src/rs_urban/preprocess.py` | 模块文档字符串第 21 行 | 「Brovey 算法」→「Gram-Schmidt 自适应（GSA）算法」 |
| `src/rs_urban/preprocess.py` | `pansharpen_2021()` 文档字符串 | 改为 GSA 五步公式说明 + 波段范围约束说明 |
| `src/rs_urban/preprocess.py` | `pansharpen_2021()` 融合实现段 | 删除 Brovey 三行，改为 GSA：块平均降采样、最小二乘回归、残差注入、逐波段增益 |
| `src/rs_urban/preprocess.py` | `reports/data/pansharpen_2021.json` 输出 | 新增 `fusion_algorithm`、`gs_intercept`、`gs_weights`、`gs_gains`、`valid_pixels`、`band_scope_note` |
| `src/01_preprocess.py` | 模块文档字符串第 6 行 | 「Brovey 融合」→「Gram-Schmidt 融合」 |
| `docs/report-template.md` | 第 42 行 | 「Gram-Schmidt / Brovey 锐化融合」→「Gram-Schmidt 自适应（GSA）锐化融合」 |

未改动：产物路径 `data/processed/2021/pan_rgb_15m.tif`、发布副本 `outputs/rasters/xindu_2021_pan_rgb_15m.tif`、3 波段（红/绿/蓝）、Float32、NoData `-9999`、`radiometry=TOA`、`purpose=visualization` 的标注。

## 3. 算法定义

设 RGB 三波段 TOA 反射率为 `MS_i`（i = 红 B4、绿 B3、蓝 B2），全色 TOA 反射率为 `Pan`（B8）：

1. **降采样**：对 `Pan` 与各 `MS_i` 做 2×2 块平均（只统计有效像元），得到 30 m 版本 `Pan_low`、`MS_i_low`；
2. **回归求模拟全色**：最小二乘求解 `Pan_low ≈ w0 + Σ w_i·MS_i_low`，得 `w0` 与 `w_i`；在 15 m 网格重建 `Pan_sim = w0 + Σ w_i·MS_i`；
3. **提取细节**：`Δ = Pan − Pan_sim`，即 B8 独有的 15 m 高频信息；
4. **逐波段增益**：`g_i = cov(MS_i, Pan_sim) / var(Pan_sim)`，保持该波段与全色的光谱比例；
5. **注入**：`MS_i_sharp = MS_i + g_i·Δ`。

该形式是 Gram-Schmidt 家族的 GSA（Gram-Schmidt Adaptive）实现：用多光谱本身合成低频全色再相减，避免直接把全色波段强行叠加到与它光谱范围不同的波段上。

## 4. 波段范围约束（重要）

Landsat 8 的 B8 全色波段为 **0.50—0.68 μm**，只覆盖：

| 波段 | 波长 | 是否被 B8 覆盖 |
| --- | --- | --- |
| B2 蓝 | 0.45—0.51 μm | 部分覆盖 |
| B3 绿 | 0.53—0.59 μm | 覆盖 |
| B4 红 | 0.64—0.67 μm | 覆盖 |
| B5 近红外 | 0.85—0.88 μm | **不覆盖** |
| B6/B7 短波红外 | 1.57—2.29 μm | **不覆盖** |

因此本步骤**只对 RGB 三波段融合**。把 B8 的高频塞进 B5/B6/B7 属于光谱外推，得到的 15 m 近红外不是观测值。分类仍使用 30 m 全波段，15 m 成果只作制图与目视解译。

## 5. 退化与异常处理

| 情况 | 处理 | 原因 |
| --- | --- | --- |
| `var(Pan_sim)` ≤ 1e-12（如整幅常数影像） | 增益 `g_i` 取 0，输出等于原多光谱 | 没有可用高频信息时不注入虚构纹理，也不引入 NaN |
| 参与回归的有效像元 < 4 | 抛 `ValueError` 并给出像元数 | 无法求解 4 个回归系数，宁可失败也不静默降级 |
| 像元在任一 RGB 波段或全色为 NoData/非有限值 | 置 `-9999` | 与全链 NoData 约定一致 |

## 6. 验证证据

### 6.1 单元测试

```
python -m pytest tests/unit/test_preprocess.py -q -p no:cacheprovider
→ 10 passed
```

其中 `test_pansharpen_2021_pipeline` 断言产物存在、3 波段、Float32、尺寸、NoData = -9999、报告含 `radiometry=TOA` 与 `purpose=visualization`。

### 6.2 真实数据运行

命令：`python src/01_preprocess.py --config configs/project.toml --env-file .env --step pansharpen`

| 项 | 结果 |
| --- | --- |
| 产物 | `data/processed/2021/pan_rgb_15m.tif`，66.4 MB |
| 尺寸 | 3 波段 × 2140 行 × 2712 列，Float32 |
| 有效像元 | 5,803,680（占 15 m 网格 100%） |
| 回归截距 `w0` | −0.00722 |
| 回归权重 `w`（红/绿/蓝） | 0.4095 / 0.5801 / 0.0547 |
| 增益 `g`（红/绿/蓝） | 1.1640 / 0.8368 / 0.6921 |

权重与波段范围一致：B8 主要覆盖绿、红，其次是蓝，故绿、红权重最大、蓝最小（0.05）。这是判断算法是否跑偏的第一道物理自检。

### 6.3 统计与细节核验

| 检查 | 结果 |
| --- | --- |
| NaN / NoData 混入 | 0 / 0 |
| 红波段值域 | 0.0714—0.7263，均值 0.1105，标准差 0.0193 |
| 绿波段值域 | 0.0913—0.5581，均值 0.1226，标准差 0.0138 |
| 蓝波段值域 | 0.1094—0.4962，均值 0.1496，标准差 0.0121 |
| 高通分量与 B8 高通相关系数 | 红 0.997 / 绿 0.997 / 蓝 0.970 |

高通相关系数接近 1，说明注入的确实是 B8 的真实纹理，而不是凭空生成的。

## 7. 复核清单（审查人照着做即可）

1. `git diff` 看 `pansharpen_2021()`：确认只替换了融合段与文档字符串，产物写出逻辑未动；
2. 打开 `reports/data/pansharpen_2021.json`，确认 `fusion_algorithm` 为 `Gram-Schmidt (GSA)`，且 `gs_gains` 三个值均为正、`valid_pixels` 与网格像元数一致；
3. 检查 `gs_weights` 是否满足「绿 ≥ 红 > 蓝」——偏离则说明波段顺序或定标系数有问题；
4. 在 QGIS 里加载 `pan_rgb_15m.tif` 与 30 m 假彩色，目视确认无偏色、无方块感、道路与建筑边缘清晰；
5. 确认 30 m 分类链路未引用 `pan_rgb_15m.tif`（`grep -r pan_rgb src/`）。

## 8. 回退方法

- **代码回退**：`git checkout -- src/rs_urban/preprocess.py`（若已提交则 `git revert`）。旧实现为 Brovey 三行公式，本文件 §1 已记录；
- **产物回退**：删除 `data/processed/2021/pan_rgb_15m.tif` 与 `outputs/rasters/xindu_2021_pan_rgb_15m.tif`，重跑 `--step pansharpen` 即可再生，不涉及原始数据；
- 本变更不触碰 `data/raw`，无需数据回退。

## 9. 已知边界

- 融合后仍为 **TOA**，不是地表反射率：15 m 版本只用于制图，不可用于定量面积统计；
- 未做 15 m 的 NIR/SWIR 外推（理由见 §4）；
- 未与 Brovey 结果做定量对比图：若报告需要「融合算法对比」，需另设消融实验，当前不包含在本变更内。

## 10. 附带修正：验收测试中的陈旧数据假定

`tests/acceptance/test_data_products.py` 的 D01—D03 三例写于旧数据状态，本次一并同步：

| 用例 | 旧断言（已失效） | 现断言 | 原因 |
| --- | --- | --- | --- |
| D01 | 1992 产品为 `LT05_L2SP_129044_...`，`WRS_ROW == 44` | `LT05_L2SP_129039_...`，`WRS_ROW == 39` | 129/044 实测在云南、不覆盖新都，已于 2026-11-06 替换为正确的 129/039 |
| D01 | 断言 2021 Level-2 目录**必须为空**（"honest gap recorded"） | 断言 2021 Level-2 目录存在且与登记表一致 | 2021 影像已入库，缺口论断题不再成立 |
| D02 / D03 | 硬编码 `LT05_L2SP_129044_...` | `LT05_L2SP_129039_...` | 同上 |

这不是为了让测试变绿而放宽断言：D01 现在**同时**校验登记行、目录、MTL 三者一致，比原断言更严。旧的 044 场景仍保留在 `data/catalog/excluded_scenes.csv`，留档可查。

## 11. 全量测试结果

```
python -m pytest -p no:cacheprovider -q
→ 108 passed, 7 failed, 1 skipped
```

7 个失败均与本次变更无关，全部是**下游成果尚未生成**导致：

| 失败用例 | 缺失对象 |
| --- | --- |
| `test_v3_f01_qgis_project_relative_paths`、`test_v3_f02_expansion_report_structure` | `reports/analysis/urban_expansion.md`、QGIS 工程 |
| `test_build_project_*`（3 例） | QGIS 工程尚未构建 |
| `test_p2_g3_map_and_report_consistency`、`test_p2_g3_real_data_gap_integrity` | 同上，另需 `reports/data/data_gaps.md` |

这些要在 02—05 阶段（样本、分类、评价、分析）跑完后才会产生，属于进度问题而非回归。

## 12. 复核用命令

```powershell
. .\activate-rs-city.ps1
python -m pytest tests/unit/test_preprocess.py -q -p no:cacheprovider   # 10 passed
python src/01_preprocess.py --config configs/project.toml --env-file .env --step pansharpen
Get-Content reports\data\pansharpen_2021.json                            # 核对 gs_weights / gs_gains
```