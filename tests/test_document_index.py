"""Tests for proceval.ingestion.document_index."""

from pathlib import Path

from proceval.ingestion import build_vendor_index


def _touch_pdf(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4\n%%EOF\n")


def test_build_vendor_index_basic_layout(tmp_path: Path):
    v1 = tmp_path / "MEHAR_GAYATRI"
    v2 = tmp_path / "SPARK_TECHNOLOGY"
    _touch_pdf(v1 / "audited_balance_sheet.pdf")
    _touch_pdf(v1 / "udyam_registration.pdf")
    _touch_pdf(v2 / "audited_balance_sheet.pdf")
    _touch_pdf(v2 / "pan_card.pdf")

    submissions = build_vendor_index([v1, v2])

    assert len(submissions) == 2
    by_name = {s.vendor_name: s for s in submissions}
    assert by_name["MEHAR_GAYATRI"].document_count == 2
    assert by_name["MEHAR_GAYATRI"].detected_msme is True
    assert by_name["SPARK_TECHNOLOGY"].document_count == 2
    assert by_name["SPARK_TECHNOLOGY"].detected_msme is False


def test_build_vendor_index_msme_token_variants(tmp_path: Path):
    """Detection fires for udyam / msme / nsic regardless of case."""
    for token in ("udyam", "Udyam", "MSME_certificate", "nsic"):
        d = tmp_path / f"vendor_{token}"
        _touch_pdf(d / f"{token}_doc.pdf")
        s = build_vendor_index([d])[0]
        assert s.detected_msme is True, f"failed token: {token}"


def test_build_vendor_index_pdf_paths_sorted(tmp_path: Path):
    v = tmp_path / "VENDOR"
    _touch_pdf(v / "z_last.pdf")
    _touch_pdf(v / "a_first.pdf")
    _touch_pdf(v / "m_middle.pdf")

    s = build_vendor_index([v])[0]
    names = [Path(p).name for p in s.document_paths]
    assert names == ["a_first.pdf", "m_middle.pdf", "z_last.pdf"]


def test_build_vendor_index_empty_dir(tmp_path: Path):
    v = tmp_path / "EMPTY_VENDOR"
    v.mkdir()

    s = build_vendor_index([v])[0]
    assert s.vendor_name == "EMPTY_VENDOR"
    assert s.document_count == 0
    assert s.document_paths == []
    assert s.detected_msme is False


def test_build_vendor_index_ignores_non_pdf_files(tmp_path: Path):
    v = tmp_path / "VENDOR"
    _touch_pdf(v / "real.pdf")
    (v / "notes.txt").write_text("ignore me")

    s = build_vendor_index([v])[0]
    assert s.document_count == 1
    assert all(p.endswith(".pdf") for p in s.document_paths)
