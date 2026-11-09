# 数据文件使用规范与回退手册（队友版）

**适用对象：** 使用本组已准备影像、边界、样本与登记表的同学。
**配套文档：** [数据目录](01-data-layout.md)、[公共契约](03-contracts.md)、[标注指南](labeling-guide.md)、[环境说明](02-environment.md)。
**一句话原则：原件只读、改动另存、动手前留快照、错了按清单回退。**

---

## 0. 30 秒速查

**三条红线（碰了就要回退，别硬扛）**

1. 不在 `data/raw/` 里改名、移动、重投影、另存、删除任何文件。
2. 不覆盖 `data/samples/{year}/labels.gpkg`；补标只追加，改结构先备份。
3. 不把中间结果写进别人的目录（`data/interim/A` 到 `F` 各写各的）。

**开工三步**

```powershell
cd 'E:\工程实践3\GCSJ3'
git status                 # 1. 确认工作区干净，知道自己在哪个分支
git switch -c try/你的名字-任务   # 2. 实验性改动先开分支，错了直接切回 main
# 3. 涉及样本/登记表/配置时，先做一次快照（见第 7 节 L1）
```

**出错第一时间**

| 症状 | 先做 | 不要做 |
| --- | --- | --- |
| 覆盖了样本 gpkg | 从 `.cache\snapshots\` 最近快照还原 | 继续在坏文件上补标 |
| 改了 `raw/` 下文件 | 用第 7 节 L3 从原始 tar 重新解压 | 手工“改回去” |
| 配置/文档改乱了 | `git checkout -- <文件>` | 凭记忆重写 |
| 类别图被重采样糊了 | 删产物重跑，用最近邻 | 在不同重采样结果上继续统计 |
| 不确定错没错 | 先跑第 7 节哈希比对 | 先跑全流程 |

---

## 1. 数据在哪：目录地图

仓库根目录（当前机器）：`E:\工程实践3\GCSJ3`。`data/` 是 `RS_DATA_ROOT` 的默认值（见 `.env.example`），所有登记表里的路径都相对它、用 `/` 书写。

```
GCSJ3\data\
├─ raw\                              # 原件，只读
│  ├─ landsat\1992\level2\<product_id>\
│  ├─ landsat\2021\level2\<product_id>\
│  ├─ landsat\2021\level1\<product_id>\
│  ├─ landsat\excluded\              # 误选场景，保留但不用
│  ├─ boundaries\county\{1990,2021}\
│  ├─ boundaries\townships\2021\
│  └─ reference_maps\{raster,vector}\
├─ samples\{1992,2021}\labels.gpkg   # 人工标注，唯一真值来源
├─ interim\A … F\                    # 并发工作线各自的临时盘
├─ processed\                        # 可再生的中间成果（边界、网格、反射率、样本 CSV）
└─ catalog\                          # 登记表：scenes / boundaries / reference_maps
outputs\                              # 最终栅格、矢量、表格、模型、地图
reports\                              # 数据、精度、分析、验收报告
```

**归属约定：** `raw` 谁都不写；`samples` 只有样本负责人写；`processed`、`outputs` 是产物，允许删了重跑；`catalog` 与 `docs` 进 Git，其余真实数据不进 Git。

### 1.1 本机现状核对（2026-11-06 更新，用前先看这一节）

| 项目 | 实际状态 | 说明 |
| --- | --- | --- |
| `data/raw/landsat/2021/level2` | 已就位：`LC08_L2SP_129039_20210205_20210303_02_T1`，27 个文件 | SR_B2—B7 + QA 齐全，30 m，云量 0.42% |
| `data/raw/landsat/2021/level1` | 已就位：`LC08_L1TP_129039_20210205_20210303_02_T1`，24 个文件 | B2/B3/B4/B8 + QA，15 m，供融合 |
| `data/raw/landsat/1992/level2` | 已就位：`LT05_L2SP_129039_19920816_20200914_02_T1`，27 个文件 | SR_B1—B5/B7 + QA，7821×7091，30 m |
| `data/raw/landsat/1992/level1` | 已就位：`LT51290391992229BJC00`，12 个文件 | L1T（DN 值），仅作对照，不进流水线 |
| `data/raw/landsat/excluded` | 已就位：`LT05_L2SP_129044_...`，27 个文件 | 129/044 且云量 100%，实测范围在云南，不覆盖新都 |
| `data/raw/boundaries/county/1990` | 已就位：全国县级区划 1990，6 个文件 | EPSG:4326，含新都县 `CODE1990=510125` |
| **2021 年县界 / 9 个街镇面** | **仍缺，当前唯一阻塞项** | `prepare_boundaries()` 要求 2021 的 `county` 与 `township` 两个**面状**图层 |
| `D:\BaiduNetdiskDownload\全国地理基础信息数据库` | **不可用** | 1:400 万国家基础地理信息，只有县面/地级市面/县点，**没有乡镇面**；县面无 `.prj`，与 1990 县面 IoU 仅 0.833、36.5 km² 落在县外 |
| 全国电子地图 shp | 仍在 `搜集的数据\全国电子地图shp（2021）\`（rar/zip） | 本机无 7z/unrar；旧记录显示其街镇只有点位，不能替代面状街镇界 |
| `data/catalog/*.csv` | 已建三张表，含真实行 | 编目与 MTL 核对四行全部一致 |
| `data/raw` 哈希基线 | `.cache/raw-manifest.csv`，131 条 SHA-256，3.73 GB | 原件是否被改动以此比对 |
| `.env` | 已创建 | 相对路径，默认值 |
| 文档里的盘符 | `docs` 早期章节仍写 `F:\工程实践3`（环境确在 F 盘） | 代码仓库与数据实际在 `E:\工程实践3\GCSJ3` |

> 结论：两期 L2 影像都已就位并核验通过；整链只剩**2021 年面状县界与 9 个街镇面**这一项外部补件。明细见 [2026-11-05 入库记录](../reports/data/2026-11-05-data-ingest.md)。

---

## 2. 七条铁律（含原因）

1. **原件只读。** `raw/` 下的文件名、目录名、波段号、MTL 都是 USGS 产品的一部分，改了之后产品号与内容对不上，任何人都无法核对。需要转换就写到 `processed/`。
2. **一套产品一个目录。** 解压目标必须是 `raw/landsat/<年>/<级别>/<product_id>/`，不要解到 `level2/` 根目录，不要把两景混在一个目录。
3. **SHP 成套。** `.shp/.shx/.dbf/.prj`（有 `.cpg` 一并）同目录同名；少一个文件在 QGIS 里就是"打不开"或"属性表空"。
4. **坐标系从元数据核实。** 不因为"位置看着偏"就手动指定 WGS84；需要换投影输出到 `processed/`。
5. **类别图只用最近邻。** 分类结果、掩膜、标签栅格重采样一律 `nearest`；`bilinear` 只用于连续影像（反射率、指数）。用了双线性会产生 2.5 这种没有意义的类别值。
6. **两期比较先统一网格。** 30 m、`EPSG:32648`、同一范围；不对齐就做变化统计，差值里会混进位置偏移。
7. **样本按地块分组隔离。** `group_id` 是划分单位，训练与验证的地块组不能有交集；同一地块的相邻多边形共用同一个 `group_id`。

---

## 3. 开工前自检（5 分钟）

```powershell
cd 'E:\工程实践3\GCSJ3'

# 1) 环境：科学计算栈在独立 conda 环境里，系统 python 没有 rasterio
python -c "import rasterio, geopandas, sklearn; print('ok')"   # 失败说明没激活 rs-city 环境
# 激活方式见 docs/02-environment.md，例如：
# & 'F:\rs-tools\miniforge3\shell\condabin\conda-hook.ps1'; conda activate 'F:\rs-tools\envs\rs-city'

# 2) 路径：确认数据根目录
Get-ChildItem data\raw\landsat -Recurse -File | Where-Object Name -ne '.gitkeep' | Measure-Object

# 3) 原件是否被改过（首次运行会生成基线，之后每次比对）
Test-Path .cache\raw-manifest.csv

# 4) 登记表是否有真实行
Get-Content data\catalog\scenes.csv -ErrorAction SilentlyContinue

# 5) 输入是否齐（波段、QA、MTL 缺一项就别开工）
Get-ChildItem 'data\raw\landsat\2021\level2\LC08_L2SP_129039_20210205_20210303_02_T1' -Filter *.TIF | Select-Object -ExpandProperty Name
```

**场景核对四问：** 年份对不对、拍摄日期对不对、WRS path/row 是不是 129/039、研究区内云量能不能接受。任何一项不符，停下来问，不要"先用着"。

---

## 4. 标准作业顺序

处理顺序固定，上一步产物是下一步输入；每一步都能单独重跑，所以**每步输出到独立目录，不覆盖上一步**。

| 步 | 入口脚本 | 典型输入 | 输出位置 | 这一步的回退点 |
| --- | --- | --- | --- | --- |
| 1 影像预处理 | `src/01_preprocess.py` | `raw/landsat/*/level2/*` | `data/processed/{year}/` | 删掉该期 `processed/{year}/` 重跑，`raw` 不受影响 |
| 2 边界与网格 | `01_preprocess.py`（边界步骤） | `raw/boundaries/2021/*` | `data/processed/boundaries`、`grids` | 边界产物可再生；原件不动 |
| 3 样本与特征 | `src/02_samples.py` | `samples/{year}/labels.gpkg` + `processed/{year}/` | `data/processed/samples/{year}/`（含 `split.json`、`train.csv`、`holdout.csv`） | `split.json` 一旦冻结，重跑前先备份；改划分等于换实验 |
| 4 分类 | `src/03_classify.py` | `processed/samples/{year}/train.csv` | `outputs/rasters`、`outputs/models/{year}` | 删模型与分类图重跑；模型可再造 |
| 5 评价 | `src/04_evaluate.py` | 分类图 + `holdout.csv` | `outputs/tables`、`reports/accuracy` | 只读 holdout，**不得为达标反复调划分** |
| 6 变化与统计 | `src/05_analyze.py` | 两期分类图 + 街镇面 | `outputs/vectors/change`、`outputs/tables` | 可重跑；面积口径按 `configs/project.toml` |

**顺序原则：** 云与云影掩膜 → 波段对应 → 反射率换算 → 坐标与范围统一 → 30 m 网格 → 特征 → 样本 → 分类 → 评价 → 变化。跳过掩膜直接换算，云像元会被当成地物。

**只跑局部时：** 用同一份 `configs/project.toml`，不要手改参数临时试；要试就复制成 `configs/project.try-XXX.toml` 并在汇报里写明。

---

## 5. 解压与登记（当前最该先做的）

### 5.1 解压影像

tar 包里是**平铺文件**（没有顶层产品目录），所以先建产品目录再解压：

```powershell
$root = 'E:\工程实践3\GCSJ3'
$tar  = 'E:\工程实践3\搜集的数据'
$id   = 'LC08_L2SP_129039_20210205_20210303_02_T1'
$dst  = Join-Path $root "data\raw\landsat\2021\level2\$id"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
& 'C:\Windows\System32\tar.exe' -xf (Join-Path $tar "$id.tar") -C $dst
Get-ChildItem $dst -Filter *.TIF | Select-Object -ExpandProperty Name
```

注意：

- 用 **Windows 自带 `tar.exe`**（`C:\Windows\System32\tar.exe`）。PATH 里若有 MSYS/Git 的 `tar`，在受限环境会报 `couldn't create signal pipe`。
- 解压前确认磁盘：两个压缩包合计 2.15 GB，解压后约 2–2.5 GB，`E:` 当前余量 38.8 GB 够用。
- L1TP 同理，目标是 `raw\landsat\2021\level1\<product_id>`。
- **解压完立刻对产物做哈希基线**（第 7 节 L3），否则日后无法证明原件没被动过。

### 5.2 登记到 catalog

真实登记表 `data/catalog/scenes.csv` 从模板复制后按行填，路径相对 `data`、用 `/`：

```powershell
Copy-Item data\catalog\scenes.example.csv data\catalog\scenes.csv
Copy-Item data\catalog\boundaries.example.csv data\catalog\boundaries.csv
```

| 字段 | 填写要求 |
| --- | --- |
| `processing_level` | 照 MTL 实写：`L2SP` / `L1TP`，不猜 Collection 号 |
| `scene_dir` / `mtl_path` | 相对 `data`，如 `raw/landsat/2021/level2/LC08_L2SP_..._T1` |
| `acquisition_date` | `YYYY-MM-DD`，取自 MTL |
| `paired_product_id` | 2021 年 L1 与 L2 互填；1992 留空 |
| `selection_status` | `candidate` 或 `selected`，同一用途只留一条 `selected` |
| `verification_status` | 没核实过就写 `pending`，不要写 `verified` |

**不可编造：** 未知下载日期、来源 URL 留空并注明，不填假值。

---

## 6. 常见错误对照表

| 现象 | 真实原因 | 立刻怎么做 | 要回退吗 |
| --- | --- | --- | --- |
| 影像值在 0–10000 之间，算出的 NDVI 全是怪值 | 没乘 `0.0000275` 再减 `0.2`，还是 DN 值 | 改用 SR 换算后重跑特征 | 删特征产物重跑 |
| 分类图出现 2.5 / 3.7 这类值 | 类别栅格用了双线性重采样 | 改 `categorical_resampling = "nearest"` | 删分类图重跑 |
| 两期叠加错位几百米 | 一期没统一到 `EPSG:32648` 或范围不一致 | 统一投影、范围、30 m 网格 | 重跑预处理 |
| QGIS 打开边界"跑到海里" | 缺 `.prj` 或 CRS 未核实就手动指定 | 补 `.prj`，从元数据查 EPSG | 不要用已错位版本出图 |
| 训练精度 0.99，留出只有 0.6 | 训练/验证像元重叠，或同一地块被拆成两组 | 检查 `train.csv`/`holdout.csv` 的 `group_id` 交集必须为空 | 重做划分（先备份旧 `split.json`） |
| 补标后旧样本属性丢失 | 在 QGIS 里"另存为"覆盖了 `labels.gpkg` | 从快照还原，再按追加方式补标 | 是，从快照还原 |
| 面积总和与研究区对不上 | 把 NoData/云当成非建设地表，或用了在线瓦片算面积 | 用共同有效掩膜 `processed/common/valid_common_30m.tif` | 重算统计 |
| 1992 年样本标成了现代地物 | 用现代高清底图推 1992 年 | 只用 1992 年影像与历史对照图重判 | 是，整组重标 |
| `gdalinfo` / `rasterio` 找不到 | 没激活 `rs-city` 环境 | 按 `docs/02-environment.md` 激活 | 否 |
| 报缺 2021 县界 / 街镇面 | 正式边界确实还没补齐 | 停下来反馈，不拿候选面顶替 | 否 |

---

## 7. 回退机制（三级，按代价从小到大）

### L0 预防：只读 + 分支

- `data/raw/` 一律不写：需要转换、裁剪、重投影就输出到 `processed/`。
- 实验性改动开分支：`git switch -c try/xxx`，回退是 `git switch main`。
- 大批量改动前，把要动的目录整体复制一份再动。

### L1 快照 + 哈希清单（样本/登记表/配置，秒级）

动 `samples`、`catalog`、`configs` 之前跑一次：

```powershell
$root  = 'E:\工程实践3\GCSJ3'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$snap  = Join-Path $root ".cache\snapshots\$stamp"
New-Item -ItemType Directory -Force -Path $snap | Out-Null
foreach ($d in 'data\samples','data\catalog','configs') {
  $src = Join-Path $root $d
  if (Test-Path $src) { Copy-Item -Recurse -Force -LiteralPath $src -Destination (Join-Path $snap (Split-Path $d -Leaf)) }
}
$rows = Get-ChildItem -Recurse -File -LiteralPath $snap | ForEach-Object { Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256 } | Select-Object Path,Hash
$rows | Export-Csv (Join-Path $snap 'manifest.csv') -NoTypeInformation -Encoding utf8
"快照已建: $snap（$($rows.Count) 个文件）"
```

还原单个文件（先确认路径再执行）：

```powershell
$root = 'E:\工程实践3\GCSJ3'
$snap = (Get-ChildItem "$root\.cache\snapshots" -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
Copy-Item -LiteralPath "$snap\samples\2021\labels.gpkg" -Destination "$root\data\samples\2021\labels.gpkg" -Force
```

还有一层：QGIS 里编辑 `labels.gpkg` 时，改错了用 **Ctrl+Z**（编辑会话内可撤销），保存前先想清楚；已经保存就用快照还原。`.cache/` 已被 `.gitignore` 排除，快照不会污染仓库。

### L2 Git 回退（文档、配置、代码）

```powershell
cd 'E:\工程实践3\GCSJ3'
git status                                  # 先看清楚改了什么
git diff -- docs/ configs/ src/             # 再确认改动范围
git stash push -m '试验改动' -- docs/ configs/   # 想保留又不想生效
git checkout -- docs/08-data-usage-and-rollback.md  # 撤销单个文件
git reset --hard HEAD                       # 丢弃全部未提交改动；执行前先 git status 确认
git switch main                             # 切回主线，放弃整条试验分支
```

数据文件不在 Git 里，**Git 回退救不了 `raw/` 和 `labels.gpkg`**，别指望 `git checkout` 还原它们。

### L3 原始数据校验与重解压

原件是否被改动，用哈希比对：

```powershell
$root = 'E:\工程实践3\GCSJ3'
$base = "$root\.cache\raw-manifest.csv"
if (-not (Test-Path $base)) {
  New-Item -ItemType Directory -Force -Path "$root\.cache" | Out-Null
  $rows = Get-ChildItem -Recurse -File -LiteralPath "$root\data\raw" | ForEach-Object { Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256 } | Select-Object Path,Hash
  $rows | Export-Csv $base -NoTypeInformation -Encoding utf8
  "已建立基线：$($rows.Count) 个文件"
} else {
  Import-Csv $base | ForEach-Object {
    $p = $_.Path
    if (-not (Test-Path -LiteralPath $p)) { [pscustomobject]@{Path=$p;状态='缺失'} }
    elseif ((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash -ne $_.Hash) { [pscustomobject]@{Path=$p;状态='被改动'} }
  }
}
```

有输出就说明原件被动过。恢复方式是**从原始 tar 重新解压到新目录**，用新目录替换旧目录（旧目录改名留证据，不要直接删）：

```powershell
$root = 'E:\工程实践3\GCSJ3'
$id   = 'LC08_L2SP_129039_20210205_20210303_02_T1'
$old  = "$root\data\raw\landsat\2021\level2\$id"
Rename-Item -LiteralPath $old -NewName "$id.broken-$(Get-Date -Format yyyyMMdd)"
New-Item -ItemType Directory -Force -Path $old | Out-Null
& 'C:\Windows\System32\tar.exe' -xf "E:\工程实践3\搜集的数据\$id.tar" -C $old
```

**产物不用备份**：`processed/{year}`、`outputs/**` 都是可再生的，坏了就删掉重跑；只有 `samples/labels.gpkg` 与 `catalog/*.csv` 是无价的人工投入，必须靠 L1 快照。

---

## 8. 交接记录与汇报

每次动手，在 `reports/data/` 留一份简短记录（可复制下面模板），这就是别人复盘和回退的依据：

```markdown
# 2026-11-05 影像解压与登记

- 操作人：
- 环境：rs-city（Python 3.11 / GDAL x.x）
- 输入：E:\工程实践3\搜集的数据\LC08_L2SP_129039_..._T1.tar（967,065,600 字节）
- 操作：解压至 data\raw\landsat\2021\level2\<product_id>；登记 scenes.csv 1 行
- 校验：解压后 20 个 TIF + 4 个 MTL/ANG 齐全；SHA-256 基线写入 .cache\raw-manifest.csv
- 产物：无（仅原件就位）
- 已知问题：1992 年影像本机缺失；2021 街镇边界未取得
- 回退方式：删除该产品目录后重新解压；登记行 git checkout
```

**汇报口径：** 说清楚"哪份数据、哪一步、产出在哪、有没有校验"，不要把"文档写了"当成"数据到了"。

---

## 9. 找谁

| 事情 | 找谁 |
| --- | --- |
| 数据来源、解压位置、登记表、处理顺序 | 数据负责人（本人） |
| 影像与样本分类核对、判读分歧 | 刘世超 |
| 环境安装、脚本报错 | 环境/集成负责人 |
| 正式边界仍缺、口径变更 | 组长汇总后找老师确认 |

---

## 附：本手册对应的 skill

在 DSH 里可以直接让助手按本手册执行：调 `rs-data-handoff` 技能，它会先核对现状、再按顺序操作、并在改动前建快照。