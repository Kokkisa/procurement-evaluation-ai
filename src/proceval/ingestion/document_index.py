"""Build a per-vendor document map from a set of vendor directories.

After unzipping vendor archives into ``data/uploads/{eval_id}/{vendor_name}/``,
each subdirectory holds that vendor's PDFs. This module turns that layout
into a list of ``VendorSubmission`` schema objects.
"""

from pathlib import Path

from ..schemas.vendor import VendorSubmission

# Filename heuristics for MSME detection. Spec note: this is intentionally
# filename-only — a richer detection would also scan extracted text for
# Udyam/MSME/NSIC registration numbers. Filename-only is the spec contract.
_MSME_TOKENS = ("udyam", "msme", "nsic")


def build_vendor_index(vendor_dirs: list[Path]) -> list[VendorSubmission]:
    """Return one ``VendorSubmission`` per directory.

    Each ``vendor_dir`` is expected to contain that vendor's PDFs (post-unzip).
    The directory's name is used as the vendor name. PDFs are listed in
    sorted order for deterministic downstream processing.
    """
    submissions: list[VendorSubmission] = []
    for d in vendor_dirs:
        d = Path(d)
        pdfs = sorted(d.glob("*.pdf"))
        msme = any(_filename_suggests_msme(p) for p in pdfs)
        submissions.append(
            VendorSubmission(
                vendor_name=d.name,
                document_count=len(pdfs),
                document_paths=[str(p) for p in pdfs],
                detected_msme=msme,
            )
        )
    return submissions


def _filename_suggests_msme(p: Path) -> bool:
    name = p.name.lower()
    return any(token in name for token in _MSME_TOKENS)
