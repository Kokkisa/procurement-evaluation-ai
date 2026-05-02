"""SQLAlchemy 2.x declarative models for evaluations, audit_log, archive, documents.

Schema mirrors spec §5. Postgres-specific types (UUID, JSONB, BIGINT) are used —
this code targets PostgreSQL 13+ and is not portable to SQLite as-is.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    tender_number: Mapped[str] = mapped_column(Text, nullable=False)
    tender_name: Mapped[str] = mapped_column(Text, nullable=False)
    tender_floated_date: Mapped[Optional[date]] = mapped_column(Date)
    tender_due_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    technical_eval_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    commercial_eval_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    reviewer_feedback: Mapped[Optional[str]] = mapped_column(Text)
    preparer_id: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[Optional[str]] = mapped_column(Text)
    approver_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    audit_events: Mapped[list["AuditLog"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_evaluations_tender_number", "tender_number"),
        Index("idx_evaluations_status", "status"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("evaluations.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    actor_role: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    evaluation: Mapped[Evaluation] = relationship(back_populates="audit_events")

    __table_args__ = (Index("idx_audit_log_eval_id", "evaluation_id"),)


class Archive(Base):
    __tablename__ = "archive"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tender_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    full_record: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pdf_path: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_archive_tender_number", "tender_number"),)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.gen_random_uuid(),
    )
    evaluation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("evaluations.id"), nullable=False
    )
    vendor_name: Mapped[Optional[str]] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text)
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    evaluation: Mapped[Evaluation] = relationship(back_populates="documents")

    __table_args__ = (Index("idx_documents_eval_id", "evaluation_id"),)


__all__ = ["Base", "Evaluation", "AuditLog", "Archive", "Document"]
