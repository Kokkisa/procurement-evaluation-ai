"""Real-LLM smoke test for MetadataExtractionAgent and CriteriaExtractionAgent
against the synthetic fixture tender.

Skipped by default — set ``RUN_LIVE_LLM_TESTS=1`` and ensure
``ANTHROPIC_API_KEY`` is set in ``.env`` (or the environment) before running:

    RUN_LIVE_LLM_TESTS=1 .venv/Scripts/python.exe -m pytest tests/test_smoke_agents.py -v -s

Prints extracted metadata, the criteria list, and a token / cost summary at
the end (cost computed at Claude Sonnet 4.5 base list rates).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from proceval.agents import CriteriaExtractionAgent, MetadataExtractionAgent
from proceval.config import settings
from proceval.ingestion import extract_text
from proceval.llm_factory import get_chat_model

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real-LLM tests",
)

TENDER_PDF = Path(__file__).parent / "fixtures" / "tender_housekeeping_demo.pdf"

# Claude Sonnet 4.5 base list pricing (USD per 1M tokens) at the 200K-context tier.
PRICE_INPUT_PER_MTOK = 3.00
PRICE_OUTPUT_PER_MTOK = 15.00


class TokenCounter(BaseCallbackHandler):
    """Sum input/output tokens across every LLM call routed through this handler."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def on_llm_end(self, response: Any, **_kwargs: Any) -> None:
        self.calls += 1
        # Preferred: per-message usage_metadata on AIMessage
        for gen_list in response.generations or []:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                usage = getattr(msg, "usage_metadata", None) if msg else None
                if usage:
                    self.input_tokens += usage.get("input_tokens", 0)
                    self.output_tokens += usage.get("output_tokens", 0)
                    return
        # Fallback: llm_output dict (older shape)
        usage = (response.llm_output or {}).get("usage") or {}
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)

    def cost_usd(self) -> float:
        return (self.input_tokens / 1_000_000) * PRICE_INPUT_PER_MTOK + (
            self.output_tokens / 1_000_000
        ) * PRICE_OUTPUT_PER_MTOK


@pytest.fixture(scope="module")
def counter() -> TokenCounter:
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not set in .env / environment")
    return TokenCounter()


@pytest.fixture(scope="module")
def model(counter: TokenCounter):
    return get_chat_model(callbacks=[counter])


@pytest.fixture(scope="module")
def tender_text() -> str:
    text, _ = extract_text(TENDER_PDF)
    return text


@pytest.fixture(scope="module")
def extracted_metadata(model, tender_text):
    agent = MetadataExtractionAgent(model=model)
    md = agent.extract(tender_text)
    print("\n--- Extracted metadata ---")
    print(md.model_dump_json(indent=2))
    return md


def test_metadata_extraction(extracted_metadata):
    md = extracted_metadata
    assert md.tender_number == "DEMO/2026/HKP/001"
    assert "Housekeeping" in md.tender_name or "Sanitation" in md.tender_name
    assert "DEMO" in md.issuing_organization.upper() or "Demo" in md.issuing_organization
    assert md.tender_floated_date is not None and md.tender_floated_date.isoformat() == "2026-04-10"
    assert md.tender_due_date is not None and md.tender_due_date.isoformat() == "2026-04-30"


def test_criteria_extraction(model, tender_text, extracted_metadata):
    agent = CriteriaExtractionAgent(model=model)
    rubric = agent.extract(tender_text, extracted_metadata)

    print(
        f"\n--- Extracted {len(rubric.technical_criteria)} technical, "
        f"{len(rubric.commercial_criteria)} commercial criteria ---"
    )
    for c in rubric.technical_criteria:
        print(f"  T  {c.id:<30} {c.name}  (threshold={c.threshold_value})")
    for c in rubric.commercial_criteria:
        print(f"  C  {c.id:<30} {c.name}")

    # The synthetic tender has 7 PQC items + 8 special conditions = 15 criteria
    assert len(rubric.technical_criteria) >= 5, (
        f"Expected >=5 technical criteria, got {len(rubric.technical_criteria)}"
    )
    # PQC-1 is the financial turnover threshold; some agent run should surface it
    has_turnover_criterion = any(
        "turnover" in c.name.lower()
        or "financial" in c.name.lower()
        or (c.threshold_value == 100.0 and c.msme_relaxation_value == 85.0)
        for c in rubric.technical_criteria
    )
    assert has_turnover_criterion, "PQC-1 turnover criterion not found"

    # PQC-2 similar work threshold should also be extracted
    has_similar_work = any(
        "similar" in c.name.lower() or "experience" in c.name.lower()
        for c in rubric.technical_criteria
    )
    assert has_similar_work, "PQC-2 similar-works criterion not found"

    # PAN, GST, Udyam, Blacklisting decl should appear as document criteria
    doc_ids_text = " ".join((c.id + " " + c.name).upper() for c in rubric.technical_criteria)
    for needle in ("PAN", "GST", "BLACK"):
        assert needle in doc_ids_text, f"Expected document criterion mentioning {needle!r}"


def test_cost_summary(counter: TokenCounter):
    """Always-pass test that prints the cost burned by this module's calls."""
    print("\n--- Block 5 smoke-test usage ---")
    print(f"  LLM calls       : {counter.calls}")
    print(f"  Input tokens    : {counter.input_tokens:,}")
    print(f"  Output tokens   : {counter.output_tokens:,}")
    print(f"  Estimated cost  : ${counter.cost_usd():.4f} USD")
    print(
        f"  (rates: ${PRICE_INPUT_PER_MTOK:.2f}/MTok input, "
        f"${PRICE_OUTPUT_PER_MTOK:.2f}/MTok output)"
    )
