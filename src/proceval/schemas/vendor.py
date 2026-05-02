"""Vendor-side schemas: submission, per-criterion eval, full vendor verdict."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class VendorSubmission(BaseModel):
    vendor_name: str
    document_count: int
    document_paths: list[str]
    detected_msme: bool = Field(False, description="Inferred from Udyam/NSIC presence")


class CriterionEvaluation(BaseModel):
    criterion_id: str
    verdict: Literal["PROVIDED", "NOT_PROVIDED", "VALUE", "PARTIAL"]
    extracted_value: Optional[str] = Field(
        None, description="Actual value when verdict=VALUE, e.g., '249 LAKHS'"
    )
    threshold_met: Optional[bool] = None
    reasoning: str = Field(..., description="Brief explanation citing source documents")
    source_document: Optional[str] = Field(
        None, description="Filename of the doc that provided evidence"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)


class VendorEvaluation(BaseModel):
    vendor_name: str
    is_msme: bool
    criterion_evaluations: list[CriterionEvaluation]
    overall_verdict: Literal["ACCEPTED", "REJECTED"]
    overall_remarks: str = Field(
        ...,
        description=(
            "Reasoned summary, e.g., 'Vendor did not provide similar works PO copies of value "
            "more than 100 Lakhs. Only 22.76 Lakhs PO value is available, hence rejected.'"
        ),
    )
