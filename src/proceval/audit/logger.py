"""Append-only audit-log writer.

Every state-changing route must call ``log_event`` with the action, the
actor, and (optionally) descriptive notes. The caller commits the session
at end of request — we don't auto-commit so the audit row stays in the
same transaction as the state change it records.

Notes are truncated to ``DEFAULT_TRUNCATE_BYTES`` (1024) by default — large
re-evaluation snapshots get clipped with a `[truncated]` suffix so the log
stays readable.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from ..db.models import AuditLog
from ..schemas.audit import ActorRole, AuditAction

DEFAULT_TRUNCATE_BYTES = 1024


def log_event(
    session: Session,
    evaluation_id: UUID,
    action: AuditAction,
    actor_id: str,
    actor_role: ActorRole,
    notes: Optional[str] = None,
    truncate_bytes: int = DEFAULT_TRUNCATE_BYTES,
) -> AuditLog:
    """Append an audit row to ``audit_log``. Caller is responsible for commit."""
    if notes is not None and len(notes) > truncate_bytes:
        marker = "...[truncated]"
        notes = notes[: max(0, truncate_bytes - len(marker))] + marker

    entry = AuditLog(
        evaluation_id=evaluation_id,
        action=action.value,
        actor_id=actor_id,
        actor_role=actor_role.value,
        notes=notes,
    )
    session.add(entry)
    session.flush()
    return entry
