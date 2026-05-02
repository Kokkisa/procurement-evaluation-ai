"""Metadata Extraction Agent.

Single LLM call against the tender PDF text to extract structured
``TenderMetadata``. Pydantic-validated output; on parse failure the call is
retried with the validation error appended to the prompt context.

The vendor list is computed deterministically from the upload directory
structure (see ``proceval.ingestion.document_index``), not by the LLM, and
is therefore not the responsibility of this agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from ..llm_factory import get_chat_model
from ..schemas.tender import TenderMetadata

PROMPT_PATH = Path(__file__).parent / "prompts" / "metadata_extraction.txt"


class MetadataExtractionAgent:
    """Wraps prompt + structured-output LLM with bounded retry on validation errors."""

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
        structured_llm = self.model.with_structured_output(TenderMetadata)
        return prompt | structured_llm

    def extract(self, tender_text: str) -> TenderMetadata:
        chain = self._build_chain()
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            inputs: dict[str, Any] = {
                "tender_text": tender_text,
                "validation_error_block": _retry_block(last_err) if attempt else "",
            }
            try:
                result = chain.invoke(inputs)
                if isinstance(result, TenderMetadata):
                    return result
                # ``with_structured_output`` may return a dict on some providers
                # — re-validate to keep the contract tight.
                return TenderMetadata.model_validate(result)
            except (ValidationError, OutputParserException) as exc:
                last_err = exc
                if attempt >= self.max_retries:
                    raise
        # unreachable — the loop either returns or re-raises
        raise RuntimeError("MetadataExtractionAgent retry loop exited without result")


def _retry_block(err: Exception | None) -> str:
    if err is None:
        return ""
    return (
        "\n\nIMPORTANT: Your previous output failed validation:\n"
        f"{err}\n"
        "Return valid JSON matching the schema this time."
    )
