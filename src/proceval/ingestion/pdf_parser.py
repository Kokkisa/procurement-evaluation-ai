"""PDF text extraction.

pdfplumber gives the best results on tabular PSU documents (audited B/S,
purchase orders) because it can extract tables row-by-row. pypdf is a
last-resort fallback for malformed PDFs that crash pdfplumber.
"""

from pathlib import Path

import pdfplumber
import pypdf


def extract_text(pdf_path: Path) -> tuple[str, int]:
    """Return ``(full_text, page_count)`` for the PDF at ``pdf_path``.

    pdfplumber is tried first. On any exception, falls back to pypdf.

    Tables are inlined as TSV after each page's body text — this preserves
    the row/column relationship for downstream LLM extraction without needing
    a separate table-extraction step.
    """
    pdf_path = Path(pdf_path)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            chunks: list[str] = []
            for page in pdf.pages:
                body = page.extract_text() or ""
                chunks.append(body)
                for table in page.extract_tables() or []:
                    chunks.append(
                        "\n".join("\t".join(cell or "" for cell in row) for row in table)
                    )
            return ("\n\n".join(chunks), len(pdf.pages))
    except Exception:
        reader = pypdf.PdfReader(str(pdf_path))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        return (text, len(reader.pages))
