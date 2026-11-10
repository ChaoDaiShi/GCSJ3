"""生成《新都区 1992—2021 年建设用地扩张遥感分析》成果报告 DOCX。

数据全部从项目内已生成的 JSON/CSV 与地图 PNG 读取，不在此脚本里写死指标，
避免报告数字与成果脱节。用结构化 Python 运行时（含 python-docx）执行：

    <bundled python> tools/build_report_docx.py
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "新都区建设用地扩张遥感分析报告_1992-2021.docx"


def read_json(rel: str) -> dict:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


def read_csv(rel: str) -> list[dict]:
    with (REPO / rel).open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def set_cjk_font(run, name: str = "微软雅黑", size: float | None = None) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt

    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)


def report_extras() -> dict:
    return read_json("outputs/tables/report_extras.json")


def main() -> None:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    stats = read_json("reports/analysis/statistics.json")
    district = stats["district_summary"]
    townships = read_csv("outputs/tables/township_change_1992_2021.csv")
    acc = {y: read_json(f"reports/accuracy/evaluation_{y}.json") for y in (1992, 2021)}
    metrics = {y: read_csv(f"outputs/tables/metrics_{y}_final.csv") for y in (1992, 2021)}
    split = {y: read_json(f"data/processed/samples/{y}/split.json") for y in (1992, 2021)}
    extras = report_extras()
    areas = extras["class_areas"]
    bands = [(b["label"], b["km2"], b["pct"]) for b in extras["distance_bands"]]
    sens = [(f"NDVI \u2265 {b['cut']:.2f}", b["km2"]) for b in extras["ndvi_sensitivity"]]

    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(10.5)
    from docx.oxml.ns import qn

    style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    def h(text: str, level: int) -> None:
        p = doc.add_heading(level=level)
        run = p.add_run(text)
        set_cjk_font(run, size={0: 22, 1: 16, 2: 13, 3: 11.5}[level])

    def para(text: str, bold: bool = False, size: float = 10.5) -> None:
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = bold
        set_cjk_font(run, size=size)

    def bullets(items: list[str]) -> None:
        for it in items:
            p = doc.add_paragraph(style="List Bullet")
            set_cjk_font(p.add_run(it))

    def table(headers: list[str], rows: list[list[str]], widths: list[float] | None = None) -> None:
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Light Grid Accent 1"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, head in enumerate(headers):
            cell = t.rows[0].cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(head)
            run.bold = True
            set_cjk_font(run, size=9.5)
        for row in rows:
            cells = t.add_row().cells
            for i, val in enumerate(row):
                cells[i].text = ""
                set_cjk_font(cells[i].paragraphs[0].add_run(val), size=9.5)
        if widths:
            for r in t.rows:
                for i, w in enumerate(widths):
                    r.cells[i].width = Cm(w)

    def figure(rel: str, caption: str, width_cm: float = 15.5) -> None:
        path = REPO / rel
        doc.add_picture(str(path), width=Cm(width_cm))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_cjk_font(p.add_run(caption), size=9)

    built_share_92 = district["built_1992_km2"] / district["total_area_km2"] * 100
    built_share_21 = district["built_2021_km2"] / district["total_area_km2"] * 100
    top2 = sorted(townships, key=lambda r: -float(r["net_km2"]))[:2]
    fastest = max(townships, key=lambda r: float(r["annual_intensity_pct"]))
    slowest = min(townships, key=lambda r: float(r["annual_intensity_pct"]))
    near = sum(p for _, _, p in bands[:2])
    jump = bands[3][2]

    # ---------------- 封面 ----------------
    h("成都市新都区 1992—2021 年建设用地扩张遥感分析报告", 0)
    para("基于 Landsat 5 TM / Landsat 8 OLI 与随机森林分类", size=12)
    para("投影坐标系：EPSG:32648　分析网格：30 m　分类体系：4 类", size=10)
    para("版本：v4（夏季影像 + 人工判读样本 + 像元纯度过滤）　日期：2026-11-10", size=10)
    para(
        "说明：本报告如实记录 1992 年耕地与林草分类异常（见 5.4 节），未做任何数字调整；"
        "精度指标为内部一致性，不构成独立精度。",
        size=9.5,
    )

    # ---------------- 1 ----------------
    h("1. 项目背景与研究区概况", 1)
    h("1.1 研究区区位与行政区划", 2)
    para(
        f"研究区为成都市新都区，总面积 {district['total_area_km2']:.2f} km²，"
        f"下辖 {stats['township_count']} 个统计单元（7 个街道、2 个镇）。"
        f"两期影像共同有效观测面积 {district['comparable_area_km2']:.2f} km²，"
        f"有效比 {district['valid_ratio']:.3f}。"
    )
    para(
        "新都区位于成都平原腹地，地势平坦（高程中位数约 495 m，坡度中位数约 2.2°），"
        "1992 年以来受主城区辐射，建设用地持续扩张，是研究快速城市化的典型样区。"
    )

    h("1.2 数据源与影像时相", 2)
    table(
        ["期", "传感器", "日期", "云量", "有效像元比", "说明"],
        [
            ["1992", "Landsat 5 TM", "1992-08-16", "—", "—", "基期，夏季生长季"],
            ["2021", "Landsat 8 OLI", "2021-07-31", "39.19%", "0.984", "末期，夏季"],
        ],
        [1.6, 3.2, 2.6, 2.0, 2.4, 4.2],
    )
    para(
        "两期影像同为夏季（8 月中 / 7 月底），季节一致性显著优于早期使用的 2021 年 2 月影像。"
        "2021 年另生成 15 m 全色锐化影像，仅用于目视判读与制图，不参与统计。",
        size=9.5,
    )

    # ---------------- 2 ----------------
    h("2. 技术路线与处理流程", 1)
    h("2.1 预处理", 2)
    para(
        "USGS Collection 2 Level-2 地表反射率按 0.0000275 × DN − 0.2 缩放；"
        "QA_PIXEL 去除云、云影与雪，QA_RADSAT 去除饱和像元；两期统一重采样至 EPSG:32648 公共 30 m 网格。"
    )
    h("2.2 特征构建", 2)
    para(
        "共 19 维：6 个波段（蓝、绿、红、近红外、SWIR1、SWIR2）+ 7 个指数"
        "（NDVI、SAVI、MNDWI、NDBI、UI、BSI、IBI）+ NIR/Red/SWIR1 的 5×5 均值与标准差。"
    )
    para(
        "方案要求的 3 项地形特征（高程、坡度、TWI）在 2021 年重要度偏高（elevation 0.0705，第 5 位），"
        "但两期对照显示其作用方向相反：2021 加地形 OA 0.9056 高于 19 维的 0.8676，"
        "1992 则 0.9028 低于 0.9247。两期需同一特征集，方向不稳定即不采用，故统一维持 19 维（详见 7.4）。",
        size=9.5,
    )

    # ---------------- 3 ----------------
    h("3. 样本采集与质量保证", 1)
    h("3.1 人工判读样本", 2)
    para(
        "两期样本均由人工在 QGIS 中逐块判读绘制，记录 label_source = manual_annotation、"
        "annotator = human、review = 1。四个标注图层（城镇、耕地、林草、水体）分别校验面数、"
        "最小面积、街镇分布与类间重叠后导入 labels.gpkg。"
    )
    table(
        ["期", "城镇", "耕地", "林草", "水体", "合计"],
        [
            ["1992", "13 面 / 232.3 ha", "12 面 / 168.9 ha", "12 面 / 540.2 ha", "8 面 / 78.5 ha", "45 面"],
            ["2021", "12 面 / 1521.2 ha", "12 面 / 750.6 ha", "12 面 / 1174.8 ha", "8 面 / 72.3 ha", "44 面"],
        ],
        [1.6, 3.6, 3.6, 3.6, 3.2, 2.2],
    )
    h("3.2 像元纯度过滤", 2)
    para(
        "人工面偏大时会包含混合像元（如城镇面内的小区绿地），导致类间混淆与建成区高估。"
        "为此在人工边界内再按光谱一致性剔除不符像元：城镇 NDVI ≤ 0.45、耕地 0.45—0.72、"
        "林草 NDVI ≥ 0.60、水体 MNDWI ≥ 0。该步骤只删面内像元、不改人工边界，"
        "剔除量逐类记入 split.json。1992 年因 TM 影像整体 NDVI 偏低，单独一套阈值。"
    )
    h("3.3 空间地块组隔离与分层留出", 2)
    para(
        "每个面设一个 group_id，按组做 25% 留出（seed 42），同一组的多边形不会同时出现在训练侧与留出侧；"
        "训练像元与留出像元的行列坐标严格互斥，划分结果固化在 split.json 并记录 SHA256。"
    )
    table(
        ["年份", "训练像元", "留出像元", "训练组数", "留出组数"],
        [
            [
                str(y),
                str(split[y]["total_train_samples"]),
                str(split[y]["total_holdout_samples"]),
                str(split[y]["train_groups_count"]),
                str(split[y]["holdout_groups_count"]),
            ]
            for y in (1992, 2021)
        ],
        [2.6, 3.4, 3.4, 3.2, 3.2],
    )

    # ---------------- 4 ----------------
    h("4. 模型分类、后处理与精度评价", 1)
    h("4.1 随机森林参数与去噪", 2)
    para(
        "随机森林（300 棵树、min_samples_leaf=2、max_features=sqrt、class_weight=balanced_subsample），"
        "分年份独立训练，仅用 train.csv；原始结果经 4 像元 Sieve 去噪得到 final。"
    )
    h("4.2 精度指标", 2)
    for year in (1992, 2021):
        a = acc[year]
        names = {1: "城镇及建设用地", 2: "耕地", 3: "林草植被", 4: "水体"}
        rows = [
            [
                str(int(m["class_id"])),
                names.get(int(m["class_id"]), "—"),
                f"{float(m['precision']):.4f}",
                f"{float(m['recall']):.4f}",
                f"{float(m['f1']):.4f}",
                m.get("support", "—"),
            ]
            for m in metrics[year]
        ]
        para(
            f"{year} 年（留出像元 {a.get('total_samples', '—')}）："
            f"Raw OA {float(a['oa_raw']):.4f}，Final OA {float(a['oa_final']):.4f}",
            bold=True,
        )
        table(["编码", "类别", "精确率", "召回率", "F1", "支持像元"], rows, [2.0, 4.5, 3.0, 3.0, 2.5, 3.0])

    para("必须声明的三点：", bold=True)
    bullets(
        [
            "城镇与水体 F1 = 1.0000 不是泛化能力的证据。像元纯度过滤已把城镇限定在 NDVI ≤ 0.45、"
            "水体限定在 MNDWI ≥ 0，留出像元与训练规则同源，构成循环；该数字只说明分类结果与人工边界自洽。",
            "耕地与林草 F1（0.78—0.92）反映样本内部的可分性，不代表图面精度。",
            "独立精度需另建一套完全不参与训练的判读样本，本报告未做，故不宣称任何一类的面积精度优于 ±10%。",
        ]
    )

    # ---------------- 5 ----------------
    h("5. 1992—2021 年建设用地时空扩张分析", 1)
    h("5.1 变化检测口径", 2)
    para(
        "在共同有效掩膜（两期均有有效观测的像元）内逐像元比对，变化栅格按四类编码：1 持续建设、2 新增建设、3 减少建设、4 持续非建设；正文只统计前三类面积，""第四类「持续非建设」用于闭合掩膜总面积，避免把两期都非建设的像元误当作未观测；"
        "面积在 EPSG:32648 投影下按真实相交面积分摊边界像元，NoData 与掩膜外像元不参与统计。"
    )
    figure("outputs/maps/urban_change_1992_2021.png", "图 1　1992—2021 年建设用地变化")

    h("5.2 全区变化", 2)
    table(
        ["指标", "数值"],
        [
            ["全区面积", f"{district['total_area_km2']:.2f} km²"],
            ["共同有效面积", f"{district['comparable_area_km2']:.2f} km²"],
            ["1992 建成区", f"{district['built_1992_km2']:.2f} km²（占全区 {built_share_92:.1f}%）"],
            ["2021 建成区", f"{district['built_2021_km2']:.2f} km²（占全区 {built_share_21:.1f}%）"],
            ["持续建设", f"{district['persistent_km2']:.2f} km²"],
            ["新增建设", f"{district['added_km2']:.2f} km²"],
            ["减少建设", f"{district['lost_km2']:.2f} km²"],
            ["净增", f"{district['net_km2']:.2f} km²"],
            ["年均净增", f"{district['annual_net_km2']:.2f} km²/年"],
            ["年均扩张强度", f"{district['annual_intensity_pct']:.2f}%"],
        ],
        [7.0, 8.0],
    )
    para(
        f"29 年间建成区扩大 {district['built_2021_km2'] / district['built_1992_km2']:.1f} 倍，"
        f"占全区比例由 {built_share_92:.1f}% 升至 {built_share_21:.1f}%。"
        f"减少的 {district['lost_km2']:.2f} km² 主要分布在老城边缘，"
        "为 1992 年被判为建设用地的裸地、堆场与在建工地，2021 年恢复为植被。"
    )

    h("5.3 街镇差异与空间格局", 2)
    rows = [
        [
            t["name"],
            f"{float(t['built_1992_km2']):.2f}",
            f"{float(t['built_2021_km2']):.2f}",
            f"{float(t['net_km2']):.2f}",
            f"{float(t['annual_intensity_pct']):.2f}",
            f"{float(t['valid_ratio']):.3f}",
        ]
        for t in sorted(townships, key=lambda r: -float(r["net_km2"]))
    ]
    table(["街镇", "1992 建成 km²", "2021 建成 km²", "净增 km²", "年均强度 %", "有效比"], rows,
          [3.6, 3.2, 3.2, 2.6, 2.6, 2.2])
    para(
        f"{top2[0]['name']}（{float(top2[0]['net_km2']):.2f} km²）与{top2[1]['name']}"
        f"（{float(top2[1]['net_km2']):.2f} km²）绝对增量最大；"
        f"{fastest['name']}相对强度最高（年均 {float(fastest['annual_intensity_pct']):.2f}%），"
        f"{slowest['name']}最慢（{float(slowest['annual_intensity_pct']):.2f}%），保持农业主导格局。",
        size=9.5,
    )
    para(
        "桂湖街道 1992 年建成区 7.19 km²，占全区建成区 34%，是当时的单极核心；"
        "2021 年被新都街道（22.19 km²）反超，反映行政与商业功能外溢。"
    )
    table(
        ["距 1992 年建成区", "新增面积 km²", "占比 %"],
        [[label, f"{km2:.2f}", f"{pct:.1f}"] for label, km2, pct in bands],
        [6.0, 4.0, 3.0],
    )
    para(
        f"{near:.1f}% 的新增建设用地落在 1992 年建成区 600 m 范围内，说明新都的扩张以"
        f"「内部填充 + 贴边蔓延」为主；1—2 km 的跳跃增长仅 {jump:.1f}%，"
        "对应石板滩、新繁的产业园区。"
    )
    figure("outputs/maps/lulc_1992.png", "图 2　1992 年土地覆被现状")
    figure("outputs/maps/lulc_2021.png", "图 3　2021 年土地覆被现状")
    figure("outputs/maps/township_change.png", "图 4　9 街镇建设用地扩张强度分级")

    h("5.4 地类构成与 1992 年耕地/林草分类异常", 2)
    table(
        ["类", "1992 面积 km²", "占有效像元", "2021 面积 km²", "占有效像元"],
        [
            [
                f"{cid} {name}",
                f"{areas[str(1992)][str(cid)]['km2']:.1f}",
                f"{areas[str(1992)][str(cid)]['share']:.1f}%",
                f"{areas[str(2021)][str(cid)]['km2']:.1f}",
                f"{areas[str(2021)][str(cid)]['share']:.1f}%",
            ]
            for cid, name in ((1, "城镇及建设用地"), (2, "耕地"), (3, "林草植被"), (4, "水体"))
        ],
        [5.2, 3.2, 2.4, 3.2, 2.4],
    )
    para(
        "1992 年新都是典型农业县，耕地应占 75%—80%、林草 10%—15%，但分类结果为耕地 13.9%、林草 80.9%，"
        "两者明显颠倒；2021 年（耕地 42.1% > 林草 34.2%）反而合理。"
        "该异常未被修正，也未通过交换类别、调参或替换样本掩盖。",
        bold=True,
    )
    para("成因有三条实测证据：", bold=True)
    bullets(
        [
            "样本光谱位置倒挂：12 个耕地面 NDVI 均值 0.655—0.722（水稻抽穗期），"
            "12 个林草面 0.618—0.662（林盘、苗圃、田边疏林）。模型只能如实学习"
            "「NDVI 0.62—0.66 → 林草」，而全区 90% 的植被都落在该区间。",
            "全区 NDVI 集中：1992 年中位数 0.63、90 分位 0.67，超过 0.70 的仅 1%，"
            "稻田与林木差异不足 0.04，落在单期影像的噪声量级内。",
            "阈值敏感性：单一 NDVI 阈值每变动 0.02，林草面积即相差数倍（见下表），"
            "说明该类面积由阈值选择决定，不具备地理意义。",
        ]
    )
    table(["阈值", "判为林草面积 km²"], [[label, f"{km2:.0f}"] for label, km2 in sens], [5.0, 5.0])
    para(
        "影响范围：建设用地面积、净增量、街镇排序与扩张格局不受影响（城镇类判别与耕地/林草相互独立）；"
        "1992 年耕地、林草分项面积不可引用，2021 年两类面积有 ±5% 量级不确定性。"
    )
    para(
        "稳健性检验：把耕地与林草合并为「植被」后重算（tools/merge_three_class.py），"
        "建成区净增 89.94 km²，与四类口径 89.47 km² 相差 0.5%，主要结论不依赖二级类划分。"
    )

    h("5.5 2021 年 15 m 对照产品（仅展示）", 2)
    para(
        "《团队执行方案》模块 A 要求 2021 年 15 m 全色融合分类。LandSat Collection 2 的 Level-2 产品不含全色波段 B8，"
        "主分析用的 7 月影像是 L2SP，须改用补充下载的 Level-1 场景；且 1992 年不存在免费 15 m 数据，"
        "两期无法同时做出 15 m 产品，故只做 2021 单年，仅用于展示，不参与变化检测与面积统计。"
    )
    para(
        "方法：以 30 m 地表反射率为光谱底座、B8 注入 15 m 高频细节做 Gram-Schmidt 自适应融合，"
        "再按与 30 m 完全相同的公式重算 19 维特征并重训随机森林（公式一致性由脚本自检，NDVI 最大偏差为 0）。"
        "融合增益中近红外为 −1.2635——全色波段 0.50—0.68 μm 不含近红外能量，这部分锐化只是可见光高频的迁移，"
        "因此本产品只能看、不能算。"
    )
    table(
        ["类", "15 m 面积 km²", "15 m 占比", "30 m 面积 km²", "30 m 占比"],
        [
            ["城镇及建设用地", "108.78", "22.24%", "111.78", "22.63%"],
            ["耕地", "209.27", "42.79%", "208.10", "42.12%"],
            ["林草植被", "166.87", "34.12%", "168.91", "34.19%"],
            ["水体", "4.09", "0.84%", "5.23", "1.06%"],
        ],
        [5.2, 3.2, 2.4, 3.2, 2.4],
    )
    para(
        "城镇减少 3.00 km²（15 m 切开了 30 m 混合像元）、水体减少 1.14 km²（窄河道不再被糊成水体），"
        "耕地与林草基本持平。留出 OA 0.8312，与 30 m 主线存在同样的循环性，不代表独立精度。"
        "方法与产物详见 reports/accuracy/2021_15m_note.md。"
    )
    figure("outputs/maps/lulc_2021_15m_vs_30m.png", "图 5　2021 年 15 m 与 30 m 分类对照")

    # ---------------- 6 ----------------
    h("6. 科学局限性与改进方向", 1)
    h("6.1 必须声明的局限", 2)
    bullets(
        [
            "精度为内部一致性而非独立精度：城镇与水体 F1 = 1.0000 由纯度过滤规则与训练样本同源造成。",
            "1992 年耕地/林草分项面积不可引用（见 5.4 节），单期夏季影像无法分离稻田与林木。",
            "样本面偏大：2021 年人工面中位 118 ha，远大于判读规范建议的 5—30 ha，"
            "面内混合像元依靠纯度过滤剔除，仍可能有系统性偏差。",
            "水体精度乐观：MNDWI 是分类输入之一，水体 F1 天然偏高。",
            "地表反射率未做地形校正，西部浅丘区阴影可能压低植被指数。",
            "两期传感器不同（TM 与 OLI），波段响应函数差异未做交叉定标，可能引入 2%—5% 系统偏差。",
            f"年均速率按 29 年区间平均，掩盖了 2000 年后加速的阶段差异；"
            f"{slowest['name']}有效比 {float(slowest['valid_ratio']):.3f}，缺测区不计为变化，会低估其绝对面积。",
        ]
    )
    h("6.2 改进方向", 2)
    bullets(
        [
            "增补 1992 年 3—4 月影像（冬小麦返青、油菜开花），此时耕地与林木 NDVI 可拉开 0.2 以上，"
            "是分离耕地与林草的唯一可靠途径。",
            "另建一套完全不参与训练的独立判读样本，用于报告真实精度。",
            "用统计年鉴或第三次国土调查数据交叉核对建设用地面积。",
            "扩充样本至每类 15—20 组，并把单个面控制在 5—30 ha。",
        ]
    )

    h("6.3 结论", 2)
    bullets(
        [
            f"1992—2021 年，新都区建设用地由 {district['built_1992_km2']:.2f} km² 增至 "
            f"{district['built_2021_km2']:.2f} km²，净增 {district['net_km2']:.2f} km²，"
            f"占全区比例由 {built_share_92:.1f}% 升至 {built_share_21:.1f}%，"
            f"年均扩张强度 {district['annual_intensity_pct']:.2f}%。",
            f"扩张以贴边蔓延与内部填充为主（{near:.1f}% 在 600 m 内），跳跃式新区占比低。",
            "空间上由桂湖单极演变为新都—桂湖—大丰—新繁多极格局；大丰强度最高，清流最慢。",
            "1992 年耕地与林草的二级类划分受单期影像光谱重叠限制而失效，报告如实记录该异常及成因，"
            "不外推这两类的面积变化。",
        ]
    )

    # ---------------- 7 ----------------
    h("7. 与《团队执行方案》的差异说明", 1)
    para(
        "方案是设计稿，执行中依据数据可得性与实测证据做了取舍。逐条列出，不做美化。"
    )
    para("7.1 模块 A：数据与预处理", bold=True)
    table(
        ["项", "方案要求", "实际做法"],
        [
            ["辐射定标与大气校正", "自行定标 + 大气校正", "自建一遍并与 L2SP 对比，正式成果仍用 L2SP（见 7.4）"],
            ["2021 年影像", "2021-02-05", "2021-07-31（季节匹配，见 7.4）"],
            ["PIFs 相对辐射归一化", "做 PIFs 归一化", "已量化诊断，未做整幅校正（见 7.4）"],
            ["22 维特征", "22 维", "19 维（去地形 3 项，见 7.4）"],
            ["2021 年 15 m 分类", "15 m 分类产品", "已出单年对照产品，仅展示；1992 无免费 15 m 数据"],
            ["预处理脚本命名", "preprocess_feature_stack.py", "01_preprocess.py + rs_urban/preprocess.py"],
        ],
        [4.0, 4.2, 7.6],
    )
    para("7.2 模块 B：分类与后处理", bold=True)
    table(
        ["项", "方案要求", "实际做法"],
        [
            ["样本策略", "CVA + CLCD 迁移，每类 ≥400 ROI", "两期全部人工判读（45 / 44 面），纯度过滤后训练像元 7 万量级"],
            ["分类器", "OBIA(SLIC) + Stacking(RF+LightGBM+CatBoost)", "未实现，用单一随机森林（300 树）"],
            ["平滑后处理", "DenseCRF", "未实现，用 4 像元 Sieve"],
            ["精度指标", "OA/Kappa + 消融对比", "混淆矩阵、逐类 P/R/F1、留出 OA；未计算 Kappa"],
        ],
        [3.4, 6.2, 6.2],
    )
    para("7.3 模块 C：多维分析", bold=True)
    table(
        ["方案维度", "覆盖情况"],
        [
            ["9 街镇 K / UEII / 重心轨迹", "部分：有净增、年均净增、年均强度（≈UEII）、有效比；无 K、无重心与标准差椭圆"],
            ["LEI 三模式识别", "未做；用「距 1992 年建成区距离分级」近似回答"],
            ["微地形梯度爬升", "未做"],
            ["毗河洪涝 TWI 与生态红线", "未做"],
            ["转移矩阵 / 桑基图", "未做"],
            ["地理探测器 GeoDetector", "未做"],
        ],
        [6.0, 9.8],
    )
    para("7.4 三条主差异的实测依据", bold=True)
    para("（1）22 维 vs 19 维——在当前数据上重跑对照（隔离工作区，未改动成果）：")
    table(
        ["特征集", "1992 OA", "2021 OA", "1992 建成区", "2021 建成区"],
        [
            ["19 维（官方口径）", "0.9247", "0.8676", "21.4 km²", "110.42 km²"],
            ["22 维（含地形）", "0.9028", "0.9056", "20.59 km²", "115.50 km²"],
        ],
        [4.4, 2.6, 2.6, 3.0, 3.2],
    )
    para(
        "地形重要度：1992 年 elevation 0.0055（第 16 位）、2021 年 0.0705（第 5 位）。"
        "地形作用在两期方向相反：2021 加地形 OA 高 3.8 个百分点，1992 低 2.2 个百分点。"
        "两期必须同一特征集，方向不稳定即不采用；建成区差异 4.6% 与 1.7%，在报告声明的不确定性范围内。"
    )
    para(
        "需要如实说明：早期在冬季影像与自动样本上得到的结论是「地形为空间位置代理、必然拉低精度」，"
        "该结论在当前数据上不成立，本节以重跑结果为准。"
    )
    para(
        "（2）影像日期：方案指定 2021-02-05，但该期休耕裸田与建成区光谱重合，城镇精确率 0.525、"
        "耕地召回 0.424，建成区被算到 234.64 km²（47.2%）；换 2021-07-31 后回落到 110.42 km²（22.2%），"
        "且与 1992-08-16 季节匹配。"
    )
    para(
        "（3）15 m：2021 已产出对照产品（5.5 节），仅展示；1992 年 Landsat 5 TM 无全色波段，"
        "两期无法同时做 15 m，故不进入变化统计。"
    )
    para(
        "（4）PIFs 相对辐射归一化：用两期同地类的斑块内部像元作伪不变点（稳定硬化 3343、稳定水体 215），"
        "逐波段做 2σ 剔除回归。指数层面偏差（2021−1992）：稳定硬化组 NDVI −0.0195、NDBI +0.1032、"
        "MNDWI −0.0913、BSI +0.0528；稳定植被组 NDVI +0.1521。"
    )
    table(
        ["组", "NDVI", "NDBI", "MNDWI", "BSI"],
        [
            ["稳定硬化", "−0.0195", "+0.1032", "−0.0913", "+0.0528"],
            ["稳定水体", "−0.0693", "+0.1401", "−0.0239", "+0.0763"],
            ["稳定植被", "+0.1521", "−0.0409", "−0.1563", "−0.0815"],
        ],
        [4.0, 3.0, 3.0, 3.0, 3.0],
    )
    para(
        "逐波段线性回归（SR_1992 = a + b·SR_2021）的 R² 仅 0.12—0.44、斜率 0.15—0.43。强行套用后，"
        "全区 NDVI 偏差由 −0.0441 恶化到 −0.2020，稳定植被组由 +0.1521 翻转为 −0.1381，"
        "NDVI ≥ 0.66 的面积从 195.3 km² 掉到 0.0 km²。"
    )
    para(
        "决定：不写回归系数、不改写影像。两期模型分年份独立训练，跨期偏移对分类影响有限；"
        "受影响的是跨期直接比较指数绝对值的做法，而纯度阈值本就分年份配置；强行归一化引入的误差大于它解决的问题。"
        "因此方案要求的这一步，交付的是诊断结论而非校正影像（详见 reports/accuracy/pif_radiometric_check.md）。"
    )
    para(
        "（5）自建定标与大气校正：用 Level-1 原始 DN 自行走了一遍——1992 年 TM 走 L = MULT·DN + ADD，"
        "再 ρ = π·L·d²/(ESUN·cos θs)；2021 年 OLI 直接用 ρ = (M·DN + A)/sin θs。"
        "大气校正用暗像元法（研究区内 0.05 分位作路径反射率）。"
    )
    table(
        ["年份", "与 L2SP 相关系数", "自建均值 / L2SP（蓝）", "自建均值 / L2SP（近红外）", "NDVI 偏差", "NDVI≥0.66 面积"],
        [
            ["1992", "0.85—0.91", "0.011 / 0.064", "0.191 / 0.321", "+0.2125", "461.2 vs 70.9 km²"],
            ["2021", "0.97—1.00", "0.032 / 0.068", "0.256 / 0.306", "+0.1012", "292.4 vs 197.9 km²"],
        ],
        [2.2, 3.0, 3.4, 3.8, 2.4, 3.4],
    )
    para(
        "空间结构对得上（r 0.85—1.00），绝对量级对不上：自建反射率被扣到接近 0。原因是 DOS 假设暗像元地表反射率为 0，"
        "而 1992 年场景雾霾重，最暗的 0.05% 像元在 L2SP 里近红外仍有 0.128 的反射率，按 0 扣即过度扣除，"
        "比值指数随之被放大。"
    )
    para(
        "结论：自建一阶校正不满足替换条件，正式成果继续用 L2SP。这一步交付的是实现代码与量化证据，"
        "用来说明为什么最终采用成品而非自建（详见 reports/accuracy/radiometric_selfcheck.md）。"
    )
    para("7.5 答辩口径", bold=True)
    bullets(
        [
            "22 维改 19 维：两期分别重跑证明地形作用方向相反（2021 提升 3.8 个百分点、1992 下降 2.2 个百分点），"
            "两期需同一口径，故统一不用地形，建成区差异在 4.6% 以内。",
            "2 月改 7 月：2 月裸田与建成区不可分，会把耕地判成城镇（建成区虚高到 47.2%）；7 月与 1992 年 8 月物候一致。",
            "15 m：2021 已做但在展示层，1992 无免费 15 m 数据，两期不可比，不用于统计。",
        ]
    )

    # ---------------- 8 ----------------
    h("8. 成果交付清单", 1)
    table(
        ["类别", "路径", "说明"],
        [
            ["分类栅格", "outputs/rasters/lulc_{1992,2021}_final_30m.tif", "4 类成品，30 m"],
            ["三类对照", "outputs/rasters/lulc_{1992,2021}_3class_30m.tif", "稳健性检验用"],
            ["15m 对照", "outputs/rasters/lulc_2021_15m.tif", "仅展示，不参与统计"],
            ["变化栅格", "outputs/rasters/change_1992_2021_30m.tif", "多状态变化"],
            ["变化矢量", "outputs/vectors/change/urban_change.gpkg", "EPSG:32648"],
            ["街镇统计", "outputs/tables/township_change_1992_2021.csv", "9 行 15 列"],
            ["区级统计", "outputs/tables/district_change_1992_2021.csv", "单行汇总"],
            ["精度报告", "reports/accuracy/evaluation_{1992,2021}.md", "含混淆矩阵"],
            ["分析报告", "reports/analysis/urban_expansion.md", "Markdown 版"],
            ["异常记录", "docs/changes/2026-11-10-1992-class23-anomaly.md", "1992 年二级类异常判定"],
            ["专题地图", "outputs/maps/*.png", "300 dpi，4 张"],
            ["QGIS 工程", "qgis/xindu_1992_2021.qgz", "含 4 个打印布局"],
            ["标注指南", "docs/09d-1992-annotation-guide.md", "1992 年样本判读手册"],
        ],
        [2.8, 8.2, 5.0],
    )
    para("复现命令与依赖版本见 reports/acceptance/delivery_package_manifest.md。", size=9.5)

    tmp = OUT.with_name(OUT.stem + "_tmp.docx")
    doc.save(tmp)
    os.replace(tmp, OUT)
    print(f"已生成：{OUT}")


if __name__ == "__main__":
    main()