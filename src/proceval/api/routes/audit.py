"""GET /audit/{eval_id} — full audit log for one evaluation."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db.models import AuditLog
from ..deps import get_db
from ..schemas import AuditEventResponse, AuditLogResponse
from ..state import get_eval_or_404

router = APIRouter()


@router.get("/audit/{eval_id}", response_model=AuditLogResponse)
def get_audit_log(eval_id: UUID, db: Session = Depends(get_db)) -> AuditLogResponse:
    ev = get_eval_or_404(db, eval_id)
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.evaluation_id == eval_id)
        .order_by(AuditLog.occurred_at, AuditLog.id)
        .all()
    )
    events = [
        AuditEventResponse(
            id=r.id,
            evaluation_id=r.evaluation_id,
            action=r.action,
            actor_id=r.actor_id,
            actor_role=r.actor_role,
            notes=r.notes,
            occurred_at=r.occurred_at,
        )
        for r in rows
    ]
    return AuditLogResponse(
        eval_id=eval_id, iteration=ev.iteration, status=ev.status, events=events
    )
