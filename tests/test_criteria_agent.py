"""Mocked unit tests for CriteriaExtractionAgent."""

from __future__ import annotations

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda

from proceval.agents import CriteriaExtractionAgent
from proceval.agents.criteria_agent import _CriteriaExtractionResult
from proceval.schemas.tender import (
    CriterionType,
    EvalCriterion,
    TenderMetadata,
    TenderRubric,
)


class _StubLLM:
    def __init__(self, results: list):
        self._results = list(results)
        self.calls: list[str] = []
        self.schemas_used: list = []

    def with_structured_output(self, schema, **_kwargs):
        self.schemas_used.append(schema)

        def _fn(prompt_value):
            text = (
                prompt_value.to_string()
                if hasattr(prompt_value, "to_string")
                else str(prompt_value)
            )
            self.calls.append(text)
            if not self._results:
                raise RuntimeError("_StubLLM exhausted")
            nxt = self._results.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

        return RunnableLambda(_fn)


def _meta() -> TenderMetadata:
    return TenderMetadata(
        tender_number="DEMO/2026/HKP/001",
        tender_name="Housekeeping Services",
        issuing_organization="Demo Procurement Corporation Limited",
    )


def _result_with_one_each() -> _CriteriaExtractionResult:
    return _CriteriaExtractionResult(
        technical_criteria=[
            EvalCriterion(
                id="PQC_FIN_TURNOVER",
                name="Annual Turnover",
                description="Avg annual turnover >= 100 lakhs",
                type=CriterionType.FINANCIAL,
                threshold_value=100.0,
                msme_relaxation_value=85.0,
                aggregation_rule="average",
                source_clause="PQC-1",
            )
        ],
        commercial_criteria=[
            EvalCriterion(
                id="COMM_PPE",
                name="PPE",
                description="Bidder shall provide PPE to all deployed personnel.",
                type=CriterionType.COMMERCIAL,
                source_clause="Section 4 — Special Conditions",
            )
        ],
    )


def test_extract_assembles_rubric_from_llm_result_and_metadata():
    stub = _StubLLM([_result_with_one_each()])
    agent = CriteriaExtractionAgent(model=stub, max_retries=2)

    rubric = agent.extract("tender text", _meta())

    assert isinstance(rubric, TenderRubric)
    assert rubric.metadata == _meta()
    assert len(rubric.technical_criteria) == 1
    assert rubric.technical_criteria[0].id == "PQC_FIN_TURNOVER"
    assert rubric.technical_criteria[0].threshold_value == 100.0
    assert len(rubric.commercial_criteria) == 1
    assert rubric.commercial_criteria[0].id == "COMM_PPE"


def test_prompt_includes_tender_text_and_metadata_json():
    stub = _StubLLM([_result_with_one_each()])
    agent = CriteriaExtractionAgent(model=stub)

    sentinel = "TENDER-BODY-SENTINEL-XYZ"
    agent.extract(sentinel, _meta())

    rendered = stub.calls[0]
    assert sentinel in rendered
    # metadata is rendered as JSON inside the prompt
    assert "DEMO/2026/HKP/001" in rendered
    assert "Demo Procurement Corporation Limited" in rendered


def test_no_feedback_section_on_first_run():
    stub = _StubLLM([_result_with_one_each()])
    agent = CriteriaExtractionAgent(model=stub)
    agent.extract("text", _meta())

    assert "REVIEWER FEEDBACK" not in stub.calls[0]


def test_feedback_section_appears_when_provided():
    stub = _StubLLM([_result_with_one_each()])
    agent = CriteriaExtractionAgent(model=stub)
    agent.extract("text", _meta(), feedback_text="Vendor 3 turnover figure looks wrong, recheck")

    rendered = stub.calls[0]
    assert "REVIEWER FEEDBACK" in rendered
    assert "Vendor 3 turnover figure looks wrong, recheck" in rendered


def test_retries_on_output_parser_exception_then_succeeds():
    stub = _StubLLM(
        [
            OutputParserException("bad json round 1"),
            _result_with_one_each(),
        ]
    )
    agent = CriteriaExtractionAgent(model=stub, max_retries=2)

    rubric = agent.extract("text", _meta())

    assert isinstance(rubric, TenderRubric)
    assert len(stub.calls) == 2
    assert "previous output failed" in stub.calls[1].lower()
    assert "bad json round 1" in stub.calls[1]


def test_raises_after_exhausting_retries():
    stub = _StubLLM(
        [
            OutputParserException("e1"),
            OutputParserException("e2"),
            OutputParserException("e3"),
        ]
    )
    agent = CriteriaExtractionAgent(model=stub, max_retries=2)

    with pytest.raises(OutputParserException, match="e3"):
        agent.extract("text", _meta())
    assert len(stub.calls) == 3


def test_revalidates_dict_returned_by_provider():
    raw = {
        "technical_criteria": [
            {
                "id": "PQC_DOC_PAN",
                "name": "PAN",
                "description": "Self-attested PAN copy required.",
                "type": "document",
            }
        ],
        "commercial_criteria": [],
    }
    stub = _StubLLM([raw])
    agent = CriteriaExtractionAgent(model=stub)

    rubric = agent.extract("text", _meta())

    assert len(rubric.technical_criteria) == 1
    assert rubric.technical_criteria[0].id == "PQC_DOC_PAN"
