import pdfplumber
import os
from pathlib import Path

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file. Returns empty string on error."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages)
    except Exception:
        return ""

def extract_all_pdfs(pdfs_dir: str) -> dict[str, str]:
    """Extract text from all PDFs in directory tree.
    Returns dict mapping filename -> extracted text."""
    result = {}
    for pdf_path in Path(pdfs_dir).rglob("*.pdf"):
        text = extract_text_from_pdf(str(pdf_path))
        if text.strip():
            result[pdf_path.name] = text
    return result
