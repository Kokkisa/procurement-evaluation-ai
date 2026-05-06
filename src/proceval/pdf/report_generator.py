"""Final PDF generation — formal PSU technical-evaluation layout via ReportLab.

Sections in order (per spec §10):
1. Header band (tender + iteration + generation date)
2. Tender metadata block (compact 2-column)
3. Participating-vendors list (numbered, MSME tagged)
4. Technical evaluation matrix (criteria x vendors, colour-coded cells,
   OVERALL REMARKS row)
5. Commercial evaluation matrix (same shape, only if non-empty)
6. Lifecycle audit log appendix (chronological table)
7. Signature blocks (Preparer / Reviewer / Approver)

Page is A4 landscape — 5+ vendor columns need horizontal real estate.

Cell colour coding mirrors the Streamlit matrix (ui/styles.py CSS):
    pass    light green   #d4edda      OVERALL row pass dark green #1e7e34
    fail    light red     #f8d7da      OVERALL row fail dark red   #b21f2d
    partial light yellow  #fff3cd
    n/a     light grey    #e9ecef
    headers dark navy     #1f3349
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from uuid import UUID

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
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

from ..schemas.audit import AuditEvent
from ..schemas.evaluation import CommercialEvaluation, TechnicalEvaluation
from ..schemas.tender import EvalCriterion, TenderMetadata
from ..schemas.vendor import VendorEvaluation

# --- palette ---------------------------------------------------------------

C_HEADER_BG = HexColor("#1f3349")
C_HEADER_FG = HexColor("#ffffff")
C_PASS = HexColor("#d4edda")
C_FAIL = HexColor("#f8d7da")
C_PARTIAL = HexColor("#fff3cd")
C_NA = HexColor("#e9ecef")
C_OVERALL_BG = HexColor("#1f3349")
C_OVERALL_PASS = HexColor("#1e7e34")
C_OVERALL_FAIL = HexColor("#b21f2d")
C_GRID = HexColor("#444444")
C_BORDER = HexColor("#cccccc")

# --- styles ----------------------------------------------------------------

_base = getSampleStyleSheet()
S = {
    "Title": ParagraphStyle(
        "Title",
        parent=_base["Title"],
        fontSize=14,
        alignment=1,
        textColor=C_HEADER_FG,
        spaceAfter=2,
    ),
    "TitleSub": ParagraphStyle(
        "TitleSub",
        parent=_base["Normal"],
        fontSize=10,
        alignment=1,
        textColor=C_HEADER_FG,
        spaceAfter=2,
    ),
    "TitleMeta": ParagraphStyle(
        "TitleMeta",
        parent=_base["Normal"],
        fontSize=8,
        alignment=1,
        textColor=C_HEADER_FG,
    ),
    "Section": ParagraphStyle(
        "Section",
        parent=_base["Heading2"],
        fontSize=11,
        spaceBefore=10,
        spaceAfter=4,
        textColor=C_HEADER_BG,
    ),
    "Body": ParagraphStyle(
        "Body",
        parent=_base["BodyText"],
        fontSize=8,
        leading=10,
        spaceAfter=2,
    ),
    "Cell": ParagraphStyle(
        "Cell",
        parent=_base["BodyText"],
        fontSize=7.5,
        leading=9,
    ),
    "CellMono": ParagraphStyle(
        "CellMono",
        parent=_base["BodyText"],
        fontSize=7.5,
        leading=9,
        fontName="Courier-Bold",
    ),
    "CellSmall": ParagraphStyle(
        "CellSmall",
        parent=_base["BodyText"],
        fontSize=6.5,
        leading=8,
        textColor=HexColor("#444444"),
    ),
    "OverallCell": ParagraphStyle(
        "OverallCell",
        parent=_base["BodyText"],
        fontSize=8,
        leading=10,
        textColor=C_HEADER_FG,
    ),
    "OverallVerdict": ParagraphStyle(
        "OverallVerdict",
        parent=_base["BodyText"],
        fontSize=9,
        leading=11,
        fontName="Helvetica-Bold",
        textColor=C_HEADER_FG,
    ),
    "VendorHead": ParagraphStyle(
        "VendorHead",
        parent=_base["BodyText"],
        fontSize=8,
        leading=10,
        alignment=1,
        fontName="Helvetica-Bold",
        textColor=C_HEADER_FG,
    ),
    "ColHead": ParagraphStyle(
        "ColHead",
        parent=_base["BodyText"],
        fontSize=8,
        leading=10,
        fontName="Helvetica-Bold",
        textColor=C_HEADER_FG,
    ),
    "AuditCell": ParagraphStyle(
        "AuditCell",
        parent=_base["BodyText"],
        fontSize=7,
        leading=9,
    ),
}


# --- public API ------------------------------------------------------------


def generate_final_pdf(
    *,
    eval_id: UUID,
    iteration: int,
    metadata: TenderMetadata,
    technical: TechnicalEvaluation,
    commercial: Optional[CommercialEvaluation] = None,
    audit_events: Iterable[AuditEvent] = (),
    preparer_id: str = "",
    reviewer_id: Optional[str] = None,
    approver_id: Optional[str] = None,
    output_dir: Path,
    generated_at: Optional[datetime] = None,
) -> Path:
    """Write the final PDF and return its path.

    Filename: ``<tender_number_safe>_iter<N>_technical_evaluation.pdf``."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = metadata.tender_number.replace("/", "_").replace("\\", "_").replace(" ", "_")
    out = output_dir / f"{safe}_iter{iteration}_technical_evaluation.pdf"

    if generated_at is None:
        generated_at = datetime.now(timezone.utc)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Technical Evaluation - {metadata.tender_number}",
    )

    story: list = []
    story.extend(_header_band(metadata, iteration, generated_at))
    story.append(Spacer(1, 6))
    story.extend(_metadata_block(metadata))
    story.append(Spacer(1, 6))
    story.extend(_vendor_list(technical.vendor_evaluations))
    story.append(Spacer(1, 6))
    story.extend(
        _matrix_section(
            "TECHNICAL EVALUATION MATRIX",
            technical.rubric.technical_criteria,
            technical.vendor_evaluations,
            technical.summary_remarks,
        )
    )
    if commercial and commercial.rubric.commercial_criteria:
        story.append(PageBreak())
        story.extend(
            _matrix_section(
                "COMMERCIAL EVALUATION MATRIX",
                commercial.rubric.commercial_criteria,
                commercial.vendor_evaluations,
                summary=None,
            )
        )
    story.append(PageBreak())
    story.extend(_audit_section(audit_events))
    story.append(Spacer(1, 12))
    story.extend(_signature_blocks(preparer_id, reviewer_id, approver_id))

    doc.build(story)
    return out


# --- section builders ------------------------------------------------------


def _header_band(metadata: TenderMetadata, iteration: int, generated_at: datetime) -> list:
    inner = [
        [Paragraph("PROCUREMENT EVALUATION REPORT", S["Title"])],
        [
            Paragraph(
                f"<b>{_esc(metadata.tender_number)}</b> &nbsp;|&nbsp; {_esc(metadata.tender_name)}",
                S["TitleSub"],
            )
        ],
        [
            Paragraph(
                f"{_esc(metadata.issuing_organization)} &nbsp;|&nbsp; "
                f"Iteration {iteration} &nbsp;|&nbsp; "
                f"Generated {generated_at.strftime('%Y-%m-%d %H:%M %Z') or generated_at.isoformat()}",
                S["TitleMeta"],
            )
        ],
    ]
    t = Table(inner, colWidths=[270 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_HEADER_BG),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return [t]


def _metadata_block(metadata: TenderMetadata) -> list:
    rows = [
        [
            "Tender Floated Date",
            _fmt_date(metadata.tender_floated_date),
            "Issuing Office",
            _esc(metadata.location or "-"),
        ],
        [
            "Bid Due Date",
            _fmt_date(metadata.tender_due_date),
            "Tender Number",
            _esc(metadata.tender_number),
        ],
    ]
    wrapped = [[Paragraph(c, S["Body"]) if isinstance(c, str) else c for c in row] for row in rows]
    t = Table(wrapped, colWidths=[42 * mm, 90 * mm, 35 * mm, 105 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (0, -1), HexColor("#f0f0f0")),
                ("BACKGROUND", (2, 0), (2, -1), HexColor("#f0f0f0")),
                ("GRID", (0, 0), (-1, -1), 0.4, C_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return [t]


def _vendor_list(vendor_evaluations: list[VendorEvaluation]) -> list:
    items = [Paragraph("<b>Participating Vendors</b>", S["Section"])]
    if not vendor_evaluations:
        items.append(Paragraph("(no vendors)", S["Body"]))
        return items
    for i, ve in enumerate(vendor_evaluations, start=1):
        msme = " <b>[MSME]</b>" if ve.is_msme else ""
        items.append(Paragraph(f"{i}. {_esc(ve.vendor_name)}{msme}", S["Body"]))
    return items


def _matrix_section(
    heading: str,
    criteria: list[EvalCriterion],
    vendor_evaluations: list[VendorEvaluation],
    summary: Optional[str] = None,
) -> list:
    out: list = [Paragraph(f"<b>{_esc(heading)}</b>", S["Section"])]
    if summary:
        out.append(Paragraph(_esc(summary), S["Body"]))
    if not criteria or not vendor_evaluations:
        out.append(Paragraph("<i>(no rows)</i>", S["Body"]))
        return out

    n_vendors = len(vendor_evaluations)
    # Geometry: 12mm + 60mm + 60mm = 132mm fixed; remaining ~136mm split across vendors.
    fixed = 12 + 55 + 55
    avail = 273 - fixed
    vendor_w = max(20, avail / n_vendors)
    col_widths = [12 * mm, 55 * mm, 55 * mm] + [vendor_w * mm] * n_vendors

    # Header row
    header = [
        Paragraph("S.No.", S["ColHead"]),
        Paragraph("CRITERION", S["ColHead"]),
        Paragraph("REQUIREMENT", S["ColHead"]),
    ]
    for ve in vendor_evaluations:
        msme_tag = " <font size=6>[MSME]</font>" if ve.is_msme else ""
        header.append(Paragraph(_esc(ve.vendor_name) + msme_tag, S["VendorHead"]))

    rows = [header]

    cell_styles: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
        ("GRID", (0, 0), (-1, -1), 0.4, C_GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    for r, c in enumerate(criteria, start=1):
        row = [
            Paragraph(str(r), S["Cell"]),
            Paragraph(_esc(c.name), S["Cell"]),
            Paragraph(_format_requirement(c), S["Cell"]),
        ]
        for col_idx, ve in enumerate(vendor_evaluations):
            cell_eval = next((e for e in ve.criterion_evaluations if e.criterion_id == c.id), None)
            cell_para, bg = _format_cell(c, cell_eval)
            row.append(cell_para)
            cell_styles.append(("BACKGROUND", (3 + col_idx, r), (3 + col_idx, r), bg))
        rows.append(row)

    # OVERALL REMARKS row (combines first 3 columns)
    overall_row = [
        Paragraph("<b>OVERALL REMARKS</b>", S["OverallVerdict"]),
        "",
        "",
    ]
    overall_row_idx = len(rows)
    for col_idx, ve in enumerate(vendor_evaluations):
        verdict_text = ve.overall_verdict
        cell_para = Paragraph(
            f"<b>{verdict_text}</b><br/>{_esc(ve.overall_remarks)}",
            S["OverallCell"],
        )
        overall_row.append(cell_para)
        bg = C_OVERALL_PASS if verdict_text == "ACCEPTED" else C_OVERALL_FAIL
        cell_styles.append(
            ("BACKGROUND", (3 + col_idx, overall_row_idx), (3 + col_idx, overall_row_idx), bg)
        )
    rows.append(overall_row)
    cell_styles.extend(
        [
            ("BACKGROUND", (0, overall_row_idx), (2, overall_row_idx), C_OVERALL_BG),
            ("SPAN", (0, overall_row_idx), (2, overall_row_idx)),
            ("TEXTCOLOR", (0, overall_row_idx), (2, overall_row_idx), C_HEADER_FG),
            ("VALIGN", (0, overall_row_idx), (-1, overall_row_idx), "MIDDLE"),
        ]
    )

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(cell_styles))
    out.append(table)
    return out


def _audit_section(audit_events: Iterable[AuditEvent]) -> list:
    events = list(audit_events)
    out: list = [Paragraph("<b>LIFECYCLE AUDIT LOG</b>", S["Section"])]
    if not events:
        out.append(Paragraph("<i>(no audit events recorded)</i>", S["Body"]))
        return out

    header = [
        Paragraph("#", S["ColHead"]),
        Paragraph("WHEN (UTC)", S["ColHead"]),
        Paragraph("ACTION", S["ColHead"]),
        Paragraph("ROLE", S["ColHead"]),
        Paragraph("ACTOR", S["ColHead"]),
        Paragraph("NOTES", S["ColHead"]),
    ]
    rows = [header]
    for i, ev in enumerate(events, start=1):
        when = ev.occurred_at.strftime("%Y-%m-%d %H:%M:%S") if ev.occurred_at else "-"
        notes = ev.notes or ""
        if len(notes) > 200:
            notes = notes[:197] + "..."
        rows.append(
            [
                Paragraph(str(i), S["AuditCell"]),
                Paragraph(when, S["AuditCell"]),
                Paragraph(
                    f"<b>{_esc(ev.action.value if hasattr(ev.action, 'value') else str(ev.action))}</b>",
                    S["AuditCell"],
                ),
                Paragraph(
                    _esc(
                        ev.actor_role.value
                        if hasattr(ev.actor_role, "value")
                        else str(ev.actor_role)
                    ),
                    S["AuditCell"],
                ),
                Paragraph(_esc(ev.actor_id), S["AuditCell"]),
                Paragraph(_esc(notes), S["AuditCell"]),
            ]
        )
    table = Table(
        rows,
        colWidths=[10 * mm, 35 * mm, 50 * mm, 22 * mm, 30 * mm, 126 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), C_HEADER_BG),
                ("GRID", (0, 0), (-1, -1), 0.4, C_GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    out.append(table)
    return out


def _signature_blocks(
    preparer_id: str, reviewer_id: Optional[str], approver_id: Optional[str]
) -> list:
    labels = ["Prepared By", "Reviewed By", "Approved By"]
    names = [
        preparer_id or "(preparer)",
        reviewer_id or "(reviewer)",
        approver_id or "(approver)",
    ]

    rows = [
        [Paragraph(f"<b>{lbl}</b>", S["Body"]) for lbl in labels],
        [Paragraph(f"Name: {_esc(n)}", S["Body"]) for n in names],
        [Paragraph("Sd/-", S["Body"]) for _ in labels],
        ["", "", ""],  # blank row reserved for the wet signature
        [Paragraph("____________________", S["Body"]) for _ in labels],
        [Paragraph("Signature &amp; Date", S["Body"]) for _ in labels],
    ]
    t = Table(
        rows,
        colWidths=[91 * mm, 91 * mm, 91 * mm],
        rowHeights=[None, None, None, 32, None, None],
    )
    t.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.4, C_BORDER),
                ("LINEBEFORE", (1, 0), (1, -1), 0.4, C_BORDER),
                ("LINEBEFORE", (2, 0), (2, -1), 0.4, C_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f0f0f0")),
            ]
        )
    )
    return [Paragraph("<b>SIGNATURES</b>", S["Section"]), t]


# --- helpers ---------------------------------------------------------------


def _format_requirement(c: EvalCriterion) -> str:
    parts: list[str] = []
    if c.threshold_value is not None:
        chunk = f">= {c.threshold_value:.2f} L"
        if c.msme_relaxation_value is not None:
            chunk += f" (MSME {c.msme_relaxation_value:.2f} L)"
        if c.aggregation_rule:
            chunk += f", {c.aggregation_rule}"
        parts.append(chunk)
    if c.source_clause:
        parts.append(f"<font size=6>{_esc(c.source_clause)}</font>")
    if not parts:
        return "<i>document submission</i>"
    return "<br/>".join(parts)


def _format_cell(criterion: EvalCriterion, cell_eval) -> tuple[Paragraph, HexColor]:
    if cell_eval is None:
        return Paragraph("<i>no result</i>", S["Cell"]), C_NA

    verdict = (cell_eval.verdict or "").upper()
    reasoning = cell_eval.reasoning or ""
    short_reason = reasoning[:120] + ("..." if len(reasoning) > 120 else "")

    if verdict == "PROVIDED":
        return (
            Paragraph(
                f"<b>PROVIDED</b><br/><font size=6>{_esc(short_reason)}</font>",
                S["Cell"],
            ),
            C_PASS,
        )
    if verdict == "NOT_PROVIDED":
        return (
            Paragraph(
                f"<b>NOT PROVIDED</b><br/><font size=6>{_esc(short_reason)}</font>",
                S["Cell"],
            ),
            C_FAIL,
        )
    if verdict == "VALUE":
        bg = C_PASS if cell_eval.threshold_met else C_FAIL
        value = cell_eval.extracted_value or "(no value)"
        return (
            Paragraph(
                f"<font face='Courier-Bold' size=8>{_esc(value)}</font>"
                f"<br/><font size=6>{_esc(short_reason)}</font>",
                S["Cell"],
            ),
            bg,
        )
    if verdict == "PARTIAL":
        return (
            Paragraph(
                f"<b>PARTIAL</b><br/><font size=6>{_esc(short_reason)}</font>",
                S["Cell"],
            ),
            C_PARTIAL,
        )
    return (
        Paragraph(f"<b>{_esc(verdict)}</b>", S["Cell"]),
        C_PARTIAL,
    )


def _fmt_date(d) -> str:
    if d is None:
        return "-"
    if hasattr(d, "isoformat"):
        return d.isoformat()
    return str(d)


def _esc(s: object) -> str:
    """Minimal HTML escape for ReportLab Paragraph markup."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
