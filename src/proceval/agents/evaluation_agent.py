"""Vendor Evaluation Agent.

For one vendor, runs an LLM call per (criterion) in parallel via
``asyncio.gather`` (with a semaphore-bounded concurrency limit so we don't
hammer Anthropic's rate limits at higher vendor / criterion counts). Each
call returns a ``CriterionEvaluation``. Per-call retry on
``ValidationError`` / ``OutputParserException``, same pattern as the
metadata + criteria agents.

After all per-criterion calls return, the deterministic post-processor in
``verdict.py`` produces the overall ACCEPTED/REJECTED verdict and remarks.
The LLM is responsible for the per-criterion judgement only — the final
roll-up is pure logic so it's reproducible and auditable.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from ..config import settings
from ..ingestion.pdf_parser import extract_text
from ..llm_factory import get_chat_model
from ..schemas.tender import EvalCriterion
from ..schemas.vendor import CriterionEvaluation, VendorEvaluation
from .verdict import compute_overall_verdict

PROMPT_PATH = Path(__file__).parent / "prompts" / "vendor_evaluation.txt"

logger = logging.getLogger(__name__)


class VendorEvaluationAgent:
    """Concurrency model:

    A single ``asyncio.Semaphore`` lives on the *instance* (lazily bound to
    the first event loop that touches it). All per-criterion calls acquire
    it, including those issued in parallel for technical + commercial
    rubrics from ``api/services.py``. That gives a hard global cap; the
    inter-batch sleep adds a token-bucket safety margin so cumulative
    tokens-per-minute stay under the org's tier limit.
    """

    def __init__(
        self,
        model: BaseChatModel | None = None,
        max_retries: int = 2,
        max_concurrency: int | None = None,
        inter_batch_sleep_seconds: float | None = None,
        prompt_template: str | None = None,
    ) -> None:
        self.model = model if model is not None else get_chat_model(temperature=0.0)
        self.max_retries = max_retries
        self.max_concurrency = (
            max_concurrency
            if max_concurrency is not None
            else settings.llm_max_concurrency
        )
        self.inter_batch_sleep_seconds = (
            inter_batch_sleep_seconds
            if inter_batch_sleep_seconds is not None
            else settings.llm_inter_batch_sleep_seconds
        )
        self._prompt_text = prompt_template or PROMPT_PATH.read_text(encoding="utf-8")
        # Lazy: bound on first acquire, so it picks up whichever event loop
        # the route handler / script is running under.
        self._semaphore: asyncio.Semaphore | None = None
        self._in_flight: int = 0
        self._batch_no: int = 0

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    def _build_chain(self) -> Runnable:
        prompt = ChatPromptTemplate.from_template(self._prompt_text)
        structured_llm = self.model.with_structured_output(CriterionEvaluation)
        return prompt | structured_llm

    async def aevaluate_criterion(
        self,
        criterion: EvalCriterion,
        vendor_name: str,
        is_msme: bool,
        vendor_docs_text: str,
    ) -> CriterionEvaluation:
        sem = self._get_semaphore()
        async with sem:
            self._in_flight += 1
            slot = self._in_flight
            logger.info(
                "Acquired LLM slot %d/%d for %s / %s",
                slot, self.max_concurrency, vendor_name, criterion.id,
            )
            try:
                return await self._run_call(
                    criterion, vendor_name, is_msme, vendor_docs_text
                )
            finally:
                self._in_flight -= 1

    async def _run_call(
        self,
        criterion: EvalCriterion,
        vendor_name: str,
        is_msme: bool,
        vendor_docs_text: str,
    ) -> CriterionEvaluation:
        chain = self._build_chain()
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            inputs: dict[str, Any] = {
                "criterion_id": criterion.id,
                "criterion_name": criterion.name,
                "criterion_description": criterion.description,
                "criterion_type": criterion.type.value if hasattr(criterion.type, "value") else str(criterion.type),
                "threshold": (
                    f"{criterion.threshold_value:.2f}"
                    if criterion.threshold_value is not None
                    else "n/a"
                ),
                "msme_relaxation": (
                    f"{criterion.msme_relaxation_value:.2f}"
                    if criterion.msme_relaxation_value is not None
                    else "n/a"
                ),
                "aggregation_rule": criterion.aggregation_rule or "n/a",
                "vendor_name": vendor_name,
                "is_msme": str(is_msme),
                "vendor_docs_text": vendor_docs_text,
                "validation_error_block": _retry_block(last_err) if attempt else "",
            }
            try:
                result = await chain.ainvoke(inputs)
                if isinstance(result, CriterionEvaluation):
                    # Force the criterion_id field — LLMs sometimes drop or
                    # mangle it; we already know the right value here.
                    if result.criterion_id != criterion.id:
                        result = result.model_copy(update={"criterion_id": criterion.id})
                    return result
                if isinstance(result, dict):
                    result.setdefault("criterion_id", criterion.id)
                return CriterionEvaluation.model_validate(result)
            except (ValidationError, OutputParserException) as exc:
                last_err = exc
                if attempt >= self.max_retries:
                    raise
        raise RuntimeError("VendorEvaluationAgent retry loop exited without result")

    async def aevaluate_vendor(
        self,
        criteria: list[EvalCriterion],
        vendor_name: str,
        is_msme: bool,
        vendor_docs_text: str,
    ) -> list[CriterionEvaluation]:
        """Evaluate every criterion for one vendor.

        Criteria are processed in batches of ``max_concurrency`` so the
        inter-batch sleep is visible (each batch is logged explicitly). The
        per-call semaphore on ``aevaluate_criterion`` is the hard cap and
        also covers parallel ``aevaluate_vendor`` invocations (technical +
        commercial fan-out from ``api/services.py``).
        """
        results: list[CriterionEvaluation] = []
        chunks = [
            criteria[i : i + self.max_concurrency]
            for i in range(0, len(criteria), self.max_concurrency)
        ]
        for chunk in chunks:
            self._batch_no += 1
            current_batch = self._batch_no
            if current_batch > 1 and self.inter_batch_sleep_seconds > 0:
                logger.info(
                    "Sleeping %.2fs before batch %d (token-bucket margin)",
                    self.inter_batch_sleep_seconds,
                    current_batch,
                )
                await asyncio.sleep(self.inter_batch_sleep_seconds)
            else:
                logger.info(
                    "Starting batch %d (%d call(s)) for %s",
                    current_batch,
                    len(chunk),
                    vendor_name,
                )

            batch_results = await asyncio.gather(
                *[
                    self.aevaluate_criterion(c, vendor_name, is_msme, vendor_docs_text)
                    for c in chunk
                ]
            )
            results.extend(batch_results)
        return results

    async def aevaluate_vendor_full(
        self,
        criteria: list[EvalCriterion],
        vendor_name: str,
        is_msme: bool,
        vendor_docs_text: str,
    ) -> VendorEvaluation:
        """Async equivalent of ``evaluate_vendor`` — fan out per-criterion calls
        and route through the deterministic post-processor. Use this from inside
        an existing event loop (FastAPI route handlers, Streamlit async paths)."""
        evaluations = await self.aevaluate_vendor(
            criteria, vendor_name, is_msme, vendor_docs_text
        )
        verdict, remarks = compute_overall_verdict(
            vendor_name=vendor_name,
            is_msme=is_msme,
            criteria=criteria,
            criterion_evaluations=evaluations,
        )
        return VendorEvaluation(
            vendor_name=vendor_name,
            is_msme=is_msme,
            criterion_evaluations=evaluations,
            overall_verdict=verdict,
            overall_remarks=remarks,
        )

    def evaluate_vendor(
        self,
        criteria: list[EvalCriterion],
        vendor_name: str,
        is_msme: bool,
        vendor_docs_text: str,
    ) -> VendorEvaluation:
        """Sync convenience wrapper. Use ``aevaluate_vendor_full`` from inside
        an existing event loop instead — ``asyncio.run`` cannot nest."""
        return asyncio.run(
            self.aevaluate_vendor_full(criteria, vendor_name, is_msme, vendor_docs_text)
        )


def concatenate_vendor_docs(vendor_dir: Path) -> str:
    """Concatenate every PDF in ``vendor_dir`` into a single text blob.

    Each document is preceded by a filename header so the LLM can cite a
    specific source. Sorted for determinism.
    """
    chunks: list[str] = []
    for pdf in sorted(vendor_dir.glob("*.pdf")):
        text, _ = extract_text(pdf)
        chunks.append(f"=== {pdf.name} ===\n{text}")
    return "\n\n".join(chunks)


def _retry_block(err: Exception | None) -> str:
    if err is None:
        return ""
    return (
        "\n\nIMPORTANT: Your previous output failed validation:\n"
        f"{err}\n"
        "Return valid JSON matching the CriterionEvaluation schema this time."
    )
