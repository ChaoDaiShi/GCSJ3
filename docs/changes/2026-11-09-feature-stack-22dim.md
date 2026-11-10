# 变更记录：新增 22 维特征堆栈（--step features）

| 项目 | 内容 |
| --- | --- |
| 变更日期 | 2026-11-09 |
| 变更类型 | 新增预处理步骤（A 模块交付物） |
| 影响范围 | 新增 `--step features`；新增 `data/processed/features/`；不改变 `sr_30m.tif` 与现有 10 维训练口径 |
| 触发原因 | 团队执行方案 §3.2 要求 **22 维特征张量**（原实现仅 10 维：6 波段 + 4 指数） |
| 审查状态 | 待组内复核 |

---

## 1. 背景与口径对齐

方案 §3.2「针对新都区地物痛点的 22 维高阶特征张量设计」，表 5 给出构成：

| 组成 | 维数 | 方案依据 |
| --- | --- | --- |
| 6 个光谱波段 | 6 | 痛点 1—3 的光谱基底 |
| 7 项指数（NDVI/SAVI/MNDWI/NDBI/UI/BSI/IBI） | 7 | 表 5 痛点 1—3 |
| 6 项纹理（NIR/Red/SWIR1 均值与标准差） | 6 | 表 5 痛点 1（林盘/农田纹理差异） |
| DEM 高程 + 坡度 + TWI | 3 | 表 5 痛点 4（浅丘坡耕地 vs 平坝建筑） |
| **合计** | **22** | |

原代码只产出 10 维（6 波段 + NDVI/NDBI/MNDWI/BSI）。本次补齐 12 维：SAVI、UI、IBI、6 项纹理、高程、坡度、TWI。

## 2. 交付物

| 项 | 路径 |
| --- | --- |
| 特征堆栈 | `data/processed/features/feat_1992_30m.tif`、`feat_2021_30m.tif` |
| 发布副本 | `outputs/rasters/xindu_1992_features_30m.tif`、`xindu_2021_features_30m.tif` |
| 元数据 | `reports/data/features_1992.json`、`features_2021.json` |
| 命令行 | `python src/01_preprocess.py --config configs/project.toml --env-file .env --step features --year 1992` |

产物规格：22 波段、Float32、30 m、EPSG:32648、NoData `-9999`、网格与 `grid_30m.json` 一致，波段描述即为特征名。

## 3. 22 维特征定义

| # | 特征 | 定义 |
| --- | --- | --- |
| 1—6 | blue/green/red/nir/swir1/swir2 | 地表反射率 |
| 7 | ndvi | (nir−red)/(nir+red) |
| 8 | savi | 1.5(nir−red)/(nir+red+0.5) |
| 9 | mndwi | (green−swir1)/(green+swir1) |
| 10 | ndbi | (swir1−nir)/(swir1+nir) |
| 11 | ui | (swir2−nir)/(swir2+nir) |
| 12 | bsi | ((swir1+red)−(nir+blue))/((swir1+red)+(nir+blue)) |
| 13 | ibi | (Tb−Tv)/(Tb+Tv)，Tb=2swir1/(swir1+nir)，Tv=nir/(nir+red)+green/(green+swir1) |
| 14—19 | nir_mean/nir_std/red_mean/red_std/swir1_mean/swir1_std | 5×5 窗口有效像元均值与标准差 |
| 20 | elevation | DEM 双线性重投影至 30 m（米） |
| 21 | slope | arctan(hypot(dz/dx, dz/dy))，度 |
| 22 | twi | ln(a/tanβ)，a=汇流累积量×30 m，见 §4.2 |

1—6 与 7、9、10、12 的公式、NoData 规则与 `samples.calculate_indices()` 完全一致，由单测逐像元比对守护（实测最大差异 0）。

## 4. 三处需要审的科学决定

### 4.1 DEM 平滑（默认 5×5）

DEM 为 ASTER GDEM 镶嵌。直接用原始 DEM 求坡度被噪声主导：

| 处理 | 坡度中位数 | P90 |
| --- | --- | --- |
| 原始（窗口 1） | 5.01° | 9.99° |
| 3×3 | 3.45° | 7.04° |
| **5×5（默认）** | **2.31°** | **4.85°** |
| 7×7 | 1.65° | 3.53° |

新都区以平原为主，真实坡度应在 1° 量级，原始 5° 是 GDEM 逐像元噪声。5×5 是压噪声与保留浅丘起伏的折中。配置项 `[feature_stack].dem_smooth_window`，设 1 恢复原始 DEM。

**这是口径选择，不改任何原始数据**，只影响高程/坡度/TWI 三个特征。

### 4.2 TWI 的计算方式（不是近似值）

TWI = ln(a / tanβ) 需要汇流累积量 a，不能由坡度或高程直接拟合。实现路径：

1. 把 DEM 外扩 **67 像元（约 2 km）** 重采样到 30 m；
2. **Priority-Flood 填洼**（Barnes et al., 2014）：从窗口边界向内抬升洼地，保证每个像元都有严格下坡邻域；
3. **D8 单流向**：取八邻域中最陡下降方向；
4. **汇流累积**：按填洼后高程从高到低累加上游像元数；
5. `a = 累积像元数 × 30 m`，`tanβ` 下限取 1e-3 防止平地除零；
6. 裁回主网格，只保留主网格与 DEM 均有效的像元。

**边界限制（如实说明）**：研究区外的上游汇水只覆盖 2 km 缓冲，紧贴网格边缘的 TWI 仍会略偏低（本区地势平坦、边界外无大山，影响有限）。若要做严格流域 TWI，需用更大范围的 DEM 单独算一次再裁切。

### 4.3 纹理用「均值+标准差」而非方案写的 GLCM

方案表 5 描述的是 GLCM 的 Contrast/Variance/Entropy。本次实现的是 5×5 窗口的均值与标准差，原因：

- 三者都是「局部异质性」度量，标准差与 GLCM Contrast 在识别林盘/农田边界上高度相关；
- GLCM 在 30 m 分辨率、5×5 窗口下统计样本仅 24 个灰度对，量化级数一高就不稳定；
- 均值+标准差的实现可复现、可解释，且与 `docs/03-contracts.md` 现有纹理口径一致。

**这是与方案文字的偏离，需要组内确认。** 若坚持 GLCM，本步骤可扩展为 22 维之外的附加波段，但会改变维数，需同步报告口径。

## 5. 验证证据

### 5.1 单元测试

```
python -m pytest tests/unit/test_preprocess.py -q -p no:cacheprovider
→ 11 passed
```

`test_build_feature_stack_22_bands` 覆盖：22 波段与顺序、dtype、NoData 传播、4 个共用指数与 `samples.calculate_indices` 逐像元一致、高程等于输入 DEM、TWI 有限且量级合理、sidecar 字段。

### 5.2 真实数据运行

| 项 | 1992 | 2021 |
| --- | --- | --- |
| 尺寸 | 22×1070×1356 | 同 |
| 有效像元 | 548,264（37.79%） | 557,022（38.39%） |
| 高程 P50 | 494.5 m | 494.9 m |
| 坡度 P50 / P90 | 2.23° / 4.59° | 2.23° / 4.61° |
| TWI P10/P50/P90 | 6.56 / **7.75** / 10.63 | 6.56 / 7.75 / 10.64 |
| NDVI 均值 | 0.611 | 0.380 |
| 单景耗时 | ≈12 s | ≈12 s |

TWI 与坡度相关系数 −0.36、与高程 −0.10：平坦汇水区 TWI 高、坡度大处 TWI 低，方向符合物理规律。TWI 值域 4.4—22.6 与文献常见区间（ln 单位 3—20）一致。

两期 NDVI 差异（0.61 vs 0.38）为物候差：1992-08 水稻生长季，2021-02 冬春枯黄期。

## 6. 与训练口径的关系

`[features].order` 仍是 **10 维**，即 `02_samples.py` 写出的 train.csv 与模型输入未变。22 维堆栈是**已备好的交付物**，切换训练口径需同步改：

1. `configs/project.toml` 的 `[features].order` → 22 个名字；
2. `samples.py::calculate_indices()` / `extract_pixel_samples()` 按 22 维取列；
3. `docs/03-contracts.md` 特征契约；
4. 相关单测。

在此之前不要把 `feat_*_30m.tif` 当成已生效的模型输入。

## 7. 复核清单

1. `--step features --year 2021` 一次跑通，约 12 秒；
2. QGIS 打开 `feat_2021_30m.tif`，波段名为 22 个特征名；
3. 抽查 `elevation` 430—600 m、`slope` 中位数 ~2.2°、`twi` 中位数 ~7.7——明显偏离说明 DEM/平滑/缓冲参数不对；
4. `features_2021.json` 的 `feature_order` 与 TIF 波段顺序逐项一致；
5. 确认 `twi_buffer_cells=67` 与 `dem_smooth_window=5` 是你认可的口径（这两项直接改变 TWI 与坡度数值）。

## 8. 回退方法

- 删除 `data/processed/features/`、`outputs/rasters/xindu_*_features_30m.tif`、`reports/data/features_*.json`，移除 `01_preprocess.py` 的 `features` 分支与 `build_feature_stack` 及其 4 个水文辅助函数；
- 本步骤不写 `sr_30m.tif` 与任何分类中间产物，回退不破坏已完成成果；
- `data/raw/dem/xindu_dem_mosaic_30m.tif`（81.2 MB）为原始 DEM 副本，删除不影响其它模块。