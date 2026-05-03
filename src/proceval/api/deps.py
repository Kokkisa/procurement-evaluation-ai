"""FastAPI dependency factories.

Tests override these via ``app.dependency_overrides`` to inject:
- a transactional DB session that rolls back at end of test
- mocked agent instances so no LLM is hit during plumbing tests
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..agents import (
    CriteriaExtractionAgent,
    MetadataExtractionAgent,
    VendorEvaluationAgent,
)
from ..db.session import get_session


def get_db() -> Iterator[Session]:
    yield from get_session()


def get_metadata_agent() -> MetadataExtractionAgent:
    return MetadataExtractionAgent()


def get_criteria_agent() -> CriteriaExtractionAgent:
    return CriteriaExtractionAgent()


def get_evaluation_agent() -> VendorEvaluationAgent:
    return VendorEvaluationAgent(max_concurrency=2)
