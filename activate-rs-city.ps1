# 激活 rs-city 环境（PowerShell 5.1 / 7 通用）
#
# 用法（点号引入，作用于当前会话）：
#   . .\activate-rs-city.ps1
#   python src/01_preprocess.py --config configs/project.toml --env-file .env --step boundaries
#
# 环境前缀默认 F:\rs-tools\envs\rs-city。换机器或换位置时先设置变量再执行：
#   $env:RS_CITY_PREFIX = 'D:\conda\envs\rs-city'
#   . .\activate-rs-city.ps1
# 脚本优先采用 RS_CITY_PREFIX，未设置时回落到默认路径。
#
# 说明：本机未安装 conda/micromamba 的命令行激活钩子，因此这里直接设置
# CONDA_PREFIX 派生的 PATH、PROJ_DATA、GDAL_DATA。缺少 PROJ_DATA 时
# pyproj 会报 "unable to set PROJ database path"，坐标转换与 CRS 判断可能失败。

$rsCityPrefix = if ($env:RS_CITY_PREFIX) { $env:RS_CITY_PREFIX } else { 'F:\rs-tools\envs\rs-city' }

$env:CONDA_PREFIX = $rsCityPrefix
$env:CONDA_DEFAULT_ENV = 'rs-city'
$env:PATH = @(
    $env:CONDA_PREFIX
    "$env:CONDA_PREFIX\Library\mingw-w64\bin"
    "$env:CONDA_PREFIX\Library\usr\bin"
    "$env:CONDA_PREFIX\Library\bin"
    "$env:CONDA_PREFIX\Scripts"
    $env:PATH
) -join ';'
$env:PROJ_DATA = "$env:CONDA_PREFIX\Library\share\proj"
$env:PROJ_LIB = $env:PROJ_DATA
$env:GDAL_DATA = "$env:CONDA_PREFIX\Library\share\gdal"

Write-Host "rs-city 已激活：$env:CONDA_PREFIX\python.exe"