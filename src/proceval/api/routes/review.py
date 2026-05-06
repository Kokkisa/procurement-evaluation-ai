"""POST /review/{eval_id}/{accept,reject} — reviewer actions.

On reject: snapshot the current technical_eval_json (truncated to ~1KB)
into audit notes, then re-run the criteria + per-vendor evaluation chain
with feedback_text plumbed into the criteria agent. Iteration counter
increments. Status returns to ``eval_ready``.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...agents import CriteriaExtractionAgent, VendorEvaluationAgent
from ...audit import log_event
from ...config import settings
from ...schemas.audit import ActorRole, AuditAction
from ...schemas.tender import TenderMetadata
from ..deps import get_criteria_agent, get_db, get_evaluation_agent
from ..schemas import (
    ReviewAcceptRequest,
    ReviewAcceptResponse,
    ReviewRejectRequest,
    ReviewRejectResponse,
)
from ..services import run_full_evaluation
from ..state import EvalStatus, get_eval_or_404, require_status

router = APIRouter()


@router.post("/review/{eval_id}/accept", response_model=ReviewAcceptResponse)
def review_accept(
    eval_id: UUID,
    body: ReviewAcceptRequest,
    db: Session = Depends(get_db),
) -> ReviewAcceptResponse:
    ev = get_eval_or_404(db, eval_id)
    require_status(ev, EvalStatus.EVAL_READY)

    ev.reviewer_id = body.actor_id
    ev.status = EvalStatus.REVIEW_ACCEPTED

    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.REVIEW_ACCEPTED,
        actor_id=body.actor_id,
        actor_role=ActorRole.REVIEWER,
        notes=f"iteration={ev.iteration}",
    )
    db.commit()

    return ReviewAcceptResponse(eval_id=eval_id, status=ev.status, reviewer_id=body.actor_id)


@router.post("/review/{eval_id}/reject", response_model=ReviewRejectResponse)
async def review_reject(
    eval_id: UUID,
    body: ReviewRejectRequest,
    db: Session = Depends(get_db),
    criteria_agent: CriteriaExtractionAgent = Depends(get_criteria_agent),
    eval_agent: VendorEvaluationAgent = Depends(get_evaluation_agent),
) -> ReviewRejectResponse:
    ev = get_eval_or_404(db, eval_id)
    require_status(ev, EvalStatus.EVAL_READY)

    # Snapshot the previous evaluation in the audit log BEFORE we overwrite it.
    prev_snapshot = json.dumps(
        {
            "iteration": ev.iteration,
            "technical": ev.technical_eval_json,
            "commercial": ev.commercial_eval_json,
        }
    )

    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.REVIEW_REJECTED,
        actor_id=body.actor_id,
        actor_role=ActorRole.REVIEWER,
        notes=f"feedback_text={body.feedback_text!r}",
    )
    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.RE_EVALUATION_TRIGGERED,
        actor_id=body.actor_id,
        actor_role=ActorRole.SYSTEM,
        notes=f"prev_iteration={ev.iteration} prev_snapshot={prev_snapshot}",
    )
    ev.reviewer_feedback = body.feedback_text
    ev.reviewer_id = body.actor_id
    ev.iteration = ev.iteration + 1

    eval_root = Path(settings.upload_dir) / str(eval_id)
    metadata = TenderMetadata.model_validate(ev.tender_metadata_json or {})

    technical, commercial = await run_full_evaluation(
        tender_path=eval_root / "tender.pdf",
        vendors_root=eval_root / "vendors",
        metadata=metadata,
        criteria_agent=criteria_agent,
        eval_agent=eval_agent,
        feedback_text=body.feedback_text,
    )

    ev.technical_eval_json = technical.model_dump(mode="json")
    ev.commercial_eval_json = commercial.model_dump(mode="json")
    ev.status = EvalStatus.EVAL_READY

    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.EVALUATION_GENERATED,
        actor_id=body.actor_id,
        actor_role=ActorRole.SYSTEM,
        notes=(
            f"iteration={ev.iteration} (re-eval) "
            f"tech_qualified={technical.qualified_count}/{technical.total_count}"
        ),
    )
    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.SENT_FOR_REVIEW,
        actor_id=body.actor_id,
        actor_role=ActorRole.SYSTEM,
    )
    db.commit()

    return ReviewRejectResponse(
        eval_id=eval_id,
        iteration=ev.iteration,
        technical=technical,
        commercial=commercial,
    )
