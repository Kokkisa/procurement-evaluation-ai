"""Evaluation state constants + small helpers shared across routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..db.models import Evaluation


class EvalStatus:
    UPLOADED = "uploaded"
    METADATA_EXTRACTED = "metadata_extracted"
    METADATA_CONFIRMED = "metadata_confirmed"
    EVAL_READY = "eval_ready"
    REVIEW_ACCEPTED = "review_accepted"
    APPROVED = "approved"
    COMPLETE_AND_PUSHED = "complete_and_pushed"


def get_eval_or_404(db: Session, eval_id: UUID) -> Evaluation:
    ev = db.get(Evaluation, eval_id)
    if ev is None:
        raise HTTPException(status_code=404, detail=f"Evaluation {eval_id} not found")
    return ev


def require_status(ev: Evaluation, *expected: str) -> None:
    if ev.status not in expected:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Invalid state transition for evaluation {ev.id}: current status "
                f"is {ev.status!r}, expected one of {list(expected)}"
            ),
        )
