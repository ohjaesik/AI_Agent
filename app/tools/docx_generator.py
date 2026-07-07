# app/tools/docx_generator.py

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


def set_cell_text(cell, text: Any, font_size: int = 9, bold: bool = False) -> None:
    cell.text = ""

    paragraph = cell.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = paragraph.add_run("" if text is None else str(text))
    run.bold = bold
    run.font.size = Pt(font_size)
    run.font.name = "맑은 고딕"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")


def set_cell_shading(cell, fill: str = "E7E6E6") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    tc_pr.append(shading)


def set_cell_vertical_alignment(cell, align: str = "center") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    v_align = OxmlElement("w:vAlign")
    v_align.set(qn("w:val"), align)
    tc_pr.append(v_align)


def set_run_font(run, size: int = 10, bold: bool = False) -> None:
    run.font.name = "맑은 고딕"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    run.font.size = Pt(size)
    run.bold = bold


def configure_document_styles(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = "맑은 고딕"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    normal.font.size = Pt(10)

    for style_name, size, bold in [
        ("Title", 18, True),
        ("Heading 1", 14, True),
        ("Heading 2", 12, True),
        ("Heading 3", 11, True),
    ]:
        style = doc.styles[style_name]
        style.font.name = "맑은 고딕"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
        style.font.size = Pt(size)
        style.font.bold = bold


def add_paragraph_block(doc: Document, text: str, font_size: int = 10) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.line_spacing = 1.35
    paragraph.paragraph_format.space_after = Pt(6)

    run = paragraph.add_run(text)
    set_run_font(run, size=font_size)


def add_code_block(doc: Document, text: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.line_spacing = 1.1
    paragraph.paragraph_format.space_after = Pt(6)

    run = paragraph.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(40, 40, 40)


def add_table_block(
    doc: Document,
    headers: list[Any],
    rows: list[list[Any]],
    font_size: int = 8,
) -> None:
    if not headers:
        return

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = True

    header_cells = table.rows[0].cells

    for idx, header in enumerate(headers):
        set_cell_text(header_cells[idx], header, font_size=font_size, bold=True)
        set_cell_shading(header_cells[idx], "D9EAF7")
        set_cell_vertical_alignment(header_cells[idx])

    for row in rows:
        cells = table.add_row().cells

        for idx, value in enumerate(row[: len(headers)]):
            set_cell_text(cells[idx], value, font_size=font_size)
            set_cell_vertical_alignment(cells[idx])

    doc.add_paragraph()


def add_cover_page(doc: Document, report_data: dict[str, Any]) -> None:
    for _ in range(5):
        doc.add_paragraph()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    title_run = title.add_run(report_data.get("title", "AX Delivery Planner 보고서"))
    set_run_font(title_run, size=18, bold=True)

    subtitle_text = report_data.get(
        "subtitle",
        "제조기업 AX 전환 업무 프로세스 진단 및 AI Agent 도입 우선순위 추천 Agent 설계",
    )
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle_run = subtitle.add_run(subtitle_text)
    set_run_font(subtitle_run, size=12, bold=False)

    for _ in range(10):
        doc.add_paragraph()

    metadata = [
        ("작성자", report_data.get("author", "")),
        ("대상 기업", report_data.get("company_name", "")),
        ("MVP Agent", report_data.get("mvp_agent", "")),
        ("작성일", report_data.get("date", "")),
    ]
    metadata = [(key, value) for key, value in metadata if value]

    if metadata:
        table = doc.add_table(rows=len(metadata), cols=2)
        table.style = "Table Grid"

        for row_idx, (key, value) in enumerate(metadata):
            set_cell_text(table.rows[row_idx].cells[0], key, font_size=10, bold=True)
            set_cell_shading(table.rows[row_idx].cells[0], "E7E6E6")
            set_cell_text(table.rows[row_idx].cells[1], value, font_size=10)

    doc.add_page_break()


def add_table_of_contents(doc: Document, sections: list[dict[str, Any]]) -> None:
    doc.add_heading("목차", level=1)

    for section in sections:
        heading = section.get("heading", "제목 없음")
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.line_spacing = 1.3
        run = paragraph.add_run(heading)
        set_run_font(run, size=10)

    doc.add_page_break()


def add_section(doc: Document, section: dict[str, Any]) -> None:
    heading = section.get("heading", "제목 없음")
    doc.add_heading(heading, level=1)

    for block in section.get("blocks", []):
        block_type = block.get("type")

        if block_type == "paragraph":
            add_paragraph_block(doc, block.get("text", ""))

        elif block_type == "table":
            add_table_block(
                doc=doc,
                headers=block.get("headers", []),
                rows=block.get("rows", []),
                font_size=block.get("font_size", 8),
            )

        elif block_type == "code":
            add_code_block(doc, block.get("text", ""))

        elif block_type == "page_break":
            doc.add_page_break()

        else:
            add_paragraph_block(doc, str(block))


def format_reference(reference: Any, idx: int) -> str:
    if isinstance(reference, str):
        return f"[{idx}] {reference}"

    source_name = reference.get("source_name") or "출처명 없음"
    author_or_org = reference.get("author_or_org")
    source_type = reference.get("source_type")
    published_date = reference.get("published_date")
    accessed_date = reference.get("accessed_date")
    source_url = reference.get("source_url")
    citation_label = reference.get("citation_label")

    parts = [f"[{idx}]"]

    if citation_label:
        parts.append(str(citation_label))

    if author_or_org:
        parts.append(str(author_or_org))

    parts.append(str(source_name))

    if source_type:
        parts.append(f"({source_type})")

    if published_date:
        parts.append(f"Published: {published_date}")

    if accessed_date:
        parts.append(f"Accessed: {accessed_date}")

    if source_url:
        parts.append(str(source_url))

    return " ".join(parts)


def add_references(doc: Document, references: list[Any]) -> None:
    doc.add_page_break()
    doc.add_heading("참고문헌", level=1)

    if not references:
        paragraph = doc.add_paragraph()
        run = paragraph.add_run("사용된 참고자료가 없습니다.")
        set_run_font(run, size=9)
        return

    for idx, reference in enumerate(references, start=1):
        paragraph = doc.add_paragraph()
        run = paragraph.add_run(format_reference(reference, idx))
        set_run_font(run, size=9)


def generate_docx_report(
    report_data: dict[str, Any],
    output_path: str | Path,
) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    configure_document_styles(doc)

    sections = report_data.get("sections", [])

    add_cover_page(doc, report_data)
    add_table_of_contents(doc, sections)

    for idx, section in enumerate(sections):
        add_section(doc, section)

        if idx < len(sections) - 1:
            doc.add_page_break()

    add_references(doc, report_data.get("references", []))

    doc.save(output_path)

    return str(output_path)
