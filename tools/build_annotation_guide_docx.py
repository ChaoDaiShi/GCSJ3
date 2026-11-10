"""把 docs/09c 人工标注手册转成 Word，便于发给组员。

    <dependencies-python> tools\\build_annotation_guide_docx.py
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "docs" / "09c-manual-annotation-summer-2026-11.md"
OUT = REPO / "reports" / "新都区地类样本人工标注操作手册.docx"

BODY_FONT = "微软雅黑"
CODE_FONT = "Consolas"


def set_font(run, name: str = BODY_FONT, size: float | None = None, bold: bool = False,
             color: str | None = None) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size:
        run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def add_rich(par, text: str, size: float = 10.5) -> None:
    """处理 **粗体** 与 `代码`。"""
    for token in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            set_font(par.add_run(token[2:-2]), size=size, bold=True)
        elif token.startswith("`") and token.endswith("`"):
            set_font(par.add_run(token[1:-1]), name=CODE_FONT, size=size - 0.5,
                     color="B03A2E")
        else:
            set_font(par.add_run(token), size=size)


def parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            rows.append(cells)
        i += 1
    return rows, i


def build() -> None:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

    for section in doc.sections:
        section.left_margin = section.right_margin = Pt(56)

    lines = SRC.read_text(encoding="utf-8").splitlines()
    i = 0
    in_code = False
    code_buf: list[str] = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Pt(12)
                p.paragraph_format.space_after = Pt(6)
                for k, cl in enumerate(code_buf):
                    if k:
                        p.add_run().add_break()
                    set_font(p.add_run(cl), name=CODE_FONT, size=9, color="1F3A93")
                code_buf, in_code = [], False
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        if stripped.startswith("|"):
            rows, i = parse_table(lines, i)
            if rows:
                cols = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=cols)
                table.style = "Table Grid"
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                for ri, row in enumerate(rows):
                    for ci in range(cols):
                        cell = table.cell(ri, ci)
                        cell.paragraphs[0].text = ""
                        txt = row[ci] if ci < len(row) else ""
                        add_rich(cell.paragraphs[0], txt, size=9)
                        if ri == 0:
                            for run in cell.paragraphs[0].runs:
                                run.bold = True
                doc.add_paragraph()
            continue

        if stripped == "---":
            i += 1
            continue

        level = len(stripped) - len(stripped.lstrip("#"))
        if level and stripped[level] == " ":
            text = stripped[level + 1:]
            if level == 1:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                set_font(p.add_run(text), size=18, bold=True, color="1F3864")
                p.paragraph_format.space_after = Pt(14)
            else:
                h = doc.add_heading(level=min(level - 1, 4))
                h.text = ""
                set_font(h.add_run(text), size=15 if level == 2 else 12.5, bold=True,
                         color="1F3864" if level == 2 else "2E74B5")
            i += 1
            continue

        m = re.match(r"^(\s*)[-*] (.*)$", line)
        if m:
            indent = len(m.group(1)) // 2
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.left_indent = Pt(18 + indent * 14)
            p.paragraph_format.space_after = Pt(3)
            add_rich(p, m.group(2))
            i += 1
            continue

        m = re.match(r"^(\s*)(\d+)\. (.*)$", line)
        if m:
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.left_indent = Pt(18)
            p.paragraph_format.space_after = Pt(3)
            add_rich(p, m.group(3))
            i += 1
            continue

        if stripped.startswith(">"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(16)
            add_rich(p, stripped.lstrip("> ").strip(), size=9.5)
            for run in p.runs:
                run.italic = True
                run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            i += 1
            continue

        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(5)
        p.paragraph_format.line_spacing = 1.25
        add_rich(p, stripped)
        i += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"已生成 {OUT}（{OUT.stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    build()