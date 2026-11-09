# 环境变量、依赖与 Windows 环境

## 1. 三种配置的位置

| 文件 | 存什么 | Git | 当前状态 |
| --- | --- | --- | --- |
| `E:\工程实践3\.env` | 本机目录、GDAL 缓存大小 | 忽略 | 已由模板生成 |
| `E:\工程实践3\.env.example` | 可共享的变量名与默认值 | 保留 | 已创建 |
| `E:\工程实践3\configs\project.toml` | 投影、波段、类别、采样、模型、指标参数 | 保留 | 已创建，尚无程序读取 |
| `E:\工程实践3\environment.yml` | Python/GIS 包依赖 | 保留 | 已声明，未安装或求解验证 |

算法参数不塞进 `.env`；机器路径不写死在源码中。第一阶段离线运行，不需要地图 API Key、数据库连接、AI Key 或 Web 服务密钥。EarthExplorer 账号在下载网站使用，无需放入项目。

## 2. 已预留的环境变量

| 名称 | 默认值 | 含义 |
| --- | --- | --- |
| RS_DATA_ROOT | `./data` | 原始影像、地图、样本、目录表及中间数据根目录 |
| RS_OUTPUT_ROOT | `./outputs` | 栅格、矢量、模型、CSV、地图成果根目录 |
| RS_REPORT_ROOT | `./reports` | 文字报告、评价 JSON 和验收证据根目录 |
| RS_SCRATCH_ROOT | `./.cache/processing` | GDAL 处理临时目录 |
| GDAL_CACHEMAX | `512` | GDAL 缓存上限，单位 MB |

未来五个入口统一接受 `--config configs/project.toml --env-file .env`。I 在 P0 实现加载规则：显式命令行参数决定配置文件位置；进程中已设置的环境变量优先于 `.env`；`.env` 缺项采用 `.env.example` 所列程序默认值。这里的默认值是唯一已声明配置口径，不增加备用数据源或路径搜索机制。所有相对路径固定以仓库根目录解析，与启动命令的当前目录无关。

当前 `.env` 只是文本文件，PowerShell、QGIS 和 GDAL 不会自动读取它。未来 Python 入口通过 python-dotenv 加载，并在首次使用 GDAL 之前设置对应参数；临时目录映射到 `CPL_TMPDIR`。这部分逻辑尚未实现。

外置数据示例，修改本机 `.env`：

```dotenv
RS_DATA_ROOT=F:/rs-data/xindu
RS_OUTPUT_ROOT=F:/rs-results/xindu/outputs
RS_REPORT_ROOT=F:/rs-results/xindu/reports
RS_SCRATCH_ROOT=F:/rs-cache/xindu
GDAL_CACHEMAX=512
```

目录换位置不改变内部结构；含空格的路径用双引号包围。不要提交真实 `.env`。

## 3. 环境准备方案（未来执行，本次未安装）

Python 固定 3.11。GIS 依赖统一来自 conda-forge，同一个环境内安装 GDAL/Rasterio/GeoPandas，避免各自混装。QGIS 使用 3.44 LTR 独立桌面安装；该 LTR 在本次核查的官方下载页面仍提供。[QGIS 官方下载](https://qgis.org/download/)

新工具建议位置：Miniforge `F:\rs-tools\miniforge3`，Python 环境 `F:\rs-tools\envs\rs-city`，包缓存 `F:\rs-tools\cache\conda-pkgs`，安装临时目录 `F:\rs-tools\tmp`，QGIS `F:\rs-tools\QGIS-3.44`。这些是未来安装位置，本次没有创建安装或改变全局环境变量。

先从 [Miniforge 官方仓库](https://github.com/conda-forge/miniforge) 下载 Windows 安装器，选择上述 F 盘路径。已有可用 Miniforge 时可使用现有安装；不要卸载或替换 C 盘工具。当前 PowerShell 的命令检索发现 Python 3.11，未发现 PATH 中的 conda/mamba；这不代表整台机器没有其他安装。

在能够调用 conda 的 PowerShell 中执行以下命令；若普通终端尚未加载 conda，使用安装器提供的 Miniforge PowerShell 入口：

```powershell
Set-Location -LiteralPath 'E:\工程实践3'
New-Item -ItemType Directory -Force -Path 'F:\rs-tools\envs', 'F:\rs-tools\cache\conda-pkgs', 'F:\rs-tools\tmp' | Out-Null
$env:CONDA_PKGS_DIRS = 'F:\rs-tools\cache\conda-pkgs'
$env:TEMP = 'F:\rs-tools\tmp'
$env:TMP = 'F:\rs-tools\tmp'
conda env create --prefix 'F:\rs-tools\envs\rs-city' --file .\environment.yml
conda activate 'F:\rs-tools\envs\rs-city'
python -c "from osgeo import gdal; import rasterio, geopandas, sklearn; print(gdal.VersionInfo()); print('GIS imports OK')"
gdalinfo --version
python -m osgeo_utils.gdal_pansharpen --help
```

这些命令只设置当前终端的缓存与临时目录。测试成功后记录实装版本；依赖声明目前只固定 Python 主次版本，**不是经过求解的锁文件**。后续在环境验收通过后导出 Windows 显式包清单到 `reports/acceptance/environment-win-64.txt`，归档复现版本，不把未验证版本写成已可运行。

```powershell
conda list --explicit | Set-Content -LiteralPath .\reports\acceptance\environment-win-64.txt -Encoding utf8
```

## 3.1 本机实际安装记录（2026-11-05）

本机没有 conda/mamba，也没有 QGIS；实际用 **micromamba** 从 conda-forge 建了独立环境，未改动 C 盘安装。

| 项目 | 实际值 |
| --- | --- |
| micromamba | `F:\rs-tools\bin\micromamba.exe`（2.10.0），`MAMBA_ROOT_PREFIX=F:\rs-tools\mamba` |
| 环境前缀 | `F:\rs-tools\envs\rs-city` |
| 包缓存 | `F:\rs-tools\cache\conda-pkgs` |
| Python | 3.11.18 |
| GDAL | 3.12.3（`from osgeo import gdal` 可用） |
| Rasterio / GeoPandas / Shapely | 1.4.4 / 1.2.0 / 2.2.0 |
| scikit-learn / numpy / pandas | 1.9.1 / 2.4.6 / 3.1.1 |
| 包数 | 166（含 pyogrio 0.12.1、pyproj 3.7.2） |
| 锁文件 | `reports/acceptance/environment-win-64.txt`（`--explicit` 清单） |

激活方式（仓库根目录执行，点号引入作用于当前会话）：

```powershell
. .\activate-rs-city.ps1
python -m pytest -p no:cacheprovider -q
```

`activate-rs-city.ps1` 只设置 `CONDA_PREFIX` 派生的 `PATH`、`PROJ_DATA`、`GDAL_DATA`。**缺 `PROJ_DATA` 时 pyproj 会警告 `unable to set PROJ database path`**，CRS 判断可能失败。

脚本的环境前缀默认为上表的 `F:\rs-tools\envs\rs-city`。队友机器上环境不在该位置时，先设置变量再激活，不要改脚本：

```powershell
$env:RS_CITY_PREFIX = 'D:\conda\envs\rs-city'   # 指向自己的 rs-city 前缀
. .\activate-rs-city.ps1
```

两个实测坑：

1. `micromamba create -f environment.yml` 在本机报 `YAML error in spec file`（连最小示例也复现），因此实际安装是把 `environment.yml` 里的依赖逐条写成命令行参数。`environment.yml` 本身仍是有效的依赖声明，用真正的 conda 应可正常求解。
2. 不要设置 `PYTHONIOENCODING=utf-8` 再跑测试：子进程输出变 UTF-8，而 `tests/unit/test_cli_*_invocation` 按 GBK 解码父进程捕获的输出，会以 `TypeError: argument of type 'NoneType' is not iterable` 失败。控制台中文乱码用 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` 解决，不要动 `PYTHONIOENCODING`。

2026-11-05 实测：`107 passed, 8 failed, 1 skipped`。8 项失败全部是真实数据/成果缺口（缺 `catalog/scenes.csv`、`catalog/boundaries.csv`、1992 L2 影像、`qgis/xindu_1992_2021.qgs`、`reports/analysis/urban_expansion.md`、`reports/data/data_gaps.md`），不是代码缺陷。

---

## 4. 后续运行方式

开发完成且真实输入到位后，统一从仓库根目录运行五个脚本。参数契约见[公共契约](03-contracts.md)。当前执行会因为入口尚不存在而失败，因此本次不运行这些业务命令。

不需要 npm、Docker、CUDA、PyTorch、数据库或服务器。GDAL_DATA/PROJ_DATA 不手写到其他软件目录，使用所激活 conda 环境自带配置。
