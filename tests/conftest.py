"""Shared pytest fixtures.

The PDF helpers here generate small documents on demand so unit tests don't
depend on committed binary fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


def _write_pdf(path: Path, lines_per_page: list[list[str]]) -> Path:
    """Write a PDF with one page per inner list of text lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER
    for page_lines in lines_per_page:
        y = height - 72
        for line in page_lines:
            c.drawString(72, y, line)
            y -= 16
        c.showPage()
    c.save()
    return path


@pytest.fixture
def make_pdf(tmp_path: Path):
    """Factory fixture: returns a callable that writes a PDF under tmp_path."""

    def _make(filename: str, lines_per_page: list[list[str]]) -> Path:
        return _write_pdf(tmp_path / filename, lines_per_page)

    return _make
