# 2026-10-29 边界与参考地图补充

本次从用户提供的四个本地压缩包中筛选新都研究所需资料。原始压缩包保留在原位置；选中的原始图层和四川 KMZ 保存到项目 data/raw，局部提取保存到 data/interim/boundary_review/2026-10-29。没有修改业务源码或科学参数，没有将候选资料发布为正式 2021 年统计边界。

## 筛选结果

| 用户提供资料 | 实际核验结果 | 项目用途 |
| --- | --- | --- |
| 成都市_510100_关注锐多宝获取更多资讯.zip | 只有一个成都市整体面；属性 year=2023；SHP 声明 EPSG:4326 | 成都市区位背景，不能替代新都区县界 |
| 全国政区图-村级-point.zip | 按省组织的 KMZ；四川 KML 说明版本为 2008-01-13；含区县、乡镇和村等地名点 | 保留四川原件，提取新都附近地名点；点位不能替代行政面 |
| 全国电子地图数据shp格式.rar | 县界_region 中有一个新都区面；没有年份或行政编码字段；坐标系为 MapInfo Generic Lat/Long 自定义基准 | 保留县界候选，以及道路、水系、镇点参考资料；不将其坐标系强制标成 WGS84 |
| 县级_截止08年_shp.rar | 包名标称截至 2008 年，但新都记录为新都县、ADCODE99=510125；实际边界年份未核实 | 历史县界候选；采用包内自带 .prj 的完整文件组；不用包名替代实际年份证据 |

县级 RAR 包内两套 SHP/DBF/SHX/SBN/SBX 的 SHA-256 分别一致，采用带 .prj 的一套，没有混接其他来源的投影文件。

## 文件入口

以下路径相对项目 data 目录：

- `raw/boundaries/county/candidates/county_claimed_until_2008/`：历史县界原始文件组。
- `raw/boundaries/county/candidates/emap_unknown_year/`：电子地图县界原始文件组。
- `raw/reference_maps/vector/chengdu_2023_ruiduobao/`：成都市市界及原说明。
- `raw/reference_maps/vector/admin_points_20080113/SiChuan.kmz`：四川地名点原件。
- `raw/reference_maps/vector/national_emap_unknown_year/`：筛选保留的道路、水系及镇点原始图层。
- `interim/boundary_review/2026-10-29/xindu_historical_candidate.gpkg`：新都县历史候选面。
- `interim/boundary_review/2026-10-29/xindu_emap_reference.gpkg`：新都区候选面及周边参考地图，共七个图层。
- `interim/boundary_review/2026-10-29/xindu_vicinity_admin_points_20080113.gpkg`：周边地名点，保留原分组和版本字段。

局部提取窗口为两个候选县界经纬度数值外包框的并集，各方向扩展 0.02 度。它只是参考资料的检索窗口，可能包含相邻区县；线、面保留完整原始要素，不裁剪到新都行政区。电子地图采用原自定义坐标系，未执行基准转换；KML 点按 KML 经纬度定义保存为 EPSG:4326，原始定位精度未得到独立验证。

## 登记与使用边界

`data/catalog/boundary_candidates.csv` 是本次新增的人工审阅清单，沿用边界表字段；实际年份未知的记录保持空白、状态为 pending。**这份清单不作为当前预处理入口输入**。活动 `boundaries.csv` 保持原样，以免未知年份候选被误选为 2021 年正式输入。

`data/catalog/reference_maps.csv` 登记选中的参考数据和局部 GPKG。原文件年份、说明中的版本日期、下载时间分别记录，不混作地图观测日期。

水系局部数据中存在原始无效多边形；详细数量与原因见本机核验报告，未自动修复。参考图层不作为面积统计或分类训练真值。

成都市包内说明将用途限定为学术、教育等非商业参考，来源标注为锐多宝及 CTAMap；其余资料的原始授权未核实。这里只记录附件说明，没有将其中的宣传或操作文字视为用户指令。

## 仍缺少的数据

正式 2021 年新都区县界，以及同年 9 个街镇完整面边界，仍未由这四个包补齐。街镇边界仍需核验名称、编码、年份、9 个单元和区级覆盖。后续取得真实资料后，再更新活动登记并运行正式边界步骤。

本机完整清单与核验结果位于 `reports/data/2026-10-29-boundary-supplement.json` 和同名 Markdown 报告；原始文件、候选清单、中间图层及报告按现有 Git 忽略规则保留在本地。
