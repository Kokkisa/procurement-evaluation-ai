"""Vendor-archive unzipper.

Vendors typically submit one ZIP per submission containing ~10 PDFs.
This helper extracts a ZIP and returns the list of PDFs found inside.
"""

import zipfile
from pathlib import Path


def unzip_to_directory(zip_path: Path, target_dir: Path) -> list[Path]:
    """Extract ``zip_path`` into ``target_dir`` and return all PDFs found.

    Raises:
        zipfile.BadZipFile: if the archive is corrupt or not a ZIP.
        FileNotFoundError: if ``zip_path`` does not exist.

    Behaviour:
        - Creates ``target_dir`` (and parents) if missing.
        - Recursively returns every ``*.pdf`` under ``target_dir`` after extraction,
          sorted for deterministic ordering.
        - Skips any zip entry whose normalized path tries to escape ``target_dir``
          (Zip-Slip defense).
    """
    zip_path = Path(zip_path)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    target_resolved = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            extracted = (target_dir / member.filename).resolve()
            try:
                extracted.relative_to(target_resolved)
            except ValueError:
                raise zipfile.BadZipFile(
                    f"Refusing to extract entry that escapes target dir: {member.filename!r}"
                ) from None
        zf.extractall(target_dir)

    return sorted(target_dir.rglob("*.pdf"))
