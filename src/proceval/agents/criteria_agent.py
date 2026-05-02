"""Criteria Extraction Agent.

Reads the tender PDF text + extracted metadata and produces a ``TenderRubric``
(technical_criteria + commercial_criteria). On reviewer reject + feedback,
the same agent is re-invoked with ``feedback_text`` populated; the re-run
prompt steers the LLM to revisit gaps the reviewer flagged.

The LLM only returns the criteria lists; metadata is plumbed through
unchanged so we don't pay for re-extraction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ValidationError

from ..llm_factory import get_chat_model
from ..schemas.tender import EvalCriterion, TenderMetadata, TenderRubric

PROMPT_PATH = Path(__file__).parent / "prompts" / "criteria_extraction.txt"


class _CriteriaExtractionResult(BaseModel):
    """LLM output schema. Combined with caller-supplied metadata into a TenderRubric."""

    technical_criteria: list[EvalCriterion]
    commercial_criteria: list[EvalCriterion]


class CriteriaExtractionAgent:
    def __init__(
        self,
        model: BaseChatModel | None = None,
        max_retries: int = 2,
        prompt_template: str | None = None,
    ) -> None:
        self.model = model if model is not None else get_chat_model(temperature=0.0)
        self.max_retries = max_retries
        self._prompt_text = prompt_template or PROMPT_PATH.read_text(encoding="utf-8")

    def _build_chain(self) -> Runnable:
        prompt = ChatPromptTemplate.from_template(self._prompt_text)
        structured_llm = self.model.with_structured_output(_CriteriaExtractionResult)
        return prompt | structured_llm

    def extract(
        self,
        tender_text: str,
        tender_metadata: TenderMetadata,
        feedback_text: str | None = None,
    ) -> TenderRubric:
        chain = self._build_chain()
        feedback_section = _build_feedback_section(feedback_text)

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            inputs: dict[str, Any] = {
                "tender_text": tender_text,
                "tender_metadata": tender_metadata.model_dump_json(indent=2),
                "feedback_section": feedback_section,
                "validation_error_block": _retry_block(last_err) if attempt else "",
            }
            try:
                result = chain.invoke(inputs)
                if not isinstance(result, _CriteriaExtractionResult):
                    result = _CriteriaExtractionResult.model_validate(result)
                return TenderRubric(
                    metadata=tender_metadata,
                    technical_criteria=result.technical_criteria,
                    commercial_criteria=result.commercial_criteria,
                )
            except (ValidationError, OutputParserException) as exc:
                last_err = exc
                if attempt >= self.max_retries:
                    raise
        raise RuntimeError("CriteriaExtractionAgent retry loop exited without result")


def _build_feedback_section(feedback_text: str | None) -> str:
    if not feedback_text:
        return ""
    return (
        "\n\nIMPORTANT — REVIEWER FEEDBACK FROM PREVIOUS ITERATION:\n"
        "---\n"
        f"{feedback_text}\n"
        "---\n"
        "Re-extract criteria with this feedback as a primary lens. Preserve "
        "previously-correct criteria; correct or expand criteria where the "
        "feedback indicates gaps or errors."
    )


def _retry_block(err: Exception | None) -> str:
    if err is None:
        return ""
    return (
        "\n\nIMPORTANT: Your previous output failed validation:\n"
        f"{err}\n"
        "Return valid JSON matching the schema this time."
    )
