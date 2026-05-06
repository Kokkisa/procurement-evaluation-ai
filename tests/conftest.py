"""Shared pytest fixtures + test-session env shims.

Two things happen at import time, *before* any test module imports
``proceval.config``:

1. ``LANGCHAIN_TRACING_V2=false`` — ``proceval.config`` propagates LangSmith
   env vars from .env into ``os.environ`` so LangChain's auto-tracer can
   pick them up. During tests that means every mocked ``chain.ainvoke()``
   would attempt a trace POST over the network. Forcing tracing off here
   keeps the unit suite fast + offline. The propagation logic is still
   exercised directly via the dedicated tests in test_config.py.

2. ``LLM_INTER_BATCH_SLEEP_SECONDS=0`` — production .env values for the
   throttle knob can be very conservative (e.g. 10s for Tier-1 safety).
   Without this override, tests that exercise ``aevaluate_vendor``
   without passing an explicit sleep value would inherit the production
   throttle and a 5-criterion test would take ~40s. Tests that
   *specifically* exercise the sleep behaviour pass their own
   ``inter_batch_sleep_seconds`` value to the agent, so they still work.

Both use ``setdefault`` so a deliberate shell-exported value
(e.g. ``LANGCHAIN_TRACING_V2=true pytest ...`` for ad-hoc trace
debugging) still wins.
"""

from __future__ import annotations

import os

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LLM_INTER_BATCH_SLEEP_SECONDS", "0")
# Disable OCR fallback during tests so make_pdf-generated fixtures (which are
# tiny, often <50 chars/page) don't try to invoke the system Tesseract binary.
# OCR-specific tests in test_ocr_extraction.py re-enable it via monkeypatch.
os.environ.setdefault("OCR_ENABLED", "false")

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
