import os
import pytest
from services.pdf_extractor import extract_text_from_pdf, extract_all_pdfs

def test_extract_text_returns_string(tmp_path):
    from services.pdf_extractor import extract_text_from_pdf
    result = extract_text_from_pdf("nonexistent.pdf")
    assert isinstance(result, str)
    assert result == ""

def test_extract_all_returns_dict(tmp_path):
    result = extract_all_pdfs(str(tmp_path))
    assert isinstance(result, dict)
    assert len(result) == 0
