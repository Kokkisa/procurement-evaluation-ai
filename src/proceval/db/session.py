"""Synchronous SQLAlchemy engine + session factory.

Used by the FastAPI dependency, the audit logger, and CLI scripts.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings

engine: Engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session and closes it after the request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
