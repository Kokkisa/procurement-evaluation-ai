"""Mocked unit tests for VendorEvaluationAgent and concatenate_vendor_docs.

Stubs the chat model with RunnableLambda-backed fakes so the agent's prompt
pipeline, retry logic, async-parallel fan-out via ``asyncio.gather``, and
the sync wrapper that routes through the deterministic post-processor are
all exercised without any LLM calls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda

from proceval.agents import VendorEvaluationAgent
from proceval.agents.evaluation_agent import concatenate_vendor_docs
from proceval.schemas.tender import CriterionType, EvalCriterion
from proceval.schemas.vendor import CriterionEvaluation


# --- Stub models -----------------------------------------------------------


class _MappingStubLLM:
    """Returns the result whose key (a criterion_id) appears in the prompt
    text as ``'ID: <key>'``. Lets parallel calls map deterministically to
    expected outputs."""

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


def _ev(criterion_id: str, verdict: str = "PROVIDED", **overrides) -> CriterionEvaluation:
    base = dict(criterion_id=criterion_id, verdict=verdict, reasoning="ok", confidence=0.9)
    base.update(overrides)
    return CriterionEvaluation(**base)


# --- Single-criterion calls ------------------------------------------------


def test_aevaluate_criterion_returns_pydantic_instance():
    expected = _ev("PQC_DOC_PAN")
    stub = _MappingStubLLM({"PQC_DOC_PAN": expected})
    agent = VendorEvaluationAgent(model=stub)
    result = asyncio.run(
        agent.aevaluate_criterion(
            _crit("PQC_DOC_PAN", name="PAN"), "VENDOR-A", False, "vendor docs..."
        )
    )
    assert isinstance(result, CriterionEvaluation)
    assert result.criterion_id == "PQC_DOC_PAN"


def test_aevaluate_criterion_renders_all_expected_fields_into_prompt():
    stub = _MappingStubLLM({"PQC_FIN_TURNOVER": _ev("PQC_FIN_TURNOVER", "VALUE", extracted_value="V", threshold_met=True)})
    agent = VendorEvaluationAgent(model=stub)
    asyncio.run(
        agent.aevaluate_criterion(
            _crit(
                "PQC_FIN_TURNOVER",
                name="Average Annual Turnover",
                type_=CriterionType.FINANCIAL,
                threshold_value=100.0,
                msme_relaxation_value=85.0,
                aggregation_rule="average",
            ),
            vendor_name="VENDOR-Z",
            is_msme=True,
            vendor_docs_text="DOC-TEXT-SENTINEL",
        )
    )
    prompt = stub.calls[0]
    assert "ID: PQC_FIN_TURNOVER" in prompt
    assert "Average Annual Turnover" in prompt
    assert "VENDOR-Z" in prompt
    assert "True" in prompt  # is_msme
    assert "DOC-TEXT-SENTINEL" in prompt
    assert "100.00" in prompt
    assert "85.00" in prompt
    assert "average" in prompt


def test_aevaluate_criterion_overrides_criterion_id_if_llm_drifts():
    """LLMs sometimes echo a different criterion_id; the agent forces the right one."""
    stub = _MappingStubLLM({"PQC_DOC_PAN": _ev("WRONG_ID_FROM_LLM")})
    agent = VendorEvaluationAgent(model=stub)
    result = asyncio.run(
        agent.aevaluate_criterion(_crit("PQC_DOC_PAN"), "V", False, "docs")
    )
    assert result.criterion_id == "PQC_DOC_PAN"


def test_aevaluate_criterion_retries_on_validation_error_then_succeeds():
    expected = _ev("PQC_DOC_PAN")
    stub = _ListStubLLM([OutputParserException("bad output 1"), expected])
    agent = VendorEvaluationAgent(model=stub, max_retries=2)
    result = asyncio.run(
        agent.aevaluate_criterion(_crit("PQC_DOC_PAN"), "V", False, "docs")
    )
    assert isinstance(result, CriterionEvaluation)
    assert len(stub.calls) == 2
    assert "previous output failed" in stub.calls[1].lower()
    assert "bad output 1" in stub.calls[1]


def test_aevaluate_criterion_raises_after_max_retries():
    stub = _ListStubLLM([OutputParserException(f"err{i}") for i in range(5)])
    agent = VendorEvaluationAgent(model=stub, max_retries=2)
    with pytest.raises(OutputParserException, match="err2"):
        asyncio.run(
            agent.aevaluate_criterion(_crit("PQC_DOC_PAN"), "V", False, "docs")
        )
    assert len(stub.calls) == 3  # 1 initial + 2 retries


# --- Parallel per-vendor evaluation ----------------------------------------


def test_aevaluate_vendor_calls_llm_once_per_criterion():
    criteria = [_crit(f"C{i}") for i in range(5)]
    results = {c.id: _ev(c.id) for c in criteria}
    stub = _MappingStubLLM(results)
    agent = VendorEvaluationAgent(model=stub)

    out = asyncio.run(agent.aevaluate_vendor(criteria, "V", False, "docs"))

    assert len(out) == 5
    assert len(stub.calls) == 5


def test_aevaluate_vendor_preserves_input_criterion_order_in_results():
    """``asyncio.gather`` returns results in input order regardless of which
    coroutine completes first — verify this contract holds end-to-end."""
    criteria = [_crit("A"), _crit("B"), _crit("C"), _crit("D"), _crit("E")]
    results = {c.id: _ev(c.id) for c in criteria}
    stub = _MappingStubLLM(results)
    agent = VendorEvaluationAgent(model=stub)

    out = asyncio.run(agent.aevaluate_vendor(criteria, "V", False, "docs"))

    assert [e.criterion_id for e in out] == ["A", "B", "C", "D", "E"]


def test_aevaluate_vendor_respects_concurrency_limit():
    """With max_concurrency=1, every concurrent_calls observation should be 1."""
    criteria = [_crit(f"C{i}") for i in range(5)]
    in_flight = {"current": 0, "max_seen": 0}

    class _CountingStub:
        def __init__(self):
            self.calls: list[str] = []

        def with_structured_output(self, _s, **_k):
            async def _afn(prompt_value):
                in_flight["current"] += 1
                in_flight["max_seen"] = max(in_flight["max_seen"], in_flight["current"])
                # Yield to event loop so other coroutines can be scheduled
                await asyncio.sleep(0)
                in_flight["current"] -= 1
                text = prompt_value.to_string() if hasattr(prompt_value, "to_string") else str(prompt_value)
                self.calls.append(text)
                for c in criteria:
                    if f"ID: {c.id}" in text:
                        return _ev(c.id)
                raise RuntimeError("no match")

            return RunnableLambda(_afn)

    stub = _CountingStub()
    agent = VendorEvaluationAgent(model=stub, max_concurrency=1)
    asyncio.run(agent.aevaluate_vendor(criteria, "V", False, "docs"))
    assert in_flight["max_seen"] == 1


# --- Sync wrapper + verdict roll-up ----------------------------------------


def test_evaluate_vendor_returns_full_VendorEvaluation_with_accepted_verdict():
    criteria = [_crit("PQC_DOC_PAN", name="PAN"), _crit("PQC_DOC_GST", name="GST")]
    results = {c.id: _ev(c.id, "PROVIDED") for c in criteria}
    stub = _MappingStubLLM(results)
    agent = VendorEvaluationAgent(model=stub)

    full = agent.evaluate_vendor(criteria, "VENDOR-A", False, "docs")

    assert full.vendor_name == "VENDOR-A"
    assert full.is_msme is False
    assert full.overall_verdict == "ACCEPTED"
    assert "All 2 evaluated criteria" in full.overall_remarks


def test_evaluate_vendor_routes_failure_through_post_processor():
    """End-to-end: agent + post-processor produce REJECTED with a remark
    that names the failing criterion."""
    criteria = [
        _crit("PQC_DOC_PAN", name="PAN Card"),
        _crit("PQC_DOC_BLACKLIST_DECL", name="Blacklisting Declaration"),
    ]
    results = {
        "PQC_DOC_PAN": _ev("PQC_DOC_PAN", "PROVIDED"),
        "PQC_DOC_BLACKLIST_DECL": _ev(
            "PQC_DOC_BLACKLIST_DECL", "NOT_PROVIDED", reasoning="missing"
        ),
    }
    stub = _MappingStubLLM(results)
    agent = VendorEvaluationAgent(model=stub)

    full = agent.evaluate_vendor(criteria, "V", False, "docs")

    assert full.overall_verdict == "REJECTED"
    assert "did not provide Blacklisting Declaration" in full.overall_remarks
    assert "PAN Card" not in full.overall_remarks  # passed, not named


# --- Helper: vendor-doc concatenation --------------------------------------


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
    # Sorted: a < m < z
    assert text.find("a_first.pdf") < text.find("m_middle.pdf") < text.find("z_last.pdf")


def test_concatenate_vendor_docs_empty_dir_returns_empty_string(tmp_path: Path):
    assert concatenate_vendor_docs(tmp_path) == ""
