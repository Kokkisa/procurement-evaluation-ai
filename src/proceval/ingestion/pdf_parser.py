"""Hybrid PDF text extraction: text-layer first, OCR fallback for scanned pages.

Real procurement bid packs mix digital PDFs (audited B/S, purchase orders —
text-layer extraction works) with notarised scans (turnover certificates,
experience letters — text layer is empty, image-only). pdfplumber returns
"" for scanned pages; without OCR fallback the LLM evaluator sees a missing
document and downgrades the verdict.

Extraction strategy per ADR-0006:
1. Open with pdfplumber, iterate pages.
2. For each page, take the text-layer body + table extractions.
3. If the combined per-page text comes back thinner than
   ``settings.ocr_fallback_threshold`` chars, OCR that page only via
   pdf2image (Poppler) + pytesseract.
4. Combine all pages into the final text blob.
5. Per-page method is logged at INFO so the operator (and LangSmith trace
   reader) sees exactly which pages were OCR'd.

If pdfplumber itself fails to open the file, fall back to pypdf for raw
text-layer extraction. OCR is not attempted on that path because we'd have
no reliable page count without a working PDF parser.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pdfplumber
import pypdf

from ..config import settings

logger = logging.getLogger(__name__)


def extract_text(pdf_path: Path) -> tuple[str, int]:
    """Return ``(full_text, page_count)`` for the PDF at ``pdf_path``.

    Hybrid: text-layer per page, OCR fallback for thin pages when
    ``settings.ocr_enabled`` is True.
    """
    pdf_path = Path(pdf_path)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            page_chunks: list[str] = []
            for idx, page in enumerate(pdf.pages, start=1):
                page_chunks.append(_extract_page(pdf_path, page, idx))
            return ("\n\n".join(page_chunks), page_count)
    except Exception as exc:
        # Malformed PDF that pdfplumber can't open; fall back to pypdf
        # text-layer extraction. We don't try OCR here because we'd have no
        # reliable page count to drive a per-page loop.
        logger.warning("pdfplumber failed for %s (%s); falling back to pypdf", pdf_path.name, exc)
        reader = pypdf.PdfReader(str(pdf_path))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        return (text, len(reader.pages))


def _extract_page(pdf_path: Path, page, page_number: int) -> str:
    """Pull text + tables from one pdfplumber page; OCR-fallback if thin."""
    body = page.extract_text() or ""
    tables_text: list[str] = []
    for table in page.extract_tables() or []:
        tables_text.append(
            "\n".join("\t".join(cell or "" for cell in row) for row in table)
        )
    combined = body
    if tables_text:
        combined = combined + "\n" + "\n".join(tables_text)

    body_chars = len(combined.strip())
    if (
        settings.ocr_enabled
        and body_chars < settings.ocr_fallback_threshold
    ):
        logger.info(
            "page %d: text layer thin (%d chars < threshold %d) -> OCR",
            page_number, body_chars, settings.ocr_fallback_threshold,
        )
        ocr_text = _ocr_page(pdf_path, page_number, settings.ocr_dpi)
        return normalize_ocr_text(ocr_text)

    logger.info("page %d: text layer (%d chars)", page_number, body_chars)
    return combined


def _ocr_page(pdf_path: Path, page_number: int, dpi: int) -> str:
    """Render one page to an image and run Tesseract on it.

    Imports are lazy so the module stays importable on systems without the
    OCR system binaries (Tesseract + Poppler). If OCR is needed and the
    binaries are missing, the underlying libraries raise a clear error which
    bubbles up; caller can decide to retry, fail loudly, or set
    ``OCR_ENABLED=false`` to skip.
    """
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_number,
        last_page=page_number,
    )
    if not images:
        return ""
    return pytesseract.image_to_string(images[0])


_OCR_NON_PRINTABLE_RE = re.compile(r"[^\x20-\x7e\n\r\t]")
_OCR_WHITESPACE_RE = re.compile(r"[ \t]+")


def normalize_ocr_text(text: str) -> str:
    """Clean common OCR artefacts:

    - Strip non-ASCII / non-printable characters (mojibake like ``â€"``,
      ``Â©``, smart-quote borders, decorative bullets that the model
      hallucinated from page noise).
    - Collapse runs of intra-line whitespace.
    - Strip leading/trailing whitespace per line.
    - Drop blank lines so the resulting blob is dense.

    Tradeoff: this is aggressive on non-English text. For procurement docs
    in English (which is the v0.1 demo target), the precision win
    outweighs the recall loss. ADR-0006 records this and lists alternatives
    (Unicode normalisation, language-tagged OCR) for v0.3+.
    """
    if not text:
        return ""
    cleaned = _OCR_NON_PRINTABLE_RE.sub(" ", text)
    lines: list[str] = []
    for line in cleaned.splitlines():
        compact = _OCR_WHITESPACE_RE.sub(" ", line).strip()
        if compact:
            lines.append(compact)
    return "\n".join(lines)
