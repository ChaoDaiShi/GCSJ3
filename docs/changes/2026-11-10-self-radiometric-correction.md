# 2026-11-10　自建辐射定标 + 大气校正（模块 A 收尾）

## 触发

《团队执行方案》模块 A 要求「自行完成辐射定标与大气校正」。此前一直用 USGS L2SP 成品，该项在差异说明里标为偏离。本轮用 Level-1 原始 DN 自行实现了一遍。

## 实现

`tools/self_radiometric_correction.py`，两条路径：

| 年份 | 传感器 | 定标公式 |
| --- | --- | --- |
| 1992 | TM（8 bit 老格式） | `L = RADIANCE_MULT·DN + RADIANCE_ADD`，`ρ = π·L·d²/(ESUN·cos θs)` |
| 2021 | OLI（Collection 2） | `ρ = (REFLECTANCE_MULT·DN + REFLECTANCE_ADD)/sin θs` |

大气校正两版：

1. **DOS1**：研究区内 0.05 分位作路径反射率，`ρ_s = ρ_TOA − ρ_path`；
2. **DOS + Rayleigh**：再除 `Tz·Tv`，`τr = 0.008569·λ⁻⁴(1+0.0113λ⁻²+0.00013λ⁻⁴)`。

重投影到分析网格（与 `sr_30m.tif` 完全对齐）。

## 结果（与 L2SP 对比）

| 年份 | 相关系数 | 蓝（自建/L2SP） | 近红外（自建/L2SP） | NDVI 偏差 | NDVI≥0.66（自建/L2SP） |
| --- | --- | --- | --- | ---: | --- |
| 1992 | 0.85—0.91 | 0.011 / 0.064 | 0.191 / 0.321 | **+0.2125** | 461.2 / 70.9 km² |
| 2021 | 0.97—1.00 | 0.032 / 0.068 | 0.256 / 0.306 | +0.1012 | 292.4 / 197.9 km² |

DOS+Rayleigh 变体 NDVI 平均绝对差：1992 0.2203、2021 0.0825（同样不可用）。

## 判断

空间结构一致（r 0.85—1.00），绝对量级不一致。原因是 DOS 假设暗像元地表反射率为 0，而 1992 年场景雾霾重，最暗 0.05% 像元在 L2SP 中近红外仍有 0.128 反射率，按 0 扣除即过度扣除；比值指数随之被系统性放大。

**结论：自建一阶校正不满足替换条件，正式成果继续用 L2SP。** 本节交付实现与量化证据，说明为什么最终采用成品。

## 产物

| 产物 | 路径 |
| --- | --- |
| 自建 SR（DOS1，1992/2021） | `data/processed/{1992,2021}/sr_selfcal_30m.tif` |
| 自建 SR（DOS+Rayleigh） | `data/processed/{1992,2021}/sr_selfcal_rayleigh_30m.tif` |
| 有效掩膜 | `data/processed/{1992,2021}/valid_selfcal_30m.tif` |
| 对比报告 | `reports/accuracy/radiometric_selfcheck.md` |
| 参数与统计 | `reports/accuracy/radiometric_selfcheck.json` |
| 脚本 | `tools/self_radiometric_correction.py` |

## 对既有成果的影响

无。`sr_30m.tif`、特征、分类、面积、变化检测全部未改动。