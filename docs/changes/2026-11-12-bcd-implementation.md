# B/C/D 实现与本机验证（2026-11-12）

## 基线与授权

按用户要求先更新仓库，再基于《工程实践3优化方案》完成 B/C/D 当前可实施部分。`main` 已从 `e085566` 快进至 `29363ab`，没有创建提交或推送。文档中的示范结果与目标精度不视为研究证据。

A 的 19 维默认特征、原有 01—05 入口及原分类结果路径保持原有约定。用户已有 `.gitignore` 修改及未跟踪的 `web/` 保留。本次不引入 Web 服务、数据库或子智能体。

## 已实现

| 模块 | 实现 | 运行限制 |
| --- | --- | --- |
| B | 六波段 SVM、配置特征 RF、RF/LightGBM/CatBoost 空间分组 OOF Stacking；同一冻结 holdout 评价、概率栅格、可选 SLIC/DenseCRF、CVA 稳定标签复核候选 | 缺真实特征与样本；可选算法缺包 |
| C | 四类转移与面积平衡、LEI、街镇 K/UEII、PD/LPI/AI/FRAC、面积重心与椭圆、真实地形/道路/河道/规划叠加、GeoDetector q/交互 | 缺两期分类、边界、DEM 和真实驱动因子 |
| D | 六组 PNG 与基于实际产物的 Markdown 报告、输入和成果哈希核对、待运行清单 | 缺输入时记录 pending，不生成占位研究图或数值 |

统一入口为 `src/06_bcd.py`，配置为 `configs/bcd.toml`，完整命令、输出结构和公式见 [B/C/D 优化流程](../12-bcd-workflow.md)。

新增斑块按配置的四/八邻接连通分组，再用四邻接边界矢量化，避免对角相连时形成自接触的无效多边形。有效分析网格全部被覆盖率门槛筛掉时，GeoDetector 明确记录未定义。文件 SHA256 采用流式读取，避免将完整遥感栅格读入内存计算摘要。

## 验证证据

使用本机已有 `D:\rs-tools\envs\rs-city` 环境，没有安装新包。项目要求新的环境、工具和缓存放 F 盘，但本机没有 F 盘；本次复用 D 盘已有环境及其临时目录，没有修改 C 盘安装。

最终单元测试命令：

```powershell
& 'D:\rs-tools\bin\micromamba.exe' run --prefix 'D:\rs-tools\envs\rs-city' python -B -m pytest tests/unit -q -p no:cacheprovider --basetemp D:/rs-tools/tmp/bcd-reviewed-unit
```

结果：**62 passed, 3 skipped**。跳过项分别为缺少 LightGBM/CatBoost 的指定 Stacking、缺少 scikit-image 的 SLIC、缺少 pydensecrf 的 DenseCRF；这些实现不能据此宣称已运行验证。

新增用例包括空间组隔离、留出像元防重叠、NoData 计错、CVA 候选比例、LEI 外环与 50 边界、精确转移面积、含孔洞的面积椭圆、四/八邻接斑块有效性、景观邻接、无合格网格、q/交互，以及完整 B→C→D 微型流程。六组图通过像素非空检查和目视检查，修复了 GeoDetector 横轴标签裁切。微型输入及其成果只存在 pytest 临时目录，不是新都区实测成果。

既有 `test_load_context_basic` 原先会读取本机 `.env`，导致 scratch 路径断言随机器变化；本次仅改为隔离读取不存在的临时环境文件，没有更改生产配置行为。

既有集成测试命令：

```powershell
python -B -m pytest tests/integration/test_pipeline.py -q -k 'not real' -p no:cacheprovider --basetemp D:/rs-tools/tmp/bcd-integration
```

结果：**10 passed, 1 failed, 3 deselected**。失败项 `test_p2_g3_map_and_report_consistency` 缺少本机生成的 `qgis/xindu_1992_2021.qgs`。该文件在本次开发前即不存在，没有创建虚构工程或修改测试掩盖缺口。真实数据验收、QGIS 真加载及真实模型精度验证未执行。

## 本机运行结果与待办

已运行新入口的 `check` 和 `all`。本机真实影像、样本、特征、DEM、分类栅格与边界只有占位目录，相关阶段均记录为 pending。实际生成的本机状态文件为：

- `reports/bcd/readiness.json`
- `reports/bcd/run.json`
- `reports/bcd/figures.json`
- `reports/bcd/report.md`

没有在项目成果目录生成替代分类栅格或正式研究图件。这些运行产物遵循已有忽略规则；可共享实现和文档留在工作区待审查。

继续运行需要：

1. 同步 A 的真实处理成果、两期训练与冻结 holdout、边界及 DEM。
2. 在符合项目磁盘约定的环境中补齐需要使用的可选算法包，再运行其测试。
3. 提供有来源、年份和坐标系记录的道路、站点、河道、保护区/规划区因子。
4. 运行真实分类、空间分析与制图，独立核验精度及面积，再形成研究结论。

当前不保证精度提高，不把两期平均变化解释为政策节点突变，也不把 GeoDetector 的空间关联解释为因果效应。
