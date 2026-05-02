"""Round-trip tests for all Pydantic schemas — model -> JSON -> model preserves data."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from proceval.schemas import (
    ActorRole,
    AuditAction,
    AuditEvent,
    CommercialEvaluation,
    CriterionEvaluation,
    CriterionType,
    EvalCriterion,
    FullEvaluation,
    ReviewerFeedback,
    TechnicalEvaluation,
    TenderMetadata,
    TenderRubric,
    VendorEvaluation,
    VendorSubmission,
)


def _sample_metadata() -> TenderMetadata:
    return TenderMetadata(
        tender_number="GEM/2024/B/5533836",
        tender_name="Cylinder Handling Services",
        tender_floated_date=date(2024, 5, 1),
        tender_due_date=date(2024, 5, 21),
        issuing_organization="Hindustan Petroleum Corporation Limited",
        location="HPCL Visakh Refinery",
    )


def _sample_criterion(cid: str = "PQC_FIN_TURNOVER") -> EvalCriterion:
    return EvalCriterion(
        id=cid,
        name="Annual Turnover",
        description="Bidder must have an annual turnover of at least 100 lakhs.",
        type=CriterionType.FINANCIAL,
        threshold_value=100.0,
        msme_relaxation_value=85.0,
        aggregation_rule=None,
        source_clause="PQC §3.1",
    )


def _sample_rubric() -> TenderRubric:
    return TenderRubric(
        metadata=_sample_metadata(),
        technical_criteria=[_sample_criterion()],
        commercial_criteria=[
            EvalCriterion(
                id="COMM_TOC_ACCEPT",
                name="Acceptance of Terms & Conditions",
                description="Bidder must accept all special terms.",
                type=CriterionType.COMMERCIAL,
            )
        ],
    )


def _sample_vendor_eval() -> VendorEvaluation:
    return VendorEvaluation(
        vendor_name="MEHAR GAYATRI ENTERPRISES",
        is_msme=True,
        criterion_evaluations=[
            CriterionEvaluation(
                criterion_id="PQC_FIN_TURNOVER",
                verdict="VALUE",
                extracted_value="65.52 LAKHS (MSME)",
                threshold_met=True,
                reasoning="Audited B/S FY2023-24 shows turnover of 65.52 lakhs.",
                source_document="audited_balance_sheet_FY2023-24.pdf",
                confidence=0.95,
            )
        ],
        overall_verdict="ACCEPTED",
        overall_remarks="All PQC met.",
    )


def test_tender_metadata_round_trip():
    m = _sample_metadata()
    restored = TenderMetadata.model_validate_json(m.model_dump_json())
    assert restored == m


def test_eval_criterion_round_trip():
    c = _sample_criterion()
    restored = EvalCriterion.model_validate_json(c.model_dump_json())
    assert restored == c
    assert restored.type is CriterionType.FINANCIAL


def test_eval_criterion_invalid_type_rejected():
    with pytest.raises(ValidationError):
        EvalCriterion.model_validate(
            {
                "id": "X",
                "name": "Y",
                "description": "Z",
                "type": "not-a-real-type",
            }
        )


def test_tender_rubric_round_trip():
    r = _sample_rubric()
    restored = TenderRubric.model_validate_json(r.model_dump_json())
    assert restored == r


def test_vendor_submission_round_trip():
    v = VendorSubmission(
        vendor_name="SPARK TECHNOLOGY",
        document_count=10,
        document_paths=["a.pdf", "b.pdf"],
        detected_msme=False,
    )
    restored = VendorSubmission.model_validate_json(v.model_dump_json())
    assert restored == v


def test_criterion_evaluation_confidence_bounds():
    base = {
        "criterion_id": "PQC_FIN_TURNOVER",
        "verdict": "PROVIDED",
        "reasoning": "Doc found.",
        "confidence": 0.5,
    }
    CriterionEvaluation.model_validate(base)
    with pytest.raises(ValidationError):
        CriterionEvaluation.model_validate({**base, "confidence": 1.5})
    with pytest.raises(ValidationError):
        CriterionEvaluation.model_validate({**base, "confidence": -0.1})


def test_vendor_evaluation_round_trip():
    e = _sample_vendor_eval()
    restored = VendorEvaluation.model_validate_json(e.model_dump_json())
    assert restored == e


def test_technical_evaluation_round_trip():
    rubric = _sample_rubric()
    te = TechnicalEvaluation(
        rubric=rubric,
        vendor_evaluations=[_sample_vendor_eval()],
        qualified_count=1,
        total_count=1,
        summary_remarks="1 of 1 vendor qualified.",
    )
    restored = TechnicalEvaluation.model_validate_json(te.model_dump_json())
    assert restored == te


def test_full_evaluation_round_trip_with_optional_commercial_none():
    eid = uuid4()
    rubric = _sample_rubric()
    full = FullEvaluation(
        evaluation_id=eid,
        technical=TechnicalEvaluation(
            rubric=rubric,
            vendor_evaluations=[_sample_vendor_eval()],
            qualified_count=1,
            total_count=1,
            summary_remarks="x",
        ),
        commercial=None,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        iteration=1,
    )
    restored = FullEvaluation.model_validate_json(full.model_dump_json())
    assert restored == full


def test_full_evaluation_with_commercial():
    eid = uuid4()
    rubric = _sample_rubric()
    commercial = CommercialEvaluation(
        rubric=rubric,
        vendor_evaluations=[_sample_vendor_eval()],
        qualified_count=1,
        total_count=1,
    )
    full = FullEvaluation(
        evaluation_id=eid,
        technical=TechnicalEvaluation(
            rubric=rubric,
            vendor_evaluations=[_sample_vendor_eval()],
            qualified_count=1,
            total_count=1,
            summary_remarks="x",
        ),
        commercial=commercial,
        generated_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        iteration=2,
    )
    restored = FullEvaluation.model_validate_json(full.model_dump_json())
    assert restored == full
    assert restored.commercial is not None


def test_reviewer_feedback_defaults_empty_lists():
    f = ReviewerFeedback(reviewer_id="rev1", feedback_text="Re-check vendor 3")
    assert f.flagged_vendors == []
    assert f.flagged_criteria == []
    restored = ReviewerFeedback.model_validate_json(f.model_dump_json())
    assert restored == f


def test_audit_event_round_trip_and_enum_coercion():
    event = AuditEvent(
        evaluation_id=uuid4(),
        action=AuditAction.METADATA_CONFIRMED,
        actor_id="preparer1",
        actor_role=ActorRole.PREPARER,
        notes="Confirmed metadata after review",
        occurred_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )
    restored = AuditEvent.model_validate_json(event.model_dump_json())
    assert restored == event
    # string values coerce back to enum members
    assert restored.action is AuditAction.METADATA_CONFIRMED
    assert restored.actor_role is ActorRole.PREPARER
