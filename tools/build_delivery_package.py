"""打包本次交付产物，供队友接手模块 B/C/D。

产出：
    F:\\handoff\\GCSJ3_delivery_<日期>.zip
    （同目录保留未压缩的 staging 目录，便于补发单个文件）

打包原则：
    - 原始影像（data/raw，6 GB）不入包，队友不需要重跑预处理；
    - 可重跑的中间产物酌情收录，人工判读样本（不可再生）必须收录；
    - 只存不压的格式（tif/png/docx/gpkg）用 STORED，文本用 DEFLATE；
    - 附 manifest.csv（sha256）与 README，传坏了能查出来。

    python -X utf8 tools/build_delivery_package.py
"""

from __future__ import annotations

import csv
import hashlib
import shutil
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAMP = "2026-11-10"
OUT_ROOT = Path(r"F:\handoff")
PKG_NAME = f"GCSJ3_delivery_{STAMP}"
STAGE = OUT_ROOT / PKG_NAME
ZIP_PATH = OUT_ROOT / f"{PKG_NAME}.zip"

# (源路径, 包内相对路径)
INCLUDE_FILES: list[tuple[str, str]] = [
    # 配置
    ("configs/project.toml", "configs/project.toml"),
    # 地表反射率（分类与分析的底座）
    ("data/processed/1992/sr_30m.tif", "data/processed/1992/sr_30m.tif"),
    ("data/processed/2021/sr_30m.tif", "data/processed/2021/sr_30m.tif"),
    ("data/processed/1992/valid_sr_30m.tif", "data/processed/1992/valid_sr_30m.tif"),
    ("data/processed/2021/valid_sr_30m.tif", "data/processed/2021/valid_sr_30m.tif"),
    # 19 维特征
    ("data/processed/features/feat_1992_30m.tif", "data/processed/features/feat_1992_30m.tif"),
    ("data/processed/features/feat_2021_30m.tif", "data/processed/features/feat_2021_30m.tif"),
    ("data/processed/1992/valid_features_30m.tif", "data/processed/1992/valid_features_30m.tif"),
    ("data/processed/2021/valid_features_30m.tif", "data/processed/2021/valid_features_30m.tif"),
    # 边界
    ("data/processed/boundaries/xindu_2021.gpkg", "data/processed/boundaries/xindu_2021.gpkg"),
    # 人工样本（不可再生）
    ("data/samples/1992/labels.gpkg", "data/samples/1992/labels.gpkg"),
    ("data/samples/2021/labels.gpkg", "data/samples/2021/labels.gpkg"),
    ("data/processed/samples/1992/train.csv", "data/samples/1992/train.csv"),
    ("data/processed/samples/2021/train.csv", "data/samples/2021/train.csv"),
    ("data/processed/samples/1992/split.json", "data/samples/1992/split.json"),
    ("data/processed/samples/2021/split.json", "data/samples/2021/split.json"),
    # 分类成果
    ("outputs/rasters/lulc_1992_final_30m.tif", "outputs/rasters/lulc_1992_final_30m.tif"),
    ("outputs/rasters/lulc_2021_final_30m.tif", "outputs/rasters/lulc_2021_final_30m.tif"),
    ("outputs/rasters/lulc_1992_3class_30m.tif", "outputs/rasters/lulc_1992_3class_30m.tif"),
    ("outputs/rasters/lulc_2021_3class_30m.tif", "outputs/rasters/lulc_2021_3class_30m.tif"),
    ("outputs/rasters/change_1992_2021_30m.tif", "outputs/rasters/change_1992_2021_30m.tif"),
    # 15 m 对照产品（仅展示）
    ("outputs/rasters/lulc_2021_15m.tif", "outputs/rasters/lulc_2021_15m.tif"),
    ("outputs/rasters/pan_2021_6band_15m.tif", "outputs/rasters/pan_2021_6band_15m.tif"),
    # 自建定标诊断（模块 A 证据）
    ("data/processed/1992/sr_selfcal_30m.tif", "data/processed/selfcal/1992_sr_selfcal_30m.tif"),
    ("data/processed/2021/sr_selfcal_30m.tif", "data/processed/selfcal/2021_sr_selfcal_30m.tif"),
]

INCLUDE_DIRS: list[tuple[str, str]] = [
    ("outputs/vectors", "outputs/vectors"),
    ("outputs/tables", "outputs/tables"),
    ("outputs/maps", "outputs/maps"),
    ("reports", "reports"),
    ("docs", "docs"),
]

# 已压缩格式直接存，不再压
STORED_SUFFIXES = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".gpkg", ".zip", ".qgz"}

README = """# GCSJ3 交付包（2026-11-10）

新都区 1992—2021 建设用地扩张分析的全部可用产物。代码在 GitHub：
<https://github.com/ChaoDaiShi/GCSJ3>

## 1. 先做三件事

1. 解压到本地任意目录，**不要放进 Git 仓库**（体积大且已被 .gitignore 忽略）；
2. 复制 `.env.example` 为 `.env`，把 `RS_DATA_ROOT` 等改成你的实际路径；
3. 跑验收命令（见第 5 节），确认数字能对上再开始改代码。

## 2. 目录说明

| 路径 | 内容 | 谁用 |
| --- | --- | --- |
| `data/processed/{1992,2021}/sr_30m.tif` | 6 波段地表反射率（30 m，L2SP） | B |
| `data/processed/{1992,2021}/valid_sr_30m.tif` | 有效像元掩膜（QA + AOI） | B |
| `data/processed/features/feat_*_30m.tif` | 19 维特征堆栈 | B |
| `data/processed/boundaries/xindu_2021.gpkg` | 9 镇街道界 | B/C |
| `data/samples/{1992,2021}/labels.gpkg` | **人工判读样本，不可再生** | B |
| `data/samples/{1992,2021}/train.csv` | 提取后的训练像元 | B |
| `data/samples/{1992,2021}/split.json` | 地块组分层留出划分 | B |
| `outputs/rasters/lulc_*_final_30m.tif` | 四类分类结果（已 Sieve） | C/D |
| `outputs/rasters/lulc_*_3class_30m.tif` | 三类稳健性对照 | C |
| `outputs/rasters/change_1992_2021_30m.tif` | 变化检测栅格 | C |
| `outputs/rasters/lulc_2021_15m.tif` | 15 m 对照产品（**仅展示**） | D |
| `outputs/vectors/` | 分类矢量、镇街统计面 | C |
| `outputs/tables/` | 面积表、街镇表、指标表 | C/D |
| `outputs/maps/` | 成图 PNG | D |
| `reports/` | Word/Markdown 报告、精度 JSON | D |
| `docs/` | 方法文档、变更记录 | 全部 |
| `data/processed/selfcal/` | 自建定标+大气校正结果（诊断证据，**未用于正式成果**） | 查阅 |

**没有收录**：`data/raw/`（原始影像 6 GB）。要重跑预处理请自行从 EarthExplorer 下载，
场景清单见 `docs/03-contracts.md` 与 GitHub 上的 `data/catalog/*.example.csv`。

## 3. 关键数字（验收基准）

| 指标 | 1992 | 2021 |
| --- | ---: | ---: |
| 留出 OA | 0.9247 | 0.8676 |
| 建设用地 km² | 20.94 | 110.42 |
| 占全区 | 4.2% | 22.2% |

全区净增 89.47 km²，年均 3.09 km²，扩张强度 0.62%。

## 4. 三条必须知道的口径

1. **精度是内部一致性**：像元纯度过滤把城镇限定在 NDVI ≤ 0.45、水体限定在 MNDWI ≥ 0，
   留出像元与训练规则同源，F1=1.0 不代表独立精度；
2. **1992 年耕地/林草分项面积不可引用**：两类的光谱可分性不足，只保证建设用地与水体可靠；
3. **15 m 产品只用于展示**：1992 年无免费 15 m 数据，两期不可比，不进入变化统计。

## 5. 验收命令

```powershell
# 环境
. .\\activate-rs-city.ps1

# 重跑精度评价，应与上表一致
python -X utf8 src\\04_evaluate.py --config configs\\project.toml --env-file .env --year 2021
python -X utf8 src\\04_evaluate.py --config configs\\project.toml --env-file .env --year 1992

# 重跑分析表
python -X utf8 src\\05_analyze.py --config configs\\project.toml --env-file .env
```

## 6. 数据来源

| 年份 | 产品 | 场景号 | 说明 |
| --- | --- | --- | --- |
| 1992 | Landsat 5 TM L2SP | LT05_L2SP_129039_19920816_20200914_02_T1 | 夏季，物候可比 |
| 2021 | Landsat 8 OLI L2SP | LC08_L2SP_129039_20210731_20210804_02_T1 | 夏季，**非方案写的 2 月** |
| 2021 | Landsat 8 OLI L1TP | LC08_L1TP_129039_20210731_20210804_02_T1 | 仅用于 15 m 融合取 B8 |

2021 年为什么不用 2 月：冬闲裸田与建成区光谱重合，建成区会被高估到 47.2%。

## 7. 校验

`manifest.csv` 记录了每个文件的 sha256。校验：

```powershell
Import-Csv manifest.csv | ForEach-Object {
  $h = (Get-FileHash $_.path -Algorithm SHA256).Hash
  if ($h -ne $_.sha256) { "校验失败：$($_.path)" }
}
```
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    copied: list[tuple[Path, str]] = []
    missing: list[str] = []

    for rel_src, rel_dst in INCLUDE_FILES:
        src = REPO / rel_src
        if not src.exists():
            missing.append(rel_src)
            continue
        dst = STAGE / rel_dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append((dst, rel_dst))

    for rel_dir, dst_dir in INCLUDE_DIRS:
        src_dir = REPO / rel_dir
        if not src_dir.exists():
            missing.append(rel_dir)
            continue
        for src in sorted(src_dir.rglob("*")):
            if not src.is_file():
                continue
            if src.suffix.lower() in {".tif", ".tiff"} and src.stat().st_size > 30 * 1024 * 1024:
                continue  # 目录里的大栅格已在 INCLUDE_FILES 中单独挑选
            rel = src.relative_to(src_dir)
            dst = STAGE / dst_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append((dst, str(Path(dst_dir) / rel).replace("\\", "/")))

    (STAGE / "README.md").write_text(README, encoding="utf-8")
    (STAGE / ".env.example").write_text(
        "# 复制为 .env 后改成你的实际路径（相对路径以仓库根目录解析）\n"
        "RS_DATA_ROOT=./data\n"
        "RS_OUTPUT_ROOT=./outputs\n"
        "RS_REPORT_ROOT=./reports\n"
        "RS_SCRATCH_ROOT=./.cache/processing\n"
        "GDAL_CACHEMAX=512\n",
        encoding="utf-8",
    )

    # manifest
    rows = []
    total = 0
    for path in sorted(STAGE.rglob("*")):
        if not path.is_file() or path.name == "manifest.csv":
            continue
        size = path.stat().st_size
        total += size
        rows.append({
            "path": str(path.relative_to(STAGE)).replace("\\", "/"),
            "bytes": size,
            "sha256": sha256(path),
        })
    with (STAGE / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["path", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"暂存目录：{STAGE}")
    print(f"文件数：{len(rows)}，合计 {total / 1024 ** 3:.2f} GB")
    if missing:
        print("缺失（未打包）：" + "、".join(missing))

    # 压缩：已压缩格式 STORED，文本 DEFLATE
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", allowZip64=True) as zf:
        for path in sorted(STAGE.rglob("*")):
            if not path.is_file():
                continue
            arc = str(path.relative_to(STAGE)).replace("\\", "/")
            method = zipfile.ZIP_STORED if path.suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
            zf.write(path, arc, compress_type=method, compresslevel=None if method == zipfile.ZIP_STORED else 6)
    print(f"压缩包：{ZIP_PATH}（{ZIP_PATH.stat().st_size / 1024 ** 3:.2f} GB）")
    print(f"压缩包 sha256：{sha256(ZIP_PATH)}")


if __name__ == "__main__":
    main()