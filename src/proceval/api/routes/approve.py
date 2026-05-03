"""POST /approve/{eval_id} and POST /push/{eval_id} — approver actions.

/approve assembles the full evaluation payload (metadata + technical +
commercial + audit log + actor IDs) and hands it to the formal PDF
generator (Block 9 ReportLab implementation). /push moves the record into
the archive table — logically (status=complete_and_pushed) so the
audit_log FK stays valid; the archive row holds a snapshot of the full
evaluation + audit history.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...audit import log_event
from ...config import settings
from ...db.models import Archive, AuditLog
from ...pdf import generate_final_pdf
from ...schemas.audit import ActorRole, AuditAction, AuditEvent
from ...schemas.evaluation import CommercialEvaluation, TechnicalEvaluation
from ...schemas.tender import TenderMetadata
from ..deps import get_db
from ..schemas import ApproveRequest, ApproveResponse, PushRequest, PushResponse
from ..state import EvalStatus, get_eval_or_404, require_status

router = APIRouter()


@router.post("/approve/{eval_id}", response_model=ApproveResponse)
def approve(
    eval_id: UUID,
    body: ApproveRequest,
    db: Session = Depends(get_db),
) -> ApproveResponse:
    ev = get_eval_or_404(db, eval_id)
    require_status(ev, EvalStatus.REVIEW_ACCEPTED)

    # Reconstruct the typed payload for the PDF generator from the JSONB blobs.
    metadata = TenderMetadata.model_validate(ev.tender_metadata_json or {})
    technical = TechnicalEvaluation.model_validate(ev.technical_eval_json or {})
    commercial = (
        CommercialEvaluation.model_validate(ev.commercial_eval_json)
        if ev.commercial_eval_json
        else None
    )

    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.evaluation_id == eval_id)
        .order_by(AuditLog.occurred_at, AuditLog.id)
        .all()
    )
    audit_events = [
        AuditEvent(
            evaluation_id=r.evaluation_id,
            action=AuditAction(r.action),
            actor_id=r.actor_id,
            actor_role=ActorRole(r.actor_role),
            notes=r.notes,
            occurred_at=r.occurred_at,
        )
        for r in audit_rows
    ]

    pdf_path = generate_final_pdf(
        eval_id=eval_id,
        iteration=ev.iteration,
        metadata=metadata,
        technical=technical,
        commercial=commercial,
        audit_events=audit_events,
        preparer_id=ev.preparer_id,
        reviewer_id=ev.reviewer_id,
        approver_id=body.actor_id,
        output_dir=settings.output_dir,
    )

    ev.approver_id = body.actor_id
    ev.status = EvalStatus.APPROVED

    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.APPROVED,
        actor_id=body.actor_id,
        actor_role=ActorRole.APPROVER,
        notes=f"pdf_path={pdf_path}",
    )
    db.commit()

    return ApproveResponse(
        eval_id=eval_id,
        status=ev.status,
        approver_id=body.actor_id,
        pdf_path=str(pdf_path),
    )


@router.post("/push/{eval_id}", response_model=PushResponse)
def push(
    eval_id: UUID,
    body: PushRequest,
    db: Session = Depends(get_db),
) -> PushResponse:
    ev = get_eval_or_404(db, eval_id)
    require_status(ev, EvalStatus.APPROVED)

    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.evaluation_id == eval_id)
        .order_by(AuditLog.occurred_at, AuditLog.id)
        .all()
    )
    audit_snapshot = [
        {
            "id": r.id,
            "action": r.action,
            "actor_id": r.actor_id,
            "actor_role": r.actor_role,
            "notes": r.notes,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
        }
        for r in audit_rows
    ]

    full_record = {
        "evaluation": {
            "id": str(ev.id),
            "tender_number": ev.tender_number,
            "tender_name": ev.tender_name,
            "preparer_id": ev.preparer_id,
            "reviewer_id": ev.reviewer_id,
            "approver_id": ev.approver_id,
            "iteration": ev.iteration,
            "tender_metadata": ev.tender_metadata_json,
            "technical_eval": ev.technical_eval_json,
            "commercial_eval": ev.commercial_eval_json,
            "reviewer_feedback": ev.reviewer_feedback,
        },
        "audit_log": audit_snapshot,
    }

    archive = Archive(
        id=uuid4(),
        tender_number=ev.tender_number,
        full_record=full_record,
        pdf_path=f"{settings.output_dir}/{ev.tender_number.replace('/', '_')}_iter{ev.iteration}_technical_evaluation.pdf",
    )
    db.add(archive)
    ev.status = EvalStatus.COMPLETE_AND_PUSHED

    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.COMPLETE_AND_PUSHED,
        actor_id=body.actor_id,
        actor_role=ActorRole.APPROVER,
        notes=f"archive_id={archive.id}",
    )
    db.commit()

    return PushResponse(eval_id=eval_id, archive_id=archive.id, status=ev.status)
