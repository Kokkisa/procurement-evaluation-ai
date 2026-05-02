"""Regression baseline for the Criteria Extraction Agent.

Runs the agent live against the synthetic housekeeping tender and asserts the
invariants encoded in tests/fixtures/expected_criteria.json:

- All 7 ``core_required`` PQC criteria are present with the expected IDs.
- Their threshold_value matches the ground truth (None for document-only items;
  100.0 for the financial and similar-works thresholds).
- At minimum 12 total criteria are extracted.

The agent_inferred extras (Special Conditions items, EMD, etc.) are tolerated
to vary in count and ID across runs — LLM non-determinism is fine there.

Skipped by default. Run with:
    RUN_LIVE_LLM_TESTS=1 .venv/Scripts/python.exe -m pytest tests/test_criteria_regression.py -v -s
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from proceval.agents import CriteriaExtractionAgent, MetadataExtractionAgent
from proceval.config import settings
from proceval.ingestion import extract_text

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real-LLM tests",
)

FIXTURES = Path(__file__).parent / "fixtures"
TENDER_PDF = FIXTURES / "tender_housekeeping_demo.pdf"
GROUND_TRUTH = FIXTURES / "expected_criteria.json"


@pytest.fixture(scope="module")
def ground_truth() -> dict:
    return json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def extracted_rubric():
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not set in .env / environment")
    text, _ = extract_text(TENDER_PDF)
    metadata = MetadataExtractionAgent().extract(text)
    rubric = CriteriaExtractionAgent().extract(text, metadata)
    print(
        f"\n[regression] extracted {len(rubric.technical_criteria)} technical + "
        f"{len(rubric.commercial_criteria)} commercial = "
        f"{len(rubric.technical_criteria) + len(rubric.commercial_criteria)} total"
    )
    return rubric


def _all_criteria(rubric):
    return rubric.technical_criteria + rubric.commercial_criteria


def test_total_criteria_meets_minimum(extracted_rubric, ground_truth):
    minimum = ground_truth["regression_invariants"]["min_total_criteria"]
    total = len(_all_criteria(extracted_rubric))
    assert total >= minimum, (
        f"Expected at least {minimum} criteria, got {total}. "
        "The agent may be regressing on completeness."
    )


def test_all_core_required_ids_present(extracted_rubric, ground_truth):
    extracted_ids = {c.id for c in _all_criteria(extracted_rubric)}
    expected_ids = set(ground_truth["regression_invariants"]["core_required_ids"])
    missing = expected_ids - extracted_ids
    assert not missing, (
        f"Core PQC criteria missing from extraction: {sorted(missing)}. "
        f"Got: {sorted(extracted_ids)}"
    )


def test_core_threshold_values_match(extracted_rubric, ground_truth):
    by_id = {c.id: c for c in _all_criteria(extracted_rubric)}
    failures: list[str] = []
    for expected in ground_truth["core_required"]:
        actual = by_id.get(expected["id"])
        if actual is None:
            # Missing-ID failure is the previous test's job; don't double-report.
            continue
        if actual.threshold_value != expected["threshold_value"]:
            failures.append(
                f"  {expected['id']}: expected threshold_value={expected['threshold_value']!r}, "
                f"got {actual.threshold_value!r}"
            )
    assert not failures, "Core threshold mismatches:\n" + "\n".join(failures)


def test_core_types_match(extracted_rubric, ground_truth):
    """Per the ground truth, each core PQC item has a fixed type
    (financial / technical / document). A type drift is a regression."""
    by_id = {c.id: c for c in _all_criteria(extracted_rubric)}
    failures: list[str] = []
    for expected in ground_truth["core_required"]:
        actual = by_id.get(expected["id"])
        if actual is None:
            continue
        if actual.type.value != expected["type"]:
            failures.append(
                f"  {expected['id']}: expected type={expected['type']!r}, "
                f"got {actual.type.value!r}"
            )
    assert not failures, "Core type mismatches:\n" + "\n".join(failures)
