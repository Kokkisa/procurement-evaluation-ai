"""SQLAlchemy round-trip tests against the local Postgres.

Skipped automatically if the database isn't reachable. To run them:
    1. Start local Postgres with the credentials in .env.example
    2. Run `alembic upgrade head` (or `make migrate`)
    3. pytest tests/test_db_models.py
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from proceval.db import Archive, AuditLog, Document, Evaluation, SessionLocal, engine


@pytest.fixture(scope="module")
def db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError as e:
        pytest.skip(f"Postgres not reachable, skipping DB round-trip tests: {e}")


@pytest.fixture
def session(db_available):
    """Yield a transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    s = SessionLocal(bind=connection)
    try:
        yield s
    finally:
        s.close()
        transaction.rollback()
        connection.close()


def test_evaluation_round_trip(session):
    eid = uuid4()
    ev = Evaluation(
        id=eid,
        tender_number="GEM/2024/B/5533836",
        tender_name="Cylinder Handling Services",
        tender_floated_date=date(2024, 5, 1),
        tender_due_date=date(2024, 5, 21),
        status="uploaded",
        preparer_id="preparer1",
        technical_eval_json={"sample": "jsonb-payload", "n": 5},
    )
    session.add(ev)
    session.flush()

    fetched = session.get(Evaluation, eid)
    assert fetched is not None
    assert fetched.tender_number == "GEM/2024/B/5533836"
    assert fetched.technical_eval_json == {"sample": "jsonb-payload", "n": 5}
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


def test_evaluation_id_server_default_when_omitted(session):
    """Postgres should fill id via gen_random_uuid() if Python doesn't supply it."""
    ev = Evaluation(
        tender_number="T2",
        tender_name="No-id evaluation",
        status="uploaded",
        preparer_id="preparer1",
    )
    session.add(ev)
    session.flush()
    session.refresh(ev)
    assert ev.id is not None


def test_audit_log_fk_cascade_on_evaluation(session):
    eid = uuid4()
    ev = Evaluation(
        id=eid,
        tender_number="T-AUDIT",
        tender_name="Audit cascade test",
        status="uploaded",
        preparer_id="preparer1",
    )
    session.add(ev)
    session.flush()

    log = AuditLog(
        evaluation_id=eid,
        action="uploaded",
        actor_id="preparer1",
        actor_role="preparer",
        notes="Initial upload",
    )
    session.add(log)
    session.flush()

    fetched_ev = session.get(Evaluation, eid)
    assert len(fetched_ev.audit_events) == 1
    assert fetched_ev.audit_events[0].action == "uploaded"
    assert fetched_ev.audit_events[0].id is not None  # BIGSERIAL filled by DB


def test_documents_relationship(session):
    eid = uuid4()
    ev = Evaluation(
        id=eid,
        tender_number="T-DOC",
        tender_name="Doc relationship test",
        status="uploaded",
        preparer_id="preparer1",
    )
    session.add(ev)
    session.flush()

    doc = Document(
        evaluation_id=eid,
        vendor_name="VENDOR-1",
        document_type="vendor_submission",
        file_path="/uploads/V1/balance_sheet.pdf",
        page_count=3,
    )
    session.add(doc)
    session.flush()

    fetched_ev = session.get(Evaluation, eid)
    assert len(fetched_ev.documents) == 1
    assert fetched_ev.documents[0].vendor_name == "VENDOR-1"


def test_archive_unique_tender_number(session):
    aid1, aid2 = uuid4(), uuid4()
    a = Archive(
        id=aid1,
        tender_number="T-ARCH-UNIQUE",
        full_record={"snapshot": True},
        pdf_path="/outputs/T-ARCH-UNIQUE.pdf",
    )
    session.add(a)
    session.flush()

    dupe = Archive(
        id=aid2,
        tender_number="T-ARCH-UNIQUE",
        full_record={"snapshot": True},
        pdf_path="/outputs/T-ARCH-UNIQUE-dupe.pdf",
    )
    session.add(dupe)
    with pytest.raises(Exception):
        session.flush()
