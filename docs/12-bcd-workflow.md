# B/C/D 优化流程

本入口对应团队分工中的 B 分类、C 多维扩张分析、D 制图报告。A 的默认 19 维特征和原有 01—05 流程不变。优化文档中的示范结论、目标精度、其他区县案例不作为新都区计算结果。

## 本机状态（2026-11-12）

仓库已更新至 `29363ab`。当前机器的真实影像、样本、特征、DEM、分类栅格与边界目录均只有占位文件，不能据历史文字报告复现实景结果。LightGBM、CatBoost、scikit-image、pydensecrf 尚未安装。新入口已执行，生成本机缺口清单及待运行报告，没有生成替代影像或研究数值。

原项目要求新环境和缓存放 F 盘；本机无 F 盘。本次使用现有 D 盘 rs-city 环境和其临时目录，没有新建环境或改动 C 盘安装。

## 命令

在仓库根目录、现有 rs-city 环境执行：

```powershell
python -B src/06_bcd.py --step check
python -B src/06_bcd.py --step classify --methods svm rf
python -B src/06_bcd.py --step classify --methods stacking
python -B src/06_bcd.py --step analyze --source baseline
python -B src/06_bcd.py --step render --source baseline
python -B src/06_bcd.py --step all
```

使用本机已有环境的完整命令：

```powershell
& 'D:\rs-tools\bin\micromamba.exe' run --prefix 'D:\rs-tools\envs\rs-city' python -B src/06_bcd.py --step all
```

共用原有 `--config`、`--env-file`；新增 `--bcd-config configs/bcd.toml`、`--year 1992 2021`、`--methods`、`--source`。相对配置路径以仓库根目录解析。退出码 0 表示请求的阶段完成，2 表示存在待补输入/依赖；计算异常直接报错，不自动替换算法。

`check` 只检查输入存在性和可选包可发现性，读取就绪成果形成报告，不做模型训练。文件内容、投影、波段及样本组在实际运算时核验。`all` 依次执行可运行的分类、分析和图件，缺数据项登记为 pending。

默认分析来源明确为 `baseline`，即原有两期最终栅格。使用实验分类时显式指定 `--source rf` 或 `--source stacking` 等，不根据 holdout 的最高分自动选模型。实验栅格是直接预测结果，不冒充原有 Sieve 后处理成果。

## B：分类和对比

- SVM：只用六个反射率波段，标准化后 RBF SVC；标准化器只在训练组拟合。
- RF：沿用项目配置的 19 维特征、类别权重和随机种子。
- Stacking：RF + LightGBM + CatBoost，逻辑回归融合类概率。训练集内先生成 StratifiedGroupKFold 的空间组划分，再交给 StackingClassifier；缺包明确停止该方法，不替换成其他模型。
- RF/SVM 同时记录训练组交叉验证分数；Stacking 记录其内部 OOF 折数，不将元学习器训练分数包装成独立验证分数。
- 同一年所有方法使用同一 `holdout.csv`，核对地块组和像元坐标不与训练集交叠。报告保留训练、划分、留出表和输出图的 SHA256。
- 分类概率按实际类别顺序写多波段 GeoTIFF；预测按窗口处理，无效特征/掩膜保持 NoData。
- 可在配置中显式启用 `object_smoothing`、`crf`。SLIC 在有效像元中分割，以对象均值融合类别概率；DenseCRF 在有效节点构图，避免缺测区作为隐节点传递信息。后处理仍在同一留出点评价。
- OA 计入未分类点的错误，混淆矩阵额外保留 unclassified 列；输出 Kappa、逐类 precision/recall/F1/support、覆盖率。

可选包要求：

| 功能 | 包 | 当前验证 |
| --- | --- | --- |
| RF/SVM、分组划分 | scikit-learn | 微型流程已运行 |
| 指定的三模型 Stacking | lightgbm、catboost | 缺包，测试跳过 |
| SLIC | scikit-image | 缺包，测试跳过 |
| DenseCRF | pydensecrf | 缺包，测试跳过 |

未创建深度分割训练流程：当前没有相应训练数据、GPU 环境或人工独立验证集，不能把未经验证的深度网络作为可交付的优化结果。

### 迁移候选

```powershell
python -B src/06_bcd.py --step transfer --labels-first D:/data/labels_1992_project_codes.tif --labels-last D:/data/labels_2021_project_codes.tif
```

输入两期外部标签必须先映射为本项目 1—4 类、0 为 NoData，并与 A 的 30m 网格对齐。CLCD 的原始类别编码不能直接当作项目编码。候选限定两期标签一致、共同有效的像元，按六波段反射率 CVA 大小取最低 30%；输出只有 `needs_manual_review` 状态的 CSV，不改 train/holdout。正式采纳还需人工核查、来源记录和空间划分审计。CVA 未做 MMD 域适配，也不宣称候选标签独立可靠。

## C：指标和因子

- 四类转移矩阵：两期共同有效掩膜，图斑与研究边界精确相交，保留全 4×4 组合及面积平衡。
- 街镇动态度 K 与 UEII：复用原有街镇叠加，K 的期初建设面积为零时留空。
- LEI：对新增斑块构建 100m 外环，再与共同观测区域相交。分母为可观测环面积，旧建设用地交叠为分子。>50 填充，0—50（不含 0）边缘，0 飞地；无可观测外环则未定义。浮点面积接近 0/50/100 时在 1e-9 指数单位内归到边界。
- 景观：PD（斑块/100ha）、LPI、AI、面积加权 FRAC。斑块连通默认四邻接，AI 永远采用单计数四邻接，理论最大邻接为 `2n-ceil(2sqrt(n))`。景观指标按共同有效像元中心网格计算，和精确裁剪的面积表分开。
- 重心和标准差椭圆：以建设用地图斑面积均匀加权，积分处理孔洞；半轴为协方差特征值的 `sqrt(2λ)`，输出米制迁移量与方位角。两期只在共同有效区比较。
- 地形：有真实 DEM 时复用 A 的高程/坡度/TWI 算法，独立用于 C 分析，不加入 A 的默认分类特征。
- 因子：`configs/bcd.toml` 中登记真实栅格、道路/站点/河道距离、保护区/规划区覆盖。矢量缓冲暴露面积精确相交；距离分层和地形梯度以共同有效栅格统计。
- GeoDetector：500m 网格，响应为净增建设面积/网格研究区面积/29 年×100；最低共同观测覆盖率默认 80%。因子按观测像元中心均值聚合，因子覆盖不足的网格留空。所有因子使用同一个完整样本网格集，固定分位数离散，输出 q、交互类型、分层数、单样本网格层数与固定种子的探索性置换 p。

外部驱动输入位置可改配置：`data/raw/drivers/`。`kind=raster` 需预先与 A 对齐；`kind=distance/zone` 指定真实 GPKG 图层。默认河道统计包括 200m/500m 累计缓冲，道路/地铁提供距离梯度。当前计算欧氏距离，没有声称为交通成本距离或通行时间。

外部数据缺失时逐项 pending。保护红线不能用分类中的耕地替代，河道不能用所有水体替代。后期道路、站点和规划与历史扩张仅能做回溯空间关联，必须核对年代。两期数据不能推断中间年份的政策斜率突变。普通置换 p 未修正空间自相关，q 不是因果效应，稀疏交互层的高 q 不作为机制证明。

## D：六组图件

1. 两期假彩色、NDBI、NIR 局部标准差。局部标准差不标为 GLCM。
2. 同一留出集的 SVM/RF/Stacking 图与 OA、建设类 F1 对比。
3. 两期分类与四类转移 Sankey。
4. 街镇 UEII、面积重心/标准差椭圆、建设面积柱图。
5. 真实地形和河道缓冲暴露。
6. GeoDetector q 排序和交互矩阵。

缺少任一图组所需真实输入时记录 pending，不生成占位图。图件会检查分析输入哈希与分类留出集一致性；数据改变应重新运行对应阶段。当前交付为 PNG 和 Markdown，不把历史 Word 报告覆盖成新的实景结论。

## 输出

```text
outputs/bcd/classification/<year>/<method>/{model.joblib,lulc.tif,probabilities.tif}
outputs/bcd/transfer/{review_candidates.csv,manifest.json}
outputs/bcd/analysis/<source>/
  spatial.gpkg                 transitions / lei_patches / driver_grid
  transition_km2.csv           精确裁剪面积
  lei.csv                     新增斑块 LEI
  township.csv / district.csv  UEII、动态度、面积平衡
  factor_*.tif                真实因子对齐输出
  factor_exposure.csv         缓冲区/保护区/规划区暴露
  gradients.csv               距离/地形梯度
  driver_grid.csv / geodetector.json / summary.json
outputs/bcd/figures/<source>/01~06_*.png
reports/bcd/{readiness.json,run.json,figures.json,report.md,accuracy_*.json}
```

这些本机生成物遵循已有 `.gitignore`，不入库。输入缺失时相应文件不产生；SVM 不需要概率栅格。

## 验证

```powershell
python -B -m pytest tests/unit -q -p no:cacheprovider --basetemp D:/rs-tools/tmp/bcd-unit
python -B -m pytest tests/integration/test_pipeline.py -q -k 'not real' -p no:cacheprovider --basetemp D:/rs-tools/tmp/bcd-integration
```

新增测试用例覆盖空间组隔离、NoData 计错、CVA 候选比例、LEI 外环及 50 阈值、精确转移面积、含孔洞面积椭圆、景观邻接、q/交互和完整 B→C→D 微型流程。合成图仅存 pytest 临时目录，不是新都区成果；六组图已经过像素非空检查和目视检查。

实际测试记录见 [本次实施记录](changes/2026-11-12-bcd-implementation.md)。需要真实数据的验收没有执行。
