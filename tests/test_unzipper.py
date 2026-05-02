"""Tests for proceval.ingestion.unzipper."""

import zipfile
from pathlib import Path

import pytest

from proceval.ingestion import unzip_to_directory


def test_unzip_returns_pdfs_in_sorted_order(make_pdf, tmp_path: Path):
    pdf_a = make_pdf("a.pdf", [["A"]])
    pdf_b = make_pdf("b.pdf", [["B"]])

    archive = tmp_path / "vendor.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(pdf_b, arcname="b.pdf")
        zf.write(pdf_a, arcname="a.pdf")

    target = tmp_path / "extracted"
    extracted = unzip_to_directory(archive, target)

    assert [p.name for p in extracted] == ["a.pdf", "b.pdf"]
    assert all(p.exists() for p in extracted)


def test_unzip_creates_target_dir(make_pdf, tmp_path: Path):
    pdf = make_pdf("only.pdf", [["X"]])
    archive = tmp_path / "vendor.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(pdf, arcname="only.pdf")

    target = tmp_path / "does" / "not" / "exist" / "yet"
    extracted = unzip_to_directory(archive, target)
    assert target.is_dir()
    assert len(extracted) == 1


def test_unzip_recurses_into_nested_dirs(make_pdf, tmp_path: Path):
    pdf = make_pdf("nested.pdf", [["nested"]])
    archive = tmp_path / "vendor.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(pdf, arcname="subdir/nested.pdf")

    extracted = unzip_to_directory(archive, tmp_path / "out")
    assert len(extracted) == 1
    assert extracted[0].name == "nested.pdf"
    assert extracted[0].parent.name == "subdir"


def test_unzip_skips_non_pdf_entries(make_pdf, tmp_path: Path):
    pdf = make_pdf("real.pdf", [["X"]])
    archive = tmp_path / "vendor.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(pdf, arcname="real.pdf")
        zf.writestr("readme.txt", "ignore me")

    extracted = unzip_to_directory(archive, tmp_path / "out")
    assert len(extracted) == 1
    assert extracted[0].name == "real.pdf"


def test_unzip_rejects_zip_slip(tmp_path: Path):
    """An entry whose path escapes the target dir must be refused."""
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.pdf", b"%PDF-1.4\n%%EOF\n")

    with pytest.raises(zipfile.BadZipFile):
        unzip_to_directory(archive, tmp_path / "out")
