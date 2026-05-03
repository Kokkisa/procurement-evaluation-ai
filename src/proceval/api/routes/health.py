"""GET /health — liveness probe."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ... import __version__
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        timestamp=datetime.now(timezone.utc),
    )
