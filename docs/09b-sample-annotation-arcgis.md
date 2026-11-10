# 样本标注操作手册（ArcGIS 版，4 类）

> 目标产物：`E:\工程实践3\GCSJ3\data\samples\2021\labels.gpkg` 与 `...\1992\labels.gpkg`
> 硬性要求：**图层名 `labels`**、**几何类型 Polygon**、**坐标系 EPSG:32648（WGS 1984 UTM Zone 48N）**、字段 `sample_id` / `group_id` / `class_id` 必须有。
> 对应 QGIS 版：[09-sample-annotation-sop.md](09-sample-annotation-sop.md)。两版规则完全一致，只是操作路径不同。

---

## 0. 先确认你的 ArcGIS 版本

| 版本 | 能不能直接写 GeoPackage | 做法 |
| --- | --- | --- |
| **ArcGIS Pro 2.2 及以上** | 能 | 按 §1—§7 直接干，一步到位 |
| ArcGIS Pro 2.0/2.1 | 不能 | 按 §8 先建 File GDB，我帮你转 |
| **ArcMap 10.x** | 不能（根本不支持 gpkg） | 按 §8 建 File GDB 或 Shapefile，我帮你转 |

不确定版本：Pro 里 `工程 → 关于`；ArcMap 里 `帮助 → 关于 ArcMap`。

> 说明：本机没装 ArcGIS，我无法截图。下面用「功能名（英文菜单名）」写法，中英文界面都能对上位置。

---

## 1. 新建工程并设定坐标系

1. 打开 ArcGIS Pro → **新建（New）→ 地图（Map）**；
2. 命名如 `xindu_labels`，位置随意（**不要**放中文路径过深的目录，路径里别带空格）；
3. 关键一步：**地图属性改坐标系**。内容窗格右键「地图（Map）」→ **属性（Properties）→ 坐标系（Coordinate Systems）** → 搜 `WGS 1984 UTM Zone 48N` → 选中（其 WKID 就是 **32648**）。

**为什么必须先设**：Pro 默认可能是 `WGS 1984 Web Mercator`。地图坐标系错了，后面新建的要素类也会跟着错，等标完几百个面再发现，只能全部重画。

---

## 2. 加载底图并设置显示

`添加数据（Add Data）`，依次加入：

| 用途 | 文件 | 符号系统设置 |
| --- | --- | --- |
| **2021 主底图（15 m 真彩色）** | `outputs\rasters\xindu_2021_pan_rgb_15m.tif` | RGB 合成：红=Band 1、绿=Band 2、蓝=Band 3；拉伸类型「**百分比裁剪（Percent Clip）**」，最小 2 / 最大 98 |
| **2021 假彩色（30 m）** | `outputs\rasters\xindu_2021_sr_30m.tif` | RGB 合成：红=**nir**、绿=**red**、蓝=**green**；拉伸 2%–98% |
| **1992 假彩色（30 m）** | `outputs\rasters\xindu_1992_sr_30m.tif` | 同上：红=nir、绿=red、蓝=green；拉伸 2%–98% |
| **镇街边界** | `data\processed\boundaries\xindu_2021.gpkg`，要素类 `townships` | 空心描边、线宽 1.5，不填充 |
| **研究区范围** | 同库，要素类 `study_area` | 空心描边、虚线 |

具体操作（Pro）：内容窗格右键栅格 → **符号系统（Symbology）** → 顶部选 **RGB 合成（RGB Composite）** → 三个下拉框分别指定红/绿/蓝波段 → 展开 **拉伸（Stretch）** → 类型选「百分比裁剪」，设 2 / 98。

> **最常见的坑**：`sr_30m.tif` 里存的是 0—1 的地表反射率，不做 2%–98% 拉伸，加载出来是全黑或全灰，什么都看不见。这不是数据坏了。
>
> 波段名对应关系：本项目的波段顺序是 `blue, green, red, nir, swir1, swir2`，即 **1=蓝、2=绿、3=红、4=近红外、5=短波红外1、6=短波红外2**。所以「真彩色=1-2-3」「标准假彩色=4-3-2」。Pro 里下拉框会直接显示波段名，按名字选比按序号选更稳。

---

## 3. 创建 `labels` 要素类

1. 打开 **目录（Catalog）** 窗格 → 定位到 `E:\工程实践3\GCSJ3\data\samples\2021\`；
2. 右键该文件夹 → **新建（New）→ GeoPackage**，命名 `labels.gpkg`（如果已有同名文件会提示，选新建/覆盖前先备份）；
3. 右键新建出来的 `labels.gpkg` → **新建（New）→ 要素类（Feature Class）**；
4. 参数：

| 项 | 填什么 |
| --- | --- |
| 名称（Name） | **`labels`**（必须一字不差，小写） |
| 别名（Alias） | `labels` |
| 几何类型（Geometry Type） | **Polygon（面）** |
| 坐标系 | **WGS 1984 UTM Zone 48N**（EPSG:32648）——**不要**用默认的 WGS 1984 |
| 含 M/Z 值 | 都不勾 |
| 容差 | 默认即可 |

5. 切到 **字段（Fields）** 页，按下表添加（**字段名必须完全一致，区分大小写，不能有中文和空格**）：

| 字段名 | 数据类型（GPKG） | 长度 | 别名 | 说明 |
| --- | --- | --- | --- | --- |
| `sample_id` | Text | 32 | 样本编号 | 唯一，如 `2021_c1_g01_12` |
| `group_id` | Text | 32 | 地块组 | 如 `c1_g01`，同地块多个面共用 |
| `year` | Long（整型） | — | 年份 | 2021 / 1992 |
| `class_id` | Long（整型） | — | 类别码 | **只能 1—4** |
| `label_source` | Text | 32 | 来源 | `manual_2021` / `manual_1992` |
| `source_date` | Text | 16 | 成像日期 | `2021-02-05` / `1992-08-16` |
| `annotator` | Text | 32 | 标注人 | 你的名字缩写 |

> 代码只强制要 `sample_id`、`group_id`、`class_id` 三个；其余四个是留档与验收要看的，别省。
>
> **`class_id` 用 Long，不要用 Text**：代码里 `int(row["class_id"])` 遇到 `"1 "` 这种带空格的文本会崩。

---

## 4. 开始画多边形

1. 顶部 **编辑（Edit）** 选项卡 → **创建（Create）** → 要素模板里选 `labels` → 工具选 **多边形（Polygon）**；
2. 沿地物边界逐个点击顶点，双击或按 `F2` 闭合；
3. 画完后在 **属性（Attributes）** 窗格（或弹出的属性框）里填那 7 个字段；
4. 每标完一批按 **Ctrl+S** 或 **编辑 → 保存（Save Edits）**。

省力技巧：

- **按类集中标注**：先把 1 类标够 8 组，再换 2 类。混着标判读标准容易漂。
- **批量填 `class_id`**：属性表里按 `group_id` 排序 → 选中同一类的所有行 → 右键 `class_id` → **计算字段（Calculate Field）** → 填 `1`。比一个个点快得多。
- **自动生成 `sample_id`**：属性表右键 `sample_id` → 计算字段 → 表达式（Python 3）：
  ```python
  !group_id! + "_" + str(!OBJECTID!)
  ```
  （需先填好 `group_id`；这样每个面的 `sample_id` 天然唯一）
- **`year` / `label_source` / `source_date` / `annotator` 同理**批量计算，一次填完一整批。
- **顶点捕捉**：编辑选项卡打开 **捕捉（Snapping）**，画相邻地块时能贴齐，避免留缝。
- 不确定的地物**跳过**，不要猜。错标比缺标危害大。

---

## 5. 标注规则（与 QGIS 版一致，简版）

| 类 | 判读 | 易错 |
| --- | --- | --- |
| **1 城镇及建设用地** | 成片房屋、厂房、仓储、硬化道路广场、农村硬化院落、**在建工地与推平待建地** | 别把田埂、机耕道画进来；别把大棚当建筑 |
| **2 耕地** | 规则田块、水田旱地菜地、休耕田、**翻耕后暂时裸露的田** | 1992-08 生长期红得发亮；2021-02 冬闲田偏灰，按田块轮廓判 |
| **3 林草植被** | 成片林、苗圃、公园绿地、荒草地、**川西林盘竹冠** | 林盘常半树半房，选竹冠占比高的整块 |
| **4 水体** | 河流、渠、水库、坑塘、养殖水面 | 枯水期河床砂石滩不算水体 |

**原「裸地」归并**：在建工地/待建地 → 1；翻耕裸田/冬闲裸田 → 2；河滩按常水位岸线（线内→4，线外→2）；浅丘裸露土坡 → 2。**不得新造第 5 类。**

**`group_id` 编码**：`c{类号}_g{序号:02d}`，如 `c1_g01`、`c4_g12`。一个物理地块 = 一个组；被路切开或夹了小地物仍算同组，多个面共用同一个 `group_id`。空间上相隔远的才算不同组。**一个 `group_id` 只能对应一个 `class_id`**——代码会检查，违反直接报错。

**数量**：每类 ≥8 组（建议 10—12 组），尽量分散到 9 个镇街，别把同类样本全挤在一个片区，否则留出验证会虚高。

**面大小**：最小 3×3 像元（90 m×90 m），建议 5×5 像元（150 m×150 m）以上，保证内部有纯像元。

---

## 6. 交给我之前必须做的事（ArcGIS 特有）

1. **保存编辑**（Ctrl+S），确认没有未提交的编辑会话；
2. **把 `labels` 图层从地图里移除**，或者干脆**关掉 ArcGIS Pro**。

> 这一步不能省：ArcGIS 会独占锁住 `.gpkg`，我这边 Python 读的时候会报 `database is locked` 或读到空表。QGIS 也一样有锁，只是没这么顽强。

3. 确认文件确实在：
   - `E:\工程实践3\GCSJ3\data\samples\2021\labels.gpkg`
   - `E:\工程实践3\GCSJ3\data\samples\1992\labels.gpkg`

4. 跑一遍自检（Pro 开着也能跑，读不到再关）：

```powershell
cd 'E:\工程实践3\GCSJ3'
. .\activate-rs-city.ps1
python -X utf8 -c @'
import geopandas as gpd
g = gpd.read_file(r"data\samples\2021\labels.gpkg", layer="labels")
print("CRS:", g.crs)
print("字段:", list(g.columns))
print("每类组数:"); print(g.groupby("class_id")["group_id"].nunique())
print("类别码:", sorted(g["class_id"].unique()))
print("空 class_id:", int(g["class_id"].isna().sum()))
print("组跨类别冲突:", int((g.groupby("group_id")["class_id"].nunique() > 1).sum()))
'@
```

合格标准：

- [ ] `CRS: EPSG:32648`
- [ ] 字段里能查到 `sample_id`、`group_id`、`class_id`
- [ ] 每类组数都 ≥ 8
- [ ] 类别码只有 `[1, 2, 3, 4]`
- [ ] 空 `class_id` 为 0
- [ ] 组跨类别冲突为 0

五项全过，告诉我，我跑 02 → 05。

---

## 7. 常见错误对照表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 底图全黑/全灰 | 没做 2%–98% 拉伸（反射率是 0—1 小数） | 符号系统里改拉伸 |
| 假彩色颜色怪 | 波段选成 1-2-3 了 | 红=nir(4)、绿=red(3)、蓝=green(2) |
| 建要素类时找不到 GeoPackage 选项 | Pro 版本 < 2.2 或建在了文件夹上 | 按 §8 走 File GDB |
| `Required input labels vector not found` | 路径或文件名不对 | 必须叫 `labels.gpkg`，放在 `data\samples\{year}\` |
| `no such table: labels` | 要素类名不叫 `labels`（可能被建成 `labels_1`） | 重命名要素类 |
| `database is locked` | ArcGIS 还开着并锁着文件 | 关 Pro / 移除图层 |
| 我报「class_id 不是整数」 | 字段建成 Text 且填了空格 | 字段类型改 Long，重新计算 |
| 提取到的像元数为 0 | 面太小，或压在云/无效像元上 | 换位置、画大一点 |
| CRS 显示 `EPSG:4326` | 建要素类时用了默认 WGS 1984 地理坐标系 | 重投影或重建（这一步返工最贵，一开始就设对） |

---

## 8. 附录：ArcMap 10.x，或 Pro 版本 < 2.2

这两类都**不能直接写 GeoPackage**，改走 File Geodatabase：

1. 在 `data\samples\2021\` 下新建 **文件地理数据库（File Geodatabase）** `labels.gdb`；
2. 其中新建要素类 `labels`：Polygon、坐标系 `WGS_1984_UTM_Zone_48N`，字段同 §3；
3. 照常标注、保存、关闭 ArcGIS；
4. 告诉我，我用 GDAL 转成 gpkg（一行命令，我这边有环境）：

```powershell
# 我执行，你不用管
ogr2ogr -f GPKG "data\samples\2021\labels.gpkg" "data\samples\2021\labels.gdb" labels -nln labels -a_srs EPSG:32648 -lco GEOMETRY_NAME=geom
```

如果是 Shapefile：同理，`-nln labels -a_srs EPSG:32648`，注意 Shapefile 字段名会被截到 10 字符，`label_source`/`source_date` 会变 `label_sour`/`source_dat`，转换时我再映射回来。

---

## 9. 时间估算与建议顺序

- 4 类 × 8 组 × 2 年 ≈ 64 个组，每组 1—3 分钟，熟练后 **2—4 小时**；
- 先标 2021（15 m 底图清楚），再标 1992（30 m 假彩色，参照 2021 的轮廓位置平移着找）；
- 1992 与 2021 物候差极大（8 月水稻旺长 vs 2 月冬春枯黄），**同位置两年一个红一个灰是正常的**，判读看地物类型，不看颜色深浅；
- 方案里的「CVA + CLCD 迁移」需要武汉大学 CLCD 数据，目前没下载，所以 1992 只能人工判读。