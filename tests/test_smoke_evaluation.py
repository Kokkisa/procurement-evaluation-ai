"""Real-LLM smoke test for VendorEvaluationAgent against the 5 synthetic vendors.

Loads the 7 core PQC criteria (hand-defined to match the synthetic tender),
concatenates each vendor's documents into a text blob, runs per-(vendor,
criterion) calls in parallel via asyncio.gather, and asserts the
gold-standard ACCEPT / REJECT split:

    AROHA FACILITY SERVICES PVT LTD       ACCEPT  (passes via MSME relaxation)
    TEJASWINI HOUSEKEEPING ENTERPRISES    ACCEPT
    SHRI MANGALAM SAFAI WORKS             REJECT  (similar-work PO 38.42 < 85)
    PRABHAT DEEP SANITATION SOLUTIONS     ACCEPT
    RAGHAVENDRA MAINTENANCE WORKS         REJECT  (missing blacklist decl)

Skipped by default. Run with:
    RUN_LIVE_LLM_TESTS=1 .venv/Scripts/python.exe -m pytest tests/test_smoke_evaluation.py -v -s
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from proceval.agents import VendorEvaluationAgent
from proceval.agents.evaluation_agent import load_vendor_documents
from proceval.config import settings
from proceval.ingestion.pdf_parser import extract_text
from proceval.llm_factory import get_chat_model
from proceval.schemas.tender import CriterionType, EvalCriterion
from proceval.schemas.vendor import VendorEvaluation

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real-LLM tests",
)

VENDORS_DIR = Path(__file__).parent / "fixtures" / "synthetic_vendors"

# Claude Sonnet 4.5 base list pricing (USD per 1M tokens).
PRICE_INPUT_PER_MTOK = 3.00
PRICE_OUTPUT_PER_MTOK = 15.00


CORE_CRITERIA: list[EvalCriterion] = [
    EvalCriterion(
        id="PQC_FIN_TURNOVER",
        name="Average Annual Turnover",
        description=(
            "Average annual turnover of not less than Rs. 100 Lakhs over the "
            "most recent three (3) completed financial years (FY 2023-24 / "
            "2022-23 / 2021-22). MSME bidders relaxed to Rs. 85 Lakhs."
        ),
        type=CriterionType.FINANCIAL,
        threshold_value=100.0,
        msme_relaxation_value=85.0,
        aggregation_rule="average",
        source_clause="PQC-1 (Financial)",
    ),
    EvalCriterion(
        id="PQC_TECH_SIMILAR_WORK",
        name="Similar Works Experience",
        description=(
            "At least one (1) similar contract for housekeeping / sanitation "
            "services of value not less than Rs. 100 Lakhs in the last seven "
            "years. MSME bidders relaxed to Rs. 85 Lakhs."
        ),
        type=CriterionType.TECHNICAL,
        threshold_value=100.0,
        msme_relaxation_value=85.0,
        aggregation_rule="single_max",
        source_clause="PQC-2 (Technical — Similar Works)",
    ),
    EvalCriterion(
        id="PQC_DOC_PAN",
        name="PAN Card Submission",
        description="Self-attested copy of PAN card.",
        type=CriterionType.DOCUMENT,
        source_clause="PQC-3 (Document)",
    ),
    EvalCriterion(
        id="PQC_DOC_GST",
        name="GST Registration Certificate",
        description="Self-attested copy of current GST REG-06 certificate.",
        type=CriterionType.DOCUMENT,
        source_clause="PQC-4 (Document)",
    ),
    EvalCriterion(
        id="PQC_DOC_UDYAM_MSME",
        name="Udyam Registration Certificate",
        description=(
            "Self-attested copy of Udyam registration. Mandatory if claiming "
            "MSME relaxation; not applicable otherwise."
        ),
        type=CriterionType.DOCUMENT,
        source_clause="PQC-5 (Document — Conditional)",
    ),
    EvalCriterion(
        id="PQC_DOC_BLACKLIST_DECL",
        name="Blacklisting Declaration",
        description=("Signed declaration on bidder letterhead confirming non-blacklisting."),
        type=CriterionType.DOCUMENT,
        source_clause="PQC-6 (Document)",
    ),
    EvalCriterion(
        id="PQC_DOC_BIDDER_RESPONSE",
        name="Bidder Response Form",
        description="Completed and signed Bidder Response Form per Annexure B.",
        type=CriterionType.DOCUMENT,
        source_clause="PQC-7 (Document)",
    ),
]

VENDORS = [
    ("aroha_facility_services", "AROHA FACILITY SERVICES PVT LTD", True, "ACCEPTED"),
    ("tejaswini_housekeeping_enterprises", "TEJASWINI HOUSEKEEPING ENTERPRISES", False, "ACCEPTED"),
    ("shri_mangalam_safai_works", "SHRI MANGALAM SAFAI WORKS", True, "REJECTED"),
    ("prabhat_deep_sanitation_solutions", "PRABHAT DEEP SANITATION SOLUTIONS", False, "ACCEPTED"),
    ("raghavendra_maintenance_works", "RAGHAVENDRA MAINTENANCE WORKS", False, "REJECTED"),
]


# Per-criterion document filtering. The agent itself stays generic; we filter
# at the smoke-test boundary so each LLM call sees only the documents
# relevant to that one criterion. This keeps per-call input ~1.5K tokens
# (down from ~5K) and avoids tripping low-tier rate limits.
RELEVANT_DOC_PATTERNS: dict[str, list[str]] = {
    "PQC_FIN_TURNOVER": ["audited_balance_sheet_*.pdf"],
    "PQC_TECH_SIMILAR_WORK": ["purchase_order_*.pdf", "work_completion_certificate_*.pdf"],
    "PQC_DOC_PAN": ["pan_card.pdf"],
    "PQC_DOC_GST": ["gst_certificate.pdf"],
    "PQC_DOC_UDYAM_MSME": ["udyam_registration.pdf"],
    "PQC_DOC_BLACKLIST_DECL": ["blacklist_declaration.pdf"],
    "PQC_DOC_BIDDER_RESPONSE": ["bidder_response_form.pdf"],
}


def build_focused_docs_text(vendor_dir: Path, criterion: EvalCriterion) -> str:
    """Build a per-criterion vendor-docs blob: full filename listing for
    missing-doc detection, plus full text of only the relevant document(s).
    """
    all_pdfs = sorted(vendor_dir.glob("*.pdf"))
    listing = "\n".join(f"  - {p.name}" for p in all_pdfs)

    matched: list[Path] = []
    for pattern in RELEVANT_DOC_PATTERNS.get(criterion.id, []):
        matched.extend(sorted(vendor_dir.glob(pattern)))

    header = f"Vendor's submitted documents (full filename listing):\n{listing}\n"
    if not matched:
        return (
            header + "\n[No documents matching the expected pattern for this criterion "
            "are present in the submission.]"
        )

    chunks = [header]
    for p in matched:
        text, _ = extract_text(p)
        chunks.append(f"=== {p.name} ===\n{text}")
    return "\n\n".join(chunks)


async def _evaluate_vendor_with_focused_docs(
    agent: VendorEvaluationAgent,
    criteria: list[EvalCriterion],
    vendor_name: str,
    is_msme: bool,
    vendor_dir: Path,
) -> VendorEvaluation:
    """Per ADR-0007 the agent itself fans out per-(criterion, document); the
    Block 6 focused-docs trick is obsolete. We now load every document and let
    the agent's per-doc NOT_APPLICABLE verdict do the filtering at the
    aggregator. ``build_focused_docs_text`` + ``RELEVANT_DOC_PATTERNS`` above
    are kept for reference / ad-hoc inspection but no longer used here."""
    documents = load_vendor_documents(vendor_dir)
    return await agent.aevaluate_vendor_full(criteria, vendor_name, is_msme, documents)


class TokenCounter(BaseCallbackHandler):
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def on_llm_end(self, response: Any, **_kwargs: Any) -> None:
        self.calls += 1
        for gen_list in response.generations or []:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                usage = getattr(msg, "usage_metadata", None) if msg else None
                if usage:
                    self.input_tokens += usage.get("input_tokens", 0)
                    self.output_tokens += usage.get("output_tokens", 0)
                    return
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
def all_vendor_evaluations(counter):
    """Evaluate all 5 vendors once and share results across the test functions.

    Uses ``max_concurrency=2`` and ``max_retries=10`` on the chat model so SDK
    backoff smooths over any 429s from low-tier rate limits during the burst.
    """
    model = get_chat_model(callbacks=[counter], max_retries=10)
    agent = VendorEvaluationAgent(model=model, max_concurrency=2)
    out = {}
    print()
    for slug, name, is_msme, _ in VENDORS:
        full = asyncio.run(
            _evaluate_vendor_with_focused_docs(
                agent, CORE_CRITERIA, name, is_msme, VENDORS_DIR / slug
            )
        )
        out[slug] = full
        print(f"  {name:<40} -> {full.overall_verdict}")
        print(f"    remarks: {full.overall_remarks}")
    return out


def test_gold_standard_accept_reject_split(all_vendor_evaluations):
    """The 5-vendor verdict split must match the spec's expected outcome."""
    failures = []
    for slug, name, _, expected in VENDORS:
        actual = all_vendor_evaluations[slug].overall_verdict
        if actual != expected:
            failures.append(f"  {name}: expected {expected}, got {actual}")
    assert not failures, "Gold-standard split mismatch:\n" + "\n".join(failures)


def test_aroha_passes_via_msme_relaxation(all_vendor_evaluations):
    """AROHA's 88.23-lakh turnover passes only because of MSME relaxation
    (>= 85 relaxed but < 100 standard). Verify the per-criterion result."""
    aroha = all_vendor_evaluations["aroha_facility_services"]
    turnover = next(e for e in aroha.criterion_evaluations if e.criterion_id == "PQC_FIN_TURNOVER")
    assert turnover.verdict == "VALUE"
    assert turnover.threshold_met is True, (
        f"AROHA turnover should pass (88.23 >= 85 MSME); got threshold_met={turnover.threshold_met!r} "
        f"with extracted_value={turnover.extracted_value!r}"
    )


def test_shri_mangalam_fails_similar_work_specifically(all_vendor_evaluations):
    """SHRI MANGALAM rejects on similar-work PO 38.42 < 85 (MSME-relaxed),
    not on turnover (which passes at ~92.70)."""
    shri = all_vendor_evaluations["shri_mangalam_safai_works"]

    similar_work = next(
        e for e in shri.criterion_evaluations if e.criterion_id == "PQC_TECH_SIMILAR_WORK"
    )
    assert similar_work.verdict == "VALUE"
    assert similar_work.threshold_met is False, (
        f"SHRI MANGALAM similar-work should fail (38.42 < 85 MSME-relaxed); "
        f"got threshold_met={similar_work.threshold_met!r}, extracted_value={similar_work.extracted_value!r}"
    )

    turnover = next(e for e in shri.criterion_evaluations if e.criterion_id == "PQC_FIN_TURNOVER")
    assert turnover.threshold_met is True, (
        f"SHRI MANGALAM turnover should pass (92.70 >= 85 MSME); got threshold_met={turnover.threshold_met!r}"
    )

    # Remarks should specifically mention the similar-work failure
    assert "Similar Works" in shri.overall_remarks
    assert "38.42" in shri.overall_remarks


def test_raghavendra_fails_on_missing_blacklist_declaration(all_vendor_evaluations):
    rag = all_vendor_evaluations["raghavendra_maintenance_works"]
    blacklist = next(
        e for e in rag.criterion_evaluations if e.criterion_id == "PQC_DOC_BLACKLIST_DECL"
    )
    assert blacklist.verdict == "NOT_PROVIDED", (
        f"RAGHAVENDRA blacklist declaration should be NOT_PROVIDED; "
        f"got {blacklist.verdict!r}: {blacklist.reasoning!r}"
    )
    assert "Blacklisting Declaration" in rag.overall_remarks
    assert "did not provide" in rag.overall_remarks.lower()


def test_cost_summary(counter: TokenCounter, all_vendor_evaluations):
    print("\n--- Block 6 smoke-test usage ---")
    print(f"  LLM calls       : {counter.calls}")
    print(f"  Input tokens    : {counter.input_tokens:,}")
    print(f"  Output tokens   : {counter.output_tokens:,}")
    print(f"  Estimated cost  : ${counter.cost_usd():.4f} USD")
    print(
        f"  (rates: ${PRICE_INPUT_PER_MTOK:.2f}/MTok input, ${PRICE_OUTPUT_PER_MTOK:.2f}/MTok output)"
    )
