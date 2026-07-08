# app/ingestion/loaders.py

from __future__ import annotations

from pathlib import Path

from docx import Document
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def read_text_file(path: Path) -> str:
    for encoding in ["utf-8", "utf-8-sig", "cp949"]:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    return path.read_text(errors="ignore")


def read_docx_file(path: Path) -> str:
    document = Document(str(path))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
    table_texts: list[str] = []

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            row_text = " | ".join(cell for cell in cells if cell)
            if row_text:
                table_texts.append(row_text)

    return "\n".join([*paragraphs, *table_texts]).strip()


def read_pdf_file(path: Path) -> str:
    reader = PdfReader(str(path))
    page_texts = []

    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = text.strip()

        if text:
            page_texts.append(f"[page {page_index}]\n{text}")

    return "\n\n".join(page_texts).strip()


def load_document_text(file_path: str | Path) -> str:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension: {suffix}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if suffix in {".txt", ".md", ".markdown"}:
        return read_text_file(path)

    if suffix == ".docx":
        return read_docx_file(path)

    if suffix == ".pdf":
        return read_pdf_file(path)

    raise ValueError(f"Unsupported file extension: {suffix}")
