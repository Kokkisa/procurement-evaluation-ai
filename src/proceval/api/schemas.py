"""HTTP request / response models for the FastAPI layer.

Wraps the canonical proceval.schemas types where useful and adds
endpoint-specific request bodies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from ..schemas.evaluation import CommercialEvaluation, TechnicalEvaluation
from ..schemas.tender import TenderMetadata
from ..schemas.vendor import VendorSubmission


# --- /health ---------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    timestamp: datetime


# --- /ingest ---------------------------------------------------------------


class IngestResponse(BaseModel):
    """Returned by POST /ingest. The 2-tab confirmation popup data."""

    eval_id: UUID
    metadata: TenderMetadata
    vendors: list[VendorSubmission]
    next_action: str = "POST /confirm/{eval_id}"


# --- /confirm --------------------------------------------------------------


class ConfirmRequest(BaseModel):
    actor_id: str = Field(..., description="Preparer id confirming the metadata")


class ConfirmResponse(BaseModel):
    eval_id: UUID
    iteration: int
    technical: TechnicalEvaluation
    commercial: CommercialEvaluation


# --- /review ---------------------------------------------------------------


class ReviewAcceptRequest(BaseModel):
    actor_id: str = Field(..., description="Reviewer id accepting the evaluation")


class ReviewAcceptResponse(BaseModel):
    eval_id: UUID
    status: str
    reviewer_id: str


class ReviewRejectRequest(BaseModel):
    actor_id: str = Field(..., description="Reviewer id rejecting the evaluation")
    feedback_text: str = Field(
        ..., min_length=1, description="Reviewer feedback steering the re-evaluation"
    )
    flagged_vendors: list[str] = []
    flagged_criteria: list[str] = []


class ReviewRejectResponse(BaseModel):
    eval_id: UUID
    iteration: int
    technical: TechnicalEvaluation
    commercial: CommercialEvaluation


# --- /approve / /push ------------------------------------------------------


class ApproveRequest(BaseModel):
    actor_id: str = Field(..., description="Approver id signing off")


class ApproveResponse(BaseModel):
    eval_id: UUID
    status: str
    approver_id: str
    pdf_path: str


class PushRequest(BaseModel):
    actor_id: str = Field(..., description="Approver id pushing to archive")


class PushResponse(BaseModel):
    eval_id: UUID
    archive_id: UUID
    status: str


# --- /audit ----------------------------------------------------------------


class AuditEventResponse(BaseModel):
    id: int
    evaluation_id: UUID
    action: str
    actor_id: str
    actor_role: str
    notes: Optional[str] = None
    occurred_at: datetime


class AuditLogResponse(BaseModel):
    eval_id: UUID
    iteration: int
    status: str
    events: list[AuditEventResponse]
