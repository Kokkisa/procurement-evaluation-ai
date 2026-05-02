"""Tests for proceval.ingestion.pdf_parser."""

from pathlib import Path

import pytest

from proceval.ingestion import extract_text


def test_extract_text_returns_text_and_page_count(make_pdf):
    pdf = make_pdf(
        "single.pdf",
        [["Tender No: GEM/2024/B/5533836", "Subject: Cylinder Handling Services"]],
    )
    text, pages = extract_text(pdf)
    assert pages == 1
    assert "GEM/2024/B/5533836" in text
    assert "Cylinder Handling Services" in text


def test_extract_text_multipage(make_pdf):
    pdf = make_pdf(
        "multi.pdf",
        [
            ["Page 1: PQC FINANCIAL"],
            ["Page 2: TECHNICAL CRITERIA"],
            ["Page 3: COMMERCIAL TERMS"],
        ],
    )
    text, pages = extract_text(pdf)
    assert pages == 3
    assert "PQC FINANCIAL" in text
    assert "TECHNICAL CRITERIA" in text
    assert "COMMERCIAL TERMS" in text


def test_extract_text_falls_back_for_unreadable_pdf(tmp_path: Path):
    """If pdfplumber raises, the pypdf fallback path runs (and may also fail)."""
    junk = tmp_path / "broken.pdf"
    junk.write_bytes(b"%PDF-1.4\nthis is not a real pdf\n%%EOF\n")
    with pytest.raises(Exception):
        extract_text(junk)
