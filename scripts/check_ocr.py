"""One-off CLI: run the hybrid PDF extractor on a single file and report
which method (text-layer vs OCR) was used per page.

Not part of the test suite — meant for ad-hoc inspection of real scanned
vendor PDFs that you don't want to commit. Run as:

    python scripts/check_ocr.py <path-to-pdf>

Prints:
    - Per-page method (text-layer / OCR-fallback) at INFO level via the
      pdf_parser logger.
    - Total page count.
    - First 500 chars of the extracted text (so you can eyeball whether
      OCR got anything useful).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

# Make sure pytesseract can find the Tesseract binary even when the launching
# shell hasn't inherited the right PATH (Git Bash on Windows is the common case).
_DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if shutil.which("tesseract") is None and Path(_DEFAULT_TESSERACT).exists():
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = _DEFAULT_TESSERACT
    except ImportError:
        pass

# Same for Poppler — pdf2image needs `pdftoppm` on PATH; if it isn't, allow
# an explicit override via POPPLER_PATH env var.
_POPPLER_OVERRIDE = os.environ.get("POPPLER_PATH")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/check_ocr.py <path-to-pdf>", file=sys.stderr)
        return 2

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"error: {pdf_path} not found", file=sys.stderr)
        return 1

    # Make sure OCR is on for this run (irrespective of test conftest leftovers).
    os.environ["OCR_ENABLED"] = "true"

    # Import after env setup so settings picks up OCR_ENABLED=true.
    from proceval.ingestion.pdf_parser import extract_text

    print(f"\n=== check_ocr {pdf_path} ===\n")
    text, pages = extract_text(pdf_path)
    print(f"\n--- result ---")
    print(f"  pages         : {pages}")
    print(f"  total chars   : {len(text)}")
    print(f"  first 500 chars:")
    print("-" * 60)
    print(text[:500])
    print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
