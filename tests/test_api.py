"""End-to-end API tests against the FastAPI app.

Uses TestClient (httpx-based). Stubs all three agents so no LLM is hit.
DB session is transactional and rolls back per test. Settings.upload_dir
and output_dir are monkey-patched to tmp_path so files never touch the
real data dir.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from sqlalchemy import text as sql_text
from sqlalchemy.exc import OperationalError

from proceval.api.deps import (
    get_criteria_agent,
    get_db,
    get_evaluation_agent,
    get_metadata_agent,
)
from proceval.api.main import app
from proceval.db.session import SessionLocal, engine
from proceval.schemas.tender import (
    CriterionType,
    EvalCriterion,
    TenderMetadata,
    TenderRubric,
)
from proceval.schemas.vendor import CriterionEvaluation, VendorEvaluation


# --- Stub agents (module-level call counters, reset by client fixture) ----


class _StubMetadataAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract(self, tender_text: str) -> TenderMetadata:
        self.calls.append(tender_text[:50])
        return TenderMetadata(
            tender_number="DEMO/2026/HKP/001",
            tender_name="Housekeeping & Sanitation Services (test)",
            tender_floated_date=date(2026, 4, 10),
            tender_due_date=date(2026, 4, 30),
            issuing_organization="Demo Procurement Corporation Limited",
            location="Pune",
        )


class _StubCriteriaAgent:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def extract(
        self,
        tender_text: str,
        tender_metadata: TenderMetadata,
        feedback_text: str | None = None,
    ) -> TenderRubric:
        self.calls.append({"text_len": len(tender_text), "feedback": feedback_text})
        return TenderRubric(
            metadata=tender_metadata,
            technical_criteria=[
                EvalCriterion(
                    id="PQC_FIN_TURNOVER",
                    name="Average Annual Turnover",
                    description="threshold",
                    type=CriterionType.FINANCIAL,
                    threshold_value=100.0,
                    msme_relaxation_value=85.0,
                    aggregation_rule="average",
                ),
                EvalCriterion(
                    id="PQC_DOC_PAN",
                    name="PAN Card",
                    description="doc",
                    type=CriterionType.DOCUMENT,
                ),
            ],
            commercial_criteria=[
                EvalCriterion(
                    id="COMM_PPE",
                    name="PPE",
                    description="commercial",
                    type=CriterionType.COMMERCIAL,
                ),
            ],
        )


class _StubEvaluationAgent:
    def __init__(self) -> None:
        self.max_concurrency = 1
        self.calls: list[dict] = []

    async def aevaluate_vendor_full(
        self,
        criteria: list[EvalCriterion],
        vendor_name: str,
        is_msme: bool,
        vendor_docs_text: str,
    ) -> VendorEvaluation:
        self.calls.append(
            {"vendor": vendor_name, "criteria_count": len(criteria), "is_msme": is_msme}
        )
        return VendorEvaluation(
            vendor_name=vendor_name,
            is_msme=is_msme,
            criterion_evaluations=[
                CriterionEvaluation(
                    criterion_id=c.id,
                    verdict="PROVIDED",
                    reasoning="stubbed",
                    confidence=0.95,
                )
                for c in criteria
            ],
            overall_verdict="ACCEPTED",
            overall_remarks=f"All {len(criteria)} criteria satisfied (stub).",
        )


# --- Fixtures --------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _ensure_db():
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
    except OperationalError as e:
        pytest.skip(f"Postgres not reachable, skipping API tests: {e}")


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        try:
            transaction.rollback()
        except Exception:
            pass
        connection.close()


@pytest.fixture
def stub_agents():
    return {
        "metadata": _StubMetadataAgent(),
        "criteria": _StubCriteriaAgent(),
        "evaluation": _StubEvaluationAgent(),
    }


@pytest.fixture
def client(db_session, stub_agents, tmp_path, monkeypatch):
    monkeypatch.setattr("proceval.config.settings.upload_dir", tmp_path / "uploads")
    monkeypatch.setattr("proceval.config.settings.output_dir", tmp_path / "outputs")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_metadata_agent] = lambda: stub_agents["metadata"]
    app.dependency_overrides[get_criteria_agent] = lambda: stub_agents["criteria"]
    app.dependency_overrides[get_evaluation_agent] = lambda: stub_agents["evaluation"]

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# --- Test helpers ----------------------------------------------------------


def _tiny_pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


def _vendor_zip(vendor_name: str, doc_names: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in doc_names:
            zf.writestr(n, _tiny_pdf(f"{vendor_name} - {n}"))
    return buf.getvalue()


def _ingest(client, *, vendors: list[tuple[str, bytes]] | None = None) -> dict:
    """Helper: run /ingest with one tender PDF + the given vendor uploads.
    Each vendor entry is (filename, bytes). Returns the JSON response."""
    if vendors is None:
        vendors = [("aroha.pdf", _tiny_pdf("AROHA vendor doc"))]
    files = [
        ("tender", ("tender.pdf", _tiny_pdf("Tender body"), "application/pdf")),
    ]
    for filename, payload in vendors:
        ctype = "application/zip" if filename.endswith(".zip") else "application/pdf"
        files.append(("vendor_files", (filename, payload, ctype)))
    resp = client.post("/ingest", data={"actor_id": "preparer1"}, files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _audit_actions(client, eval_id: str) -> list[str]:
    resp = client.get(f"/audit/{eval_id}")
    assert resp.status_code == 200, resp.text
    return [e["action"] for e in resp.json()["events"]]


# --- /health ---------------------------------------------------------------


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert "timestamp" in body


# --- /ingest ---------------------------------------------------------------


def test_ingest_happy_path_returns_metadata_and_vendor_list(client, stub_agents):
    body = _ingest(client)
    assert UUID(body["eval_id"])
    assert body["metadata"]["tender_number"] == "DEMO/2026/HKP/001"
    assert len(body["vendors"]) == 1
    assert body["vendors"][0]["vendor_name"] == "aroha"
    # Metadata agent was called once with non-empty text
    assert len(stub_agents["metadata"].calls) == 1
    # Audit log captures upload + metadata extraction
    actions = _audit_actions(client, body["eval_id"])
    assert "uploaded" in actions
    assert "metadata_extracted" in actions


def test_ingest_unzips_vendor_archive(client):
    payload = _vendor_zip("vendor_alpha", ["pan.pdf", "gst.pdf", "balance.pdf"])
    body = _ingest(client, vendors=[("vendor_alpha.zip", payload)])
    assert len(body["vendors"]) == 1
    assert body["vendors"][0]["document_count"] == 3


def test_ingest_rejects_non_pdf_tender(client):
    files = [
        ("tender", ("tender.txt", b"not a pdf", "text/plain")),
        ("vendor_files", ("v.pdf", _tiny_pdf("v"), "application/pdf")),
    ]
    resp = client.post("/ingest", data={"actor_id": "p"}, files=files)
    assert resp.status_code == 400


def test_ingest_rejects_unknown_vendor_extension(client):
    files = [
        ("tender", ("tender.pdf", _tiny_pdf("t"), "application/pdf")),
        ("vendor_files", ("v.exe", b"\x00\x01", "application/octet-stream")),
    ]
    resp = client.post("/ingest", data={"actor_id": "p"}, files=files)
    assert resp.status_code == 400


# --- /confirm --------------------------------------------------------------


def test_confirm_happy_path_returns_matrices(client, stub_agents):
    eval_id = _ingest(client)["eval_id"]
    resp = client.post(f"/confirm/{eval_id}", json={"actor_id": "preparer1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["iteration"] == 1
    assert body["technical"]["qualified_count"] == 1
    assert body["technical"]["total_count"] == 1
    assert body["commercial"]["total_count"] == 1
    # Criteria agent called once, eval agent called twice (technical + commercial)
    assert len(stub_agents["criteria"].calls) == 1
    assert len(stub_agents["evaluation"].calls) == 2


def test_confirm_logs_full_chain(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "preparer1"})
    actions = _audit_actions(client, eval_id)
    for needed in (
        "uploaded",
        "metadata_extracted",
        "metadata_confirmed",
        "evaluation_generated",
        "sent_for_review",
    ):
        assert needed in actions, f"missing {needed!r} in audit log; got {actions}"


def test_confirm_404_on_unknown_id(client):
    resp = client.post(
        "/confirm/00000000-0000-0000-0000-000000000000",
        json={"actor_id": "p"},
    )
    assert resp.status_code == 404


def test_confirm_409_when_already_confirmed(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    resp = client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    assert resp.status_code == 409


# --- /review/accept --------------------------------------------------------


def test_review_accept_happy_path(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    resp = client.post(f"/review/{eval_id}/accept", json={"actor_id": "rev1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "review_accepted"
    assert "review_accepted" in _audit_actions(client, eval_id)


def test_review_accept_409_when_not_eval_ready(client):
    eval_id = _ingest(client)["eval_id"]
    # Skip /confirm — eval is still in metadata_extracted
    resp = client.post(f"/review/{eval_id}/accept", json={"actor_id": "rev1"})
    assert resp.status_code == 409


# --- /review/reject + re-evaluation ---------------------------------------


def test_review_reject_increments_iteration_and_re_runs_agents(client, stub_agents):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})

    # Baseline counts after first eval
    crit_calls_before = len(stub_agents["criteria"].calls)
    eval_calls_before = len(stub_agents["evaluation"].calls)

    resp = client.post(
        f"/review/{eval_id}/reject",
        json={
            "actor_id": "rev1",
            "feedback_text": "Re-check vendor turnover - looks suspicious.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["iteration"] == 2
    # Re-eval ran both agents again, with feedback plumbed to criteria
    assert len(stub_agents["criteria"].calls) == crit_calls_before + 1
    assert (
        stub_agents["criteria"].calls[-1]["feedback"]
        == "Re-check vendor turnover - looks suspicious."
    )
    assert len(stub_agents["evaluation"].calls) == eval_calls_before + 2


def test_review_reject_preserves_previous_snapshot_in_audit(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    client.post(
        f"/review/{eval_id}/reject",
        json={"actor_id": "rev1", "feedback_text": "feedback"},
    )

    audit = client.get(f"/audit/{eval_id}").json()["events"]

    # The re_evaluation_triggered event must carry the previous snapshot
    re_eval_events = [e for e in audit if e["action"] == "re_evaluation_triggered"]
    assert len(re_eval_events) == 1
    notes = re_eval_events[0]["notes"]
    assert notes is not None
    assert "prev_iteration=1" in notes
    assert "prev_snapshot=" in notes
    # The snapshot includes the prior rubric (close to start of JSON, survives
    # the 1KB truncation). vendor_evaluations sits later and is correctly
    # truncated — verify the truncation marker is present instead.
    assert "rubric" in notes
    assert "technical_criteria" in notes
    assert notes.endswith("[truncated]"), f"expected truncation marker, got tail: {notes[-40:]!r}"
    # And the review_rejected event captures the feedback
    rej_events = [e for e in audit if e["action"] == "review_rejected"]
    assert len(rej_events) == 1
    assert "feedback" in rej_events[0]["notes"]


def test_review_reject_status_returns_to_eval_ready_after_re_eval(client, db_session):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    client.post(
        f"/review/{eval_id}/reject",
        json={"actor_id": "rev1", "feedback_text": "redo"},
    )
    # Reviewer can immediately accept the new iteration
    resp = client.post(f"/review/{eval_id}/accept", json={"actor_id": "rev1"})
    assert resp.status_code == 200


def test_review_reject_409_when_not_eval_ready(client):
    eval_id = _ingest(client)["eval_id"]
    resp = client.post(
        f"/review/{eval_id}/reject",
        json={"actor_id": "rev1", "feedback_text": "x"},
    )
    assert resp.status_code == 409


def test_review_reject_400_on_empty_feedback(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    resp = client.post(
        f"/review/{eval_id}/reject",
        json={"actor_id": "rev1", "feedback_text": ""},
    )
    assert resp.status_code == 422  # pydantic min_length validation


# --- /approve --------------------------------------------------------------


def test_approve_generates_pdf_and_returns_path(client, tmp_path):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    client.post(f"/review/{eval_id}/accept", json={"actor_id": "rev1"})
    resp = client.post(f"/approve/{eval_id}", json={"actor_id": "appr1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "approved"
    assert Path(body["pdf_path"]).exists()
    assert Path(body["pdf_path"]).stat().st_size > 0
    assert "approved" in _audit_actions(client, eval_id)


def test_approve_409_when_not_review_accepted(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    # Skip review — eval is in eval_ready, not review_accepted
    resp = client.post(f"/approve/{eval_id}", json={"actor_id": "appr1"})
    assert resp.status_code == 409


# --- /push -----------------------------------------------------------------


def test_push_creates_archive_and_logs(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    client.post(f"/review/{eval_id}/accept", json={"actor_id": "rev1"})
    client.post(f"/approve/{eval_id}", json={"actor_id": "appr1"})
    resp = client.post(f"/push/{eval_id}", json={"actor_id": "appr1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert UUID(body["archive_id"])
    assert body["status"] == "complete_and_pushed"
    assert "complete_and_pushed" in _audit_actions(client, eval_id)


def test_push_409_when_not_approved(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    client.post(f"/review/{eval_id}/accept", json={"actor_id": "rev1"})
    # Skip approve
    resp = client.post(f"/push/{eval_id}", json={"actor_id": "appr1"})
    assert resp.status_code == 409


# --- /audit ----------------------------------------------------------------


def test_audit_404_on_unknown_id(client):
    resp = client.get("/audit/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_audit_log_is_non_empty_after_each_lifecycle_transition(client):
    """Hard rule per Block 7 spec: audit log non-empty after each transition."""
    eval_id = _ingest(client)["eval_id"]
    assert len(_audit_actions(client, eval_id)) >= 2  # uploaded + metadata_extracted

    client.post(f"/confirm/{eval_id}", json={"actor_id": "p"})
    a1 = _audit_actions(client, eval_id)
    assert "metadata_confirmed" in a1
    assert "evaluation_generated" in a1
    assert "sent_for_review" in a1

    client.post(f"/review/{eval_id}/accept", json={"actor_id": "rev1"})
    a2 = _audit_actions(client, eval_id)
    assert "review_accepted" in a2

    client.post(f"/approve/{eval_id}", json={"actor_id": "appr1"})
    a3 = _audit_actions(client, eval_id)
    assert "approved" in a3

    client.post(f"/push/{eval_id}", json={"actor_id": "appr1"})
    a4 = _audit_actions(client, eval_id)
    assert "complete_and_pushed" in a4

    # Strictly increasing
    assert len(a4) > len(a3) > len(a2) > len(a1)


def test_full_lifecycle_produces_expected_action_sequence(client):
    eval_id = _ingest(client)["eval_id"]
    client.post(f"/confirm/{eval_id}", json={"actor_id": "preparer1"})
    client.post(f"/review/{eval_id}/accept", json={"actor_id": "reviewer1"})
    client.post(f"/approve/{eval_id}", json={"actor_id": "approver1"})
    client.post(f"/push/{eval_id}", json={"actor_id": "approver1"})

    actions = _audit_actions(client, eval_id)
    expected_subset = [
        "uploaded",
        "metadata_extracted",
        "metadata_confirmed",
        "evaluation_generated",
        "sent_for_review",
        "review_accepted",
        "approved",
        "complete_and_pushed",
    ]
    for action in expected_subset:
        assert action in actions, f"Missing {action!r} from happy-path log. Full: {actions}"
