"""UI smoke tests.

Streamlit UI is hard to unit-test rigorously without Selenium / AppTest, so
the bar here is intentionally light: every module imports without error, the
matrix renderer produces sane HTML for a synthetic payload, and the api_client
constructs the right request shapes.

The integration story is "the UI calls FastAPI; FastAPI is rigorously tested
in test_api.py; we trust the seam."
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

UI_MODULES = [
    "ui.api_client",
    "ui.state",
    "ui.styles",
    "ui.streamlit_app",
    "ui.components.role_switcher",
    "ui.components.matrix_table",
    "ui.components.audit_log",
    "ui.screens.upload",
    "ui.screens.confirmation",
    "ui.screens.matrix",
    "ui.screens.review",
    "ui.screens.approve",
    "ui.screens.final",
]


@pytest.mark.parametrize("module_name", UI_MODULES)
def test_ui_module_imports(module_name):
    """Every UI module must import without touching st.* runtime state."""
    importlib.import_module(module_name)


# --- api_client request-shape sanity --------------------------------------


def test_api_client_uses_default_url_and_overridable_via_env(monkeypatch):
    from ui.api_client import _base

    monkeypatch.delenv("PROCEVAL_API_URL", raising=False)
    assert _base() == "http://localhost:8000"

    monkeypatch.setenv("PROCEVAL_API_URL", "http://staging.example.com:9000/")
    assert _base() == "http://staging.example.com:9000"


def test_api_client_ingest_builds_multipart_with_actor_and_files():
    from ui import api_client

    with patch("ui.api_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            json=lambda: {"eval_id": "00000000-0000-0000-0000-000000000001"},
            raise_for_status=lambda: None,
        )
        api_client.ingest(
            actor_id="preparer1",
            tender=("tender.pdf", b"PDF-bytes"),
            vendor_files=[("v1.pdf", b"V1"), ("v2.zip", b"V2")],
        )

    args, kwargs = mock_post.call_args
    assert args[0].endswith("/ingest")
    assert kwargs["data"] == {"actor_id": "preparer1"}
    files = kwargs["files"]
    # tender first, then vendor_files in input order
    assert files[0][0] == "tender"
    assert files[0][1][0] == "tender.pdf"
    assert files[0][1][2] == "application/pdf"
    assert files[1][0] == "vendor_files"
    assert files[1][1][2] == "application/pdf"
    assert files[2][0] == "vendor_files"
    assert files[2][1][2] == "application/zip"


def test_api_client_review_reject_posts_feedback_text():
    from ui import api_client

    with patch("ui.api_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            json=lambda: {"iteration": 2}, raise_for_status=lambda: None
        )
        api_client.review_reject(eval_id="abc", actor_id="rev1", feedback_text="Re-check vendor 3")

    args, kwargs = mock_post.call_args
    assert "/review/abc/reject" in args[0]
    assert kwargs["json"] == {
        "actor_id": "rev1",
        "feedback_text": "Re-check vendor 3",
    }


# --- matrix_table HTML output ---------------------------------------------


def test_matrix_table_emits_classes_for_each_verdict_kind():
    from ui.components.matrix_table import _build_html

    criteria = [
        {
            "id": "PQC_FIN_TURNOVER",
            "name": "Average Annual Turnover",
            "type": "financial",
            "threshold_value": 100.0,
            "msme_relaxation_value": 85.0,
            "aggregation_rule": "average",
            "source_clause": "PQC-1",
        },
        {
            "id": "PQC_DOC_PAN",
            "name": "PAN Card",
            "type": "document",
            "threshold_value": None,
            "msme_relaxation_value": None,
            "aggregation_rule": None,
        },
        {
            "id": "PQC_DOC_BLACKLIST_DECL",
            "name": "Blacklisting Declaration",
            "type": "document",
            "threshold_value": None,
        },
        {
            "id": "PQC_DOC_BIDDER_RESPONSE",
            "name": "Bidder Response Form",
            "type": "document",
        },
    ]
    vendors = [
        {
            "vendor_name": "AROHA",
            "is_msme": True,
            "overall_verdict": "ACCEPTED",
            "overall_remarks": "All ok",
            "criterion_evaluations": [
                {
                    "criterion_id": "PQC_FIN_TURNOVER",
                    "verdict": "VALUE",
                    "extracted_value": "88.23 LAKHS",
                    "threshold_met": True,
                    "reasoning": "Mean of 3 FYs.",
                },
                {
                    "criterion_id": "PQC_DOC_PAN",
                    "verdict": "PROVIDED",
                    "reasoning": "PAN found.",
                },
                {
                    "criterion_id": "PQC_DOC_BLACKLIST_DECL",
                    "verdict": "PARTIAL",
                    "reasoning": "Decl present but unsigned.",
                },
                {
                    "criterion_id": "PQC_DOC_BIDDER_RESPONSE",
                    "verdict": "NOT_PROVIDED",
                    "reasoning": "Form missing.",
                },
            ],
        }
    ]

    html = _build_html(criteria, vendors)
    assert 'class="proceval-matrix"' in html
    assert "AROHA" in html
    assert "msme-badge" in html  # MSME flag rendered
    assert "cell-pass" in html  # PROVIDED + VALUE-with-threshold-met
    assert "cell-fail" in html  # NOT_PROVIDED
    assert "cell-partial" in html
    assert "OVERALL REMARKS" in html
    assert "ACCEPTED" in html
    assert "88.23 LAKHS" in html


def test_matrix_table_handles_missing_evaluation_for_a_criterion():
    """If a criterion has no matching CriterionEvaluation, render N/A."""
    from ui.components.matrix_table import _build_html

    criteria = [{"id": "X", "name": "X", "type": "document"}]
    vendors = [
        {
            "vendor_name": "V",
            "is_msme": False,
            "overall_verdict": "ACCEPTED",
            "overall_remarks": "",
            "criterion_evaluations": [],
        }
    ]
    html = _build_html(criteria, vendors)
    assert "cell-na" in html


def test_matrix_table_value_with_threshold_not_met_is_red():
    from ui.components.matrix_table import _build_html

    criteria = [
        {
            "id": "PQC_TECH_SIMILAR_WORK",
            "name": "Similar Works",
            "threshold_value": 100.0,
            "msme_relaxation_value": 85.0,
        }
    ]
    vendors = [
        {
            "vendor_name": "V",
            "is_msme": True,
            "overall_verdict": "REJECTED",
            "overall_remarks": "below threshold",
            "criterion_evaluations": [
                {
                    "criterion_id": "PQC_TECH_SIMILAR_WORK",
                    "verdict": "VALUE",
                    "extracted_value": "38.42 LAKHS",
                    "threshold_met": False,
                    "reasoning": "Below MSME-relaxed threshold.",
                }
            ],
        }
    ]
    html = _build_html(criteria, vendors)
    assert "cell-fail" in html
    assert "38.42 LAKHS" in html
    assert "REJECTED" in html
