"""Top-level evaluation schemas combining rubric + per-vendor verdicts."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from .tender import TenderRubric
from .vendor import VendorEvaluation


class TechnicalEvaluation(BaseModel):
    rubric: TenderRubric
    vendor_evaluations: list[VendorEvaluation]
    qualified_count: int
    total_count: int
    summary_remarks: str


class CommercialEvaluation(BaseModel):
    rubric: TenderRubric
    vendor_evaluations: list[VendorEvaluation]
    qualified_count: int
    total_count: int


class FullEvaluation(BaseModel):
    evaluation_id: UUID
    technical: TechnicalEvaluation
    commercial: Optional[CommercialEvaluation] = None
    generated_at: datetime
    iteration: int = 1
