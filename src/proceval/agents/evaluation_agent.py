"""Vendor Evaluation Agent.

Per ADR-0007 the LLM call shape is per-(vendor, criterion, document):

    for criterion in criteria:
        for document in vendor.documents:
            v = await aevaluate_vendor_document(...)   # one LLM call
            per_doc_verdicts.append(v)
        per_criterion = aggregate_document_verdicts(criterion, per_doc_verdicts)

The aggregator is deterministic Python (no LLM). The decision rule is
captured in ADR-0007: any ``MEETS`` wins; else if every per-doc verdict
is ``NOT_APPLICABLE`` the criterion is unevaluable; otherwise
``DOES_NOT_MEET`` with the strongest negative-evidence document cited.

The instance-level ``asyncio.Semaphore`` from Block 10 still bounds the
total concurrent LLM calls; with the per-document fan-out the call count
goes up linearly with vendor doc count, so the rate-limit guard becomes
more important, not less.

After all per-criterion CriterionEvaluations are collected, the
deterministic post-processor in ``verdict.py`` produces the overall
ACCEPTED/REJECTED verdict + remarks. The LLM is responsible for the
per-(criterion, document) judgement only.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from ..config import settings
from ..ingestion.pdf_parser import extract_text
from ..llm_factory import get_chat_model
from ..schemas.tender import EvalCriterion
from ..schemas.vendor import CriterionEvaluation, VendorEvaluation, VerdictPerDoc
from .verdict import compute_overall_verdict

PROMPT_PATH = Path(__file__).parent / "prompts" / "vendor_evaluation.txt"

# Token-budget alarm threshold per ADR-0007. Below this, no warning.
# Above, log + proceed — we want the signal in real data, not a hard block.
PER_DOC_TOKEN_WARNING = 50_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VendorDocument:
    """One file in a vendor's submission, post-extraction.

    ``filename`` is the bare PDF name (used in trace span names + cited
    in CriterionEvaluation.source_document). ``text`` is the extracted
    body (text-layer + OCR per ADR-0006).
    """

    filename: str
    text: str


def load_vendor_documents(vendor_dir: Path) -> list[VendorDocument]:
    """Walk a vendor folder and return one VendorDocument per PDF.

    Replaces the per-vendor ``concatenate_vendor_docs`` for the per-document
    evaluation path. ``concatenate_vendor_docs`` is kept (other tooling +
    the matrix-preview script may still want a flat blob).
    """
    docs: list[VendorDocument] = []
    for pdf in sorted(vendor_dir.glob("*.pdf")):
        text, _ = extract_text(pdf)
        docs.append(VendorDocument(filename=pdf.name, text=text))
    return docs


class VendorEvaluationAgent:
    """Concurrency model:

    A single ``asyncio.Semaphore`` lives on the *instance* (lazily bound to
    the first event loop that touches it). Every per-document LLM call
    acquires it. With per-document fan-out the call count multiplies by
    vendor doc count, so the cap is what keeps a 7-vendor / 60-doc / 8-
    criterion run (~3,400 calls) under the org's token-per-minute ceiling.
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
        structured_llm = self.model.with_structured_output(VerdictPerDoc)
        return prompt | structured_llm

    # --- per (vendor, criterion, document) call ----------------------------

    async def aevaluate_vendor_document(
        self,
        *,
        vendor_name: str,
        is_msme: bool,
        criterion: EvalCriterion,
        document: VendorDocument,
    ) -> VerdictPerDoc:
        """One LLM call: this document × this criterion × this vendor."""
        sem = self._get_semaphore()
        async with sem:
            self._in_flight += 1
            slot = self._in_flight
            estimated_tokens = (
                len(self._prompt_text) + len(document.text) + 500
            ) // 4
            logger.info(
                "Acquired LLM slot %d/%d for %s | %s | doc: %s (~%d tokens)",
                slot, self.max_concurrency, vendor_name,
                criterion.id, document.filename, estimated_tokens,
            )
            if estimated_tokens > PER_DOC_TOKEN_WARNING:
                logger.warning(
                    "Document %s for %s on %s estimated at %d tokens "
                    "(> %d threshold). Proceeding; consider chunking in v0.3.",
                    document.filename, vendor_name, criterion.id,
                    estimated_tokens, PER_DOC_TOKEN_WARNING,
                )
            try:
                return await self._run_doc_call(
                    vendor_name=vendor_name,
                    is_msme=is_msme,
                    criterion=criterion,
                    document=document,
                )
            finally:
                self._in_flight -= 1

    async def _run_doc_call(
        self,
        *,
        vendor_name: str,
        is_msme: bool,
        criterion: EvalCriterion,
        document: VendorDocument,
    ) -> VerdictPerDoc:
        """Build the prompt, invoke the chain with retry, force the
        source_document field to the canonical filename."""
        chain = self._build_chain()
        # Per-call run name + metadata so LangSmith spans are filterable
        # by vendor/criterion/doc (ADR-0007 trace shape).
        chain = chain.with_config(
            run_name=f"evaluate {vendor_name} | {criterion.name} | doc: {document.filename}",
            metadata={
                "vendor_name": vendor_name,
                "criterion_id": criterion.id,
                "document_filename": document.filename,
                "input_token_estimate": (
                    len(self._prompt_text) + len(document.text) + 500
                ) // 4,
            },
        )

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            inputs: dict[str, Any] = {
                "criterion_id": criterion.id,
                "criterion_name": criterion.name,
                "criterion_description": criterion.description,
                "criterion_type": criterion.type.value
                if hasattr(criterion.type, "value")
                else str(criterion.type),
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
                "document_filename": document.filename,
                "document_text": document.text,
                "validation_error_block": _retry_block(last_err) if attempt else "",
            }
            try:
                result = await chain.ainvoke(inputs)
                if isinstance(result, VerdictPerDoc):
                    # Force source_document — LLMs sometimes drop or mangle it.
                    if result.source_document != document.filename:
                        result = result.model_copy(
                            update={"source_document": document.filename}
                        )
                    return result
                if isinstance(result, dict):
                    result.setdefault("source_document", document.filename)
                return VerdictPerDoc.model_validate(result)
            except (ValidationError, OutputParserException) as exc:
                last_err = exc
                if attempt >= self.max_retries:
                    raise
        raise RuntimeError("aevaluate_vendor_document retry loop exited without result")

    # --- aggregator (deterministic, no LLM) -------------------------------

    @staticmethod
    def aggregate_document_verdicts(
        criterion: EvalCriterion,
        per_doc_verdicts: list[VerdictPerDoc],
    ) -> CriterionEvaluation:
        """Collapse a list of per-document verdicts into one CriterionEvaluation.

        Decision rule (ADR-0007):

        * Any ``MEETS`` => criterion satisfied. Surface the first such doc as
          the cited evidence.
        * No ``MEETS`` and at least one ``DOES_NOT_MEET`` => failed. Cite the
          ``DOES_NOT_MEET`` with the longest reasoning (proxy for "strongest
          negative"). v0.3 may upgrade this to a confidence score.
        * All ``NOT_APPLICABLE`` => unevaluable. Surface as PARTIAL so the
          downstream verdict.compute_overall_verdict() flags it for human
          review rather than silently passing.
        * Empty input (no documents at all) => unevaluable, same as all
          NOT_APPLICABLE.
        """
        if not per_doc_verdicts:
            return CriterionEvaluation(
                criterion_id=criterion.id,
                verdict="PARTIAL",
                extracted_value=None,
                threshold_met=None,
                reasoning="No documents available to evaluate this criterion.",
                source_document=None,
                confidence=0.5,
            )

        meets = [v for v in per_doc_verdicts if v.verdict == "MEETS"]
        if meets:
            chosen = meets[0]
            # If the document carried a numeric value (turnover figure, PO
            # value), surface as VALUE so downstream threshold reporting
            # works. Otherwise PROVIDED (document-existence criterion).
            if chosen.extracted_value:
                return CriterionEvaluation(
                    criterion_id=criterion.id,
                    verdict="VALUE",
                    extracted_value=chosen.extracted_value,
                    threshold_met=True,
                    reasoning=chosen.reasoning,
                    source_document=chosen.source_document,
                    confidence=0.95,
                )
            return CriterionEvaluation(
                criterion_id=criterion.id,
                verdict="PROVIDED",
                extracted_value=None,
                threshold_met=None,
                reasoning=chosen.reasoning,
                source_document=chosen.source_document,
                confidence=0.95,
            )

        does_not_meet = [v for v in per_doc_verdicts if v.verdict == "DOES_NOT_MEET"]
        if does_not_meet:
            # "Strongest negative": the DOES_NOT_MEET with the longest
            # reasoning. Cheap proxy, inspectable, easy to upgrade later.
            strongest = max(does_not_meet, key=lambda v: len(v.reasoning))
            if strongest.extracted_value:
                return CriterionEvaluation(
                    criterion_id=criterion.id,
                    verdict="VALUE",
                    extracted_value=strongest.extracted_value,
                    threshold_met=False,
                    reasoning=strongest.reasoning,
                    source_document=strongest.source_document,
                    confidence=0.9,
                )
            return CriterionEvaluation(
                criterion_id=criterion.id,
                verdict="NOT_PROVIDED",
                extracted_value=None,
                threshold_met=None,
                reasoning=strongest.reasoning,
                source_document=strongest.source_document,
                confidence=0.9,
            )

        # All NOT_APPLICABLE: criterion is unevaluable from the submitted
        # documents. PARTIAL so verdict.py flags it for human review.
        return CriterionEvaluation(
            criterion_id=criterion.id,
            verdict="PARTIAL",
            extracted_value=None,
            threshold_met=None,
            reasoning=(
                "No document in the submission contained information relevant "
                "to this criterion. Flagged for human review per ADR-0007."
            ),
            source_document=None,
            confidence=0.5,
        )

    # --- per-criterion fan-out (private; called by aevaluate_vendor) -----

    async def _aevaluate_one_criterion(
        self,
        *,
        vendor_name: str,
        is_msme: bool,
        criterion: EvalCriterion,
        documents: list[VendorDocument],
    ) -> CriterionEvaluation:
        """For one (vendor, criterion): fan out across documents,
        aggregate to a single CriterionEvaluation."""
        if not documents:
            return self.aggregate_document_verdicts(criterion, [])

        per_doc_verdicts = await asyncio.gather(
            *[
                self.aevaluate_vendor_document(
                    vendor_name=vendor_name,
                    is_msme=is_msme,
                    criterion=criterion,
                    document=doc,
                )
                for doc in documents
            ]
        )
        return self.aggregate_document_verdicts(criterion, list(per_doc_verdicts))

    # --- public per-vendor entry points ----------------------------------

    async def aevaluate_vendor(
        self,
        criteria: list[EvalCriterion],
        vendor_name: str,
        is_msme: bool,
        documents: list[VendorDocument],
    ) -> list[CriterionEvaluation]:
        """Evaluate every criterion for one vendor.

        Outer loop: criteria, batched in groups of ``max_concurrency`` so
        the inter-batch sleep is logged explicitly (visible in LangSmith).
        Inner loop (per-criterion): per-document fan-out, gathered.
        Per-document semaphore is the hard cap.
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
                    "Starting batch %d (%d criterion call(s)) for %s, %d docs each",
                    current_batch,
                    len(chunk),
                    vendor_name,
                    len(documents),
                )

            batch_results = await asyncio.gather(
                *[
                    self._aevaluate_one_criterion(
                        vendor_name=vendor_name,
                        is_msme=is_msme,
                        criterion=c,
                        documents=documents,
                    )
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
        documents: list[VendorDocument],
    ) -> VendorEvaluation:
        """Async equivalent of ``evaluate_vendor`` — fan out per-criterion +
        per-document calls and route through the deterministic post-processor.
        Use this from inside an existing event loop (FastAPI / Streamlit)."""
        evaluations = await self.aevaluate_vendor(
            criteria, vendor_name, is_msme, documents
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
        documents: list[VendorDocument],
    ) -> VendorEvaluation:
        """Sync convenience wrapper. Use ``aevaluate_vendor_full`` from inside
        an existing event loop instead — ``asyncio.run`` cannot nest."""
        return asyncio.run(
            self.aevaluate_vendor_full(criteria, vendor_name, is_msme, documents)
        )


def concatenate_vendor_docs(vendor_dir: Path) -> str:
    """Concatenate every PDF in ``vendor_dir`` into a single text blob.

    Kept for tooling that still wants a flat per-vendor text dump (e.g.
    matrix preview + ad-hoc inspection scripts). The evaluation agent
    itself moved to per-document calls in ADR-0007 and uses
    ``load_vendor_documents`` instead.
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
        "Return valid JSON matching the VerdictPerDoc schema this time."
    )
