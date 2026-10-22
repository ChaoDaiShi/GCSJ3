# 数据目录

原始遥感数据放 `raw/landsat/`，行政边界放 `raw/boundaries/`，参考地图放 `raw/reference_maps/`，标注样本放 `samples/`。真实数据目前均未提供。

`catalog/*.example.csv` 是可提交的表头模板；同名去掉 `.example` 的 CSV 是已创建的本机空登记表，需按真实下载内容填写。各字段和相对路径基准见[数据目录文档](../docs/01-data-layout.md)。

目录外置时修改根目录 `.env` 中的 `RS_DATA_ROOT`，保持其内部结构不变。
# 2026-10-21 数据整理与试运行

本次整理使用用户已提供的原始数据，不下载、替换或更改影像内容。共移动 69 个原始文件，合计 2,412,336,230 字节，移动前后逐文件 SHA-256 一致。

| 数据 | 当前相对 data 的位置 | 用途与状态 |
| --- | --- | --- |
| 1992-08-16 Landsat 5，129/039，L1T | `raw/landsat/1992/level1/LT51290391992229BJC00/` | 原始输入；尚未做大气校正或分类 |
| 2021-02-05 Landsat 8，129/039，L1TP | `raw/landsat/2021/level1/LC08_L1TP_129039_20210205_20210303_02_T1/` | 原始输入；含 15m B8；尚未做融合或分类 |
| 标称 1990 年全国县级区划 | `raw/boundaries/county/1990/全国县级区划1990年shp/` | 包含新都县 510125；新都要素有效；YEAR=0，来源年份仍待核实 |
| 1992 年误选的 129/044 L2 场景 | `raw/landsat/excluded/LT05_L2SP_129044_19920816_20200914_02_T1/` | 不与所提供的新都县边界相交；保留原件，移出活动登记 |

活动影像在 `catalog/scenes.csv`，排除影像在 `catalog/excluded_scenes.csv`，边界在 `catalog/boundaries.csv`。登记路径均相对 data；未知下载日期、来源 URL 不编造。老版 L1T 的场景 ID 直接采用原 MTL 的 LANDSAT_SCENE_ID，不伪造 Collection 2 产品号。

原始影像显示预览位于 `interim/preview/`，使用历史县界外包框、30m 网格和各期独立的 2%—98% 拉伸。它们不是 SR、分类图或 2021 年行政区成果。对照 PNG 位于 `../outputs/maps/input_preview_1992_2021.png`。

整理记录、原目录与新目录映射、SHA-256、原登记表备份及命令行日志位于 `../.cache/data-organization/2026-10-21/`。详细状态见 `../reports/data/2026-10-21-data-organization.md`。

现有业务入口已实际试运行：帮助命令成功；边界步骤因缺少 2021 年县区边界失败；两期 surface 步骤因没有登记 L2 场景失败。尚缺 2021 年县区/街镇边界、两期真实样本和与现有 L2 路线匹配的输入。本轮未修改业务代码或科学参数。

---

