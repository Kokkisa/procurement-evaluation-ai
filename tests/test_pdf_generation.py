"""Tests for the formal final-PDF generator (Block 9).

Smoke tests: file generated, valid, opens in pypdf, has expected content.
Asserts each spec-mandated section is present in the rendered text.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pypdf
import pytest

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


# --- helpers ---------------------------------------------------------------


def _meta() -> TenderMetadata:
    return TenderMetadata(
        tender_number="DEMO/2026/HKP/001",
        tender_name="Housekeeping & Sanitation Services at Demo Industrial Facility",
        tender_floated_date=date(2026, 4, 10),
        tender_due_date=date(2026, 4, 30),
        issuing_organization="Demo Procurement Corporation Limited",
        location="Demo Industrial Facility, Pune",
    )


def _criteria() -> tuple[list[EvalCriterion], list[EvalCriterion]]:
    technical = [
        EvalCriterion(
            id="PQC_FIN_TURNOVER",
            name="Average Annual Turnover",
            description="3-yr avg turnover threshold.",
            type=CriterionType.FINANCIAL,
            threshold_value=100.0,
            msme_relaxation_value=85.0,
            aggregation_rule="average",
            source_clause="PQC-1",
        ),
        EvalCriterion(
            id="PQC_TECH_SIMILAR_WORK",
            name="Similar Works Experience",
            description="Single similar-work PO threshold.",
            type=CriterionType.TECHNICAL,
            threshold_value=100.0,
            msme_relaxation_value=85.0,
            aggregation_rule="single_max",
            source_clause="PQC-2",
        ),
        EvalCriterion(
            id="PQC_DOC_PAN",
            name="PAN Card",
            description="PAN required",
            type=CriterionType.DOCUMENT,
            source_clause="PQC-3",
        ),
        EvalCriterion(
            id="PQC_DOC_BLACKLIST_DECL",
            name="Blacklisting Declaration",
            description="Declaration required",
            type=CriterionType.DOCUMENT,
            source_clause="PQC-6",
        ),
    ]
    commercial = [
        EvalCriterion(
            id="COMM_PPE",
            name="PPE Provision",
            description="Bidder shall provide PPE",
            type=CriterionType.COMMERCIAL,
            source_clause="Section 4",
        ),
    ]
    return technical, commercial


def _make_eval(name: str, msme: bool, accept: bool, tech_criteria, *, missing_blacklist=False, sw_value=None, sw_met=True):
    evals = []
    for c in tech_criteria:
        if c.id == "PQC_FIN_TURNOVER":
            evals.append(
                CriterionEvaluation(
                    criterion_id=c.id,
                    verdict="VALUE",
                    extracted_value=("88.23 LAKHS (MSME)" if msme else "238.67 LAKHS"),
                    threshold_met=True,
                    reasoning="From audited B/S",
                    confidence=0.95,
                )
            )
        elif c.id == "PQC_TECH_SIMILAR_WORK":
            evals.append(
                CriterionEvaluation(
                    criterion_id=c.id,
                    verdict="VALUE",
                    extracted_value=(sw_value or "118.50 LAKHS"),
                    threshold_met=sw_met,
                    reasoning="From PO copy",
                    confidence=0.95,
                )
            )
        elif c.id == "PQC_DOC_BLACKLIST_DECL" and missing_blacklist:
            evals.append(
                CriterionEvaluation(
                    criterion_id=c.id,
                    verdict="NOT_PROVIDED",
                    reasoning="Missing from submission folder",
                    confidence=0.95,
                )
            )
        else:
            evals.append(
                CriterionEvaluation(
                    criterion_id=c.id,
                    verdict="PROVIDED",
                    reasoning="Present",
                    confidence=0.95,
                )
            )
    return VendorEvaluation(
        vendor_name=name,
        is_msme=msme,
        criterion_evaluations=evals,
        overall_verdict="ACCEPTED" if accept else "REJECTED",
        overall_remarks=(
            "All evaluated criteria are satisfied."
            if accept
            else f"Vendor did not satisfy one or more criteria. Hence rejected."
        ),
    )


def _vendor_evaluations(tech_criteria) -> list[VendorEvaluation]:
    return [
        _make_eval("AROHA FACILITY SERVICES PVT LTD", True, True, tech_criteria),
        _make_eval("TEJASWINI HOUSEKEEPING ENTERPRISES", False, True, tech_criteria),
        _make_eval(
            "SHRI MANGALAM SAFAI WORKS", True, False, tech_criteria,
            sw_value="38.42 LAKHS", sw_met=False,
        ),
        _make_eval("PRABHAT DEEP SANITATION SOLUTIONS", False, True, tech_criteria),
        _make_eval(
            "RAGHAVENDRA MAINTENANCE WORKS", False, False, tech_criteria,
            missing_blacklist=True,
        ),
    ]


def _audit_events(eval_id: UUID) -> list[AuditEvent]:
    base = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
    flow = [
        (AuditAction.UPLOADED, ActorRole.PREPARER, "preparer1", "tender + 5 vendor folder(s)"),
        (AuditAction.METADATA_EXTRACTED, ActorRole.SYSTEM, "preparer1", "tender_number=DEMO/2026/HKP/001"),
        (AuditAction.METADATA_CONFIRMED, ActorRole.PREPARER, "preparer1", None),
        (AuditAction.EVALUATION_GENERATED, ActorRole.SYSTEM, "preparer1", "iteration=1 tech_qualified=3/5"),
        (AuditAction.SENT_FOR_REVIEW, ActorRole.PREPARER, "preparer1", None),
        (AuditAction.REVIEW_ACCEPTED, ActorRole.REVIEWER, "reviewer1", "iteration=1"),
    ]
    return [
        AuditEvent(
            evaluation_id=eval_id,
            action=action,
            actor_id=actor_id,
            actor_role=role,
            notes=notes,
            occurred_at=base.replace(second=i),
        )
        for i, (action, role, actor_id, notes) in enumerate(flow, start=1)
    ]


@pytest.fixture
def generated_pdf(tmp_path: Path) -> tuple[Path, dict]:
    eval_id = uuid4()
    metadata = _meta()
    tech_criteria, comm_criteria = _criteria()
    rubric = TenderRubric(
        metadata=metadata,
        technical_criteria=tech_criteria,
        commercial_criteria=comm_criteria,
    )
    vendor_evals = _vendor_evaluations(tech_criteria)
    technical = TechnicalEvaluation(
        rubric=rubric,
        vendor_evaluations=vendor_evals,
        qualified_count=3,
        total_count=5,
        summary_remarks="3 of 5 participated vendors are technically qualified.",
    )
    commercial = CommercialEvaluation(
        rubric=rubric,
        vendor_evaluations=vendor_evals,
        qualified_count=5,
        total_count=5,
    )

    pdf_path = generate_final_pdf(
        eval_id=eval_id,
        iteration=1,
        metadata=metadata,
        technical=technical,
        commercial=commercial,
        audit_events=_audit_events(eval_id),
        preparer_id="preparer1",
        reviewer_id="reviewer1",
        approver_id="approver1",
        output_dir=tmp_path,
        generated_at=datetime(2026, 5, 2, 14, 30, tzinfo=timezone.utc),
    )
    return pdf_path, {
        "eval_id": eval_id,
        "metadata": metadata,
        "vendor_evals": vendor_evals,
    }


# --- smoke tests -----------------------------------------------------------


def test_pdf_generated_and_non_empty(generated_pdf):
    pdf_path, _ = generated_pdf
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1024, "PDF is suspiciously small"


def test_pdf_filename_includes_iteration(generated_pdf):
    pdf_path, _ = generated_pdf
    assert "iter1" in pdf_path.name
    assert pdf_path.name == "DEMO_2026_HKP_001_iter1_technical_evaluation.pdf"


def test_pdf_opens_with_pypdf(generated_pdf):
    pdf_path, _ = generated_pdf
    reader = pypdf.PdfReader(str(pdf_path))
    assert len(reader.pages) >= 2
    # Also verify metadata embedded
    title = reader.metadata.get("/Title", "") if reader.metadata else ""
    assert "DEMO/2026/HKP/001" in title or "Technical Evaluation" in title


# --- content assertions ----------------------------------------------------


def _all_text(pdf_path: Path) -> str:
    reader = pypdf.PdfReader(str(pdf_path))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def test_pdf_contains_header_band_content(generated_pdf):
    pdf_path, _ = generated_pdf
    text = _all_text(pdf_path)
    assert "PROCUREMENT EVALUATION REPORT" in text
    assert "DEMO/2026/HKP/001" in text
    assert "Iteration 1" in text


def test_pdf_contains_tender_metadata(generated_pdf):
    pdf_path, _ = generated_pdf
    text = _all_text(pdf_path)
    assert "Tender Floated Date" in text
    assert "Bid Due Date" in text
    assert "2026-04-10" in text
    assert "2026-04-30" in text
    assert "Pune" in text


def test_pdf_contains_vendor_list_with_msme_tags(generated_pdf):
    pdf_path, ctx = generated_pdf
    text = _all_text(pdf_path)
    assert "Participating Vendors" in text
    for ve in ctx["vendor_evals"]:
        assert ve.vendor_name in text
    # MSME vendors get [MSME] tag in vendor list (and again in matrix header)
    assert "[MSME]" in text


def test_pdf_contains_matrix_header_and_overall_remarks_row(generated_pdf):
    pdf_path, _ = generated_pdf
    text = _all_text(pdf_path)
    assert "TECHNICAL EVALUATION MATRIX" in text
    assert "CRITERION" in text
    assert "REQUIREMENT" in text
    assert "OVERALL REMARKS" in text


def test_pdf_contains_critical_extracted_values(generated_pdf):
    pdf_path, _ = generated_pdf
    text = _all_text(pdf_path)
    # The synthetic gold-standard markers
    assert "88.23 LAKHS" in text  # AROHA turnover (MSME-relaxation pass)
    assert "38.42 LAKHS" in text  # SHRI MANGALAM similar work (fail)


def test_pdf_contains_overall_verdicts_per_vendor(generated_pdf):
    pdf_path, _ = generated_pdf
    text = _all_text(pdf_path)
    assert "ACCEPTED" in text
    assert "REJECTED" in text


def test_pdf_contains_commercial_section_when_supplied(generated_pdf):
    pdf_path, _ = generated_pdf
    text = _all_text(pdf_path)
    assert "COMMERCIAL EVALUATION MATRIX" in text


def test_pdf_contains_lifecycle_audit_log_with_actions(generated_pdf):
    pdf_path, _ = generated_pdf
    text = _all_text(pdf_path)
    assert "LIFECYCLE AUDIT LOG" in text
    for action in ("uploaded", "metadata_confirmed", "evaluation_generated", "review_accepted"):
        assert action in text, f"missing audit action {action!r} in PDF text"


def test_pdf_contains_signature_blocks(generated_pdf):
    pdf_path, _ = generated_pdf
    text = _all_text(pdf_path)
    assert "SIGNATURES" in text
    assert "Prepared By" in text
    assert "Reviewed By" in text
    assert "Approved By" in text
    assert "preparer1" in text
    assert "reviewer1" in text
    assert "approver1" in text


def test_pdf_handles_no_commercial_eval(tmp_path: Path):
    """If commercial=None, the commercial section should be omitted gracefully."""
    eval_id = uuid4()
    metadata = _meta()
    tech_criteria, _ = _criteria()
    rubric = TenderRubric(
        metadata=metadata, technical_criteria=tech_criteria, commercial_criteria=[]
    )
    technical = TechnicalEvaluation(
        rubric=rubric,
        vendor_evaluations=_vendor_evaluations(tech_criteria),
        qualified_count=3,
        total_count=5,
        summary_remarks="x",
    )
    pdf_path = generate_final_pdf(
        eval_id=eval_id,
        iteration=1,
        metadata=metadata,
        technical=technical,
        commercial=None,
        audit_events=[],
        preparer_id="p",
        reviewer_id=None,
        approver_id=None,
        output_dir=tmp_path,
    )
    assert pdf_path.exists()
    text = _all_text(pdf_path)
    assert "TECHNICAL EVALUATION MATRIX" in text
    assert "COMMERCIAL EVALUATION MATRIX" not in text


def test_pdf_iteration_number_changes_filename(tmp_path: Path):
    """Different iteration -> different filename. Both are real, no overwrite."""
    eval_id = uuid4()
    metadata = _meta()
    tech_criteria, _ = _criteria()
    rubric = TenderRubric(
        metadata=metadata, technical_criteria=tech_criteria, commercial_criteria=[]
    )
    technical = TechnicalEvaluation(
        rubric=rubric,
        vendor_evaluations=_vendor_evaluations(tech_criteria),
        qualified_count=3,
        total_count=5,
        summary_remarks="x",
    )
    pdf_v1 = generate_final_pdf(
        eval_id=eval_id, iteration=1, metadata=metadata, technical=technical,
        audit_events=[], preparer_id="p", output_dir=tmp_path,
    )
    pdf_v2 = generate_final_pdf(
        eval_id=eval_id, iteration=2, metadata=metadata, technical=technical,
        audit_events=[], preparer_id="p", output_dir=tmp_path,
    )
    assert pdf_v1 != pdf_v2
    assert "iter1" in pdf_v1.name
    assert "iter2" in pdf_v2.name
    assert pdf_v1.exists() and pdf_v2.exists()
