"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from .. import __version__
from .routes import approve, audit, evaluate, health, ingest, review

app = FastAPI(
    title="Procurement Evaluation AI",
    description="Multi-agent LLM system for PSU tender evaluation.",
    version=__version__,
)

app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(evaluate.router)
app.include_router(review.router)
app.include_router(approve.router)
app.include_router(audit.router)
