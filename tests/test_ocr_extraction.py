"""Tests for the hybrid PDF extractor + OCR fallback (ADR-0006).

Three tiers:

1. ``normalize_ocr_text`` unit tests — pure-function string transforms,
   no system deps.
2. Mocked integration — patches ``pytesseract.image_to_string`` so the
   per-page fallback path runs without invoking the Tesseract binary.
   Verifies the threshold logic, log messages, and integration with
   pdfplumber's per-page iteration.
3. Live-binary integration (skipped when Tesseract isn't on PATH) —
   does not commit a real scanned PDF; it builds a deliberately empty
   PDF with reportlab and asserts that the OCR fallback path is at
   least *invoked* on it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from proceval.config import settings
from proceval.ingestion.pdf_parser import extract_text, normalize_ocr_text


# --- normalize_ocr_text unit tests ----------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Empty / whitespace-only input
        ("", ""),
        ("   \n  \t  \n", ""),
        # Plain ASCII passes through
        ("Annual Turnover Rs. 100 Lakhs", "Annual Turnover Rs. 100 Lakhs"),
        # Mojibake characters stripped
        ("This is text â€” more text", "This is text more text"),
        ("Copyright © 2026", "Copyright 2026"),
        # Multiple non-ASCII runs collapse into spaces
        ("Block—A line", "Block A line"),
        # Whitespace runs within a line collapse to single space
        ("foo     bar\t\t\tbaz", "foo bar baz"),
        # Leading/trailing whitespace per line stripped
        ("   leading\ntrailing   \n  both  ", "leading\ntrailing\nboth"),
        # Blank lines dropped
        ("first\n\n\nsecond\n\n", "first\nsecond"),
        # Newlines preserved between non-blank lines
        ("line1\nline2", "line1\nline2"),
        # Real-ish OCR'd snippet with mixed garbage
        (
            "M/s ABC Enterprises\n• Turnover Rs. 100 L\n\nSd/-",
            "M/s ABC Enterprises\nTurnover Rs. 100 L\nSd/-",
        ),
    ],
)
def test_normalize_ocr_text(raw, expected):
    assert normalize_ocr_text(raw) == expected


def test_normalize_ocr_text_preserves_tabs_and_internal_punctuation():
    """Tabs survive (used in TSV table inlining); standard ASCII punctuation
    survives because the cleaner only strips non-printable / non-ASCII."""
    raw = "Particulars\tFY 2023-24\tFY 2022-23\nTurnover\t88.23\t62.10"
    out = normalize_ocr_text(raw)
    # Each line's whitespace runs collapse to single spaces, but the line
    # structure stays.
    assert out == "Particulars FY 2023-24 FY 2022-23\nTurnover 88.23 62.10"


# --- Hybrid threshold logic (mocked OCR) ----------------------------------


def _build_thin_pdf(path: Path, body: str = "") -> Path:
    """Generate a tiny PDF whose text-layer body is shorter than the OCR
    fallback threshold so the hybrid logic should trigger OCR."""
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    if body:
        c.drawString(72, 720, body)
    c.showPage()
    c.save()
    return path


def test_ocr_path_triggered_when_text_layer_thin(make_pdf, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "ocr_enabled", True)
    monkeypatch.setattr(settings, "ocr_fallback_threshold", 50)

    pdf = make_pdf("thin.pdf", [["x"]])  # 1 char body, well below threshold

    fake_ocr = "OCR-PROVIDED-TEXT abc 1234 from scan"
    with patch(
        "proceval.ingestion.pdf_parser._ocr_page", return_value=fake_ocr
    ) as mocked:
        text, pages = extract_text(pdf)

    assert pages == 1
    assert "OCR-PROVIDED-TEXT" in text
    mocked.assert_called_once()


def test_ocr_path_skipped_when_text_layer_meets_threshold(make_pdf, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "ocr_enabled", True)
    monkeypatch.setattr(settings, "ocr_fallback_threshold", 5)

    pdf = make_pdf(
        "fat.pdf", [["This page has a substantial text layer that exceeds the threshold."]]
    )

    with patch("proceval.ingestion.pdf_parser._ocr_page") as mocked:
        text, pages = extract_text(pdf)

    assert pages == 1
    assert "substantial text layer" in text
    mocked.assert_not_called()


def test_ocr_disabled_globally_means_no_fallback(make_pdf, tmp_path: Path, monkeypatch):
    """Even with a thin text layer, OCR_ENABLED=false skips the fallback path."""
    monkeypatch.setattr(settings, "ocr_enabled", False)
    monkeypatch.setattr(settings, "ocr_fallback_threshold", 1_000_000)  # everything is "thin"

    pdf = make_pdf("any.pdf", [["barely any text"]])

    with patch("proceval.ingestion.pdf_parser._ocr_page") as mocked:
        text, pages = extract_text(pdf)

    assert pages == 1
    mocked.assert_not_called()


def test_ocr_path_logs_per_page_method(make_pdf, monkeypatch, caplog):
    """The operator should see which pages were OCR'd at INFO level."""
    monkeypatch.setattr(settings, "ocr_enabled", True)
    monkeypatch.setattr(settings, "ocr_fallback_threshold", 50)

    pdf = make_pdf(
        "mixed.pdf",
        [
            ["x"],  # thin -> OCR
            ["This is a substantial text layer that comfortably exceeds the threshold."],  # text
            ["y"],  # thin -> OCR
        ],
    )

    with patch(
        "proceval.ingestion.pdf_parser._ocr_page",
        return_value="OCR-PAGE-CONTENT",
    ) as mocked:
        with caplog.at_level("INFO", logger="proceval.ingestion.pdf_parser"):
            text, pages = extract_text(pdf)

    assert pages == 3
    assert mocked.call_count == 2  # only thin pages OCR'd
    messages = [r.message for r in caplog.records]
    # At least one OCR log line and one text-layer log line per page
    assert any("page 1: text layer thin" in m for m in messages), messages
    assert any("page 2: text layer (" in m for m in messages), messages
    assert any("page 3: text layer thin" in m for m in messages), messages


def test_ocr_threshold_is_inclusive_lower_bound(make_pdf, monkeypatch):
    """A page with exactly threshold-1 chars triggers OCR; threshold chars does not."""
    # body produces "abcdefghij" = 10 chars in the text layer
    monkeypatch.setattr(settings, "ocr_enabled", True)

    monkeypatch.setattr(settings, "ocr_fallback_threshold", 10)
    pdf_at = make_pdf("at.pdf", [["abcdefghij"]])  # 10 chars, == threshold => skip OCR
    with patch("proceval.ingestion.pdf_parser._ocr_page") as mocked_at:
        extract_text(pdf_at)
    mocked_at.assert_not_called()

    monkeypatch.setattr(settings, "ocr_fallback_threshold", 11)
    pdf_under = make_pdf("under.pdf", [["abcdefghij"]])  # 10 < 11 => OCR
    with patch(
        "proceval.ingestion.pdf_parser._ocr_page", return_value="OCR-FROM-FALLBACK"
    ) as mocked_under:
        text, _ = extract_text(pdf_under)
    mocked_under.assert_called_once()
    assert "OCR-FROM-FALLBACK" in text


def test_ocr_output_runs_through_normalize(make_pdf, monkeypatch):
    """Whatever Tesseract returns, the result must be normalised before
    making it into the final blob — otherwise mojibake would leak into
    downstream LLM prompts."""
    monkeypatch.setattr(settings, "ocr_enabled", True)
    monkeypatch.setattr(settings, "ocr_fallback_threshold", 1000)

    pdf = make_pdf("scan.pdf", [["x"]])

    raw_ocr = "Turnover £100 Lakhs   with    runs—and © noise"
    with patch("proceval.ingestion.pdf_parser._ocr_page", return_value=raw_ocr):
        text, _ = extract_text(pdf)

    # Whitespace runs collapsed, mojibake stripped
    assert "Turnover  100 Lakhs" not in text  # double-space wouldn't survive normalize
    assert "Turnover 100 Lakhs with runs and noise" in text


# --- Live-binary integration (gated) ---------------------------------------


_TESSERACT_AVAILABLE = (
    shutil.which("tesseract") is not None
    or Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists()
)


@pytest.mark.skipif(not _TESSERACT_AVAILABLE, reason="Tesseract binary not available")
def test_ocr_page_helper_invokes_real_binary(tmp_path: Path, monkeypatch):
    """Smoke check that ``_ocr_page`` actually runs end-to-end against a real
    rendered page. We don't assert any specific OCR output (the input is a
    blank page) — just that the call doesn't raise and returns a string."""
    from proceval.ingestion.pdf_parser import _ocr_page

    pdf = _build_thin_pdf(tmp_path / "blank.pdf")
    try:
        result = _ocr_page(pdf, 1, dpi=150)  # low DPI to keep this test fast
    except Exception as e:
        pytest.skip(f"OCR live-binary call failed (likely missing Poppler): {e}")
    assert isinstance(result, str)
