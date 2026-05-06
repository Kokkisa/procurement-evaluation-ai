"""Mocked unit tests for VendorEvaluationAgent (per-document fan-out per ADR-0007).

The LLM call shape is now per-(vendor, criterion, document). Stubs return
``VerdictPerDoc`` (the new per-doc LLM-output schema) and the deterministic
``aggregate_document_verdicts`` collapses them into ``CriterionEvaluation``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda

from proceval.agents import VendorEvaluationAgent
from proceval.agents.evaluation_agent import (
    VendorDocument,
    concatenate_vendor_docs,
    load_vendor_documents,
)
from proceval.schemas.tender import CriterionType, EvalCriterion
from proceval.schemas.vendor import CriterionEvaluation, VerdictPerDoc


# --- Stub models -----------------------------------------------------------


class _MappingStubLLM:
    """Maps prompt -> result by detecting ``'ID: <criterion_id>'`` in the prompt
    text. Lets parallel per-doc calls map deterministically to expected outputs.
    """

    def __init__(self, results: dict[str, object]):
        self._results = dict(results)
        self.calls: list[str] = []

    def with_structured_output(self, _schema, **_kw):
        def _fn(prompt_value):
            text = (
                prompt_value.to_string()
                if hasattr(prompt_value, "to_string")
                else str(prompt_value)
            )
            self.calls.append(text)
            for cid, r in self._results.items():
                if f"ID: {cid}" in text:
                    if isinstance(r, Exception):
                        raise r
                    return r
            raise RuntimeError(
                f"_MappingStubLLM: no key matched in prompt. Keys: {list(self._results)}"
            )

        return RunnableLambda(_fn)


class _ListStubLLM:
    """Yields predetermined results in invocation order. For retry tests."""

    def __init__(self, results: list):
        self._results = list(results)
        self.calls: list[str] = []

    def with_structured_output(self, _schema, **_kw):
        def _fn(prompt_value):
            text = (
                prompt_value.to_string()
                if hasattr(prompt_value, "to_string")
                else str(prompt_value)
            )
            self.calls.append(text)
            if not self._results:
                raise RuntimeError("_ListStubLLM exhausted")
            r = self._results.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        return RunnableLambda(_fn)


# --- Helpers ---------------------------------------------------------------


def _crit(
    id_: str,
    name: str = "Criterion",
    type_: CriterionType = CriterionType.DOCUMENT,
    **kw,
) -> EvalCriterion:
    return EvalCriterion(
        id=id_, name=name, description=f"{name} requirement.", type=type_, **kw
    )


def _doc(filename: str, text: str = "doc body text") -> VendorDocument:
    return VendorDocument(filename=filename, text=text)


def _vpd(
    verdict: str = "MEETS",
    *,
    extracted_value: str | None = None,
    reasoning: str = "ok",
    source_document: str = "doc.pdf",
) -> VerdictPerDoc:
    return VerdictPerDoc(
        verdict=verdict,
        extracted_value=extracted_value,
        reasoning=reasoning,
        source_document=source_document,
    )


# --- aggregate_document_verdicts (deterministic; no LLM) ------------------


def test_aggregate_all_meets_returns_meets():
    crit = _crit("PQC_DOC_PAN", name="PAN")
    verdicts = [
        _vpd("MEETS", source_document="pan.pdf", reasoning="PAN found"),
        _vpd(
            "MEETS",
            extracted_value="ABCDE1234F",
            source_document="bidder_form.pdf",
            reasoning="PAN echoed in bidder form",
        ),
    ]
    result = VendorEvaluationAgent.aggregate_document_verdicts(crit, verdicts)

    # First MEETS wins; here that's the doc-existence one (no extracted_value),
    # so verdict collapses to PROVIDED, not VALUE.
    assert isinstance(result, CriterionEvaluation)
    assert result.criterion_id == "PQC_DOC_PAN"
    assert result.verdict == "PROVIDED"
    assert result.source_document == "pan.pdf"
    assert result.threshold_met is None
    assert result.confidence > 0.5


def test_aggregate_all_does_not_meet_returns_does_not_meet_with_strongest_evidence():
    crit = _crit(
        "PQC_TECH_SIMILAR_WORK",
        name="Similar Works Experience",
        threshold_value=100.0,
        msme_relaxation_value=85.0,
    )
    weak = _vpd(
        "DOES_NOT_MEET",
        extracted_value="22.76 LAKHS",
        reasoning="below threshold",
        source_document="po1.pdf",
    )
    strong = _vpd(
        "DOES_NOT_MEET",
        extracted_value="38.42 LAKHS",
        reasoning=(
            "Single PO with ARYA PACKAGING for 38.42 lakhs falls well below "
            "the MSME-relaxed 85L threshold; vendor cannot satisfy PQC-2 "
            "from this submission."
        ),
        source_document="po_arya.pdf",
    )
    # "Strongest negative" = longest reasoning; order in input shouldn't matter.
    result = VendorEvaluationAgent.aggregate_document_verdicts(crit, [weak, strong])

    assert result.verdict == "VALUE"  # because extracted_value present
    assert result.threshold_met is False
    assert result.source_document == "po_arya.pdf"
    assert "ARYA PACKAGING" in result.reasoning
    assert result.extracted_value == "38.42 LAKHS"


def test_aggregate_mixed_any_meets_wins():
    """Any MEETS in the list wins, regardless of how many DOES_NOT_MEET sit
    around it. This is the spec's load-bearing rule for ADR-0007."""
    crit = _crit(
        "PQC_TECH_SIMILAR_WORK",
        name="Similar Works",
        threshold_value=100.0,
    )
    verdicts = [
        _vpd("DOES_NOT_MEET", extracted_value="50 L", reasoning="too small", source_document="po_a.pdf"),
        _vpd("NOT_APPLICABLE", reasoning="not relevant", source_document="pan.pdf"),
        _vpd(
            "MEETS",
            extracted_value="118.50 LAKHS",
            reasoning="Single PO with MERIDIAN MANUFACTURING comfortably exceeds the threshold.",
            source_document="po_meridian.pdf",
        ),
        _vpd("DOES_NOT_MEET", extracted_value="20 L", reasoning="even smaller", source_document="po_c.pdf"),
    ]
    result = VendorEvaluationAgent.aggregate_document_verdicts(crit, verdicts)

    assert result.verdict == "VALUE"
    assert result.threshold_met is True
    assert result.source_document == "po_meridian.pdf"
    assert result.extracted_value == "118.50 LAKHS"


def test_aggregate_all_not_applicable_returns_not_applicable():
    """If every doc says NOT_APPLICABLE, the criterion is unevaluable from the
    submitted documents. Surface as PARTIAL so verdict.compute_overall_verdict()
    flags it for human review per ADR-0007."""
    crit = _crit("PQC_DOC_BLACKLIST_DECL", name="Blacklisting Declaration")
    verdicts = [
        _vpd("NOT_APPLICABLE", reasoning="this is a PAN card", source_document="pan.pdf"),
        _vpd("NOT_APPLICABLE", reasoning="this is a GST cert", source_document="gst.pdf"),
        _vpd("NOT_APPLICABLE", reasoning="this is a balance sheet", source_document="bs.pdf"),
    ]
    result = VendorEvaluationAgent.aggregate_document_verdicts(crit, verdicts)

    assert result.verdict == "PARTIAL"
    assert result.source_document is None
    assert "human review" in result.reasoning.lower()
    # PARTIAL drives REJECTED in verdict.py; that's the correct fail-safe.


def test_aggregate_empty_list_treated_as_unevaluable():
    """Defensive: zero documents shouldn't crash; treated like all NOT_APPLICABLE."""
    crit = _crit("PQC_DOC_PAN")
    result = VendorEvaluationAgent.aggregate_document_verdicts(crit, [])
    assert result.verdict == "PARTIAL"


# --- aevaluate_vendor_document (single LLM call) --------------------------


def test_aevaluate_vendor_document_returns_pydantic_instance():
    expected = _vpd(
        "MEETS",
        extracted_value="118.50 LAKHS",
        source_document="po_meridian.pdf",
        reasoning="Single PO of 118.50L",
    )
    stub = _MappingStubLLM({"PQC_TECH_SIMILAR_WORK": expected})
    agent = VendorEvaluationAgent(model=stub)

    result = asyncio.run(
        agent.aevaluate_vendor_document(
            vendor_name="VENDOR-A",
            is_msme=False,
            criterion=_crit("PQC_TECH_SIMILAR_WORK", name="Similar Works"),
            document=_doc("po_meridian.pdf", "PURCHASE ORDER ... 118.50 LAKHS ..."),
        )
    )

    assert isinstance(result, VerdictPerDoc)
    assert result.verdict == "MEETS"
    assert result.source_document == "po_meridian.pdf"


def test_aevaluate_vendor_document_renders_filename_and_doc_text_into_prompt():
    expected = _vpd("NOT_APPLICABLE", source_document="pan.pdf", reasoning="not relevant")
    stub = _MappingStubLLM({"PQC_TECH_SIMILAR_WORK": expected})
    agent = VendorEvaluationAgent(model=stub)

    asyncio.run(
        agent.aevaluate_vendor_document(
            vendor_name="VENDOR-Z",
            is_msme=True,
            criterion=_crit(
                "PQC_TECH_SIMILAR_WORK",
                name="Similar Works",
                type_=CriterionType.TECHNICAL,
                threshold_value=100.0,
                msme_relaxation_value=85.0,
                aggregation_rule="single_max",
            ),
            document=_doc("pan_card.pdf", "PAN-CARD-BODY-SENTINEL"),
        )
    )

    prompt = stub.calls[0]
    assert "ID: PQC_TECH_SIMILAR_WORK" in prompt
    assert "VENDOR-Z" in prompt
    assert "True" in prompt  # is_msme
    assert "pan_card.pdf" in prompt
    assert "PAN-CARD-BODY-SENTINEL" in prompt
    assert "100.00" in prompt
    assert "85.00" in prompt
    assert "single_max" in prompt


def test_aevaluate_vendor_document_overrides_source_document_if_llm_drifts():
    """LLMs sometimes echo a different filename in source_document; the
    agent forces the canonical one we passed in."""
    drifted = _vpd("MEETS", source_document="WRONG_FILENAME.pdf", reasoning="x")
    stub = _MappingStubLLM({"PQC_DOC_PAN": drifted})
    agent = VendorEvaluationAgent(model=stub)

    result = asyncio.run(
        agent.aevaluate_vendor_document(
            vendor_name="V",
            is_msme=False,
            criterion=_crit("PQC_DOC_PAN"),
            document=_doc("real_pan.pdf"),
        )
    )

    assert result.source_document == "real_pan.pdf"


def test_aevaluate_vendor_document_retries_on_validation_error_then_succeeds():
    expected = _vpd("MEETS", source_document="d.pdf")
    stub = _ListStubLLM([OutputParserException("bad output 1"), expected])
    agent = VendorEvaluationAgent(model=stub, max_retries=2)

    result = asyncio.run(
        agent.aevaluate_vendor_document(
            vendor_name="V",
            is_msme=False,
            criterion=_crit("PQC_DOC_PAN"),
            document=_doc("d.pdf"),
        )
    )

    assert isinstance(result, VerdictPerDoc)
    assert len(stub.calls) == 2
    assert "previous output failed" in stub.calls[1].lower()


def test_aevaluate_vendor_document_raises_after_max_retries():
    stub = _ListStubLLM([OutputParserException(f"err{i}") for i in range(5)])
    agent = VendorEvaluationAgent(model=stub, max_retries=2)
    with pytest.raises(OutputParserException, match="err2"):
        asyncio.run(
            agent.aevaluate_vendor_document(
                vendor_name="V",
                is_msme=False,
                criterion=_crit("PQC_DOC_PAN"),
                document=_doc("d.pdf"),
            )
        )
    assert len(stub.calls) == 3  # 1 initial + 2 retries


def test_aevaluate_vendor_document_warns_above_token_threshold(caplog, monkeypatch):
    """Above 50K estimated tokens, log a WARNING but still proceed."""
    expected = _vpd("MEETS", source_document="huge.pdf")
    stub = _MappingStubLLM({"PQC_DOC_PAN": expected})
    agent = VendorEvaluationAgent(model=stub)

    huge_text = "x" * (60_000 * 4)  # ~60K estimated tokens

    with caplog.at_level("WARNING", logger="proceval.agents.evaluation_agent"):
        asyncio.run(
            agent.aevaluate_vendor_document(
                vendor_name="V",
                is_msme=False,
                criterion=_crit("PQC_DOC_PAN"),
                document=_doc("huge.pdf", huge_text),
            )
        )

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("estimated at" in r.message and "tokens" in r.message for r in warnings), (
        f"expected over-budget warning, got: {[r.message for r in warnings]}"
    )


# --- Per-vendor fan-out (criteria x documents = N x M LLM calls) ---------


def test_aevaluate_vendor_fans_out_across_criteria_and_documents():
    """ADR-0007 load-bearing test. 3 docs x 2 criteria => exactly 6 LLM calls."""
    criteria = [_crit("C1"), _crit("C2")]
    documents = [_doc("d1.pdf"), _doc("d2.pdf"), _doc("d3.pdf")]
    # Stub returns MEETS for both criteria, regardless of doc
    stub = _MappingStubLLM({c.id: _vpd("MEETS", source_document="placeholder") for c in criteria})
    agent = VendorEvaluationAgent(model=stub, inter_batch_sleep_seconds=0)

    results = asyncio.run(
        agent.aevaluate_vendor(criteria, "V", False, documents)
    )

    # One CriterionEvaluation per criterion (aggregated across docs)
    assert len(results) == 2
    # 3 docs * 2 criteria = 6 LLM calls
    assert len(stub.calls) == 6, (
        f"expected 6 LLM calls (3 docs x 2 criteria), got {len(stub.calls)}"
    )


def test_aevaluate_vendor_preserves_input_criterion_order_in_results():
    criteria = [_crit("A"), _crit("B"), _crit("C"), _crit("D"), _crit("E")]
    documents = [_doc("only.pdf")]
    stub = _MappingStubLLM(
        {c.id: _vpd("MEETS", source_document="only.pdf") for c in criteria}
    )
    agent = VendorEvaluationAgent(model=stub, inter_batch_sleep_seconds=0)

    out = asyncio.run(agent.aevaluate_vendor(criteria, "V", False, documents))

    assert [e.criterion_id for e in out] == ["A", "B", "C", "D", "E"]


def test_aevaluate_vendor_respects_concurrency_limit():
    """With max_concurrency=1 every concurrent_calls observation should be 1,
    even though we now have multiple criteria each fanning out to multiple docs."""
    criteria = [_crit(f"C{i}") for i in range(3)]
    documents = [_doc(f"d{i}.pdf") for i in range(3)]
    in_flight = {"current": 0, "max_seen": 0}

    class _CountingStub:
        def __init__(self):
            self.calls: list[str] = []

        def with_structured_output(self, _s, **_k):
            async def _afn(prompt_value):
                in_flight["current"] += 1
                in_flight["max_seen"] = max(in_flight["max_seen"], in_flight["current"])
                await asyncio.sleep(0)
                in_flight["current"] -= 1
                text = (
                    prompt_value.to_string()
                    if hasattr(prompt_value, "to_string")
                    else str(prompt_value)
                )
                self.calls.append(text)
                for c in criteria:
                    if f"ID: {c.id}" in text:
                        return _vpd("MEETS", source_document="d.pdf")
                raise RuntimeError("no match")

            return RunnableLambda(_afn)

    stub = _CountingStub()
    agent = VendorEvaluationAgent(
        model=stub, max_concurrency=1, inter_batch_sleep_seconds=0
    )
    asyncio.run(agent.aevaluate_vendor(criteria, "V", False, documents))
    assert in_flight["max_seen"] == 1


def test_aevaluate_vendor_caps_concurrency_at_LLM_MAX_CONCURRENCY():
    """4 criteria x 3 docs = 12 LLM calls, capped at 3 concurrent."""
    criteria = [_crit(f"C{i}") for i in range(4)]
    documents = [_doc(f"d{i}.pdf") for i in range(3)]
    in_flight = {"current": 0, "max_seen": 0}

    class _CountingStub:
        def with_structured_output(self, _s, **_k):
            async def _afn(prompt_value):
                in_flight["current"] += 1
                in_flight["max_seen"] = max(in_flight["max_seen"], in_flight["current"])
                await asyncio.sleep(0.01)
                in_flight["current"] -= 1
                text = (
                    prompt_value.to_string()
                    if hasattr(prompt_value, "to_string")
                    else str(prompt_value)
                )
                for c in criteria:
                    if f"ID: {c.id}" in text:
                        return _vpd("MEETS", source_document="d.pdf")
                raise RuntimeError("no match")

            return RunnableLambda(_afn)

    agent = VendorEvaluationAgent(
        model=_CountingStub(), max_concurrency=3, inter_batch_sleep_seconds=0
    )
    asyncio.run(agent.aevaluate_vendor(criteria, "V", False, documents))
    assert in_flight["max_seen"] <= 3, (
        f"Concurrency cap broken: peaked at {in_flight['max_seen']} with cap=3."
    )


def test_aevaluate_vendor_logs_throttle_decisions(caplog):
    criteria = [_crit(f"C{i}") for i in range(5)]
    documents = [_doc("d.pdf")]
    stub = _MappingStubLLM(
        {c.id: _vpd("MEETS", source_document="d.pdf") for c in criteria}
    )
    agent = VendorEvaluationAgent(
        model=stub, max_concurrency=2, inter_batch_sleep_seconds=0.01
    )

    with caplog.at_level("INFO", logger="proceval.agents.evaluation_agent"):
        asyncio.run(agent.aevaluate_vendor(criteria, "V", False, documents))

    messages = [r.message for r in caplog.records]
    assert any("Acquired LLM slot" in m for m in messages)
    assert any("Sleeping" in m and "before batch" in m for m in messages)


def test_inter_batch_sleep_zero_skips_sleep_log(caplog):
    criteria = [_crit(f"C{i}") for i in range(4)]
    documents = [_doc("d.pdf")]
    stub = _MappingStubLLM(
        {c.id: _vpd("MEETS", source_document="d.pdf") for c in criteria}
    )
    agent = VendorEvaluationAgent(
        model=stub, max_concurrency=2, inter_batch_sleep_seconds=0
    )

    with caplog.at_level("INFO", logger="proceval.agents.evaluation_agent"):
        asyncio.run(agent.aevaluate_vendor(criteria, "V", False, documents))

    assert not any(
        "Sleeping" in r.message and "before batch" in r.message
        for r in caplog.records
    )


# --- Sync wrapper + verdict roll-up ---------------------------------------


def test_evaluate_vendor_returns_full_VendorEvaluation_with_accepted_verdict():
    criteria = [_crit("PQC_DOC_PAN", name="PAN"), _crit("PQC_DOC_GST", name="GST")]
    documents = [_doc("pan.pdf"), _doc("gst.pdf")]
    stub = _MappingStubLLM(
        {c.id: _vpd("MEETS", source_document="x.pdf") for c in criteria}
    )
    agent = VendorEvaluationAgent(model=stub, inter_batch_sleep_seconds=0)

    full = agent.evaluate_vendor(criteria, "VENDOR-A", False, documents)

    assert full.vendor_name == "VENDOR-A"
    assert full.is_msme is False
    assert full.overall_verdict == "ACCEPTED"
    assert "All 2 evaluated criteria" in full.overall_remarks


def test_evaluate_vendor_routes_failure_through_post_processor():
    """End-to-end: per-doc fan-out -> aggregator -> verdict.py post-processor.
    NOT_PROVIDED for blacklist-decl criterion should drive REJECTED with that
    criterion named in the remarks."""
    criteria = [
        _crit("PQC_DOC_PAN", name="PAN Card"),
        _crit("PQC_DOC_BLACKLIST_DECL", name="Blacklisting Declaration"),
    ]
    documents = [_doc("pan.pdf"), _doc("gst.pdf")]  # no blacklist decl present
    stub = _MappingStubLLM(
        {
            "PQC_DOC_PAN": _vpd("MEETS", source_document="pan.pdf"),
            "PQC_DOC_BLACKLIST_DECL": _vpd(
                "DOES_NOT_MEET",
                reasoning="No blacklisting declaration in this document.",
                source_document="pan.pdf",
            ),
        }
    )
    agent = VendorEvaluationAgent(model=stub, inter_batch_sleep_seconds=0)

    full = agent.evaluate_vendor(criteria, "V", False, documents)

    assert full.overall_verdict == "REJECTED"
    assert "Blacklisting Declaration" in full.overall_remarks
    assert "PAN Card" not in full.overall_remarks  # passed; not named


# --- Document-loading helpers ---------------------------------------------


def test_load_vendor_documents_returns_one_per_pdf(make_pdf, tmp_path: Path):
    make_pdf("a.pdf", [["Doc-A line"]])
    make_pdf("b.pdf", [["Doc-B line"]])

    docs = load_vendor_documents(tmp_path)

    assert [d.filename for d in docs] == ["a.pdf", "b.pdf"]
    assert all(isinstance(d.text, str) for d in docs)
    assert "Doc-A line" in docs[0].text
    assert "Doc-B line" in docs[1].text


def test_concatenate_vendor_docs_emits_filename_headers_in_sorted_order(make_pdf, tmp_path: Path):
    make_pdf("z_last.pdf", [["LAST-DOC-CONTENT"]])
    make_pdf("a_first.pdf", [["FIRST-DOC-CONTENT"]])
    make_pdf("m_middle.pdf", [["MIDDLE-DOC-CONTENT"]])

    text = concatenate_vendor_docs(tmp_path)

    assert "=== a_first.pdf ===" in text
    assert "=== m_middle.pdf ===" in text
    assert "=== z_last.pdf ===" in text
    assert "FIRST-DOC-CONTENT" in text
    assert "MIDDLE-DOC-CONTENT" in text
    assert "LAST-DOC-CONTENT" in text
    assert text.find("a_first.pdf") < text.find("m_middle.pdf") < text.find("z_last.pdf")


def test_concatenate_vendor_docs_empty_dir_returns_empty_string(tmp_path: Path):
    assert concatenate_vendor_docs(tmp_path) == ""
