"""Generate the synthetic Housekeeping & Sanitation Services tender PDF and
five fabricated vendor submission folders for the public demo.

Every name, number, identifier, address, date, and clause produced by this
script is FABRICATED. The script mimics the *structural* conventions of
Indian PSU procurement documents (PQC sections, manpower tables, audited
B/S 3-column FY layout, PO format, work-completion certificate, GST
Form REG-06, Udyam certificate, non-blacklisting declaration, bidder
response form) and uses correct *format patterns* for PAN / GSTIN / Udyam
identifiers so downstream regex parsing exercises real shapes — but the
values themselves do not correspond to any real entity, registration,
tender, or evaluation.

Domain: housekeeping & sanitation services at a generic industrial facility.
Issuing entity: DEMO PROCUREMENT CORPORATION LIMITED (clearly fictional).

Outputs (deterministic from SEED below):
    tests/fixtures/tender_housekeeping_demo.pdf
    tests/fixtures/synthetic_vendors/{vendor_slug}/*.pdf

Run:
    python scripts/generate_synthetic_vendors.py

Re-running rebuilds all outputs (idempotent).
"""

from __future__ import annotations

import random
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# --- Configuration ---------------------------------------------------------

SEED = 4242

REPO_ROOT = Path(__file__).resolve().parent.parent
TENDER_OUT = REPO_ROOT / "tests" / "fixtures" / "tender_housekeeping_demo.pdf"
VENDORS_OUT = REPO_ROOT / "tests" / "fixtures" / "synthetic_vendors"

TENDER_NUMBER = "DEMO/2026/HKP/001"
TENDER_NAME = "Housekeeping & Sanitation Services at Demo Industrial Facility"
TENDER_ISSUER = "DEMO PROCUREMENT CORPORATION LIMITED"
TENDER_LOCATION = "Demo Industrial Facility, Pune"
TENDER_FLOATED_DATE = date(2026, 4, 10)
TENDER_DUE_DATE = date(2026, 4, 30)

PQC_TURNOVER_THRESHOLD = 100.0  # lakhs
PQC_TURNOVER_MSME = 85.0
PQC_SIMILAR_WORK_THRESHOLD = 100.0
PQC_SIMILAR_WORK_MSME = 85.0

ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGIT = "0123456789"


# --- Identifier generators -------------------------------------------------
# Real format patterns; fabricated values. Deterministic from a string seed
# so identifiers stay stable across regenerations.


def _rng(seed_str: str) -> random.Random:
    return random.Random(f"{SEED}:{seed_str}")


def fab_pan(seed_str: str, entity_code: str = "C") -> str:
    """10 chars: AAAAA9999A. 4th alpha is entity (C=company, P=individual, F=firm)."""
    r = _rng(f"pan:{seed_str}")
    a3 = "".join(r.choices(ALPHA, k=3))
    a5 = r.choice(ALPHA)
    d4 = "".join(r.choices(DIGIT, k=4))
    chk = r.choice(ALPHA)
    return f"{a3}{entity_code}{a5}{d4}{chk}"


def fab_gstin(state_code: str, pan: str, entity_seq: str = "1") -> str:
    """15 chars: SS + 10-char PAN + 1-char entity-seq + 'Z' + 1 alphanumeric check."""
    r = _rng(f"gstin:{state_code}:{pan}")
    chk = r.choice(ALPHA + DIGIT)
    return f"{state_code}{pan}{entity_seq}Z{chk}"


def fab_udyam(state2: str, district2: str, seed_str: str) -> str:
    """UDYAM-{2 alpha}-{2 digit}-{7 digit}."""
    r = _rng(f"udyam:{seed_str}")
    n7 = "".join(r.choices(DIGIT, k=7))
    return f"UDYAM-{state2}-{district2}-{n7}"


def fab_frn(seed_str: str) -> str:
    """Auditor Firm Registration Number — 6 digits + 1 alpha zone code."""
    r = _rng(f"frn:{seed_str}")
    n6 = "".join(r.choices(DIGIT, k=6))
    a1 = r.choice("WNESC")  # zone codes
    return f"{n6}{a1}"


def fab_po_number(seed_str: str) -> str:
    r = _rng(f"po:{seed_str}")
    return f"PO/{r.randint(2022, 2024)}/HSK/{r.randint(1000, 9999)}"


def _city(addr: str) -> str:
    """Pull the city from a 'X, Y, City - PIN' style address."""
    last = addr.split(",")[-1].strip()  # 'Pune - 411026'
    return last.split("-")[0].strip()


# --- Vendor profiles -------------------------------------------------------

@dataclass(frozen=True)
class VendorProfile:
    name: str
    slug: str
    is_msme: bool
    is_accept: bool
    failure_mode: str | None  # None | 'similar_work_below_threshold' | 'missing_blacklist_decl'

    # Financial figures (in INR lakhs, rounded to 2 decimals)
    turnover_fy_23_24: float
    turnover_fy_22_23: float
    turnover_fy_21_22: float
    similar_work_po_value: float

    # Address & geography
    address: str
    state: str
    state_code: str   # 2-digit GSTIN state code
    state_2alpha: str  # 2-letter Udyam state code
    district_code: str  # 2-digit Udyam district code

    # People + counter-party + dates
    proprietor_name: str
    similar_work_buyer: str
    similar_work_po_date: date
    similar_work_completion_date: date
    incorporation_date: date

    # Auditor
    auditor_firm: str

    # --- derived identifiers ---

    @property
    def pan(self) -> str:
        # Sole proprietor for vendor 5; companies for the others.
        entity = "P" if self.slug == "raghavendra_maintenance_works" else "C"
        return fab_pan(self.slug, entity_code=entity)

    @property
    def gstin(self) -> str:
        return fab_gstin(self.state_code, self.pan)

    @property
    def udyam(self) -> str | None:
        if not self.is_msme:
            return None
        return fab_udyam(self.state_2alpha, self.district_code, self.slug)

    @property
    def auditor_frn(self) -> str:
        return fab_frn(self.auditor_firm)

    @property
    def similar_work_po_number(self) -> str:
        return fab_po_number(f"{self.slug}:po1")

    @property
    def city(self) -> str:
        return _city(self.address)


VENDORS: list[VendorProfile] = [
    VendorProfile(
        name="AROHA FACILITY SERVICES PVT LTD",
        slug="aroha_facility_services",
        is_msme=True,
        is_accept=True,
        failure_mode=None,
        turnover_fy_23_24=68.20,
        turnover_fy_22_23=62.10,
        turnover_fy_21_22=55.40,
        similar_work_po_value=118.50,
        address="Plot 47, MIDC Industrial Area, Bhosari, Pune - 411026",
        state="Maharashtra",
        state_code="27",
        state_2alpha="MH",
        district_code="19",
        proprietor_name="Mr. Anand Devle",
        similar_work_buyer="MERIDIAN MANUFACTURING (INDIA) PVT LTD",
        similar_work_po_date=date(2023, 3, 15),
        similar_work_completion_date=date(2024, 3, 14),
        incorporation_date=date(2017, 6, 12),
        auditor_firm="Karthikeyan & Associates",
    ),
    VendorProfile(
        name="TEJASWINI HOUSEKEEPING ENTERPRISES",
        slug="tejaswini_housekeeping_enterprises",
        is_msme=False,
        is_accept=True,
        failure_mode=None,
        turnover_fy_23_24=276.40,
        turnover_fy_22_23=241.10,
        turnover_fy_21_22=198.50,
        similar_work_po_value=164.20,
        address="14 Sahakara Layout 2nd Phase, Bengaluru - 560085",
        state="Karnataka",
        state_code="29",
        state_2alpha="KA",
        district_code="03",
        proprietor_name="Ms. Lakshmi Iyer",
        similar_work_buyer="ZENITH AUTOMOTIVE COMPONENTS LIMITED",
        similar_work_po_date=date(2022, 11, 1),
        similar_work_completion_date=date(2024, 10, 31),
        incorporation_date=date(2014, 4, 7),
        auditor_firm="Subramanian & Co. Chartered Accountants",
    ),
    VendorProfile(
        name="SHRI MANGALAM SAFAI WORKS",
        slug="shri_mangalam_safai_works",
        is_msme=True,
        is_accept=False,
        failure_mode="similar_work_below_threshold",
        turnover_fy_23_24=71.30,
        turnover_fy_22_23=64.85,
        turnover_fy_21_22=52.40,
        similar_work_po_value=38.42,
        address="Shop 8 Krishna Complex Civil Lines, Indore - 452001",
        state="Madhya Pradesh",
        state_code="23",
        state_2alpha="MP",
        district_code="07",
        proprietor_name="Mr. Mahesh Tiwari",
        similar_work_buyer="ARYA PACKAGING INDUSTRIES",
        similar_work_po_date=date(2023, 7, 10),
        similar_work_completion_date=date(2024, 6, 30),
        incorporation_date=date(2019, 9, 22),
        auditor_firm="Mehta Joshi & Associates",
    ),
    VendorProfile(
        name="PRABHAT DEEP SANITATION SOLUTIONS",
        slug="prabhat_deep_sanitation_solutions",
        is_msme=False,
        is_accept=True,
        failure_mode=None,
        turnover_fy_23_24=248.90,
        turnover_fy_22_23=215.60,
        turnover_fy_21_22=182.30,
        similar_work_po_value=192.70,
        address="B-12 Sector 63 Industrial Area, Noida - 201307",
        state="Uttar Pradesh",
        state_code="09",
        state_2alpha="UP",
        district_code="35",
        proprietor_name="Mr. Surinder Jindal",
        similar_work_buyer="HIRANYA TEXTILES LIMITED",
        similar_work_po_date=date(2022, 8, 15),
        similar_work_completion_date=date(2024, 8, 14),
        incorporation_date=date(2011, 2, 18),
        auditor_firm="Bhatnagar & Co.",
    ),
    VendorProfile(
        name="RAGHAVENDRA MAINTENANCE WORKS",
        slug="raghavendra_maintenance_works",
        is_msme=False,
        is_accept=False,
        failure_mode="missing_blacklist_decl",
        turnover_fy_23_24=1253.40,
        turnover_fy_22_23=1082.90,
        turnover_fy_21_22=934.20,
        similar_work_po_value=211.40,
        address="Plot 32 GIDC Estate Vatva, Ahmedabad - 382445",
        state="Gujarat",
        state_code="24",
        state_2alpha="GJ",
        district_code="04",
        proprietor_name="Mr. Raghavendra Patel",
        similar_work_buyer="VARDHAN STEEL LIMITED",
        similar_work_po_date=date(2022, 5, 20),
        similar_work_completion_date=date(2024, 5, 19),
        incorporation_date=date(2008, 11, 3),
        auditor_firm="Patel Shah & Associates",
    ),
]


# --- Common ReportLab styles ----------------------------------------------

_base = getSampleStyleSheet()
S = {
    "Title": ParagraphStyle("Title", parent=_base["Title"], fontSize=14, spaceAfter=8, alignment=1),
    "Heading": ParagraphStyle(
        "Heading", parent=_base["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=6
    ),
    "Body": ParagraphStyle(
        "Body", parent=_base["BodyText"], fontSize=10, leading=13, spaceAfter=4
    ),
    "Small": ParagraphStyle("Small", parent=_base["BodyText"], fontSize=9, leading=11),
    "Center": ParagraphStyle("Center", parent=_base["BodyText"], fontSize=10, alignment=1),
}


def _doc(out_path: Path, story: list) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=out_path.stem,
    )
    doc.build(story)


def _wrap_col(rows: list, col_indexes: list[int], skip_header: bool = True) -> list:
    """Return a copy of ``rows`` with the given columns wrapped in Paragraphs.

    Raw strings in a ReportLab ``Table`` cell don't word-wrap; only ``Flowable``
    objects do. Wrapping in ``Paragraph`` enables wrap and lets the table grow
    its row height to fit. Header row is skipped by default so its bold
    ``TableStyle`` styling still applies.
    """
    out = []
    for i, row in enumerate(rows):
        new = list(row)
        for c in col_indexes:
            if skip_header and i == 0:
                continue
            cell = new[c]
            if isinstance(cell, str):
                new[c] = Paragraph(cell, S["Body"])
        out.append(new)
    return out


# --- Tender PDF ------------------------------------------------------------


def build_tender_pdf(out_path: Path) -> None:
    story: list = []

    # Cover
    story.append(Paragraph(TENDER_ISSUER, S["Title"]))
    story.append(Paragraph("(A Demonstration Entity for Procurement Process Automation)", S["Center"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("TENDER DOCUMENT", S["Title"]))
    story.append(Spacer(1, 12))

    cover_meta = [
        ["Tender Number", TENDER_NUMBER],
        ["Tender Subject", TENDER_NAME],
        ["Issuing Office", "Procurement Division, " + TENDER_LOCATION],
        ["Tender Floated Date", TENDER_FLOATED_DATE.strftime("%d-%b-%Y")],
        ["Bid Due Date", TENDER_DUE_DATE.strftime("%d-%b-%Y, 15:00 hrs IST")],
        ["Mode of Submission", "Two-cover system (Technical + Financial) via portal"],
        ["Estimated Annual Contract Value", "Rs. 240.00 Lakhs (indicative)"],
        ["Earnest Money Deposit (EMD)", "Rs. 4.80 Lakhs"],
        ["Contract Duration", "Two (2) years, extendable by one (1) year on satisfactory performance"],
    ]
    t = Table(_wrap_col(cover_meta, [1], skip_header=False), colWidths=[60 * mm, 110 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t)
    story.append(PageBreak())

    # PQC
    story.append(Paragraph("SECTION 1 — PRE-QUALIFICATION CRITERIA (PQC)", S["Heading"]))
    story.append(
        Paragraph(
            "Bidders are required to satisfy each of the following pre-qualification "
            "criteria. Bids that do not satisfy any one of the mandatory criteria will "
            "be rejected at the technical evaluation stage without further consideration.",
            S["Body"],
        )
    )

    pqc_items = [
        (
            "PQC-1 (Financial)",
            f"The bidder shall have an average annual turnover of not less than "
            f"Rs. {PQC_TURNOVER_THRESHOLD:.0f} Lakhs over the most recent three (3) "
            f"completed financial years (FY 2023-24, FY 2022-23, FY 2021-22). For "
            f"bidders registered as Micro or Small Enterprises (MSEs) under the MSMED "
            f"Act 2006 and supported by valid Udyam registration, a relaxed threshold "
            f"of Rs. {PQC_TURNOVER_MSME:.0f} Lakhs (15% relaxation) shall apply. "
            f"Substantiating documents: audited financial statements for the said "
            f"three financial years, signed by a practising Chartered Accountant.",
        ),
        (
            "PQC-2 (Technical — Similar Works)",
            f"The bidder shall have successfully executed at least one (1) similar "
            f"contract for housekeeping / sanitation / facility-cleaning services of "
            f"value not less than Rs. {PQC_SIMILAR_WORK_THRESHOLD:.0f} Lakhs during "
            f"the last seven (7) years from the date of bid submission. For MSE "
            f"bidders the relaxed threshold shall be Rs. {PQC_SIMILAR_WORK_MSME:.0f} "
            f"Lakhs. Substantiating documents: signed copy of the purchase order / "
            f"work order for the similar work and the corresponding work-completion "
            f"certificate issued by the buyer.",
        ),
        (
            "PQC-3 (Document)",
            "The bidder shall submit a self-attested copy of its Permanent Account "
            "Number (PAN) card. Mandatory.",
        ),
        (
            "PQC-4 (Document)",
            "The bidder shall submit a self-attested copy of its current Goods and "
            "Services Tax (GST) registration certificate (Form GST REG-06). Mandatory.",
        ),
        (
            "PQC-5 (Document — Conditional)",
            "Bidders claiming MSE relaxations under PQC-1 and/or PQC-2 shall submit a "
            "self-attested copy of their Udyam registration certificate. Mandatory if "
            "claiming relaxation; not applicable otherwise.",
        ),
        (
            "PQC-6 (Document)",
            "The bidder shall submit, on its own letterhead, a signed declaration "
            "confirming that the bidder has not been blacklisted, debarred, or banned "
            "by any Central or State Government department, public sector undertaking, "
            "or any other organisation as on the date of bid submission. Mandatory.",
        ),
        (
            "PQC-7 (Document)",
            "The bidder shall submit a duly completed and signed Bidder Response Form "
            "as per the format at Annexure B. Mandatory.",
        ),
    ]
    for title, body in pqc_items:
        story.append(Paragraph(f"<b>{title}.</b> {body}", S["Body"]))
        story.append(Spacer(1, 4))
    story.append(PageBreak())

    # Scope of Work
    story.append(Paragraph("SECTION 2 — SCOPE OF WORK", S["Heading"]))
    story.append(
        Paragraph(
            "The successful bidder shall provide comprehensive housekeeping and "
            "sanitation services across all designated zones of the Demo Industrial "
            "Facility, covering production halls, administrative office blocks, "
            "canteens, restrooms, common corridors, internal roadways, parking "
            "areas, and landscaped gardens. The line-item scope is set out below.",
            S["Body"],
        )
    )
    sow = [
        "Daily sweeping and mopping of all production-area floors (~12,500 sq.m).",
        "Daily cleaning and disinfection of administrative office floors and corridors (~3,800 sq.m).",
        "Daily restroom cleaning, refilling of consumables, and chemical sanitization at all designated facilities.",
        "Twice-weekly deep cleaning of canteen and pantry areas including grease-trap upkeep.",
        "Daily waste collection from designated bins and segregation into wet, dry, and hazardous streams.",
        "Weekly disposal of segregated waste through approved municipal channels with proof-of-disposal records.",
        "Daily cleaning of common-area glass surfaces, doors, and partitions.",
        "Twice-weekly polishing of stainless-steel fittings, railings, and door handles in common areas.",
        "Daily upkeep of designated smoking and tea-break zones.",
        "Monthly pest-control treatment of all internal premises (rats, cockroaches, mosquitoes, ants).",
        "Quarterly fumigation of food-handling areas with certified chemicals.",
        "Daily watering, weeding, and trimming of landscaped lawns and ornamental garden beds.",
        "Weekly hedge trimming and seasonal pruning of ornamental plants and trees on the premises.",
        "Daily sweeping of internal roadways, parking areas, and walkways (~7,200 sq.m).",
        "Twice-weekly cleaning of designated drainage channels and storm-water inlets.",
        "Daily upkeep of pathway lighting fixtures including cleaning of glass covers and reflectors.",
        "Monthly cleaning of overhead water tanks accompanied by independent water-quality test reports.",
        "Daily attendance and shift-handover register maintenance for all deployed personnel.",
        "Provision of all consumables (cleaning agents, mops, brooms, garbage bags) within scope at no additional cost.",
        "Provision and replenishment of restroom supplies (hand soap, paper towels, sanitary disposal bags).",
    ]
    sow_data = [["S.No.", "Activity"]] + [[str(i + 1), s] for i, s in enumerate(sow)]
    t = Table(_wrap_col(sow_data, [1]), colWidths=[15 * mm, 155 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
            ]
        )
    )
    story.append(t)
    story.append(PageBreak())

    # Manpower table
    story.append(Paragraph("SECTION 3 — MANPOWER REQUIREMENT", S["Heading"]))
    story.append(
        Paragraph(
            "Indicative shift-wise manpower deployment as below. Bidder may propose "
            "marginal adjustments with justification, subject to acceptance by the "
            "issuing authority.",
            S["Body"],
        )
    )
    mp_data = [
        ["Category", "Day Shift\n(0700-1500)", "Evening Shift\n(1500-2300)", "Night Shift\n(2300-0700)", "Total"],
        ["Supervisor", "2", "1", "1", "4"],
        ["Skilled (Gardener / Pest Control Op.)", "4", "0", "0", "4"],
        ["Semi-Skilled (Cleaner-Sanitation Tech)", "12", "6", "4", "22"],
        ["Unskilled (General Helper)", "18", "8", "6", "32"],
        ["TOTAL", "36", "15", "11", "62"],
    ]
    t = Table(mp_data, colWidths=[60 * mm, 30 * mm, 30 * mm, 30 * mm, 20 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.lightgrey),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            "Indicative Minimum Wages (Reference Only — Bidder Must Comply With Statute)",
            S["Heading"],
        )
    )
    wages_data = [
        ["Category", "Monthly Wage (Rs.)", "Annual Wage (Rs.)"],
        ["Supervisor", "22,500", "2,70,000"],
        ["Skilled", "18,800", "2,25,600"],
        ["Semi-Skilled", "16,200", "1,94,400"],
        ["Unskilled", "14,500", "1,74,000"],
    ]
    t = Table(wages_data, colWidths=[60 * mm, 50 * mm, 50 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    story.append(t)
    story.append(PageBreak())

    # Special conditions
    story.append(Paragraph("SECTION 4 — SPECIAL CONDITIONS", S["Heading"]))
    sc = [
        (
            "PPE",
            "The bidder shall provide industry-grade Personal Protective Equipment "
            "(uniforms, hand gloves, face masks, safety footwear, hair caps) to all "
            "deployed personnel at the bidder's cost; replacement at not less than "
            "half-yearly intervals.",
        ),
        (
            "EPF / ESI Compliance",
            "The bidder shall comply with the Employees' Provident Fund and "
            "Miscellaneous Provisions Act 1952 and the Employees' State Insurance "
            "Act 1948. Monthly remittance challans shall accompany every monthly invoice.",
        ),
        (
            "Annual & Statutory Leave",
            "Deployed personnel shall be entitled to paid leave per applicable "
            "statutes. The bidder is responsible for ensuring uninterrupted shift "
            "cover during such leave; no additional charge shall be admissible.",
        ),
        (
            "Supervisor Qualifications",
            "Supervisors deployed under this contract shall hold a minimum graduate-"
            "level qualification and have at least three (3) years of relevant "
            "supervisory experience in housekeeping or facility-management contracts.",
        ),
        (
            "Training",
            "The bidder shall conduct quarterly refresher training on hygiene "
            "protocols, chemical handling, and emergency response. Training records "
            "(attendance + content) shall be made available for audit on request.",
        ),
        (
            "Background Verification",
            "Police verification of all deployed personnel shall be completed by "
            "the bidder prior to deployment. Copies of verification reports shall "
            "be furnished within seven (7) days of deployment.",
        ),
        (
            "Liquidated Damages",
            "In the event of significant non-performance, liquidated damages of "
            "0.5% of the monthly contract value per day shall be levied, capped at "
            "10% of the monthly contract value.",
        ),
        (
            "Subcontracting",
            "Subcontracting of any portion of the awarded scope is not permitted "
            "without the prior written approval of the issuing authority.",
        ),
    ]
    for title, body in sc:
        story.append(Paragraph(f"<b>{title}.</b> {body}", S["Body"]))
        story.append(Spacer(1, 4))
    story.append(PageBreak())

    # Annexures + signature
    story.append(Paragraph("SECTION 5 — ANNEXURES", S["Heading"]))
    story.append(Paragraph("&bull; Annexure A: Minimum Wages Calculation Table (refer Section 3)", S["Body"]))
    story.append(Paragraph("&bull; Annexure B: Bidder Response Form (template attached)", S["Body"]))
    story.append(Paragraph("&bull; Annexure C: Blacklisting Declaration Template", S["Body"]))
    story.append(Spacer(1, 24))

    story.append(Paragraph("For and on behalf of " + TENDER_ISSUER, S["Body"]))
    story.append(Spacer(1, 24))
    story.append(Paragraph("Sd/-", S["Body"]))
    story.append(Paragraph("Mr. Vikram S. Athreya", S["Body"]))
    story.append(Paragraph("Senior Manager (Procurement)", S["Body"]))
    story.append(
        Paragraph(
            f"Place: {TENDER_LOCATION} &nbsp;&nbsp; "
            f"Date: {TENDER_FLOATED_DATE.strftime('%d-%b-%Y')}",
            S["Body"],
        )
    )

    _doc(out_path, story)


# --- Vendor PDF builders ---------------------------------------------------


def build_balance_sheet(v: VendorProfile, fy_end_year: int, out_path: Path) -> None:
    fy_label = f"FY{fy_end_year - 1}-{fy_end_year % 100:02d}"
    fy_end_str = f"31st March {fy_end_year}"
    prev_fy_end_str = f"31st March {fy_end_year - 1}"

    if fy_end_year == 2024:
        cur, prev = v.turnover_fy_23_24, v.turnover_fy_22_23
    elif fy_end_year == 2023:
        cur, prev = v.turnover_fy_22_23, v.turnover_fy_21_22
    elif fy_end_year == 2022:
        cur, prev = v.turnover_fy_21_22, v.turnover_fy_21_22 * 0.85
    else:
        raise ValueError(f"Unsupported FY end: {fy_end_year}")

    cur_inr = cur * 1e5
    prev_inr = prev * 1e5

    story: list = []
    story.append(Paragraph(v.name, S["Title"]))
    story.append(Paragraph(v.address, S["Center"]))
    story.append(Paragraph(f"PAN: {v.pan} &nbsp;|&nbsp; GSTIN: {v.gstin}", S["Center"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"AUDITED BALANCE SHEET AS AT {fy_end_str}", S["Heading"]))
    story.append(
        Paragraph(
            f"We have audited the accompanying financial statements of {v.name} for "
            f"the year ended {fy_end_str}, which comprise the Balance Sheet, the "
            f"Statement of Profit and Loss, and a summary of significant accounting "
            f"policies and other explanatory information. In our opinion the financial "
            f"statements give a true and fair view in conformity with the accounting "
            f"principles generally accepted in India.",
            S["Body"],
        )
    )
    story.append(Spacer(1, 8))

    def fmt(n: float) -> str:
        return f"{n:,.2f}"

    rev_data = [
        ["Particulars", f"Year Ended\n{fy_end_str}\n(Amount in Rs.)", f"Year Ended\n{prev_fy_end_str}\n(Amount in Rs.)"],
        ["Revenue from Operations", fmt(cur_inr * 0.95), fmt(prev_inr * 0.95)],
        ["Other Income", fmt(cur_inr * 0.05), fmt(prev_inr * 0.05)],
        ["Total Revenue (Turnover)", fmt(cur_inr), fmt(prev_inr)],
        ["Total Expenses", fmt(cur_inr * 0.88), fmt(prev_inr * 0.89)],
        ["Profit Before Tax", fmt(cur_inr * 0.12), fmt(prev_inr * 0.11)],
        ["Tax Expense", fmt(cur_inr * 0.03), fmt(prev_inr * 0.028)],
        ["Net Profit", fmt(cur_inr * 0.09), fmt(prev_inr * 0.082)],
    ]
    t = Table(rev_data, colWidths=[80 * mm, 50 * mm, 50 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 3), (0, 3), "Helvetica-Bold"),
                ("FONTNAME", (0, 7), (0, 7), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            f"<b>Annual Turnover for {fy_label}: Rs. {cur:,.2f} Lakhs</b>"
            + (" (MSME)" if v.is_msme else ""),
            S["Body"],
        )
    )
    story.append(Spacer(1, 12))

    story.append(Paragraph("For " + v.auditor_firm, S["Body"]))
    story.append(Paragraph("Chartered Accountants", S["Body"]))
    story.append(Paragraph(f"Firm Registration Number (FRN): {v.auditor_frn}", S["Body"]))
    story.append(Spacer(1, 16))
    story.append(Paragraph("Sd/-", S["Body"]))
    story.append(Paragraph("(Partner)", S["Body"]))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            f"Place: {v.city} &nbsp;&nbsp; Date: 30 June {fy_end_year}",
            S["Body"],
        )
    )

    _doc(out_path, story)


def build_purchase_order(v: VendorProfile, out_path: Path) -> None:
    story: list = []
    story.append(Paragraph(v.similar_work_buyer, S["Title"]))
    story.append(Paragraph("(Purchase Order)", S["Center"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("PURCHASE ORDER", S["Heading"]))

    po_meta = [
        ["PO Number", v.similar_work_po_number],
        ["PO Date", v.similar_work_po_date.strftime("%d-%b-%Y")],
        ["Vendor", v.name],
        ["Vendor Address", v.address],
        ["Vendor PAN", v.pan],
        ["Vendor GSTIN", v.gstin],
        ["Subject", "Provision of Housekeeping & Sanitation Services"],
        [
            "Period of Contract",
            f"{v.similar_work_po_date.strftime('%d-%b-%Y')} to "
            f"{v.similar_work_completion_date.strftime('%d-%b-%Y')}",
        ],
        ["PO Value (Total)", f"Rs. {v.similar_work_po_value:,.2f} Lakhs"],
    ]
    t = Table(_wrap_col(po_meta, [1], skip_header=False), colWidths=[55 * mm, 115 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>Scope (summary):</b> Daily housekeeping and sanitation services across "
            "the buyer's industrial premises, including office blocks, restrooms, "
            "canteens, common corridors, and landscaped gardens. Manpower, supervisory, "
            "and consumables included. Detailed scope as per the contract attached.",
            S["Body"],
        )
    )
    story.append(Spacer(1, 16))
    story.append(Paragraph("For " + v.similar_work_buyer, S["Body"]))
    story.append(Spacer(1, 24))
    story.append(Paragraph("Sd/-", S["Body"]))
    story.append(Paragraph("Authorized Signatory", S["Body"]))
    story.append(Paragraph("(Procurement Department)", S["Body"]))

    _doc(out_path, story)


def build_completion_cert(v: VendorProfile, out_path: Path) -> None:
    story: list = []
    story.append(Paragraph(v.similar_work_buyer, S["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("WORK COMPLETION CERTIFICATE", S["Heading"]))
    story.append(Paragraph(f"Reference: {v.similar_work_po_number}", S["Body"]))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"This is to certify that <b>{v.name}</b>, having its registered office at "
            f"{v.address}, was awarded a contract for housekeeping and sanitation "
            f"services vide Purchase Order No. {v.similar_work_po_number} dated "
            f"{v.similar_work_po_date.strftime('%d-%b-%Y')}, for a total contract "
            f"value of <b>Rs. {v.similar_work_po_value:,.2f} Lakhs</b>, executed "
            f"during the period {v.similar_work_po_date.strftime('%d-%b-%Y')} to "
            f"{v.similar_work_completion_date.strftime('%d-%b-%Y')}.",
            S["Body"],
        )
    )
    story.append(
        Paragraph(
            "The contractor has satisfactorily completed all contractual obligations. "
            "Their conduct of the contract was found to be professional and in "
            "accordance with the agreed scope. No outstanding disputes or recovery "
            "actions are pending against the contractor in respect of this contract "
            "as on the date of this certificate.",
            S["Body"],
        )
    )
    story.append(Spacer(1, 24))
    story.append(Paragraph("For " + v.similar_work_buyer, S["Body"]))
    story.append(Spacer(1, 24))
    story.append(Paragraph("Sd/-", S["Body"]))
    story.append(Paragraph("Head — Facility Operations", S["Body"]))
    story.append(
        Paragraph(
            f"Date: {v.similar_work_completion_date.strftime('%d-%b-%Y')}",
            S["Body"],
        )
    )

    _doc(out_path, story)


def build_pan_card(v: VendorProfile, out_path: Path) -> None:
    story: list = []
    story.append(Paragraph("INCOME TAX DEPARTMENT", S["Title"]))
    story.append(Paragraph("GOVERNMENT OF INDIA", S["Center"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("PERMANENT ACCOUNT NUMBER (PAN)", S["Heading"]))

    is_individual = v.slug == "raghavendra_maintenance_works"
    fields = [
        ["PAN", v.pan],
        ["Name", v.proprietor_name if is_individual else v.name],
    ]
    if is_individual:
        fields.append(["Father's Name", "Mr. Ramesh Patel"])
        fields.append(["Date of Birth", date(1972, 8, 14).strftime("%d-%b-%Y")])
    else:
        fields.append(["Date of Incorporation", v.incorporation_date.strftime("%d-%b-%Y")])

    t = Table(fields, colWidths=[55 * mm, 115 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 24))
    story.append(Paragraph("(Computer-generated certificate. No signature required.)", S["Small"]))

    _doc(out_path, story)


def build_gst_cert(v: VendorProfile, out_path: Path) -> None:
    story: list = []
    story.append(Paragraph("FORM GST REG-06", S["Title"]))
    story.append(Paragraph("[See Rule 10(1)]", S["Center"]))
    story.append(Paragraph("CERTIFICATE OF REGISTRATION", S["Heading"]))

    if v.slug == "raghavendra_maintenance_works":
        constitution = "Sole Proprietorship"
    elif "PVT LTD" in v.name:
        constitution = "Private Limited Company"
    else:
        constitution = "Partnership Firm"

    fields = [
        ["GSTIN", v.gstin],
        ["Legal Name", v.name],
        ["Trade Name", v.name],
        ["Constitution of Business", constitution],
        ["Address of Principal Place of Business", v.address],
        ["Date of Liability", v.incorporation_date.strftime("%d-%b-%Y")],
        [
            "Date of Registration",
            v.incorporation_date.replace(day=min(28, v.incorporation_date.day)).strftime("%d-%b-%Y"),
        ],
        ["Particulars of Approving Authority", "Asst. Commissioner, Range-XII, " + v.state],
    ]
    t = Table(_wrap_col(fields, [1], skip_header=False), colWidths=[60 * mm, 110 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 24))
    story.append(Paragraph("(Digitally signed by the GST authority. No physical signature required.)", S["Small"]))

    _doc(out_path, story)


def build_udyam(v: VendorProfile, out_path: Path) -> None:
    assert v.is_msme and v.udyam is not None, "Udyam certificate only for MSME vendors"
    story: list = []
    story.append(Paragraph("Government of India", S["Title"]))
    story.append(Paragraph("Ministry of Micro, Small and Medium Enterprises", S["Center"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("UDYAM REGISTRATION CERTIFICATE", S["Heading"]))

    fields = [
        ["Udyam Registration Number", v.udyam],
        ["Name of Enterprise", v.name],
        ["Type of Enterprise", "Small Enterprise"],
        [
            "Major Activity (NIC Code 81210)",
            "Building cleaning and facility-support services",
        ],
        ["Address", v.address],
        ["State", v.state],
        [
            "Date of Registration",
            v.incorporation_date.replace(year=v.incorporation_date.year + 3).strftime("%d-%b-%Y"),
        ],
    ]
    t = Table(_wrap_col(fields, [1], skip_header=False), colWidths=[70 * mm, 100 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 16))
    story.append(
        Paragraph(
            "This is to certify that the above-named enterprise is registered under "
            "the Udyam Registration system as per the MSMED Act, 2006. This "
            "registration is valid as on the date of issue and is subject to "
            "periodic re-verification.",
            S["Body"],
        )
    )

    _doc(out_path, story)


def build_blacklist_decl(v: VendorProfile, out_path: Path) -> None:
    story: list = []
    story.append(Paragraph(v.name, S["Title"]))
    story.append(Paragraph(v.address, S["Center"]))
    story.append(Paragraph(f"PAN: {v.pan} &nbsp;|&nbsp; GSTIN: {v.gstin}", S["Center"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("DECLARATION OF NON-BLACKLISTING", S["Heading"]))
    story.append(
        Paragraph(
            f"To,<br/>The Procurement Officer,<br/>{TENDER_ISSUER},<br/>{TENDER_LOCATION}",
            S["Body"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"<b>Subject:</b> Tender No. {TENDER_NUMBER} — {TENDER_NAME}",
            S["Body"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"I, {v.proprietor_name}, the duly authorized signatory of "
            f"<b>{v.name}</b>, do hereby solemnly declare that the said firm has NOT "
            f"been blacklisted, debarred, or banned from participating in tenders by "
            f"any Central or State Government department, public sector undertaking, "
            f"municipal authority, autonomous body, or any other organisation as on "
            f"the date of this declaration.",
            S["Body"],
        )
    )
    story.append(
        Paragraph(
            "I further declare that no inquiry or disciplinary proceeding leading to "
            "such blacklisting is pending against the firm. I understand that any "
            "false statement herein shall be liable for rejection of the bid and "
            "appropriate legal action.",
            S["Body"],
        )
    )
    story.append(Spacer(1, 24))
    story.append(Paragraph("Sd/-", S["Body"]))
    story.append(Paragraph(v.proprietor_name, S["Body"]))
    story.append(Paragraph("Authorized Signatory", S["Body"]))
    story.append(
        Paragraph(
            f"Place: {v.city} &nbsp;&nbsp; "
            f"Date: {TENDER_FLOATED_DATE.strftime('%d-%b-%Y')}",
            S["Body"],
        )
    )

    _doc(out_path, story)


def build_bidder_response_form(v: VendorProfile, out_path: Path) -> None:
    story: list = []
    story.append(Paragraph(v.name, S["Title"]))
    story.append(Paragraph(v.address, S["Center"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("BIDDER RESPONSE FORM", S["Heading"]))
    story.append(Paragraph(f"Tender No.: {TENDER_NUMBER}", S["Body"]))
    story.append(Paragraph(f"Tender Subject: {TENDER_NAME}", S["Body"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("A. Compliance with Pre-Qualification Criteria", S["Heading"]))

    avg_turn = (v.turnover_fy_23_24 + v.turnover_fy_22_23 + v.turnover_fy_21_22) / 3
    sw_threshold = PQC_SIMILAR_WORK_MSME if v.is_msme else PQC_SIMILAR_WORK_THRESHOLD

    pqc_compliance = [
        ["PQC", "Status", "Remarks / Reference"],
        [
            "PQC-1 (Turnover)",
            "Complied",
            f"3-yr avg turnover Rs. {avg_turn:.2f} Lakhs. Audited B/S enclosed.",
        ],
        [
            "PQC-2 (Similar Works)",
            "Complied" if v.similar_work_po_value >= sw_threshold else "Complied (claimed)",
            f"PO value Rs. {v.similar_work_po_value:.2f} Lakhs. PO + completion cert enclosed.",
        ],
        ["PQC-3 (PAN)", "Complied", f"PAN: {v.pan}. Self-attested copy enclosed."],
        ["PQC-4 (GST)", "Complied", f"GSTIN: {v.gstin}. Form REG-06 enclosed."],
        [
            "PQC-5 (Udyam — if MSE)",
            "Complied" if v.is_msme else "Not Applicable",
            f"Udyam: {v.udyam}" if v.is_msme else "Bidder is not registered as MSE.",
        ],
        [
            "PQC-6 (Blacklisting Decl.)",
            "Not Enclosed" if v.failure_mode == "missing_blacklist_decl" else "Complied",
            "Declaration on letterhead enclosed."
            if v.failure_mode != "missing_blacklist_decl"
            else "(Declaration to follow under separate cover.)",
        ],
        ["PQC-7 (This Form)", "Complied", "Submitted herewith."],
    ]
    t = Table(_wrap_col(pqc_compliance, [2]), colWidths=[45 * mm, 30 * mm, 95 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 8))

    story.append(Paragraph("B. List of Documents Enclosed", S["Heading"]))
    docs = [
        "Audited Balance Sheet for FY 2023-24",
        "Audited Balance Sheet for FY 2022-23",
        "Audited Balance Sheet for FY 2021-22",
        "Purchase Order copy — similar work executed",
        "Work Completion Certificate — similar work",
        "Self-attested copy of PAN",
        "Self-attested copy of GST Registration Certificate (Form REG-06)",
    ]
    if v.is_msme:
        docs.append("Self-attested copy of Udyam Registration Certificate")
    if v.failure_mode != "missing_blacklist_decl":
        docs.append("Declaration of Non-Blacklisting on company letterhead")
    docs.append("This Bidder Response Form, duly signed")

    for i, d in enumerate(docs, start=1):
        story.append(Paragraph(f"{i}. {d}", S["Body"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph("C. Acceptance Declaration", S["Heading"]))
    story.append(
        Paragraph(
            "We accept all terms and conditions, scope of work, special conditions, "
            "and annexures of the said tender without any deviation or qualification "
            "save as expressly noted in our financial bid.",
            S["Body"],
        )
    )
    story.append(Spacer(1, 16))
    story.append(Paragraph("Sd/-", S["Body"]))
    story.append(Paragraph(v.proprietor_name, S["Body"]))
    story.append(Paragraph("Authorized Signatory", S["Body"]))
    story.append(
        Paragraph(
            f"Place: {v.city} &nbsp;&nbsp; "
            f"Date: {TENDER_FLOATED_DATE.strftime('%d-%b-%Y')}",
            S["Body"],
        )
    )

    _doc(out_path, story)


# --- Main ------------------------------------------------------------------


def main() -> None:
    print("Output paths:")
    print(f"  Tender:  {TENDER_OUT}")
    print(f"  Vendors: {VENDORS_OUT}")
    print()

    if VENDORS_OUT.exists():
        shutil.rmtree(VENDORS_OUT)
    VENDORS_OUT.mkdir(parents=True, exist_ok=True)
    TENDER_OUT.parent.mkdir(parents=True, exist_ok=True)

    print("Building tender PDF...")
    build_tender_pdf(TENDER_OUT)
    print(f"  -> {TENDER_OUT.relative_to(REPO_ROOT)}")
    print()

    for v in VENDORS:
        vdir = VENDORS_OUT / v.slug
        vdir.mkdir(parents=True, exist_ok=True)
        print(f"Building docs for {v.name} (MSME={v.is_msme}, accept={v.is_accept})...")
        build_balance_sheet(v, 2024, vdir / "audited_balance_sheet_FY2023-24.pdf")
        build_balance_sheet(v, 2023, vdir / "audited_balance_sheet_FY2022-23.pdf")
        build_balance_sheet(v, 2022, vdir / "audited_balance_sheet_FY2021-22.pdf")
        build_purchase_order(v, vdir / "purchase_order_similar_work_1.pdf")
        build_completion_cert(v, vdir / "work_completion_certificate_1.pdf")
        build_pan_card(v, vdir / "pan_card.pdf")
        build_gst_cert(v, vdir / "gst_certificate.pdf")
        if v.is_msme:
            build_udyam(v, vdir / "udyam_registration.pdf")
        if v.failure_mode != "missing_blacklist_decl":
            build_blacklist_decl(v, vdir / "blacklist_declaration.pdf")
        build_bidder_response_form(v, vdir / "bidder_response_form.pdf")
        n = len(list(vdir.glob("*.pdf")))
        print(f"  -> {vdir.relative_to(REPO_ROOT)} ({n} PDFs)")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
