from __future__ import annotations

from io import BytesIO

from docx import Document
from pypdf import PdfReader


def extract_text(data: bytes, filename: str, mime_type: str | None = None) -> str:
    lower = filename.lower()
    if "pdf" in (mime_type or "") or lower.endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if "wordprocessingml" in (mime_type or "") or lower.endswith(".docx"):
        doc = Document(BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    return data.decode("utf-8", errors="ignore").strip()
