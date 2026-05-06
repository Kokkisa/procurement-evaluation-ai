"""Render the formal final PDF against synthetic data — no LLM, no FastAPI.

Useful for visual debugging of the generator and for sharing the deliverable
look during demo prep. Output goes to ``data/outputs/`` (gitignored).

Run:
    python scripts/render_pdf_preview.py
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from proceval.pdf import generate_final_pdf
from proceval.schemas.audit import ActorRole, AuditAction, AuditEvent
from proceval.schemas.evaluation import CommercialEvaluation, TechnicalEvaluation
from proceval.schemas.tender import (
    CriterionType,
    EvalCriterion,
    TenderMetadata,
    TenderRubric,
)
from proceval.schemas.vendor import CriterionEvaluation, VendorEvaluation

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "outputs"


def _crit(id_, name, type_, **kw):
    return EvalCriterion(id=id_, name=name, description=name + " requirement.", type=type_, **kw)


def _ev(cid, verdict, **k):
    return CriterionEvaluation(
        criterion_id=cid, verdict=verdict, reasoning=k.pop("reason", "ok"), confidence=0.95, **k
    )


def main() -> None:
    eval_id = uuid4()
    metadata = TenderMetadata(
        tender_number="DEMO/2026/HKP/001",
        tender_name="Housekeeping & Sanitation Services at Demo Industrial Facility",
        tender_floated_date=date(2026, 4, 10),
        tender_due_date=date(2026, 4, 30),
        issuing_organization="Demo Procurement Corporation Limited",
        location="Demo Industrial Facility, Pune",
    )

    technical_criteria = [
        _crit(
            "PQC_FIN_TURNOVER",
            "Average Annual Turnover",
            CriterionType.FINANCIAL,
            threshold_value=100.0,
            msme_relaxation_value=85.0,
            aggregation_rule="average",
            source_clause="PQC-1",
        ),
        _crit(
            "PQC_TECH_SIMILAR_WORK",
            "Similar Works Experience",
            CriterionType.TECHNICAL,
            threshold_value=100.0,
            msme_relaxation_value=85.0,
            aggregation_rule="single_max",
            source_clause="PQC-2",
        ),
        _crit("PQC_DOC_PAN", "PAN Card Submission", CriterionType.DOCUMENT, source_clause="PQC-3"),
        _crit("PQC_DOC_GST", "GST Registration", CriterionType.DOCUMENT, source_clause="PQC-4"),
        _crit(
            "PQC_DOC_UDYAM_MSME",
            "Udyam Registration",
            CriterionType.DOCUMENT,
            source_clause="PQC-5",
        ),
        _crit(
            "PQC_DOC_BLACKLIST_DECL",
            "Blacklisting Declaration",
            CriterionType.DOCUMENT,
            source_clause="PQC-6",
        ),
        _crit(
            "PQC_DOC_BIDDER_RESPONSE",
            "Bidder Response Form",
            CriterionType.DOCUMENT,
            source_clause="PQC-7",
        ),
    ]
    commercial_criteria = [
        _crit(
            "COMM_PPE",
            "Personal Protective Equipment",
            CriterionType.COMMERCIAL,
            source_clause="Section 4",
        ),
        _crit(
            "COMM_EPF_ESI",
            "EPF / ESI Compliance",
            CriterionType.COMMERCIAL,
            source_clause="Section 4",
        ),
    ]
    rubric = TenderRubric(
        metadata=metadata,
        technical_criteria=technical_criteria,
        commercial_criteria=commercial_criteria,
    )

    def _vendor(name, msme, accept, sw_value, sw_met, *, missing_blacklist=False):
        evs = []
        for c in technical_criteria:
            if c.id == "PQC_FIN_TURNOVER":
                evs.append(
                    _ev(
                        c.id,
                        "VALUE",
                        extracted_value=(
                            "88.23 LAKHS (3-yr avg, MSME)" if msme else "238.67 LAKHS (3-yr avg)"
                        ),
                        threshold_met=True,
                        reason="From audited B/S FY 23-24/22-23/21-22",
                    )
                )
            elif c.id == "PQC_TECH_SIMILAR_WORK":
                evs.append(
                    _ev(
                        c.id,
                        "VALUE",
                        extracted_value=sw_value,
                        threshold_met=sw_met,
                        reason="Single PO with counter-party",
                    )
                )
            elif c.id == "PQC_DOC_BLACKLIST_DECL" and missing_blacklist:
                evs.append(
                    _ev(
                        c.id,
                        "NOT_PROVIDED",
                        reason="No blacklisting declaration found in submission folder",
                    )
                )
            elif c.id == "PQC_DOC_UDYAM_MSME" and not msme:
                evs.append(_ev(c.id, "PROVIDED", reason="N/A (non-MSME, no relaxation claimed)"))
            else:
                evs.append(_ev(c.id, "PROVIDED", reason=f"{c.name.lower()} present in submission"))
        comm = [
            _ev(c.id, "PROVIDED", reason="accepted in bidder response form")
            for c in commercial_criteria
        ]
        return (
            VendorEvaluation(
                vendor_name=name,
                is_msme=msme,
                criterion_evaluations=evs,
                overall_verdict="ACCEPTED" if accept else "REJECTED",
                overall_remarks=(
                    "All 7 evaluated criteria are satisfied. Vendor is technically qualified."
                    if accept
                    else (
                        "Vendor did not meet Similar Works Experience threshold of 85.00 Lakhs (MSME-relaxed) - provided value 38.42 LAKHS. Hence rejected."
                        if not missing_blacklist
                        else "Vendor did not provide Blacklisting Declaration. Hence rejected."
                    )
                ),
            ),
            comm,
        )

    pairs = [
        _vendor("AROHA FACILITY SERVICES PVT LTD", True, True, "118.50 LAKHS", True),
        _vendor("TEJASWINI HOUSEKEEPING ENTERPRISES", False, True, "164.20 LAKHS", True),
        _vendor("SHRI MANGALAM SAFAI WORKS", True, False, "38.42 LAKHS", False),
        _vendor("PRABHAT DEEP SANITATION SOLUTIONS", False, True, "192.70 LAKHS", True),
        _vendor(
            "RAGHAVENDRA MAINTENANCE WORKS",
            False,
            False,
            "211.40 LAKHS",
            True,
            missing_blacklist=True,
        ),
    ]
    tech_evals = [t for t, _ in pairs]
    comm_evals = [
        VendorEvaluation(
            vendor_name=t.vendor_name,
            is_msme=t.is_msme,
            criterion_evaluations=c,
            overall_verdict="ACCEPTED",
            overall_remarks="All commercial criteria accepted.",
        )
        for t, c in pairs
    ]

    technical = TechnicalEvaluation(
        rubric=rubric,
        vendor_evaluations=tech_evals,
        qualified_count=sum(1 for e in tech_evals if e.overall_verdict == "ACCEPTED"),
        total_count=len(tech_evals),
        summary_remarks=f"{sum(1 for e in tech_evals if e.overall_verdict == 'ACCEPTED')} of {len(tech_evals)} participated vendors are technically qualified.",
    )
    commercial = CommercialEvaluation(
        rubric=rubric,
        vendor_evaluations=comm_evals,
        qualified_count=len(comm_evals),
        total_count=len(comm_evals),
    )

    base = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
    audit_events = [
        AuditEvent(
            evaluation_id=eval_id,
            action=a,
            actor_id=actor,
            actor_role=role,
            notes=notes,
            occurred_at=base.replace(minute=i),
        )
        for i, (a, role, actor, notes) in enumerate(
            [
                (
                    AuditAction.UPLOADED,
                    ActorRole.PREPARER,
                    "preparer1",
                    "tender pdf + 5 vendor folder(s)",
                ),
                (
                    AuditAction.METADATA_EXTRACTED,
                    ActorRole.SYSTEM,
                    "preparer1",
                    "tender_number=DEMO/2026/HKP/001",
                ),
                (AuditAction.METADATA_CONFIRMED, ActorRole.PREPARER, "preparer1", None),
                (
                    AuditAction.EVALUATION_GENERATED,
                    ActorRole.SYSTEM,
                    "preparer1",
                    "iteration=1 tech_qualified=3/5 comm_qualified=5/5",
                ),
                (AuditAction.SENT_FOR_REVIEW, ActorRole.PREPARER, "preparer1", None),
                (AuditAction.REVIEW_ACCEPTED, ActorRole.REVIEWER, "reviewer1", "iteration=1"),
            ]
        )
    ]

    pdf = generate_final_pdf(
        eval_id=eval_id,
        iteration=1,
        metadata=metadata,
        technical=technical,
        commercial=commercial,
        audit_events=audit_events,
        preparer_id="preparer1",
        reviewer_id="reviewer1",
        approver_id="approver1",
        output_dir=OUT_DIR,
        generated_at=datetime(2026, 5, 2, 14, 30, tzinfo=timezone.utc),
    )
    print(f"Wrote {pdf}")


if __name__ == "__main__":
    main()
