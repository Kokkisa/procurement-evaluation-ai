"""POST /confirm/{eval_id} — confirm metadata, run criteria + per-vendor
evaluation, return both matrices."""

from __future__ import annotations

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
from ..schemas import ConfirmRequest, ConfirmResponse
from ..services import run_full_evaluation
from ..state import EvalStatus, get_eval_or_404, require_status

router = APIRouter()


@router.post("/confirm/{eval_id}", response_model=ConfirmResponse)
async def confirm(
    eval_id: UUID,
    body: ConfirmRequest,
    db: Session = Depends(get_db),
    criteria_agent: CriteriaExtractionAgent = Depends(get_criteria_agent),
    eval_agent: VendorEvaluationAgent = Depends(get_evaluation_agent),
) -> ConfirmResponse:
    ev = get_eval_or_404(db, eval_id)
    require_status(ev, EvalStatus.METADATA_EXTRACTED)

    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.METADATA_CONFIRMED,
        actor_id=body.actor_id,
        actor_role=ActorRole.PREPARER,
    )
    ev.status = EvalStatus.METADATA_CONFIRMED

    eval_root = Path(settings.upload_dir) / str(eval_id)
    metadata = TenderMetadata.model_validate(ev.tender_metadata_json or {})

    technical, commercial = await run_full_evaluation(
        tender_path=eval_root / "tender.pdf",
        vendors_root=eval_root / "vendors",
        metadata=metadata,
        criteria_agent=criteria_agent,
        eval_agent=eval_agent,
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
            f"iteration={ev.iteration} "
            f"tech_qualified={technical.qualified_count}/{technical.total_count} "
            f"comm_qualified={commercial.qualified_count}/{commercial.total_count}"
        ),
    )
    log_event(
        db,
        evaluation_id=eval_id,
        action=AuditAction.SENT_FOR_REVIEW,
        actor_id=body.actor_id,
        actor_role=ActorRole.PREPARER,
    )
    db.commit()

    return ConfirmResponse(
        eval_id=eval_id,
        iteration=ev.iteration,
        technical=technical,
        commercial=commercial,
    )
