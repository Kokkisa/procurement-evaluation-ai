"""Audit-log schemas: every lifecycle transition writes one of these."""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AuditAction(str, Enum):
    UPLOADED = "uploaded"
    METADATA_EXTRACTED = "metadata_extracted"
    METADATA_CONFIRMED = "metadata_confirmed"
    EVALUATION_GENERATED = "evaluation_generated"
    SENT_FOR_REVIEW = "sent_for_review"
    REVIEW_ACCEPTED = "review_accepted"
    REVIEW_REJECTED = "review_rejected"
    RE_EVALUATION_TRIGGERED = "re_evaluation_triggered"
    APPROVED = "approved"
    COMPLETE_AND_PUSHED = "complete_and_pushed"


class ActorRole(str, Enum):
    PREPARER = "preparer"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    SYSTEM = "system"


class AuditEvent(BaseModel):
    evaluation_id: UUID
    action: AuditAction
    actor_id: str
    actor_role: ActorRole
    notes: Optional[str] = None
    occurred_at: datetime
