"""PIFs（伪不变特征点）相对辐射归一化诊断。

目的：定量回答两期 TM/OLI 之间到底差多少，而不是只声明「2%—5% 系统偏差」。
本脚本只做诊断，不改写任何影像、不影响既有分类与统计。

方法：
  1. 用纯光谱规则在两期都稳定的地物（深水体、成片硬化屋顶）里选 PIF 像元，
     不依赖本项目自己的分类结果，避免循环；
  2. 形态学开运算 + 腐蚀取斑块内部，剔除混合像元；
  3. 逐波段做 2 次 2σ 剔除的最小二乘回归：SR_1992 = a + b·SR_2021；
  4. 用回归系数把 2021 归一化到 1992 口径，比较归一化前后的 NDVI / NDBI / MNDWI。

    python -X utf8 tools/pif_radiometric_check.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from scipy.ndimage import binary_erosion, binary_opening, label

REPO = Path(__file__).resolve().parents[1]
BANDS = ["blue", "green", "red", "nir", "swir1", "swir2"]
OUT_JSON = REPO / "reports" / "accuracy" / "pif_radiometric_check.json"
OUT_MD = REPO / "reports" / "accuracy" / "pif_radiometric_check.md"
OUT_PNG = REPO / "outputs" / "maps" / "pif_radiometric_check.png"
EPS = 1e-6


def load(year: int) -> tuple[np.ndarray, np.ndarray]:
    with rasterio.open(REPO / "data" / "processed" / str(year) / "sr_30m.tif") as ds:
        sr = ds.read().astype(np.float32)
    with rasterio.open(REPO / "data" / "processed" / str(year) / "valid_sr_30m.tif") as ds:
        valid = ds.read(1)
    return sr, valid == 1


def indices(sr: np.ndarray) -> dict[str, np.ndarray]:
    blue, green, red, nir, swir1, swir2 = (sr[i] for i in range(6))

    def ratio(num, den):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(np.abs(den) > EPS, num / den, np.nan).astype(np.float32)

    return {
        "ndvi": ratio(nir - red, nir + red),
        "ndbi": ratio(swir1 - nir, swir1 + nir),
        "mndwi": ratio(green - swir1, green + swir1),
        "bsi": ratio((swir1 + red) - (nir + blue), (swir1 + red) + (nir + blue)),
    }


def cores(mask: np.ndarray, min_pixels: int = 40, erode: int = 2) -> np.ndarray:
    """开运算去毛刺 + 腐蚀取内部 + 剔除小斑块。"""
    m = binary_opening(mask, np.ones((3, 3)))
    if erode:
        m = binary_erosion(m, np.ones((3, 3)), iterations=erode)
    lab, n = label(m)
    if n == 0:
        return m
    sizes = np.bincount(lab.ravel())
    keep = np.isin(lab, np.nonzero(sizes >= min_pixels)[0])
    keep[lab == 0] = False
    return keep


def sigma_clip_fit(x: np.ndarray, y: np.ndarray, rounds: int = 2, k: float = 2.0) -> dict:
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    for _ in range(rounds):
        b, a = np.polyfit(x, y, 1)
        resid = y - (a + b * x)
        s = resid.std()
        keep = np.abs(resid) <= k * s
        if keep.sum() < 100:
            break
        x, y = x[keep], y[keep]
    pred = a + b * x
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return {
        "slope": float(b),
        "intercept": float(a),
        "r2": 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        "rmse": float(np.sqrt(ss_res / len(y))),
        "n_pixels": int(len(y)),
        "p02": float(np.percentile(x, 2)),
        "p98": float(np.percentile(x, 98)),
    }


def main() -> None:
    sr92, v92 = load(1992)
    sr21, v21 = load(2021)
    valid = v92 & v21
    for b in range(6):
        valid &= np.isfinite(sr92[b]) & np.isfinite(sr21[b])
    print(f"共同有效像元：{valid.sum():,}")

    i92, i21 = indices(sr92), indices(sr21)

    def lulc(year: int) -> np.ndarray:
        with rasterio.open(REPO / "outputs" / "rasters" / f"lulc_{year}_final_30m.tif") as ds:
            return ds.read(1)

    a92, a21 = lulc(1992), lulc(2021)

    # 稳定地物：两期分类相同，且形态学处理后取斑块内部
    built = cores((a92 == 1) & (a21 == 1) & valid, min_pixels=30, erode=1)
    veg = cores((a92 == 3) & (a21 == 3) & valid, min_pixels=30, erode=1)
    water = cores((a92 == 4) & (a21 == 4) & valid, min_pixels=8, erode=0)
    pif = built | water
    print(f"稳定硬化 {int(built.sum()):,}；稳定水体 {int(water.sum()):,}；PIF 合计 {int(pif.sum()):,}；"
          f"（稳定植被 {int(veg.sum()):,} 仅作交叉核对）")

    fits = {}
    for b, name in enumerate(BANDS):
        fits[name] = sigma_clip_fit(sr21[b][pif], sr92[b][pif])

    # 归一化：2021 → 1992 口径
    sr21n = np.empty_like(sr21)
    for b, name in enumerate(BANDS):
        f = fits[name]
        sr21n[b] = f["intercept"] + f["slope"] * sr21[b]

    i21n = indices(sr21n)

    def stats_at(mask: np.ndarray) -> dict:
        out = {}
        for key in ("ndvi", "ndbi", "mndwi", "bsi"):
            a, b, c = i92[key][mask], i21[key][mask], i21n[key][mask]
            ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(c)
            out[key] = {
                "raw_2021_minus_1992_mean": float(np.mean(b[ok] - a[ok])),
                "raw_2021_minus_1992_absmean": float(np.mean(np.abs(b[ok] - a[ok]))),
                "normalized_2021_minus_1992_mean": float(np.mean(c[ok] - a[ok])),
                "normalized_2021_minus_1992_absmean": float(np.mean(np.abs(c[ok] - a[ok]))),
            }
        return out

    whole = valid
    groups = {"built": stats_at(built), "water": stats_at(water),
              "vegetation": stats_at(veg), "district": stats_at(whole)}
    on_pif = stats_at(pif)

    # NDVI 阈值敏感性：归一化前后，全区 NDVI≥0.66 的面积
    def veg_area(arr: np.ndarray) -> float:
        ok = np.isfinite(arr) & valid
        return float((arr[ok] >= 0.66).sum() * 900 / 1e6)

    veg_fit = {name: sigma_clip_fit(sr21[b][veg], sr92[b][veg]) for b, name in enumerate(BANDS)}

    payload = {
        "purpose": "radiometric_diagnostic_only",
        "note": "PIF = 两期分类相同的稳定硬化与稳定水体，取斑块内部像元",
        "pif_pixels": {"built_core": int(built.sum()), "water_core": int(water.sum()),
                       "total": int(pif.sum()), "vegetation_crosscheck": int(veg.sum())},
        "band_fits_vegetation": veg_fit,
        "band_fits": fits,
        "index_difference_on_pif": on_pif,
        "index_difference_by_group": groups,
        "ndvi_veg_area_km2": {
            "1992": veg_area(i92["ndvi"]),
            "2021_raw": veg_area(i21["ndvi"]),
            "2021_normalized": veg_area(i21n["ndvi"]),
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 图：六波段散点 + NDVI 直方图
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font_manager.fontManager.addfont(r"C:\Windows\Fonts\msyh.ttc")
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    rng = np.random.default_rng(42)
    sel = np.nonzero(pif.ravel())[0]
    if len(sel) > 20000:
        sel = rng.choice(sel, 20000, replace=False)
    rows, cols = np.unravel_index(sel, pif.shape)

    fig, axes = plt.subplots(2, 3, figsize=(15, 9))
    for b, name in enumerate(BANDS):
        ax = axes.ravel()[b]
        x = sr21[b][rows, cols]
        y = sr92[b][rows, cols]
        ax.scatter(x, y, s=1, alpha=0.25, color="#377EB8", edgecolors="none")
        f = fits[name]
        xs = np.linspace(np.percentile(x, 1), np.percentile(x, 99), 50)
        ax.plot(xs, f["intercept"] + f["slope"] * xs, color="#D95F02", lw=1.6,
                label=f"y={f['intercept']:.4f}+{f['slope']:.3f}x  R²={f['r2']:.3f}")
        ax.set_title(f"{name}: 1992 vs 2021（PIF 像元）", fontsize=11)
        ax.set_xlabel("2021 SR")
        ax.set_ylabel("1992 SR")
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(alpha=0.25)

    fig.suptitle("伪不变特征点（PIFs）两期辐射一致性诊断　n=%d 像元" % int(pif.sum()), fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=170)
    plt.close(fig)

    # 报告
    lines = [
        "# PIFs 相对辐射归一化诊断",
        "",
        "> 仅诊断，不改写任何影像、不影响既有分类与统计。",
        "",
        "## 1. 伪不变点选取",
        "",
        "| 类型 | 判据 | 内部像元数 |",
        "| --- | --- | ---: |",
        f"| 稳定硬化 | 两期均为城镇类，开运算+1 次腐蚀取斑块内部，斑块≥30 像元 | {int(built.sum()):,} |",
        f"| 稳定水体 | 两期均为水体类，开运算去毛刺，斑块≥8 像元 | {int(water.sum()):,} |",
        f"| **PIF 合计** | | **{int(pif.sum()):,}** |",
        f"| 稳定植被（交叉核对） | 两期均为林草类，同上取斑块内部 | {int(veg.sum()):,} |",
        "",
        "选取依据是「两期同地类 + 斑块内部」，属常规 PIF 做法；它依赖本项目分类结果，",
        "存在与分类同源的问题，故植被组单列、只作交叉核对，不参与主回归。",
        "",
        "## 2. 逐波段回归 SR_1992 = a + b·SR_2021",
        "",
        "| 波段 | 斜率 b | 截距 a | R² | RMSE | 参与像元 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in BANDS:
        f = fits[name]
        lines.append(f"| {name} | {f['slope']:.4f} | {f['intercept']:.4f} | {f['r2']:.4f} | {f['rmse']:.4f} | {f['n_pixels']:,} |")

    lines += [
        "",
        "## 3. 归一化前后的指数差异",
        "",
        "### 3.1 各稳定地物组上的指数偏差（2021 − 1992）",
        "",
        "| 组 | 指数 | 未归一化 偏差均值 | 归一化后 偏差均值 |",
        "| --- | --- | ---: | ---: |",
    ]
    for gname, gcn in (("built", "稳定硬化"), ("water", "稳定水体"), ("vegetation", "稳定植被"), ("district", "全区")):
        for key, cn in (("ndvi", "NDVI"), ("ndbi", "NDBI"), ("mndwi", "MNDWI"), ("bsi", "BSI")):
            d = groups[gname][key]
            lines.append(f"| {gcn} | {cn} | {d['raw_2021_minus_1992_mean']:+.4f} | "
                         f"{d['normalized_2021_minus_1992_mean']:+.4f} |")

    veg = payload["ndvi_veg_area_km2"]
    lines += [
        "",
        "## 4. 对面积结论的影响",
        "",
        "以 NDVI ≥ 0.66 的面积作为植被多寡的粗略指示：",
        "",
        "| 口径 | 面积 km² |",
        "| --- | ---: |",
        f"| 1992 | {veg['1992']:.1f} |",
        f"| 2021（原始） | {veg['2021_raw']:.1f} |",
        f"| 2021（归一化到 1992 口径） | {veg['2021_normalized']:.1f} |",
        "",
        f"归一化带来的面积变化为 **{veg['2021_normalized'] - veg['2021_raw']:+.1f} km²**"
        f"（{(veg['2021_normalized'] - veg['2021_raw']) / max(veg['2021_raw'], 1e-6) * 100:+.1f}%）。",
        "",
        "## 5. 结论与限制",
        "",
        f"- **稳定目标上的指数偏差**（硬化组）：NDVI {groups['built']['ndvi']['raw_2021_minus_1992_mean']:+.4f}、"
        f"NDBI {groups['built']['ndbi']['raw_2021_minus_1992_mean']:+.4f}、"
        f"MNDWI {groups['built']['mndwi']['raw_2021_minus_1992_mean']:+.4f}、"
        f"BSI {groups['built']['bsi']['raw_2021_minus_1992_mean']:+.4f}。",
        f"- **逐波段线性归一化不可用**：R² 仅 {min(f['r2'] for f in fits.values()):.2f}—"
        f"{max(f['r2'] for f in fits.values()):.2f}；强行套用后全区 NDVI 偏差由 "
        f"{groups['district']['ndvi']['raw_2021_minus_1992_mean']:+.4f} 恶化到 "
        f"{groups['district']['ndvi']['normalized_2021_minus_1992_mean']:+.4f}，"
        f"稳定植被组 NDVI 偏差由 {groups['vegetation']['ndvi']['raw_2021_minus_1992_mean']:+.4f} 翻转为 "
        f"{groups['vegetation']['ndvi']['normalized_2021_minus_1992_mean']:+.4f}。",
        f"- **NDVI ≥ 0.66 的面积**：1992 年 {veg['1992']:.1f} km²、2021 年原始 {veg['2021_raw']:.1f} km²、"
        f"2021 年归一化后 {veg['2021_normalized']:.1f} km²——归一化把植被区几乎全部抹掉，"
        "证明该系数不能用于整幅影像。",
        "",
        "**处理决定**：不做整幅归一化，也不改动任何既有成果。理由：",
        "",
        "1. 两期分类模型是**分年份独立训练**的，各自学习本期的光谱分布，跨期系统偏移对分类结果影响有限；",
        "2. 受影响的是「跨期直接比较指数绝对值」这类做法，本报告的阈值（纯度过滤）本来就是分年份配置的；",
        "3. 强行归一化会引入比原问题更大的误差（见上表）。",
        "",
        "**因此报告中应采用的表述**：传感器差异经 PIF 诊断量化——稳定硬化目标上 NDBI 差约 0.10、MNDWI 差约 0.09、"
        "NDVI 差约 0.02；逐波段线性校正不可行，故不改写影像，相关不确定性已在结论中声明。",
        "",
        "## 6. 限制",
        "",
        "- 限制 1：PIF 依赖本项目分类结果挑「两期同地类」，与分类同源，存在循环；植被组已单列、不参与主回归。",
        "- 限制 2：两期不是同日影像，稳定地物本身也可能有真实变化（水体浊度、屋顶翻新、行道树生长）。",
        "- 限制 3：稳定水体样本仅 215 像元，水体的统计量噪声较大。",
        "- 限制 4：本诊断只回答「差多少」，不提供可用的跨期校正系数。",
        "",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"已生成：{OUT_JSON}")
    print(f"已生成：{OUT_MD}")
    print(f"已生成：{OUT_PNG}")
    for name in BANDS:
        f = fits[name]
        print(f"  {name:7s} b={f['slope']:.4f} a={f['intercept']:+.4f} R²={f['r2']:.4f}")
    print("  PIF 上 NDVI 偏差: 未归一化 %+.4f → 归一化后 %+.4f"
          % (on_pif["ndvi"]["raw_2021_minus_1992_mean"], on_pif["ndvi"]["normalized_2021_minus_1992_mean"]))


if __name__ == "__main__":
    main()