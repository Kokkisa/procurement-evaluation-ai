"""Reviewer feedback schema, fed back into agent prompts on re-evaluation."""

from pydantic import BaseModel


class ReviewerFeedback(BaseModel):
    reviewer_id: str
    feedback_text: str
    flagged_vendors: list[str] = []
    flagged_criteria: list[str] = []
