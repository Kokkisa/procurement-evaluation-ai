"""Mocked unit tests for MetadataExtractionAgent.

Uses a stub model whose ``with_structured_output()`` returns a
``RunnableLambda`` over predetermined results, so we exercise the prompt
pipeline + retry logic without hitting any LLM.
"""

from __future__ import annotations

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import RunnableLambda

from proceval.agents import MetadataExtractionAgent
from proceval.schemas.tender import TenderMetadata


class _StubLLM:
    """A fake chat model: yields predetermined results in order, captures inputs."""

    def __init__(self, results: list):
        self._results = list(results)
        self.calls: list[str] = []
        self.schemas_used: list = []

    def with_structured_output(self, schema, **_kwargs):
        self.schemas_used.append(schema)

        def _fn(prompt_value):
            text = prompt_value.to_string() if hasattr(prompt_value, "to_string") else str(prompt_value)
            self.calls.append(text)
            if not self._results:
                raise RuntimeError("_StubLLM exhausted")
            nxt = self._results.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

        return RunnableLambda(_fn)


def _expected_metadata() -> TenderMetadata:
    return TenderMetadata(
        tender_number="DEMO/2026/HKP/001",
        tender_name="Housekeeping & Sanitation Services at Demo Industrial Facility",
        issuing_organization="Demo Procurement Corporation Limited",
        location="Pune",
    )


def test_extract_returns_pydantic_instance_on_first_try():
    expected = _expected_metadata()
    stub = _StubLLM([expected])
    agent = MetadataExtractionAgent(model=stub, max_retries=2)

    result = agent.extract("Tender body text...")

    assert result == expected
    assert isinstance(result, TenderMetadata)
    assert len(stub.calls) == 1
    assert stub.schemas_used == [TenderMetadata]


def test_prompt_includes_tender_text():
    stub = _StubLLM([_expected_metadata()])
    agent = MetadataExtractionAgent(model=stub)

    sentinel = "BODY-TEXT-SENTINEL-12345"
    agent.extract(sentinel)

    assert sentinel in stub.calls[0]


def test_first_attempt_omits_validation_error_block():
    stub = _StubLLM([_expected_metadata()])
    agent = MetadataExtractionAgent(model=stub)
    agent.extract("text")

    # The literal phrase only appears when retrying.
    assert "previous output failed" not in stub.calls[0].lower()


def test_retries_on_output_parser_exception_then_succeeds():
    expected = _expected_metadata()
    stub = _StubLLM(
        [
            OutputParserException("bad output round 1"),
            expected,
        ]
    )
    agent = MetadataExtractionAgent(model=stub, max_retries=2)

    result = agent.extract("text")

    assert result == expected
    assert len(stub.calls) == 2
    # Second attempt must include the validation-error guidance
    assert "previous output failed" in stub.calls[1].lower()
    assert "bad output round 1" in stub.calls[1]


def test_raises_after_exhausting_retries():
    stub = _StubLLM(
        [
            OutputParserException("e1"),
            OutputParserException("e2"),
            OutputParserException("e3"),
        ]
    )
    agent = MetadataExtractionAgent(model=stub, max_retries=2)

    with pytest.raises(OutputParserException, match="e3"):
        agent.extract("text")
    assert len(stub.calls) == 3  # initial + 2 retries


def test_revalidates_dict_returned_by_provider():
    """Some providers return a dict from with_structured_output; agent must re-validate."""
    raw_dict = {
        "tender_number": "X/1",
        "tender_name": "From dict",
        "issuing_organization": "Org",
    }
    stub = _StubLLM([raw_dict])
    agent = MetadataExtractionAgent(model=stub)

    result = agent.extract("text")

    assert isinstance(result, TenderMetadata)
    assert result.tender_number == "X/1"
