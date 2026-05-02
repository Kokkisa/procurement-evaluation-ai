"""Tender-side schemas: metadata, criteria, full rubric."""

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TenderMetadata(BaseModel):
    tender_number: str = Field(..., description="Unique tender ID, e.g., GEM/2024/B/5533836")
    tender_name: str = Field(..., description="Subject/title of the tender")
    tender_floated_date: Optional[date] = None
    tender_due_date: Optional[date] = None
    issuing_organization: str = Field(
        ..., description="e.g., Hindustan Petroleum Corporation Limited"
    )
    location: Optional[str] = Field(None, description="e.g., issuing plant or office name")


class CriterionType(str, Enum):
    FINANCIAL = "financial"
    TECHNICAL = "technical"
    DOCUMENT = "document"
    COMMERCIAL = "commercial"


class EvalCriterion(BaseModel):
    id: str = Field(..., description="Stable identifier, e.g., 'PQC_FIN_TURNOVER'")
    name: str = Field(..., description="Short human-readable name")
    description: str = Field(..., description="Full requirement text from the tender")
    type: CriterionType
    threshold_value: Optional[float] = Field(
        None, description="Numeric threshold if applicable, in INR lakhs"
    )
    msme_relaxation_value: Optional[float] = Field(
        None, description="Relaxed threshold for MSME bidders"
    )
    aggregation_rule: Optional[Literal["single_max", "sum", "average"]] = Field(
        None, description="For multi-document criteria like similar works"
    )
    source_clause: Optional[str] = Field(
        None, description="Section/clause reference in tender doc"
    )


class TenderRubric(BaseModel):
    metadata: TenderMetadata
    technical_criteria: list[EvalCriterion]
    commercial_criteria: list[EvalCriterion]
