"""Sanity tests for the committed synthetic fixtures.

These tests verify that the output of scripts/generate_synthetic_vendors.py
(committed under tests/fixtures/) matches the expected shape that downstream
agents will rely on: tender numbers, thresholds, vendor doc counts, MSME
detection, and the critical numeric markers used by the gold-standard
ACCEPT/REJECT integration test in Block 10.

If these tests fail, regenerate the fixtures via:
    python scripts/generate_synthetic_vendors.py
"""

from pathlib import Path

import pytest

from proceval.ingestion import build_vendor_index, extract_text

FIXTURES = Path(__file__).parent / "fixtures"
TENDER = FIXTURES / "tender_housekeeping_demo.pdf"
VENDORS = FIXTURES / "synthetic_vendors"

EXPECTED_VENDORS = {
    "aroha_facility_services":            {"is_msme": True,  "doc_count": 10, "is_accept": True},
    "tejaswini_housekeeping_enterprises": {"is_msme": False, "doc_count": 9,  "is_accept": True},
    "shri_mangalam_safai_works":          {"is_msme": True,  "doc_count": 10, "is_accept": False},
    "prabhat_deep_sanitation_solutions":  {"is_msme": False, "doc_count": 9,  "is_accept": True},
    "raghavendra_maintenance_works":      {"is_msme": False, "doc_count": 8,  "is_accept": False},
}


def test_tender_pdf_exists_and_parses():
    assert TENDER.exists(), f"missing fixture: {TENDER}"
    text, pages = extract_text(TENDER)
    assert pages >= 4
    assert "DEMO/2026/HKP/001" in text
    assert "Housekeeping" in text
    assert "PRE-QUALIFICATION CRITERIA" in text
    assert "100 Lakhs" in text  # PQC turnover threshold
    assert "MANPOWER" in text


def test_all_vendor_dirs_exist():
    assert VENDORS.is_dir()
    found = sorted(p.name for p in VENDORS.iterdir() if p.is_dir())
    assert found == sorted(EXPECTED_VENDORS.keys())


@pytest.mark.parametrize("slug,expected", list(EXPECTED_VENDORS.items()))
def test_vendor_folder_doc_count(slug, expected):
    vdir = VENDORS / slug
    pdfs = sorted(vdir.glob("*.pdf"))
    assert len(pdfs) == expected["doc_count"], (
        f"{slug}: expected {expected['doc_count']} PDFs, got {len(pdfs)}: "
        f"{[p.name for p in pdfs]}"
    )


def test_msme_vendors_have_udyam_others_dont():
    for slug, expected in EXPECTED_VENDORS.items():
        vdir = VENDORS / slug
        has_udyam = (vdir / "udyam_registration.pdf").exists()
        assert has_udyam == expected["is_msme"], (
            f"{slug}: udyam_registration.pdf present={has_udyam} but is_msme={expected['is_msme']}"
        )


def test_raghavendra_is_missing_blacklist_declaration():
    vdir = VENDORS / "raghavendra_maintenance_works"
    assert not (vdir / "blacklist_declaration.pdf").exists(), (
        "RAGHAVENDRA must be missing the blacklist declaration to exercise the REJECT path"
    )


def test_other_vendors_have_blacklist_declaration():
    for slug in EXPECTED_VENDORS:
        if slug == "raghavendra_maintenance_works":
            continue
        assert (VENDORS / slug / "blacklist_declaration.pdf").exists(), (
            f"{slug} should have blacklist_declaration.pdf"
        )


def test_vendor_index_msme_detection_matches_expected():
    vendor_dirs = sorted(p for p in VENDORS.iterdir() if p.is_dir())
    subs = build_vendor_index(vendor_dirs)
    by_slug = {s.vendor_name: s for s in subs}
    for slug, expected in EXPECTED_VENDORS.items():
        assert by_slug[slug].detected_msme == expected["is_msme"], (
            f"{slug}: detected_msme={by_slug[slug].detected_msme} but expected {expected['is_msme']}"
        )


def test_critical_numbers_parse_from_balance_sheets():
    """The numbers downstream eval will key on must be extractable from the PDF text."""
    cases = [
        ("aroha_facility_services",            "audited_balance_sheet_FY2023-24.pdf", "68.20"),
        ("tejaswini_housekeeping_enterprises", "audited_balance_sheet_FY2023-24.pdf", "276.40"),
        ("shri_mangalam_safai_works",          "audited_balance_sheet_FY2023-24.pdf", "71.30"),
        ("prabhat_deep_sanitation_solutions",  "audited_balance_sheet_FY2023-24.pdf", "248.90"),
        ("raghavendra_maintenance_works",      "audited_balance_sheet_FY2023-24.pdf", "1,253.40"),
    ]
    for slug, fname, marker in cases:
        text, _ = extract_text(VENDORS / slug / fname)
        assert marker in text, f"{slug}/{fname}: marker {marker!r} not found in extracted text"


def test_critical_similar_work_values_parse():
    cases = [
        ("aroha_facility_services",            "118.50"),
        ("tejaswini_housekeeping_enterprises", "164.20"),
        ("shri_mangalam_safai_works",          "38.42"),  # the rejection-driving number
        ("prabhat_deep_sanitation_solutions",  "192.70"),
        ("raghavendra_maintenance_works",      "211.40"),
    ]
    for slug, marker in cases:
        text, _ = extract_text(VENDORS / slug / "purchase_order_similar_work_1.pdf")
        assert marker in text, f"{slug}: similar-work PO value {marker!r} not extractable"


def test_pan_and_gstin_format_patterns():
    """PAN must match AAAAA9999A, GSTIN must match SSAAAAA9999A1ZX (15 chars)."""
    import re
    pan_re = re.compile(r"PAN:\s*([A-Z]{5}\d{4}[A-Z])")
    gstin_re = re.compile(r"GSTIN:\s*(\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z\d])")
    for slug in EXPECTED_VENDORS:
        # Use balance sheet header which prints PAN | GSTIN
        text, _ = extract_text(VENDORS / slug / "audited_balance_sheet_FY2023-24.pdf")
        pan_match = pan_re.search(text)
        gstin_match = gstin_re.search(text)
        assert pan_match, f"{slug}: PAN not found / wrong format"
        assert gstin_match, f"{slug}: GSTIN not found / wrong format"
        # GSTIN's embedded PAN substring should match the standalone PAN
        assert pan_match.group(1) == gstin_match.group(1)[2:12]
