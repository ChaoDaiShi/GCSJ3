# 方法对比成果契约

`/comparison` 独立展示原有分析 `baseline` 与文档方案 `optimized`，不替换原有分析页面或离线 Python 流程。页面仅消费发布成果；OBIA、Stacking、GeoDetector 等增强计算尚需在离线流程中实现并核验。

## 清单入口

沿用现有 `/api/v1/manifest.json`，增加可选资源：

```json
{
  "resources": {
    "method_comparison": {
      "status": "ready",
      "path": "comparison/methods.json",
      "reason": null
    }
  }
}
```

这是清单的局部示意；其他现有字段必须保留。仅在 `release_state` 为 `published` 且资源为 `ready` 时请求结果。尚未计算时，使用 `status: "not_available"`、`path: null`、`reason: "not_computed"`。不得为展示页面而填入预期数值。

成果文件使用现有包装 `{ "run_id": "...", "data": { "methods": [] } }`，其中 `run_id` 必须与清单一致。`methods` 只放已经发布的方案，最多各一个。只完成原有分析时，仅发布 `baseline`。

## 方案字段

完整 TypeScript 定义在 `src/types/api.ts` 的 `MethodResult`。

| 字段 | 内容 |
| --- | --- |
| `id` | `baseline` 或 `optimized` |
| `model_name` | 实际使用的模型名称 |
| `class_schema` | 地类体系标识；相同标识必须代表相同类别含义与编码 |
| `classes` | 按混淆矩阵顺序排列的 `{ code, name, color }` |
| `years` | 起止观测年份，顺序与清单一致 |
| `boundary_sha256` | 实际行政边界版本的 SHA256 |
| `grid_sha256` | CRS、分辨率、原点和行列数等网格定义的 SHA256 |
| `comparison_mask_sha256` | 两套结果用于统计的共同有效掩膜的 SHA256 |
| `accuracy` | 分年份的独立留出集评价，未计算时为空数组 |
| `expansion` | 现有 `ExpansionData` 结构，未计算时为 `null` |
| `maps` | 分年份分类图 `{ year, path, legend: [{ name, color }] }`，未发布时为空数组 |
| `drivers` | 因子 `{ name, q, p_value }`，未计算时为空数组 |

所有哈希均由实际输入或规范化定义计算，不能填写任意相同字符串以绕过口径核验。

`accuracy` 每项包含 `year`、`holdout_sha256`、`oa`、`kappa`、`built_up_f1` 与 `confusion`。OA 和 F1 使用 0 到 1 的比例，Kappa 使用原始系数；缺失指标为 `null`。混淆矩阵按 `classes` 的顺序，行为真值、列为预测；缺失矩阵为 `null`。留出集哈希应覆盖评价样本 ID、空间分组、真值标签与年份。

`expansion` 包含 `elapsed_years`、`district`、`townships`。每个单元包含 `unit_id`、`name`、`unit_type`、`total_area_km2`、`comparable_area_km2`、`valid_ratio`、`added_km2`、`lost_km2`、`net_km2`、`annual_intensity_pct`。街镇按稳定的 `unit_id` 配对，面积使用平方千米，年均强度使用百分数每年（不再乘 100）。缺失指标为 `null`。

图像 `path` 相对配置的 API 基地址解析，使用发布的真实分类图及对应图例。两幅图应使用相同范围、投影和输出尺寸，便于视觉对照。页面不会从静态图计算像元差异。

`q` 使用 0 到 1 的值；未发布显著性时 `p_value` 为 `null`。当前页面展示单因子排序，不展示尚未接入的交互探测、LEI 或景观指标结果。文档中的示例数值不能作为实测成果发布。

## 差值条件

年份、地类体系和类别编码顺序，以及边界、网格和共同有效范围的哈希均一致时，才允许计算结果差值。街镇扩张另要求相同统计周期；精度另要求所选年份的留出集哈希一致。差值方向统一为文档方案减原有分析，OA 差值显示百分点。

原有五类与增强四类的评价不能直接相减。需先定义共同地类体系并重新评价，或分别展示结果且保留“待统一口径”。即使差值为正，也不能据此认定增强方案更准确；精度与扩张面积的差值应分别解释。

## 发布验收

核验两套离线输出、评价样本独立性、面积与周期、分类图图例后，再将资源设为 `ready`。`data_origin: "mock"` 仅用于联调，页面会明确标记。文件缺失、批次不一致及未发布分别显示对应状态，不把缺失成果转换成零。
